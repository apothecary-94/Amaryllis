from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest


class DependencyDriftCheckTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo_root = Path(__file__).resolve().parents[1]
        self.script = self.repo_root / "scripts" / "release" / "check_dependency_drift.py"

    def _run(self, requirements_text: str, lock_text: str) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory(prefix="amaryllis-drift-") as tmp:
            tmp_path = Path(tmp)
            req = tmp_path / "requirements.txt"
            lock = tmp_path / "requirements.lock"
            req.write_text(requirements_text, encoding="utf-8")
            lock.write_text(lock_text, encoding="utf-8")
            return subprocess.run(
                [
                    sys.executable,
                    str(self.script),
                    "--requirements",
                    str(req),
                    "--lock",
                    str(lock),
                ],
                cwd=str(self.repo_root),
                capture_output=True,
                text=True,
                check=False,
            )

    def test_ok_when_lock_contains_all_entries(self) -> None:
        proc = self._run(
            requirements_text=textwrap.dedent(
                """
                fastapi>=0.1.0
                uvicorn[standard]>=0.1.0
                """
            ),
            lock_text=textwrap.dedent(
                """
                fastapi==0.2.0
                uvicorn[standard]==0.2.0
                """
            ),
        )
        self.assertEqual(proc.returncode, 0)
        self.assertIn("dependency drift check OK", proc.stdout)

    def test_fails_when_lock_is_missing_entry(self) -> None:
        proc = self._run(
            requirements_text=textwrap.dedent(
                """
                fastapi>=0.1.0
                httpx>=0.1.0
                """
            ),
            lock_text="fastapi==0.2.0\n",
        )
        self.assertEqual(proc.returncode, 1)
        self.assertIn("missing in lock: httpx", proc.stderr)

    def test_fails_when_lock_entry_not_pinned(self) -> None:
        proc = self._run(
            requirements_text="fastapi>=0.1.0\n",
            lock_text="fastapi>=0.2.0\n",
        )
        self.assertEqual(proc.returncode, 1)
        self.assertIn("lock entry must use == pin", proc.stderr)


if __name__ == "__main__":
    unittest.main()
