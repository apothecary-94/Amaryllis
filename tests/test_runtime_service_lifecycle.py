from __future__ import annotations

import plistlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class RuntimeServiceLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo_root = Path(__file__).resolve().parents[1]
        self.script = self.repo_root / "scripts" / "runtime" / "manage_service.py"

    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        command = [sys.executable, str(self.script), *args]
        return subprocess.run(
            command,
            cwd=str(self.repo_root),
            capture_output=True,
            text=True,
            check=False,
        )

    def test_help_contract(self) -> None:
        proc = self._run("--help")
        self.assertEqual(proc.returncode, 0, msg=f"stdout={proc.stdout}\nstderr={proc.stderr}")
        text = (proc.stdout or "") + (proc.stderr or "")
        self.assertIn("install", text)
        self.assertIn("rollback", text)
        self.assertIn("--skip-runtime-control", text)
        self.assertIn("--manifest-dir", text)
        self.assertIn("--systemctl-bin", text)

    def test_render_linux_manifest(self) -> None:
        proc = self._run(
            "render",
            "--target",
            "linux-systemd",
            "--install-root",
            "/tmp/amaryllis",
            "--bin-dir",
            "/tmp/bin",
        )
        self.assertEqual(proc.returncode, 0, msg=f"stdout={proc.stdout}\nstderr={proc.stderr}")
        self.assertIn("[Unit]", proc.stdout)
        self.assertIn("ExecStart=/tmp/bin/amaryllis-runtime", proc.stdout)

    def test_install_and_uninstall_linux_manifest_without_runtime_control(self) -> None:
        with tempfile.TemporaryDirectory(prefix="amaryllis-runtime-lifecycle-test-") as tmp:
            manifest_dir = Path(tmp) / "systemd-user"
            manifest_path = manifest_dir / "amaryllis-runtime.service"
            backup_path = Path(f"{manifest_path}.rollback.bak")

            install = self._run(
                "install",
                "--target",
                "linux-systemd",
                "--manifest-dir",
                str(manifest_dir),
                "--install-root",
                "/tmp/amaryllis",
                "--bin-dir",
                "/tmp/bin",
                "--skip-runtime-control",
            )
            self.assertEqual(install.returncode, 0, msg=f"stdout={install.stdout}\nstderr={install.stderr}")
            self.assertTrue(manifest_path.exists())
            text = manifest_path.read_text(encoding="utf-8")
            self.assertIn("ExecStart=/tmp/bin/amaryllis-runtime", text)

            uninstall = self._run(
                "uninstall",
                "--target",
                "linux-systemd",
                "--manifest-dir",
                str(manifest_dir),
                "--skip-runtime-control",
            )
            self.assertEqual(uninstall.returncode, 0, msg=f"stdout={uninstall.stdout}\nstderr={uninstall.stderr}")
            self.assertFalse(manifest_path.exists())
            self.assertFalse(backup_path.exists())

    def test_install_macos_manifest_without_runtime_control(self) -> None:
        with tempfile.TemporaryDirectory(prefix="amaryllis-runtime-lifecycle-test-") as tmp:
            manifest_dir = Path(tmp) / "launchagents"
            manifest_path = manifest_dir / "org.amaryllis.amaryllis-runtime.plist"

            proc = self._run(
                "install",
                "--target",
                "macos-launchd",
                "--manifest-dir",
                str(manifest_dir),
                "--install-root",
                "/tmp/amaryllis",
                "--bin-dir",
                "/tmp/bin",
                "--skip-runtime-control",
            )
            self.assertEqual(proc.returncode, 0, msg=f"stdout={proc.stdout}\nstderr={proc.stderr}")
            self.assertTrue(manifest_path.exists())
            payload = plistlib.loads(manifest_path.read_bytes())
            self.assertEqual(payload.get("Label"), "org.amaryllis.amaryllis-runtime")
            self.assertEqual(payload.get("ProgramArguments"), ["/tmp/bin/amaryllis-runtime"])

    def test_rollback_restores_previous_manifest_linux_without_runtime_control(self) -> None:
        with tempfile.TemporaryDirectory(prefix="amaryllis-runtime-lifecycle-test-") as tmp:
            manifest_dir = Path(tmp) / "systemd-user"
            manifest_path = manifest_dir / "amaryllis-runtime.service"
            backup_path = Path(f"{manifest_path}.rollback.bak")
            manifest_dir.mkdir(parents=True, exist_ok=True)

            previous_manifest = (
                "[Unit]\n"
                "Description=Previous Runtime\n"
                "[Service]\n"
                "ExecStart=/tmp/previous/amaryllis-runtime\n"
            )
            manifest_path.write_text(previous_manifest, encoding="utf-8")

            install = self._run(
                "install",
                "--target",
                "linux-systemd",
                "--manifest-dir",
                str(manifest_dir),
                "--install-root",
                "/tmp/new-runtime",
                "--bin-dir",
                "/tmp/new-bin",
                "--skip-runtime-control",
            )
            self.assertEqual(install.returncode, 0, msg=f"stdout={install.stdout}\nstderr={install.stderr}")
            self.assertTrue(backup_path.exists())
            self.assertEqual(backup_path.read_text(encoding="utf-8"), previous_manifest)
            self.assertIn("ExecStart=/tmp/new-bin/amaryllis-runtime", manifest_path.read_text(encoding="utf-8"))

            rollback = self._run(
                "rollback",
                "--target",
                "linux-systemd",
                "--manifest-dir",
                str(manifest_dir),
                "--skip-runtime-control",
            )
            self.assertEqual(rollback.returncode, 0, msg=f"stdout={rollback.stdout}\nstderr={rollback.stderr}")
            self.assertEqual(manifest_path.read_text(encoding="utf-8"), previous_manifest)

    def test_install_runtime_control_failure_triggers_manifest_rollback(self) -> None:
        with tempfile.TemporaryDirectory(prefix="amaryllis-runtime-lifecycle-test-") as tmp:
            manifest_dir = Path(tmp) / "systemd-user"
            manifest_path = manifest_dir / "amaryllis-runtime.service"
            backup_path = Path(f"{manifest_path}.rollback.bak")
            manifest_dir.mkdir(parents=True, exist_ok=True)

            previous_manifest = (
                "[Unit]\n"
                "Description=Rollback Source\n"
                "[Service]\n"
                "ExecStart=/tmp/rollback-source/amaryllis-runtime\n"
            )
            manifest_path.write_text(previous_manifest, encoding="utf-8")

            install = self._run(
                "install",
                "--target",
                "linux-systemd",
                "--manifest-dir",
                str(manifest_dir),
                "--install-root",
                "/tmp/failed-runtime",
                "--bin-dir",
                "/tmp/failed-bin",
                "--systemctl-bin",
                "false",
            )
            self.assertNotEqual(install.returncode, 0, msg=f"stdout={install.stdout}\nstderr={install.stderr}")
            self.assertIn("rollback applied", (install.stderr or "") + (install.stdout or ""))
            self.assertEqual(manifest_path.read_text(encoding="utf-8"), previous_manifest)
            self.assertTrue(backup_path.exists())

    def test_rollback_without_backup_fails(self) -> None:
        with tempfile.TemporaryDirectory(prefix="amaryllis-runtime-lifecycle-test-") as tmp:
            manifest_dir = Path(tmp) / "systemd-user"
            manifest_dir.mkdir(parents=True, exist_ok=True)

            rollback = self._run(
                "rollback",
                "--target",
                "linux-systemd",
                "--manifest-dir",
                str(manifest_dir),
                "--skip-runtime-control",
            )
            self.assertNotEqual(rollback.returncode, 0)
            self.assertIn("rollback backup not found", rollback.stderr)


if __name__ == "__main__":
    unittest.main()
