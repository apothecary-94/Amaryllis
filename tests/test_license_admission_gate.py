from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class LicenseAdmissionGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo_root = Path(__file__).resolve().parents[1]
        self.script = self.repo_root / "scripts" / "release" / "license_admission_gate.py"

    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(self.script), *args],
            cwd=str(self.repo_root),
            capture_output=True,
            text=True,
            check=False,
        )

    def test_gate_passes_default(self) -> None:
        proc = self._run("--min-admission-score-pct", "100", "--max-failed-scenarios", "0")
        self.assertEqual(proc.returncode, 0, msg=f"stdout={proc.stdout}\nstderr={proc.stderr}")
        self.assertIn("[license-admission-gate] OK", proc.stdout)

    def test_gate_fails_when_required_scenario_missing(self) -> None:
        proc = self._run("--require-scenario", "missing-scenario")
        self.assertEqual(proc.returncode, 1, msg=f"stdout={proc.stdout}\nstderr={proc.stderr}")
        self.assertIn("[license-admission-gate] FAILED", proc.stdout)
        self.assertIn("missing_required_scenarios:missing-scenario", proc.stdout)

    def test_gate_writes_report(self) -> None:
        with tempfile.TemporaryDirectory(prefix="amaryllis-license-admission-gate-test-") as tmp:
            output = Path(tmp) / "report.json"
            proc = self._run("--output", str(output))
            self.assertEqual(proc.returncode, 0, msg=f"stdout={proc.stdout}\nstderr={proc.stderr}")
            self.assertTrue(output.exists())
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(report.get("suite"), "license_admission_gate_v1")
            self.assertEqual(str(report.get("summary", {}).get("status")), "pass")
            scenario_ids = {
                str(item.get("id"))
                for item in report.get("scenarios", [])
                if isinstance(item, dict)
            }
            self.assertIn("denied_spdx_rejected", scenario_ids)

    def test_gate_validates_min_score_range(self) -> None:
        proc = self._run("--min-admission-score-pct", "101")
        self.assertEqual(proc.returncode, 2, msg=f"stdout={proc.stdout}\nstderr={proc.stderr}")
        self.assertIn("--min-admission-score-pct must be in range 0..100", proc.stderr)


if __name__ == "__main__":
    unittest.main()
