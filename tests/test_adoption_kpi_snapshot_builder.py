from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class AdoptionKPISnapshotBuilderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo_root = Path(__file__).resolve().parents[1]
        self.script = self.repo_root / "scripts" / "release" / "build_adoption_kpi_snapshot.py"

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
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _write_reports(self, base: Path, *, schema_failed: bool = False) -> dict[str, Path]:
        schema = base / "adoption-schema-gate.json"
        journey = base / "user-journey.json"
        api = base / "api-quickstart.json"
        manifest = base / "distribution-channel-manifest.json"
        quality = base / "release-quality-dashboard.json"

        self._write_json(
            schema,
            {
                "suite": "adoption_kpi_schema_gate_v1",
                "checks": [
                    {
                        "id": "api_quickstart.pass_rate_pct",
                        "threshold": 100.0,
                        "passed": not schema_failed,
                    },
                    {
                        "id": "distribution_channel_manifest.coverage_pct",
                        "threshold": 100.0,
                        "passed": not schema_failed,
                    },
                ],
                "summary": {
                    "status": "fail" if schema_failed else "pass",
                    "checks_total": 2,
                    "checks_passed": 1 if schema_failed else 2,
                    "checks_failed": 1 if schema_failed else 0,
                },
            },
        )
        self._write_json(
            journey,
            {
                "suite": "user_journey_benchmark_v1",
                "config": {
                    "thresholds": {
                        "min_activation_success_rate_pct": 100.0,
                        "max_blocked_activation_rate_pct": 0.0,
                        "min_install_success_rate_pct": 100.0,
                        "min_retention_proxy_success_rate_pct": 100.0,
                        "min_feature_adoption_rate_pct": 100.0,
                    }
                },
                "summary": {
                    "activation_success_rate_pct": 100.0,
                    "activation_blocked_rate_pct": 0.0,
                    "install_success_rate_pct": 100.0,
                    "retention_proxy_success_rate_pct": 100.0,
                    "feature_adoption_rate_pct": 100.0,
                },
            },
        )
        self._write_json(
            api,
            {
                "suite": "api_quickstart_compatibility_gate_v1",
                "summary": {
                    "status": "pass",
                    "checks_total": 16,
                    "checks_failed": 0,
                },
            },
        )
        self._write_json(
            manifest,
            {
                "suite": "distribution_channel_manifest_gate_v1",
                "summary": {
                    "status": "pass",
                    "checks_total": 4,
                    "checks_failed": 0,
                },
            },
        )
        self._write_json(
            quality,
            {
                "suite": "release_quality_dashboard_v1",
                "signals": [
                    {"metric_id": "user_journey.activation_success_rate_pct", "passed": True},
                    {"metric_id": "user_journey.install_success_rate_pct", "passed": True},
                    {"metric_id": "user_journey.retention_proxy_success_rate_pct", "passed": True},
                    {"metric_id": "user_journey.feature_adoption_rate_pct", "passed": True},
                    {"metric_id": "api_quickstart_compat.pass_rate_pct", "passed": True},
                    {"metric_id": "distribution_channel_manifest.coverage_pct", "passed": True},
                ],
            },
        )
        return {
            "schema": schema,
            "journey": journey,
            "api": api,
            "manifest": manifest,
            "quality": quality,
        }

    def test_help_contract(self) -> None:
        proc = self._run("--help")
        self.assertEqual(proc.returncode, 0, msg=f"stdout={proc.stdout}\nstderr={proc.stderr}")
        text = (proc.stdout or "") + (proc.stderr or "")
        self.assertIn("--schema-gate-report", text)
        self.assertIn("--user-journey-report", text)
        self.assertIn("--api-quickstart-report", text)
        self.assertIn("--distribution-channel-manifest-report", text)
        self.assertIn("--quality-dashboard-report", text)

    def test_builder_writes_snapshot(self) -> None:
        with tempfile.TemporaryDirectory(prefix="amaryllis-adoption-snapshot-build-") as tmp:
            base = Path(tmp)
            reports = self._write_reports(base)
            output = base / "adoption-kpi-snapshot.json"

            proc = self._run(
                "--schema-gate-report",
                str(reports["schema"]),
                "--user-journey-report",
                str(reports["journey"]),
                "--api-quickstart-report",
                str(reports["api"]),
                "--distribution-channel-manifest-report",
                str(reports["manifest"]),
                "--quality-dashboard-report",
                str(reports["quality"]),
                "--output",
                str(output),
                "--release-channel",
                "release",
            )

            self.assertEqual(proc.returncode, 0, msg=f"stdout={proc.stdout}\nstderr={proc.stderr}")
            self.assertTrue(output.exists())
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(str(payload.get("suite")), "adoption_kpi_snapshot_v1")
            self.assertEqual(str(payload.get("summary", {}).get("status")), "pass")
            self.assertIn("journey_activation_success_rate_pct", payload.get("kpis", {}))
            self.assertIn("[adoption-kpi-snapshot] OK", proc.stdout)

    def test_builder_fails_when_schema_gate_failed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="amaryllis-adoption-snapshot-build-") as tmp:
            base = Path(tmp)
            reports = self._write_reports(base, schema_failed=True)
            output = base / "adoption-kpi-snapshot.json"

            proc = self._run(
                "--schema-gate-report",
                str(reports["schema"]),
                "--user-journey-report",
                str(reports["journey"]),
                "--api-quickstart-report",
                str(reports["api"]),
                "--distribution-channel-manifest-report",
                str(reports["manifest"]),
                "--output",
                str(output),
            )
            self.assertEqual(proc.returncode, 1, msg=f"stdout={proc.stdout}\nstderr={proc.stderr}")
            self.assertIn("[adoption-kpi-snapshot] FAILED", proc.stdout)


if __name__ == "__main__":
    unittest.main()
