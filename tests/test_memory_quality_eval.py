from __future__ import annotations

import unittest

from memory.eval_suite import MemoryQualityEvaluator


class MemoryQualityEvalTests(unittest.TestCase):
    def test_core_suite_runs_and_reports_cases(self) -> None:
        evaluator = MemoryQualityEvaluator(
            profile_decay_enabled=True,
            profile_decay_half_life_days=45,
            profile_decay_floor=0.35,
            profile_decay_min_delta=0.05,
        )
        report = evaluator.run("core")

        self.assertEqual(report["suite"], "core")
        self.assertGreaterEqual(int(report["total_cases"]), 4)
        self.assertEqual(int(report["total_cases"]), len(report["cases"]))
        self.assertGreaterEqual(float(report["pass_rate"]), 0.75)

        case_ids = {str(item.get("id")) for item in report["cases"]}
        self.assertIn("profile_decay_overwrite", case_ids)
        self.assertIn("semantic_consolidation_strength", case_ids)
        self.assertIn("retrieval_ranking_quality", case_ids)
        self.assertIn("extraction_coverage", case_ids)

    def test_extended_suite_includes_conflict_audit_case(self) -> None:
        evaluator = MemoryQualityEvaluator()
        report = evaluator.run("extended")

        self.assertEqual(report["suite"], "extended")
        self.assertGreaterEqual(int(report["total_cases"]), 5)
        case_ids = {str(item.get("id")) for item in report["cases"]}
        self.assertIn("conflict_audit_coverage", case_ids)

    def test_invalid_suite_raises(self) -> None:
        evaluator = MemoryQualityEvaluator()
        with self.assertRaises(ValueError):
            evaluator.run("unknown")


if __name__ == "__main__":
    unittest.main()
