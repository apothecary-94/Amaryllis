from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class DistributionResilienceReportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo_root = Path(__file__).resolve().parents[1]
        self.script = self.repo_root / "scripts" / "release" / "build_distribution_resilience_report.py"

    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        command = [sys.executable, str(self.script), *args]
        return subprocess.run(
            command,
            cwd=str(self.repo_root),
            capture_output=True,
            text=True,
            check=False,
        )

    @staticmethod
    def _write_json(path: Path, payload: dict) -> None:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _write_linux_parity(self, path: Path, *, checks_failed: int = 0, error_rate_pct: float = 0.0) -> None:
        self._write_json(
            path,
            {
                "suite": "linux_parity_smoke_v1",
                "generated_at": "2026-03-21T00:00:00+00:00",
                "summary": {
                    "checks_total": 20,
                    "checks_failed": checks_failed,
                    "error_rate_pct": error_rate_pct,
                    "latency_ms": {"p50": 30.0, "p95": 120.0, "max": 180.0},
                },
            },
        )

    def _write_linux_installer(self, path: Path, *, fail_required: bool = False) -> None:
        required_checks = [
            "installer_exists",
            "rollback_script_exists",
            "upgrade_keeps_prior_release",
            "rollback_keeps_canary_release_history",
            "release_r2_channel_target",
            "release_r2_current_target",
            "canary_rollback_channel_target",
            "canary_rollback_channel_history",
            "canary_rollback_current_target",
        ]
        checks = []
        for name in required_checks:
            ok = True
            if fail_required and name == "rollback_keeps_canary_release_history":
                ok = False
            checks.append({"name": name, "ok": ok, "detail": "test"})

        self._write_json(
            path,
            {
                "suite": "linux_installer_smoke_v1",
                "generated_at": "2026-03-21T00:00:00+00:00",
                "checks": checks,
                "commands": [
                    {"label": "install_release_r1", "returncode": 0},
                    {"label": "install_release_r2_upgrade", "returncode": 0},
                ],
            },
        )

    def _write_runtime_lifecycle(self, path: Path) -> None:
        self._write_json(
            path,
            {
                "suite": "runtime_lifecycle_smoke_v1",
                "generated_at": "2026-03-21T00:00:00+00:00",
                "summary": {
                    "targets_ok": True,
                    "startup_ok": True,
                    "checks_total": 12,
                    "checks_failed": 0,
                },
            },
        )

    def test_report_is_generated_for_passing_sources(self) -> None:
        with tempfile.TemporaryDirectory(prefix="amaryllis-distribution-resilience-") as tmp:
            base = Path(tmp)
            parity = base / "linux-parity.json"
            installer = base / "linux-installer.json"
            runtime = base / "runtime-lifecycle.json"
            output = base / "distribution-report.json"

            self._write_linux_parity(parity)
            self._write_linux_installer(installer)
            self._write_runtime_lifecycle(runtime)

            proc = self._run(
                "--linux-parity-report",
                str(parity),
                "--linux-installer-report",
                str(installer),
                "--runtime-lifecycle-report",
                str(runtime),
                "--output",
                str(output),
            )
            self.assertEqual(proc.returncode, 0, msg=f"stdout={proc.stdout}\nstderr={proc.stderr}")
            self.assertIn("[distribution-resilience] OK", proc.stdout)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload.get("suite"), "distribution_resilience_report_v1")
            self.assertEqual(str(payload.get("summary", {}).get("status")), "pass")
            self.assertGreaterEqual(int(payload.get("summary", {}).get("checks_total", 0)), 1)

    def test_report_fails_when_required_installer_check_is_false(self) -> None:
        with tempfile.TemporaryDirectory(prefix="amaryllis-distribution-resilience-") as tmp:
            base = Path(tmp)
            parity = base / "linux-parity.json"
            installer = base / "linux-installer.json"
            output = base / "distribution-report.json"

            self._write_linux_parity(parity)
            self._write_linux_installer(installer, fail_required=True)

            proc = self._run(
                "--linux-parity-report",
                str(parity),
                "--linux-installer-report",
                str(installer),
                "--output",
                str(output),
            )
            self.assertEqual(proc.returncode, 1, msg=f"stdout={proc.stdout}\nstderr={proc.stderr}")
            self.assertIn("[distribution-resilience] FAILED", proc.stdout)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(str(payload.get("summary", {}).get("status")), "fail")

    def test_report_fails_when_required_source_is_missing(self) -> None:
        with tempfile.TemporaryDirectory(prefix="amaryllis-distribution-resilience-") as tmp:
            base = Path(tmp)
            installer = base / "linux-installer.json"
            output = base / "distribution-report.json"
            self._write_linux_installer(installer)

            proc = self._run(
                "--linux-parity-report",
                str(base / "missing-parity.json"),
                "--linux-installer-report",
                str(installer),
                "--output",
                str(output),
            )
            self.assertEqual(proc.returncode, 2, msg=f"stdout={proc.stdout}\nstderr={proc.stderr}")
            self.assertIn("missing report", proc.stderr.lower())


if __name__ == "__main__":
    unittest.main()
