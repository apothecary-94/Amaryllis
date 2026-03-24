from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class GenerationLoopConformanceGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo_root = Path(__file__).resolve().parents[1]
        self.script = self.repo_root / "scripts" / "release" / "generation_loop_conformance_gate.py"

    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        command = [sys.executable, str(self.script), *args]
        return subprocess.run(
            command,
            cwd=str(self.repo_root),
            capture_output=True,
            text=True,
            check=False,
        )

    def test_generation_loop_conformance_gate_passes_default(self) -> None:
        proc = self._run("--min-providers", "1", "--max-warning-providers", "9999")
        self.assertEqual(proc.returncode, 0, msg=f"stdout={proc.stdout}\nstderr={proc.stderr}")
        self.assertIn("[generation-loop-gate] OK", proc.stdout)

    def test_generation_loop_conformance_gate_fails_when_required_provider_missing(self) -> None:
        proc = self._run("--require-provider", "missing-provider")
        self.assertEqual(proc.returncode, 1, msg=f"stdout={proc.stdout}\nstderr={proc.stderr}")
        self.assertIn("[generation-loop-gate] FAILED", proc.stdout)
        self.assertIn("missing_required_providers:missing-provider", proc.stdout)

    def test_generation_loop_conformance_gate_writes_report(self) -> None:
        with tempfile.TemporaryDirectory(prefix="amaryllis-genloop-gate-test-") as tmp:
            output = Path(tmp) / "report.json"
            proc = self._run("--output", str(output))
            self.assertEqual(proc.returncode, 0, msg=f"stdout={proc.stdout}\nstderr={proc.stderr}")
            self.assertTrue(output.exists())
            payload = output.read_text(encoding="utf-8")
            self.assertIn("generation_loop_conformance_gate_v1", payload)


if __name__ == "__main__":
    unittest.main()
