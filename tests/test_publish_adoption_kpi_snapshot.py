from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class PublishAdoptionKPISnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo_root = Path(__file__).resolve().parents[1]
        self.script = self.repo_root / "scripts" / "release" / "publish_adoption_kpi_snapshot.py"

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
        self.assertIn("--channel", text)
        self.assertIn("--expect-release-channel", text)
        self.assertIn("--install-root", text)
        self.assertIn("--output", text)

    def test_publish_release_snapshot_default_path(self) -> None:
        with tempfile.TemporaryDirectory(prefix="amaryllis-adoption-publish-") as tmp:
            base = Path(tmp)
            snapshot = base / "adoption-snapshot.json"
            install_root = base / "install-root"
            self._write_json(
                snapshot,
                {
                    "suite": "adoption_kpi_snapshot_v1",
                    "release": {"release_channel": "release"},
                    "summary": {"status": "pass"},
                },
            )

            proc = self._run(
                "--snapshot-report",
                str(snapshot),
                "--channel",
                "release",
                "--install-root",
                str(install_root),
            )
            self.assertEqual(proc.returncode, 0, msg=f"stdout={proc.stdout}\nstderr={proc.stderr}")
            output = install_root / "observability" / "adoption-kpi-snapshot-latest.json"
            self.assertTrue(output.exists())
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(str(payload.get("suite")), "adoption_kpi_snapshot_v1")

    def test_publish_nightly_snapshot_default_path(self) -> None:
        with tempfile.TemporaryDirectory(prefix="amaryllis-adoption-publish-") as tmp:
            base = Path(tmp)
            snapshot = base / "nightly-adoption-snapshot.json"
            install_root = base / "install-root"
            self._write_json(
                snapshot,
                {
                    "suite": "adoption_kpi_snapshot_v1",
                    "release": {"release_channel": "nightly"},
                    "summary": {"status": "pass"},
                },
            )

            proc = self._run(
                "--snapshot-report",
                str(snapshot),
                "--channel",
                "nightly",
                "--expect-release-channel",
                "nightly",
                "--install-root",
                str(install_root),
            )
            self.assertEqual(proc.returncode, 0, msg=f"stdout={proc.stdout}\nstderr={proc.stderr}")
            output = install_root / "observability" / "nightly-adoption-kpi-snapshot-latest.json"
            self.assertTrue(output.exists())

    def test_invalid_suite_fails(self) -> None:
        with tempfile.TemporaryDirectory(prefix="amaryllis-adoption-publish-") as tmp:
            base = Path(tmp)
            snapshot = base / "snapshot.json"
            self._write_json(snapshot, {"suite": "unexpected"})
            proc = self._run("--snapshot-report", str(snapshot))
            self.assertEqual(proc.returncode, 2, msg=f"stdout={proc.stdout}\nstderr={proc.stderr}")
            self.assertIn("unexpected snapshot suite", proc.stderr)


if __name__ == "__main__":
    unittest.main()
