from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class GoldenTasksEvalRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo_root = Path(__file__).resolve().parents[1]
        self.runner = self.repo_root / "scripts" / "eval" / "run_golden_tasks.py"

    def test_validate_only_accepts_valid_suite(self) -> None:
        suite = {
            "suite": "sample",
            "version": "1.0",
            "tasks": [
                {
                    "id": "TASK-001",
                    "title": "Sample",
                    "category": "testing",
                    "prompt": "Say hello",
                    "expected": {
                        "min_response_chars": 1,
                        "required_keywords": ["hello"],
                        "forbidden_keywords": [],
                    },
                }
            ],
        }
        with tempfile.TemporaryDirectory(prefix="amaryllis-golden-valid-") as tmp:
            suite_path = Path(tmp) / "suite.json"
            suite_path.write_text(json.dumps(suite), encoding="utf-8")
            proc = subprocess.run(
                [
                    sys.executable,
                    str(self.runner),
                    "--tasks-file",
                    str(suite_path),
                    "--validate-only",
                ],
                cwd=str(self.repo_root),
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(proc.returncode, 0)
        self.assertIn("suite validation OK", proc.stdout)

    def test_validate_only_rejects_duplicate_task_ids(self) -> None:
        suite = {
            "suite": "sample",
            "version": "1.0",
            "tasks": [
                {
                    "id": "TASK-001",
                    "title": "Sample A",
                    "category": "testing",
                    "prompt": "A",
                    "expected": {
                        "min_response_chars": 1,
                        "required_keywords": [],
                        "forbidden_keywords": [],
                    },
                },
                {
                    "id": "TASK-001",
                    "title": "Sample B",
                    "category": "testing",
                    "prompt": "B",
                    "expected": {
                        "min_response_chars": 1,
                        "required_keywords": [],
                        "forbidden_keywords": [],
                    },
                },
            ],
        }
        with tempfile.TemporaryDirectory(prefix="amaryllis-golden-invalid-") as tmp:
            suite_path = Path(tmp) / "suite.json"
            suite_path.write_text(json.dumps(suite), encoding="utf-8")
            proc = subprocess.run(
                [
                    sys.executable,
                    str(self.runner),
                    "--tasks-file",
                    str(suite_path),
                    "--validate-only",
                ],
                cwd=str(self.repo_root),
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(proc.returncode, 2)
        self.assertIn("duplicate task id", proc.stderr)


if __name__ == "__main__":
    unittest.main()
