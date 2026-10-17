from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest


PROJECT_DIRECTORY = Path(__file__).resolve().parents[1]


class PlaybookPlanCLITest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.directory = Path(self.temporary_directory.name)
        self.inventory = self._write(
            "inventory.yml",
            """
            ---
            all:
              children:
                targets:
                  hosts:
                    node-c:
                    node-a:
                    node-d:
                    node-b:
            """,
        )

    def test_sorted_hosts_are_split_into_resolved_serial_batches(self) -> None:
        playbook = self._write(
            "sorted.yml",
            """
            ---
            - name: Sorted rollout
              hosts: targets
              order: sorted
              serial: "{{ rollout_serial | default(1) }}"
              gather_facts: false
              tasks: []
            """,
        )

        output = self._run(
            "-f",
            "1",
            "-e",
            "rollout_serial=2",
            str(playbook),
        )

        self.assertIn("order: sorted", output)
        self.assertIn("serial: 2", output)
        self.assertIn("hosts (4), serial batches (2)", output)
        self.assertIn("serial batch 1 (2 hosts)", output)
        self.assertIn("initial fork slots (1 used of 1)", output)
        self.assertIn("dispatch queue (1 host", output)
        self.assertLess(output.index("1. node-a"), output.index("2. node-b"))
        self.assertLess(output.index("2. node-b"), output.index("3. node-c"))
        self.assertLess(output.index("3. node-c"), output.index("4. node-d"))

    def test_inventory_order_and_limit_are_preserved(self) -> None:
        playbook = self._write(
            "inventory_order.yml",
            """
            ---
            - name: Inventory order
              hosts: targets
              order: inventory
              gather_facts: false
              tasks: []
            """,
        )

        output = self._run("--limit", "node-c,node-d", str(playbook))

        self.assertIn("order: inventory", output)
        self.assertIn("serial: all", output)
        self.assertIn("hosts (2), serial batches (1)", output)
        self.assertLess(output.index("1. node-c"), output.index("2. node-d"))
        self.assertNotIn("node-a", output)
        self.assertNotIn("node-b", output)

    def test_imported_play_vars_and_percentage_serial_are_resolved(self) -> None:
        imported = self._write(
            "imported.yml",
            """
            ---
            - name: Imported rollout
              hosts: targets
              order: sorted
              serial: "{{ imported_serial }}"
              gather_facts: false
              tasks: []
            """,
        )
        playbook = self._write(
            "root.yml",
            f"""
            ---
            - name: Import rollout
              ansible.builtin.import_playbook: {imported.name}
              vars:
                imported_serial: 50%
            """,
        )

        output = self._run(str(playbook))

        self.assertIn("play #1 (targets): Imported rollout", output)
        self.assertIn("serial: 50%", output)
        self.assertIn("hosts (4), serial batches (2)", output)

    def test_multiple_playbooks_and_empty_host_patterns_are_displayed(self) -> None:
        empty_playbook = self._write(
            "empty.yml",
            """
            ---
            - name: Empty selection
              hosts: missing
              order: sorted
              gather_facts: false
              tasks: []
            """,
        )
        populated_playbook = self._write(
            "populated.yml",
            """
            ---
            - name: Populated selection
              hosts: targets
              order: sorted
              gather_facts: false
              tasks: []
            """,
        )

        output = self._run(str(empty_playbook), str(populated_playbook))

        self.assertIn(f"playbook: {empty_playbook}", output)
        self.assertIn("play #1 (missing): Empty selection", output)
        self.assertIn("hosts (0), serial batches (0)", output)
        self.assertIn(f"playbook: {populated_playbook}", output)
        self.assertIn("play #1 (targets): Populated selection", output)

    def test_tasks_and_run_once_execution_hosts_are_displayed(self) -> None:
        playbook = self._write(
            "tasks.yml",
            """
            ---
            - name: Task details
              hosts: targets
              order: sorted
              serial: 2
              gather_facts: false
              pre_tasks:
                - name: Check each batch once
                  ansible.builtin.debug:
                    msg: check
                  run_once: true
                  when: checks_enabled | default(true) | bool
              tasks:
                - name: Update every host
                  ansible.builtin.debug:
                    msg: update
                  throttle: 1
            """,
        )

        output = self._run(str(playbook))

        self.assertIn("tasks (2)", output)
        self.assertIn("1. Check each batch once", output)
        self.assertIn("section: pre_tasks", output)
        self.assertIn("action: ansible.builtin.debug", output)
        self.assertIn("execution: first host in each serial batch", output)
        self.assertIn("batch 1: node-a", output)
        self.assertIn("batch 2: node-c", output)
        self.assertIn("when: checks_enabled | default(true) | bool", output)
        self.assertIn("2. Update every host", output)
        self.assertIn("execution: all 4 play hosts", output)
        self.assertIn("throttle: 1", output)

    def test_play_with_only_statically_skipped_tasks_is_omitted(self) -> None:
        playbook = self._write(
            "skipped.yml",
            """
            ---
            - name: Disabled checks
              hosts: targets
              gather_facts: false
              tasks:
                - name: Check health
                  ansible.builtin.debug:
                    msg: check
                  when: checks_enabled | default(true) | bool

            - name: Enabled rollout
              hosts: targets
              gather_facts: false
              tasks:
                - name: Update nodes
                  ansible.builtin.debug:
                    msg: update
            """,
        )

        output = self._run("-e", "checks_enabled=false", str(playbook))

        self.assertNotIn("Disabled checks", output)
        self.assertNotIn("Check health", output)
        self.assertIn("play #2 (targets): Enabled rollout", output)
        self.assertIn("omitted 1 statically skipped play", output)

    def test_statically_skipped_task_is_omitted_from_active_play(self) -> None:
        playbook = self._write(
            "mixed.yml",
            """
            ---
            - name: Mixed rollout
              hosts: targets
              gather_facts: false
              tasks:
                - name: Optional check
                  ansible.builtin.debug:
                    msg: check
                  when: checks_enabled | default(true) | bool
                - name: Required update
                  ansible.builtin.debug:
                    msg: update
            """,
        )

        output = self._run("-e", "checks_enabled=false", str(playbook))

        self.assertNotIn("Optional check", output)
        self.assertIn("tasks (1)", output)
        self.assertIn("1. Required update", output)
        self.assertIn("omitted 1 statically skipped task", output)

    def test_check_mode_omits_normal_mode_tasks_and_plays(self) -> None:
        playbook = self._write(
            "check_mode.yml",
            """
            ---
            - name: Mixed mode
              hosts: targets
              gather_facts: false
              tasks:
                - name: Normal operation
                  ansible.builtin.debug:
                    msg: normal
                  when: not ansible_check_mode
                - name: Check-mode report
                  ansible.builtin.debug:
                    msg: check
                  when: ansible_check_mode

            - name: Normal mode only
              hosts: targets
              gather_facts: false
              tasks:
                - name: Final verification
                  ansible.builtin.debug:
                    msg: verify
                  when: not ansible_check_mode
            """,
        )

        output = self._run("--check", str(playbook))

        self.assertNotIn("Normal operation", output)
        self.assertIn("Check-mode report", output)
        self.assertNotIn("Normal mode only", output)
        self.assertNotIn("Final verification", output)
        self.assertIn("omitted 1 statically skipped task", output)
        self.assertIn("omitted 1 statically skipped play", output)

    def _run(self, *arguments: str) -> str:
        environment = os.environ.copy()
        environment["ANSIBLE_LOCAL_TEMP"] = str(self.directory / "ansible-tmp")
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "ansible_playbook_plan",
                "-i",
                str(self.inventory),
                *arguments,
            ],
            cwd=PROJECT_DIRECTORY,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def _write(self, name: str, content: str) -> Path:
        path = self.directory / name
        path.write_text(textwrap.dedent(content), encoding="utf-8")
        return path


if __name__ == "__main__":
    unittest.main()
