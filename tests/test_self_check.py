import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from dtf_manager.core import self_check


class SelfCheckTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "win32", "SMBIOS and DPAPI are Windows only")
    def test_cli_writes_a_report_without_serials_or_machine_id(self):
        with TemporaryDirectory() as folder:
            report = Path(folder) / "report.json"
            result = subprocess.run([sys.executable, "app.py", "--self-check", str(report)],
                                    cwd=Path(__file__).resolve().parents[1],
                                    capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(report.read_text(encoding="utf-8"))
        self.assertTrue(data["ok"])
        self.assertTrue(data["dpapi_round_trip"] and data["dpapi_binds_entropy"])
        self.assertGreaterEqual(len(data["machine_components"]), 2)
        from dtf_manager.services.machine_id import get_machine_id
        self.assertNotIn(get_machine_id(), json.dumps(data))

    def test_failure_is_reported_with_a_non_zero_exit_code(self):
        with TemporaryDirectory() as folder, \
             patch.object(self_check, "collect", return_value={"ok": False}):
            report = Path(folder) / "report.json"
            self.assertEqual(self_check.run(str(report)), 1)
            self.assertFalse(json.loads(report.read_text(encoding="utf-8"))["ok"])


if __name__ == "__main__":
    unittest.main()
