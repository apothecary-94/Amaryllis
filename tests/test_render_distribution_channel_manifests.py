from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


class RenderDistributionChannelManifestsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo_root = Path(__file__).resolve().parents[1]
        self.script = self.repo_root / "scripts" / "release" / "render_distribution_channel_manifests.py"

    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(self.script), *args],
            cwd=str(self.repo_root),
            capture_output=True,
            text=True,
            check=False,
        )

    def _base_args(self, out_dir: Path, report: Path, root: Path | None = None) -> list[str]:
        args = [
            "--output-dir",
            str(out_dir),
            "--report",
            str(report),
            "--version",
            "1.2.3",
            "--windows-x64-url",
            "https://example.org/amaryllis-windows-x64.zip",
            "--windows-x64-sha256",
            "1111111111111111111111111111111111111111111111111111111111111111",
            "--macos-arm64-url",
            "https://example.org/amaryllis-macos-arm64.tar.gz",
            "--macos-arm64-sha256",
            "2222222222222222222222222222222222222222222222222222222222222222",
            "--macos-x64-url",
            "https://example.org/amaryllis-macos-x64.tar.gz",
            "--macos-x64-sha256",
            "3333333333333333333333333333333333333333333333333333333333333333",
            "--flathub-archive-url",
            "https://example.org/amaryllis-flatpak.tar.gz",
            "--flathub-archive-sha256",
            "4444444444444444444444444444444444444444444444444444444444444444",
        ]
        if root is not None:
            args.extend(["--root", str(root)])
        return args

    def test_render_success(self) -> None:
        with tempfile.TemporaryDirectory(prefix="amaryllis-render-channel-test-") as tmp:
            out_dir = Path(tmp) / "rendered"
            report = Path(tmp) / "report.json"
            proc = self._run(*self._base_args(out_dir, report))
            self.assertEqual(proc.returncode, 0, msg=f"stdout={proc.stdout}\nstderr={proc.stderr}")
            self.assertIn("[render-distribution-channel-manifests] OK", proc.stdout)
            self.assertTrue((out_dir / "homebrew" / "amaryllis.rb").exists())
            self.assertTrue((out_dir / "winget" / "Amaryllis.installer.yaml").exists())
            self.assertTrue((out_dir / "flathub" / "org.amaryllis.Amaryllis.yaml").exists())

            formula = (out_dir / "homebrew" / "amaryllis.rb").read_text(encoding="utf-8")
            self.assertIn('version "1.2.3"', formula)
            self.assertNotIn("{{", formula)

            payload = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(str(payload.get("suite")), "render_distribution_channel_manifests_v1")
            self.assertEqual(str(payload.get("summary", {}).get("status")), "pass")

    def test_render_fails_when_unknown_placeholder_remains(self) -> None:
        with tempfile.TemporaryDirectory(prefix="amaryllis-render-channel-test-") as tmp:
            copied_root = Path(tmp) / "channels"
            shutil.copytree(self.repo_root / "distribution" / "channels", copied_root)
            manifest = copied_root / "winget" / "Amaryllis.locale.en-US.yaml"
            manifest.write_text(
                manifest.read_text(encoding="utf-8") + "\nUnknown: {{UNMAPPED_TOKEN}}\n",
                encoding="utf-8",
            )

            out_dir = Path(tmp) / "rendered"
            report = Path(tmp) / "report.json"
            proc = self._run(*self._base_args(out_dir, report, root=copied_root))
            self.assertEqual(proc.returncode, 1, msg=f"stdout={proc.stdout}\nstderr={proc.stderr}")
            self.assertIn("[render-distribution-channel-manifests] FAILED", proc.stdout)
            self.assertIn("unresolved_placeholders", proc.stdout)


if __name__ == "__main__":
    unittest.main()
