from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class RuntimeLifecycleSmokeGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo_root = Path(__file__).resolve().parents[1]
        self.script = self.repo_root / "scripts" / "release" / "runtime_lifecycle_smoke_gate.py"

    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        command = [sys.executable, str(self.script), *args]
        return subprocess.run(
            command,
            cwd=str(self.repo_root),
            capture_output=True,
            text=True,
            check=False,
        )

    def test_runtime_lifecycle_smoke_gate_report_contract(self) -> None:
        with tempfile.TemporaryDirectory(prefix="amaryllis-runtime-lifecycle-gate-test-") as tmp:
            output = Path(tmp) / "runtime-lifecycle-smoke-report.json"
            proc = self._run(
                "--output",
                str(output),
                "--max-startup-slo-latency-ms",
                "10000",
            )
            self.assertEqual(proc.returncode, 0, msg=f"stdout={proc.stdout}\nstderr={proc.stderr}")
            self.assertTrue(output.exists(), msg=f"report not found: {output}")

            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload.get("suite"), "runtime_lifecycle_smoke_v1")
            summary = payload.get("summary")
            self.assertIsInstance(summary, dict)
            assert isinstance(summary, dict)
            self.assertEqual(summary.get("checks_failed"), 0)
            self.assertTrue(summary.get("targets_ok"))
            self.assertTrue(summary.get("startup_ok"))

            checks = payload.get("checks")
            self.assertIsInstance(checks, list)
            assert isinstance(checks, list)
            names = {str(item.get("name")) for item in checks if isinstance(item, dict)}
            self.assertIn("linux-systemd_install", names)
            self.assertIn("macos-launchd_install", names)
            self.assertIn("startup_probe_slo_latency", names)


if __name__ == "__main__":
    unittest.main()
