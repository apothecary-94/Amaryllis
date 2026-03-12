from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.policy import ToolIsolationPolicy
from tools.tool_executor import ToolExecutionError, ToolExecutor
from tools.tool_registry import ToolRegistry


class ToolIsolationPolicyTests(unittest.TestCase):
    def test_strict_profile_blocks_high_risk_tools_by_default(self) -> None:
        registry = ToolRegistry()
        registry.load_builtin_tools()
        policy = ToolIsolationPolicy(profile="strict")
        executor = ToolExecutor(registry=registry, policy=policy, approval_enforcement_mode="strict")

        with self.assertRaises(ToolExecutionError) as ctx:
            executor.execute("python_exec", {"code": "print('x')", "timeout": 2})

        self.assertIn("high-risk", str(ctx.exception).lower())

    def test_filesystem_write_can_be_disabled_by_policy(self) -> None:
        with tempfile.TemporaryDirectory(prefix="amaryllis-tools-policy-") as tmp:
            root = Path(tmp)
            registry = ToolRegistry()
            registry.load_builtin_tools()
            policy = ToolIsolationPolicy(
                profile="balanced",
                filesystem_allow_write=False,
            )
            executor = ToolExecutor(registry=registry, policy=policy)

            with self.assertRaises(ToolExecutionError) as ctx:
                executor.execute(
                    "filesystem",
                    {
                        "action": "write",
                        "path": str(root / "a.txt"),
                        "content": "hello",
                    },
                )

            self.assertIn("disabled", str(ctx.exception).lower())


if __name__ == "__main__":
    unittest.main()
