from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class PublishReleaseQualitySnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo_root = Path(__file__).resolve().parents[1]
        self.script = self.repo_root / "scripts" / "release" / "publish_release_quality_snapshot.py"

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
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def test_help_contract(self) -> None:
        proc = self._run("--help")
        self.assertEqual(proc.returncode, 0, msg=f"stdout={proc.stdout}\nstderr={proc.stderr}")
        text = (proc.stdout or "") + (proc.stderr or "")
        self.assertIn("--snapshot-report", text)
        self.assertIn("--trend-report", text)
        self.assertIn("--install-root", text)
        self.assertIn("--output-snapshot", text)

    def test_publish_snapshot_to_default_install_root_path(self) -> None:
        with tempfile.TemporaryDirectory(prefix="amaryllis-release-quality-publish-") as tmp:
            base = Path(tmp)
            snapshot = base / "snapshot.json"
            install_root = base / "install-root"
            self._write_json(
                snapshot,
                {
                    "suite": "release_quality_dashboard_v1",
                    "summary": {"status": "pass"},
                    "signals": [],
                },
            )

            proc = self._run(
                "--snapshot-report",
                str(snapshot),
                "--install-root",
                str(install_root),
            )
            self.assertEqual(proc.returncode, 0, msg=f"stdout={proc.stdout}\nstderr={proc.stderr}")
            target = install_root / "observability" / "release-quality-dashboard-latest.json"
            self.assertTrue(target.exists())
            payload = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(str(payload.get("suite")), "release_quality_dashboard_v1")

    def test_publish_snapshot_and_trend(self) -> None:
        with tempfile.TemporaryDirectory(prefix="amaryllis-release-quality-publish-") as tmp:
            base = Path(tmp)
            snapshot = base / "snapshot.json"
            trend = base / "trend.json"
            out_snapshot = base / "published" / "snapshot-latest.json"
            out_trend = base / "published" / "trend-latest.json"
            self._write_json(
                snapshot,
                {
                    "suite": "release_quality_dashboard_v1",
                    "summary": {"status": "pass"},
                    "signals": [],
                },
            )
            self._write_json(
                trend,
                {
                    "suite": "release_quality_dashboard_trend_v1",
                    "summary": {"compared_metrics": 1},
                    "comparisons": [],
                },
            )

            proc = self._run(
                "--snapshot-report",
                str(snapshot),
                "--trend-report",
                str(trend),
                "--output-snapshot",
                str(out_snapshot),
                "--output-trend",
                str(out_trend),
            )
            self.assertEqual(proc.returncode, 0, msg=f"stdout={proc.stdout}\nstderr={proc.stderr}")
            self.assertTrue(out_snapshot.exists())
            self.assertTrue(out_trend.exists())

    def test_missing_snapshot_fails(self) -> None:
        proc = self._run("--snapshot-report", "artifacts/does-not-exist.json")
        self.assertEqual(proc.returncode, 2, msg=f"stdout={proc.stdout}\nstderr={proc.stderr}")
        self.assertIn("missing snapshot report", proc.stderr.lower())


if __name__ == "__main__":
    unittest.main()
