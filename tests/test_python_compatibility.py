from pathlib import Path
import subprocess
import sys
import unittest


CLI_PATH = Path(__file__).resolve().parents[1] / "src/ansible_playbook_plan/cli.py"


class PythonCompatibilityTest(unittest.TestCase):
    def test_unsupported_python_is_rejected_before_importing_ansible(self) -> None:
        for major, minor in ((3, 10), (3, 15), (4, 0)):
            with self.subTest(python=f"{major}.{minor}"):
                script = f"""
import runpy
import sys
from collections import namedtuple
Version = namedtuple('Version', 'major minor micro releaselevel serial')
sys.version_info = Version({major}, {minor}, 0, 'final', 0)
try:
    runpy.run_path({str(CLI_PATH)!r})
except SystemExit:
    assert 'ansible' not in sys.modules
    raise
"""
                result = subprocess.run(
                    [sys.executable, "-c", script],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("requires Python 3.11-3.14", result.stderr)
                self.assertIn(f"found Python {major}.{minor}", result.stderr)
                self.assertIn("--python 3.14", result.stderr)
                self.assertNotIn("Traceback", result.stderr)

    def test_supported_python_can_show_help(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "ansible_playbook_plan", "--help"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("usage:", result.stdout)
