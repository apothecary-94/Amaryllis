from __future__ import annotations

import unittest

from automation.mission_policy import list_mission_policy_profiles, resolve_mission_policy_overlay


class MissionPolicyTests(unittest.TestCase):
    def test_policy_catalog_contains_required_profiles(self) -> None:
        profiles = list_mission_policy_profiles()
        profile_ids = {str(item.get("id")) for item in profiles}
        self.assertEqual(profile_ids, {"balanced", "strict", "watchdog", "release"})

    def test_resolve_profile_with_custom_override(self) -> None:
        policy = resolve_mission_policy_overlay(
            policy={"slo": {"disable_failures": 5}},
            profile="strict",
        )
        self.assertEqual(str(policy.get("profile")), "strict")
        slo = policy.get("slo")
        self.assertIsInstance(slo, dict)
        assert isinstance(slo, dict)
        self.assertEqual(int(slo.get("warning_failures", 0)), 1)
        self.assertEqual(int(slo.get("critical_failures", 0)), 2)
        self.assertEqual(int(slo.get("disable_failures", 0)), 5)

    def test_resolve_rejects_unsupported_profile(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported mission policy profile"):
            resolve_mission_policy_overlay(
                policy={},
                profile="not-supported",
            )


if __name__ == "__main__":
    unittest.main()
