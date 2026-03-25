from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class DistributionChannelRenderGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo_root = Path(__file__).resolve().parents[1]
        self.render_script = self.repo_root / "scripts" / "release" / "render_distribution_channel_manifests.py"
        self.gate_script = self.repo_root / "scripts" / "release" / "distribution_channel_render_gate.py"

    def _run_render(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(self.render_script), *args],
            cwd=str(self.repo_root),
            capture_output=True,
            text=True,
            check=False,
        )

    def _run_gate(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(self.gate_script), *args],
            cwd=str(self.repo_root),
            capture_output=True,
            text=True,
            check=False,
        )

    def _render_args(self, out_dir: Path, report: Path, *, version: str = "1.2.3") -> list[str]:
        return [
            "--output-dir",
            str(out_dir),
            "--report",
            str(report),
            "--version",
            version,
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

    def test_gate_passes_for_rendered_manifests(self) -> None:
        with tempfile.TemporaryDirectory(prefix="amaryllis-distribution-render-gate-test-") as tmp:
            out_dir = Path(tmp) / "rendered"
            render_report = Path(tmp) / "render-report.json"
            gate_report = Path(tmp) / "gate-report.json"
            render_proc = self._run_render(*self._render_args(out_dir, render_report))
            self.assertEqual(render_proc.returncode, 0, msg=f"stdout={render_proc.stdout}\nstderr={render_proc.stderr}")

            gate_proc = self._run_gate(
                "--render-report",
                str(render_report),
                "--expected-version",
                "1.2.3",
                "--output",
                str(gate_report),
            )
            self.assertEqual(gate_proc.returncode, 0, msg=f"stdout={gate_proc.stdout}\nstderr={gate_proc.stderr}")
            self.assertIn("[distribution-channel-render-gate] OK", gate_proc.stdout)
            payload = json.loads(gate_report.read_text(encoding="utf-8"))
            self.assertEqual(str(payload.get("suite")), "distribution_channel_render_gate_v1")
            self.assertEqual(str(payload.get("summary", {}).get("status")), "pass")

    def test_gate_fails_when_expected_version_differs(self) -> None:
        with tempfile.TemporaryDirectory(prefix="amaryllis-distribution-render-gate-test-") as tmp:
            out_dir = Path(tmp) / "rendered"
            render_report = Path(tmp) / "render-report.json"
            render_proc = self._run_render(*self._render_args(out_dir, render_report, version="1.2.3"))
            self.assertEqual(render_proc.returncode, 0, msg=f"stdout={render_proc.stdout}\nstderr={render_proc.stderr}")

            gate_proc = self._run_gate(
                "--render-report",
                str(render_report),
                "--expected-version",
                "1.2.4",
            )
            self.assertEqual(gate_proc.returncode, 1, msg=f"stdout={gate_proc.stdout}\nstderr={gate_proc.stderr}")
            self.assertIn("manifest.expected_version_match", gate_proc.stdout)

    def test_gate_fails_when_placeholder_remains_in_rendered_output(self) -> None:
        with tempfile.TemporaryDirectory(prefix="amaryllis-distribution-render-gate-test-") as tmp:
            out_dir = Path(tmp) / "rendered"
            render_report = Path(tmp) / "render-report.json"
            render_proc = self._run_render(*self._render_args(out_dir, render_report))
            self.assertEqual(render_proc.returncode, 0, msg=f"stdout={render_proc.stdout}\nstderr={render_proc.stderr}")

            formula = out_dir / "homebrew" / "amaryllis.rb"
            formula.write_text(formula.read_text(encoding="utf-8") + "\n# broken {{UNRESOLVED}}\n", encoding="utf-8")

            gate_proc = self._run_gate("--render-report", str(render_report))
            self.assertEqual(gate_proc.returncode, 1, msg=f"stdout={gate_proc.stdout}\nstderr={gate_proc.stderr}")
            self.assertIn("homebrew.placeholders_resolved", gate_proc.stdout)


if __name__ == "__main__":
    unittest.main()
