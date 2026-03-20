from __future__ import annotations

import importlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from fastapi.testclient import TestClient
except Exception:  # pragma: no cover - dependency may be unavailable
    TestClient = None  # type: ignore[assignment]


@unittest.skipIf(TestClient is None, "fastapi dependency is not available")
class AgentRunSimulationAPITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(prefix="amaryllis-tests-run-sim-api-")
        support_dir = Path(cls._tmp.name) / "support"
        auth_tokens = {
            "admin-token": {"user_id": "admin", "scopes": ["admin", "user"]},
            "user-token": {"user_id": "user-1", "scopes": ["user"]},
            "user2-token": {"user_id": "user-2", "scopes": ["user"]},
            "service-token": {"user_id": "svc-runtime", "scopes": ["service"]},
        }
        cls._env_patch = patch.dict(
            os.environ,
            {
                "AMARYLLIS_SUPPORT_DIR": str(support_dir),
                "AMARYLLIS_AUTH_ENABLED": "true",
                "AMARYLLIS_AUTH_TOKENS": json.dumps(auth_tokens, ensure_ascii=False),
                "AMARYLLIS_MEMORY_CONSOLIDATION_ENABLED": "false",
                "AMARYLLIS_MCP_ENDPOINTS": "",
                "AMARYLLIS_SECURITY_PROFILE": "production",
            },
            clear=False,
        )
        cls._env_patch.start()

        import runtime.server as server_module

        cls.server_module = importlib.reload(server_module)
        cls._client_cm = TestClient(cls.server_module.app)
        cls.client = cls._client_cm.__enter__()
        services = cls.server_module.app.state.services
        if services.tool_registry.get("dangerous_echo") is None:
            services.tool_registry.register(
                name="dangerous_echo",
                description="High-risk test tool.",
                input_schema={"type": "object", "properties": {"echo": {"type": "string"}}},
                handler=lambda arguments: {"ok": True, "echo": str(arguments.get("echo", ""))},
                source="test",
                risk_level="high",
                approval_mode="none",
                isolation="process_internal",
            )

    @classmethod
    def tearDownClass(cls) -> None:
        cls._client_cm.__exit__(None, None, None)
        cls._env_patch.stop()
        cls._tmp.cleanup()

    @staticmethod
    def _auth(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    def test_simulation_returns_plan_risk_and_dry_run_receipt(self) -> None:
        created = self.client.post(
            "/agents/create",
            headers=self._auth("user-token"),
            json={
                "name": "Sim Agent",
                "system_prompt": "simulate",
                "user_id": "user-1",
                "tools": ["dangerous_echo", "web_search"],
            },
        )
        self.assertEqual(created.status_code, 200)
        agent_id = str(created.json().get("id"))

        response = self.client.post(
            f"/agents/{agent_id}/runs/simulate",
            headers=self._auth("user-token"),
            json={
                "user_id": "user-1",
                "message": "Find latest notes and summarize with an action plan",
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()

        simulation = payload.get("simulation", {})
        self.assertEqual(str(simulation.get("mode")), "dry_run")
        self.assertEqual(str(simulation.get("agent_id")), agent_id)
        self.assertTrue(str(simulation.get("simulation_id", "")).strip())

        plan = simulation.get("plan", [])
        self.assertTrue(isinstance(plan, list) and len(plan) >= 1)
        first_step = plan[0]
        self.assertIn("risk_tags", first_step)
        self.assertIn("rollback_hints", first_step)

        tools = simulation.get("tools", {})
        available = tools.get("available", [])
        self.assertTrue(any(str(item.get("name")) == "dangerous_echo" for item in available))
        dangerous = next(item for item in available if str(item.get("name")) == "dangerous_echo")
        self.assertEqual(str(dangerous.get("risk_level")), "high")
        self.assertIn("rollback", str(dangerous.get("rollback_hint", "")).lower())

        summary = simulation.get("risk_summary", {})
        self.assertIn(str(summary.get("overall_risk_level")), {"low", "medium", "high", "critical", "unknown"})
        self.assertGreaterEqual(int(summary.get("step_count", 0)), 1)

        run_preview = simulation.get("run_preview", {})
        budget = run_preview.get("budget", {})
        self.assertIn("max_tokens", budget)
        self.assertIn("max_duration_sec", budget)

        apply_hint = simulation.get("apply_hint", {})
        self.assertEqual(str(apply_hint.get("endpoint")), f"/agents/{agent_id}/runs")
        apply_payload = apply_hint.get("payload", {})
        self.assertEqual(str(apply_payload.get("message")), "Find latest notes and summarize with an action plan")

        receipt = payload.get("dry_run_receipt", {})
        self.assertTrue(bool(receipt.get("signature")))

    def test_simulation_cross_tenant_is_blocked(self) -> None:
        created = self.client.post(
            "/agents/create",
            headers=self._auth("user-token"),
            json={
                "name": "Owner Agent",
                "system_prompt": "owner",
                "user_id": "user-1",
                "tools": ["web_search"],
            },
        )
        self.assertEqual(created.status_code, 200)
        agent_id = str(created.json().get("id"))

        denied = self.client.post(
            f"/agents/{agent_id}/runs/simulate",
            headers=self._auth("user2-token"),
            json={
                "user_id": "user-2",
                "message": "simulate this run",
            },
        )
        self.assertEqual(denied.status_code, 403)
        payload = denied.json()
        self.assertEqual(str(payload.get("error", {}).get("type")), "permission_denied")


if __name__ == "__main__":
    unittest.main()
