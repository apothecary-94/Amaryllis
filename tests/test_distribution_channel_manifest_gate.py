from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


class DistributionChannelManifestGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo_root = Path(__file__).resolve().parents[1]
        self.script = self.repo_root / "scripts" / "release" / "distribution_channel_manifest_gate.py"

    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(self.script), *args],
            cwd=str(self.repo_root),
            capture_output=True,
            text=True,
            check=False,
        )

    def test_gate_passes_default_templates(self) -> None:
        proc = self._run()
        self.assertEqual(proc.returncode, 0, msg=f"stdout={proc.stdout}\nstderr={proc.stderr}")
        self.assertIn("[distribution-channel-manifest-gate] OK", proc.stdout)

    def test_gate_fails_when_required_placeholder_is_missing(self) -> None:
        with tempfile.TemporaryDirectory(prefix="amaryllis-channel-gate-test-") as tmp:
            copied_root = Path(tmp) / "channels"
            shutil.copytree(self.repo_root / "distribution" / "channels", copied_root)
            formula = copied_root / "homebrew" / "amaryllis.rb"
            text = formula.read_text(encoding="utf-8")
            formula.write_text(text.replace("{{MACOS_ARM64_SHA256}}", "MISSING"), encoding="utf-8")

            proc = self._run("--root", str(copied_root))
            self.assertEqual(proc.returncode, 1, msg=f"stdout={proc.stdout}\nstderr={proc.stderr}")
            self.assertIn("[distribution-channel-manifest-gate] FAILED", proc.stdout)
            self.assertIn("missing placeholders", proc.stdout)

    def test_gate_writes_report(self) -> None:
        with tempfile.TemporaryDirectory(prefix="amaryllis-channel-gate-test-") as tmp:
            output = Path(tmp) / "report.json"
            proc = self._run("--output", str(output))
            self.assertEqual(proc.returncode, 0, msg=f"stdout={proc.stdout}\nstderr={proc.stderr}")
            self.assertTrue(output.exists())
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(str(payload.get("suite")), "distribution_channel_manifest_gate_v1")
            self.assertEqual(str(payload.get("summary", {}).get("status")), "pass")


if __name__ == "__main__":
    unittest.main()
