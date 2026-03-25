from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class APIQuickstartCompatibilityGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo_root = Path(__file__).resolve().parents[1]
        self.script = self.repo_root / "scripts" / "release" / "api_quickstart_compatibility_gate.py"

    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(self.script), *args],
            cwd=str(self.repo_root),
            capture_output=True,
            text=True,
            check=False,
        )

    def test_gate_passes_default(self) -> None:
        proc = self._run()
        self.assertEqual(proc.returncode, 0, msg=f"stdout={proc.stdout}\nstderr={proc.stderr}")
        self.assertIn("[api-quickstart-gate] OK", proc.stdout)

    def test_gate_fails_when_quickstart_doc_missing(self) -> None:
        proc = self._run("--quickstart-doc", "docs/missing-quickstart.md")
        self.assertEqual(proc.returncode, 1, msg=f"stdout={proc.stdout}\nstderr={proc.stderr}")
        self.assertIn("[api-quickstart-gate] FAILED", proc.stdout)
        self.assertIn("quickstart_doc_exists", proc.stdout)

    def test_gate_writes_report(self) -> None:
        with tempfile.TemporaryDirectory(prefix="amaryllis-api-quickstart-gate-test-") as tmp:
            output = Path(tmp) / "report.json"
            proc = self._run("--output", str(output))
            self.assertEqual(proc.returncode, 0, msg=f"stdout={proc.stdout}\nstderr={proc.stderr}")
            self.assertTrue(output.exists())
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(str(payload.get("suite")), "api_quickstart_compatibility_gate_v1")
            self.assertEqual(str(payload.get("summary", {}).get("status")), "pass")


if __name__ == "__main__":
    unittest.main()
