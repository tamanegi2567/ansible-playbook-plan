#!/usr/bin/env python3
"""Show the host dispatch plan for Ansible playbooks without running tasks."""

from __future__ import annotations

import sys


# uv tool resolution can ignore Requires-Python upper bounds.
if not (3, 11) <= sys.version_info[:2] < (3, 15):
    raise SystemExit(
        "ansible-playbook-plan requires Python 3.11-3.14; "
        f"found Python {sys.version_info.major}.{sys.version_info.minor}. "
        "Run uvx with --python 3.14."
    )

# Import ansible.cli first so Ansible can initialize its controller state.
from ansible.cli import CLI

import os
import re
import stat

from ansible import context
from ansible.cli.playbook import PlaybookCLI
from ansible.errors import AnsibleError, AnsibleOptionsError
from ansible.executor.playbook_executor import PlaybookExecutor
from ansible.module_utils.common.text.converters import to_bytes
from ansible.module_utils.parsing.convert_bool import boolean
from ansible.playbook.block import Block
from ansible.plugins.loader import add_all_plugin_dirs
from ansible.utils.collection_loader import AnsibleCollectionConfig
from ansible.utils.collection_loader._collection_finder import (
    _get_collection_name_from_path,
    _get_collection_playbook_path,
)
from ansible.utils.display import Display


display = Display()


class PlaybookPlanCLI(PlaybookCLI):
    """Render play-level host ordering and serial batches."""

    name = "ansible-playbook-plan"
    USES_CONNECTION = False
    _UNKNOWN = object()
    _SIMPLE_CONDITION = re.compile(
        r"^\s*(?P<negated>not\s+)?(?P<variable>[A-Za-z_]\w*)"
        r"(?P<filters>(?:\s*\|\s*(?:bool|default\(\s*(?:true|false)\s*\)))*)\s*$",
        re.IGNORECASE,
    )
    _SENSITIVE_VARIABLE = re.compile(
        r"(?:credential|password|secret|token|(?:^|_)key(?:_|$))", re.IGNORECASE
    )

    def init_parser(self) -> None:
        super().init_parser()
        self.parser.description = (
            "Shows play-level host ordering and serial batches without executing tasks."
        )
        self.parser.set_defaults(listhosts=True)

    def run(self) -> int:
        CLI.run(self)
        if context.CLIARGS["flush_cache"]:
            raise AnsibleOptionsError(
                "--flush-cache is not supported because this command is read-only."
            )
        self._prepare_playbook_paths()

        loader, inventory, variable_manager = self._play_prereqs()
        CLI.get_host_list(inventory, context.CLIARGS["subset"])

        executor = PlaybookExecutor(
            playbooks=context.CLIARGS["args"],
            inventory=inventory,
            variable_manager=variable_manager,
            loader=loader,
            passwords={},
        )
        results = executor.run()
        if not isinstance(results, list):
            return int(results)

        self._display_plan(results, executor)
        return 0

    def _prepare_playbook_paths(self) -> None:
        playbook_directories: list[bytes] = []

        for playbook in context.CLIARGS["args"]:
            resource = _get_collection_playbook_path(playbook)
            if resource is not None:
                playbook_collection = resource[2]
            else:
                if not os.path.exists(playbook):
                    raise AnsibleError(f"the playbook: {playbook} could not be found")
                if not (
                    os.path.isfile(playbook) or stat.S_ISFIFO(os.stat(playbook).st_mode)
                ):
                    raise AnsibleError(
                        f"the playbook: {playbook} does not appear to be a file"
                    )
                playbook_collection = _get_collection_name_from_path(playbook)

            if not playbook_collection:
                playbook_directory = os.path.dirname(
                    os.path.abspath(to_bytes(playbook, errors="surrogate_or_strict"))
                )
                add_all_plugin_dirs(playbook_directory)
                playbook_directories.append(playbook_directory)

        if playbook_directories:
            AnsibleCollectionConfig.playbook_paths = playbook_directories

    @staticmethod
    def _display_plan(results: list[dict], executor: PlaybookExecutor) -> None:
        forks = int(context.CLIARGS["forks"])
        static_variables = {
            **executor._variable_manager.extra_vars,
            "ansible_check_mode": bool(context.CLIARGS["check"]),
            "ansible_diff_mode": bool(context.CLIARGS["diff"]),
        }

        for result in results:
            display.display(f"\nplaybook: {result['playbook']}")
            skipped_play_count = 0
            for index, play in enumerate(result["plays"], start=1):
                tasks = list(PlaybookPlanCLI._iter_tasks(play))
                if PlaybookPlanCLI._play_is_statically_skipped(
                    play, tasks, static_variables
                ):
                    skipped_play_count += 1
                    continue

                batches = executor._get_serialized_batches(play)
                host_count = sum(len(batch) for batch in batches)
                serial = PlaybookPlanCLI._format_serial(play.serial)
                order = play.order or "inventory"
                strategy = play.strategy or "linear"
                pattern = ", ".join(play.hosts)

                display.display(f"\n  play #{index} ({pattern}): {play.name}")
                display.display(f"    pattern: {play.hosts}")
                display.display(f"    strategy: {strategy}")
                display.display(f"    order: {order}")
                display.display(f"    serial: {serial}")
                display.display(f"    forks: {forks}")
                display.display(
                    f"    hosts ({host_count}), serial batches ({len(batches)}):"
                )

                host_number = 0
                for batch_number, batch in enumerate(batches, start=1):
                    max_parallel = min(len(batch), forks)
                    batch_host_label = PlaybookPlanCLI._host_label(len(batch))
                    display.display(
                        f"      serial batch {batch_number} "
                        f"({len(batch)} {batch_host_label}):"
                    )
                    display.display(
                        f"        initial fork slots ({max_parallel} used of {forks}):"
                    )
                    for fork_slot, host in enumerate(batch[:max_parallel], start=1):
                        host_number += 1
                        display.display(
                            f"          fork {fork_slot}: {host_number}. {host.name}"
                        )

                    queued_hosts = batch[max_parallel:]
                    if queued_hosts:
                        queue_host_label = PlaybookPlanCLI._host_label(
                            len(queued_hosts)
                        )
                        display.display(
                            f"        dispatch queue "
                            f"({len(queued_hosts)} {queue_host_label}; "
                            "starts as fork slots become available):"
                        )
                        for host in queued_hosts:
                            host_number += 1
                            display.display(f"          {host_number}. {host.name}")

                PlaybookPlanCLI._display_tasks(
                    tasks, batches, host_count, static_variables
                )

                if order == "shuffle" and host_count:
                    display.warning(
                        "order=shuffle is randomized again when the playbook executes."
                    )

            if skipped_play_count:
                play_label = "play" if skipped_play_count == 1 else "plays"
                display.display(
                    f"\n  omitted {skipped_play_count} statically skipped {play_label}."
                )

    @staticmethod
    def _display_tasks(
        tasks: list[tuple],
        batches: list[list],
        host_count: int,
        static_variables: dict,
    ) -> None:
        visible_tasks = [
            task_entry
            for task_entry in tasks
            if not PlaybookPlanCLI._task_is_statically_skipped(
                task_entry[2], static_variables
            )
        ]
        skipped_task_count = len(tasks) - len(visible_tasks)
        display.display(f"    tasks ({len(visible_tasks)}):")

        for task_number, (section, block_path, task) in enumerate(
            visible_tasks, start=1
        ):
            name = task.name or task.action
            display.display(f"      {task_number}. {name}")
            display.display(f"        section: {section}")
            if block_path:
                display.display(f"        block: {' > '.join(block_path)}")
            display.display(f"        action: {task.action}")

            if task.run_once is True:
                display.display("        execution: first host in each serial batch")
                for batch_number, batch in enumerate(batches, start=1):
                    if batch:
                        display.display(
                            f"          batch {batch_number}: {batch[0].name}"
                        )
            elif task.run_once:
                display.display(
                    f"        execution: runtime-dependent (run_once={task.run_once})"
                )
            else:
                display.display(
                    f"        execution: all {host_count} play hosts, "
                    "subject to runtime conditions"
                )

            if task.throttle:
                display.display(f"        throttle: {task.throttle}")
            if task.delegate_to:
                display.display(f"        delegate_to: {task.delegate_to}")
            for condition in task.when:
                display.display(f"        when: {condition}")

        if skipped_task_count:
            task_label = "task" if skipped_task_count == 1 else "tasks"
            display.display(
                f"    omitted {skipped_task_count} statically skipped {task_label}."
            )

    @staticmethod
    def _play_is_statically_skipped(play, tasks: list[tuple], variables: dict) -> bool:
        if play.gather_facts or not tasks:
            return False
        return all(
            PlaybookPlanCLI._task_is_statically_skipped(task, variables)
            for _, _, task in tasks
        )

    @staticmethod
    def _task_is_statically_skipped(task, variables: dict) -> bool:
        return any(
            PlaybookPlanCLI._evaluate_simple_condition(condition, variables) is False
            for condition in task.when
        )

    @staticmethod
    def _evaluate_simple_condition(condition, variables: dict):
        if isinstance(condition, bool):
            return condition
        if not isinstance(condition, str):
            return PlaybookPlanCLI._UNKNOWN

        match = PlaybookPlanCLI._SIMPLE_CONDITION.fullmatch(condition)
        if not match:
            return PlaybookPlanCLI._UNKNOWN

        variable = match.group("variable")
        if PlaybookPlanCLI._SENSITIVE_VARIABLE.search(variable):
            return PlaybookPlanCLI._UNKNOWN

        value = variables.get(variable, PlaybookPlanCLI._UNKNOWN)
        filters = re.findall(
            r"bool|default\(\s*(?:true|false)\s*\)",
            match.group("filters"),
            re.IGNORECASE,
        )
        for filter_expression in filters:
            if filter_expression.lower() == "bool":
                if value is PlaybookPlanCLI._UNKNOWN:
                    return PlaybookPlanCLI._UNKNOWN
                value = boolean(value, strict=False)
                continue
            if value is PlaybookPlanCLI._UNKNOWN:
                value = "true" in filter_expression.lower()

        if value is PlaybookPlanCLI._UNKNOWN:
            return PlaybookPlanCLI._UNKNOWN
        result = bool(value)
        return not result if match.group("negated") else result

    @staticmethod
    def _iter_tasks(play):
        sections = (
            ("pre_tasks", play.pre_tasks),
            ("tasks", play.tasks),
            ("post_tasks", play.post_tasks),
        )
        for section, entries in sections:
            yield from PlaybookPlanCLI._walk_task_entries(entries, section, ())

    @staticmethod
    def _walk_task_entries(entries, section: str, block_path: tuple[str, ...]):
        for entry in entries:
            if not isinstance(entry, Block):
                yield section, block_path, entry
                continue

            current_path = block_path
            if entry.name:
                current_path = (*current_path, entry.name)
            yield from PlaybookPlanCLI._walk_task_entries(
                entry.block, section, current_path
            )
            yield from PlaybookPlanCLI._walk_task_entries(
                entry.rescue, section, (*current_path, "rescue")
            )
            yield from PlaybookPlanCLI._walk_task_entries(
                entry.always, section, (*current_path, "always")
            )

    @staticmethod
    def _format_serial(serial: list) -> str:
        if not serial:
            return "all"
        if len(serial) == 1:
            return str(serial[0])
        return f"[{', '.join(str(value) for value in serial)}]"

    @staticmethod
    def _host_label(host_count: int) -> str:
        return "host" if host_count == 1 else "hosts"


def main() -> None:
    PlaybookPlanCLI.cli_executor()


if __name__ == "__main__":
    main()
