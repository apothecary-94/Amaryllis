from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class EnvironmentPassportGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo_root = Path(__file__).resolve().parents[1]
        self.script = self.repo_root / "scripts" / "release" / "environment_passport_gate.py"

    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(self.script), *args],
            cwd=str(self.repo_root),
            capture_output=True,
            text=True,
            check=False,
        )

    @staticmethod
    def _write_json(path: Path, payload: dict) -> None:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def test_environment_passport_gate_passes_default(self) -> None:
        proc = self._run("--min-completeness-score-pct", "100", "--max-missing-required", "0")
        self.assertEqual(proc.returncode, 0, msg=f"stdout={proc.stdout}\nstderr={proc.stderr}")
        self.assertIn("[environment-passport] OK", proc.stdout)

    def test_environment_passport_gate_writes_report(self) -> None:
        with tempfile.TemporaryDirectory(prefix="amaryllis-environment-passport-gate-test-") as tmp:
            output = Path(tmp) / "report.json"
            proc = self._run("--output", str(output))
            self.assertEqual(proc.returncode, 0, msg=f"stdout={proc.stdout}\nstderr={proc.stderr}")
            self.assertTrue(output.exists())
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(report.get("suite"), "environment_passport_gate_v1")
            self.assertEqual(str(report.get("summary", {}).get("status")), "pass")
            self.assertIn("passport", report)

    def test_environment_passport_gate_uses_quantization_reference_from_admission_report(self) -> None:
        with tempfile.TemporaryDirectory(prefix="amaryllis-environment-passport-gate-test-") as tmp:
            base = Path(tmp)
            admission_report = base / "model-admission.json"
            output = base / "env-passport.json"
            self._write_json(
                admission_report,
                {
                    "suite": "model_artifact_admission_gate_v1",
                    "quantization_reference": {
                        "method": "int8",
                        "bits": 8,
                        "recipe_id": "int8-recipe-v2",
                        "converter": "test-converter",
                        "converter_version": "1.2.3",
                    },
                },
            )

            proc = self._run(
                "--model-artifact-admission-report",
                str(admission_report),
                "--output",
                str(output),
            )
            self.assertEqual(proc.returncode, 0, msg=f"stdout={proc.stdout}\nstderr={proc.stderr}")
            report = json.loads(output.read_text(encoding="utf-8"))
            quant = report.get("passport", {}).get("quantization", {})
            self.assertEqual(quant.get("source"), "model_artifact_admission_report")
            self.assertEqual(quant.get("recipe_id"), "int8-recipe-v2")
            self.assertEqual(int(quant.get("bits")), 8)

    def test_environment_passport_gate_validates_min_completeness_range(self) -> None:
        proc = self._run("--min-completeness-score-pct", "101")
        self.assertEqual(proc.returncode, 2, msg=f"stdout={proc.stdout}\nstderr={proc.stderr}")
        self.assertIn("--min-completeness-score-pct must be in range 0..100", proc.stderr)


if __name__ == "__main__":
    unittest.main()
