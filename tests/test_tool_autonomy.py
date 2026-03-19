from __future__ import annotations

import unittest

from tools.autonomy_policy import AutonomyPolicy, normalize_autonomy_level
from tools.policy import ToolIsolationPolicy
from tools.tool_executor import ToolExecutionError, ToolExecutor
from tools.tool_registry import ToolRegistry


def _build_registry_with_medium_and_high_tools() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        name="medium_echo",
        description="Medium-risk synthetic tool",
        input_schema={"type": "object", "properties": {"text": {"type": "string"}}},
        handler=lambda arguments: {"echo": str(arguments.get("text", ""))},
        risk_level="medium",
        approval_mode="none",
        source="test",
    )
    registry.register(
        name="high_echo",
        description="High-risk synthetic tool",
        input_schema={"type": "object", "properties": {"text": {"type": "string"}}},
        handler=lambda arguments: {"echo": str(arguments.get("text", ""))},
        risk_level="high",
        approval_mode="none",
        source="test",
    )
    return registry


class ToolAutonomyTests(unittest.TestCase):
    def test_invalid_autonomy_level_normalizes_to_l3(self) -> None:
        self.assertEqual(normalize_autonomy_level("invalid"), "l3")
        self.assertEqual(normalize_autonomy_level("L4"), "l4")

    def test_l0_blocks_low_risk_tool_execution(self) -> None:
        registry = ToolRegistry()
        registry.load_builtin_tools()
        executor = ToolExecutor(
            registry=registry,
            policy=ToolIsolationPolicy(profile="balanced"),
            autonomy_policy=AutonomyPolicy(level="l0"),
            approval_enforcement_mode="strict",
        )

        with self.assertRaises(ToolExecutionError) as ctx:
            executor.execute("web_search", {"query": "local test"})

        self.assertIn("autonomy level l0", str(ctx.exception).lower())

    def test_l2_blocks_high_risk_even_when_policy_would_allow_with_approval(self) -> None:
        registry = _build_registry_with_medium_and_high_tools()
        executor = ToolExecutor(
            registry=registry,
            policy=ToolIsolationPolicy(profile="balanced"),
            autonomy_policy=AutonomyPolicy(level="l2"),
            approval_enforcement_mode="prompt_and_allow",
        )

        with self.assertRaises(ToolExecutionError) as ctx:
            executor.execute("high_echo", {"text": "x"})

        self.assertIn("autonomy level l2 blocks high-risk", str(ctx.exception).lower())

    def test_l2_requires_approval_for_medium_risk_tool(self) -> None:
        registry = _build_registry_with_medium_and_high_tools()
        executor = ToolExecutor(
            registry=registry,
            policy=ToolIsolationPolicy(profile="balanced"),
            autonomy_policy=AutonomyPolicy(level="l2"),
            approval_enforcement_mode="prompt_and_allow",
        )

        result = executor.execute("medium_echo", {"text": "x"})
        self.assertEqual(result["tool"], "medium_echo")
        self.assertIn("permission_prompt", result)

    def test_debug_guardrails_exposes_autonomy_policy(self) -> None:
        registry = _build_registry_with_medium_and_high_tools()
        executor = ToolExecutor(
            registry=registry,
            policy=ToolIsolationPolicy(profile="balanced"),
            autonomy_policy=AutonomyPolicy(level="l4"),
            approval_enforcement_mode="strict",
        )

        snapshot = executor.debug_guardrails()
        autonomy = snapshot.get("autonomy_policy")
        self.assertIsInstance(autonomy, dict)
        assert isinstance(autonomy, dict)
        self.assertEqual(autonomy.get("level"), "l4")


if __name__ == "__main__":
    unittest.main()
