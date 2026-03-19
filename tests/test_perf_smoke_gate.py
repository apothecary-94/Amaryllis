from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import unittest


class PerfSmokeGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo_root = Path(__file__).resolve().parents[1]
        self.script = self.repo_root / "scripts" / "release" / "perf_smoke_gate.py"

    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        command = [sys.executable, str(self.script), *args]
        return subprocess.run(
            command,
            cwd=str(self.repo_root),
            capture_output=True,
            text=True,
            check=False,
        )

    def test_perf_smoke_gate_passes_with_relaxed_thresholds(self) -> None:
        proc = self._run(
            "--iterations",
            "1",
            "--max-p95-latency-ms",
            "10000",
            "--max-error-rate-pct",
            "0",
        )
        self.assertEqual(proc.returncode, 0, msg=f"stdout={proc.stdout}\nstderr={proc.stderr}")
        self.assertIn("[perf-smoke] OK", proc.stdout)

    def test_perf_smoke_gate_fails_with_impossible_latency_threshold(self) -> None:
        proc = self._run(
            "--iterations",
            "1",
            "--max-p95-latency-ms",
            "0",
            "--max-error-rate-pct",
            "0",
        )
        self.assertEqual(proc.returncode, 1, msg=f"stdout={proc.stdout}\nstderr={proc.stderr}")
        self.assertIn("[perf-smoke] FAILED", proc.stdout)


if __name__ == "__main__":
    unittest.main()
