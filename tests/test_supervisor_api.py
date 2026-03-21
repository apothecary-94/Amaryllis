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
except Exception:  # pragma: no cover
    TestClient = None  # type: ignore[assignment]


@unittest.skipIf(TestClient is None, "fastapi dependency is not available")
class SupervisorAPITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(prefix="amaryllis-tests-supervisor-api-")
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

    @classmethod
    def tearDownClass(cls) -> None:
        cls._client_cm.__exit__(None, None, None)
        cls._env_patch.stop()
        cls._tmp.cleanup()

    @staticmethod
    def _auth(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    def _create_agent(self, *, user_token: str, user_id: str, name: str) -> str:
        response = self.client.post(
            "/agents/create",
            headers=self._auth(user_token),
            json={
                "name": name,
                "system_prompt": "supervisor-api-test",
                "user_id": user_id,
                "tools": ["web_search"],
            },
        )
        self.assertEqual(response.status_code, 200)
        return str(response.json().get("id") or "")

    def test_contract_endpoint(self) -> None:
        response = self.client.get(
            "/supervisor/graphs/contract",
            headers=self._auth("user-token"),
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("planned", payload.get("graph_statuses", []))
        self.assertIn("queued", payload.get("node_statuses", []))

    def test_create_launch_tick_and_get_graph(self) -> None:
        agent_triage = self._create_agent(user_token="user-token", user_id="user-1", name="Sup Triage")
        agent_fix = self._create_agent(user_token="user-token", user_id="user-1", name="Sup Fix")

        created = self.client.post(
            "/supervisor/graphs/create",
            headers=self._auth("user-token"),
            json={
                "user_id": "user-1",
                "objective": "Respond to production incident",
                "nodes": [
                    {
                        "node_id": "triage",
                        "agent_id": agent_triage,
                        "message": "Triage the incident",
                    },
                    {
                        "node_id": "fix",
                        "agent_id": agent_fix,
                        "message": "Prepare remediation patch",
                        "depends_on": ["triage"],
                    },
                ],
            },
        )
        self.assertEqual(created.status_code, 200)
        created_payload = created.json()
        graph = created_payload.get("supervisor_graph", {})
        graph_id = str(graph.get("id") or "")
        self.assertTrue(graph_id.startswith("sup-"))
        self.assertEqual(str(graph.get("status")), "planned")

        launched = self.client.post(
            f"/supervisor/graphs/{graph_id}/launch",
            headers=self._auth("user-token"),
            json={"session_id": "sup-api-session-1"},
        )
        self.assertEqual(launched.status_code, 200)
        launched_graph = launched.json().get("supervisor_graph", {})
        self.assertEqual(str(launched_graph.get("status")), "running")
        triage_node = next(
            item for item in launched_graph.get("nodes", []) if str(item.get("node_id")) == "triage"
        )
        self.assertIn(str(triage_node.get("status")), {"queued", "running", "succeeded"})

        ticked = self.client.post(
            f"/supervisor/graphs/{graph_id}/tick",
            headers=self._auth("user-token"),
            json={"noop": True},
        )
        self.assertEqual(ticked.status_code, 200)
        self.assertIn(
            str(ticked.json().get("supervisor_graph", {}).get("status")),
            {"running", "succeeded", "failed"},
        )

        fetched = self.client.get(
            f"/supervisor/graphs/{graph_id}",
            headers=self._auth("user-token"),
        )
        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(str(fetched.json().get("supervisor_graph", {}).get("id")), graph_id)

    def test_owner_scope_is_enforced(self) -> None:
        agent_id = self._create_agent(user_token="user-token", user_id="user-1", name="Sup Owner")
        created = self.client.post(
            "/supervisor/graphs/create",
            headers=self._auth("user-token"),
            json={
                "user_id": "user-1",
                "objective": "Owner test",
                "nodes": [
                    {
                        "node_id": "n1",
                        "agent_id": agent_id,
                        "message": "run",
                    }
                ],
            },
        )
        self.assertEqual(created.status_code, 200)
        graph_id = str(created.json().get("supervisor_graph", {}).get("id") or "")

        foreign_get = self.client.get(
            f"/supervisor/graphs/{graph_id}",
            headers=self._auth("user2-token"),
        )
        self.assertEqual(foreign_get.status_code, 403)
        self.assertEqual(str(foreign_get.json().get("error", {}).get("type")), "permission_denied")

    def test_cycle_graph_is_rejected(self) -> None:
        agent_a = self._create_agent(user_token="user-token", user_id="user-1", name="Sup A")
        agent_b = self._create_agent(user_token="user-token", user_id="user-1", name="Sup B")
        response = self.client.post(
            "/supervisor/graphs/create",
            headers=self._auth("user-token"),
            json={
                "user_id": "user-1",
                "objective": "Invalid cycle",
                "nodes": [
                    {
                        "node_id": "a",
                        "agent_id": agent_a,
                        "message": "A",
                        "depends_on": ["b"],
                    },
                    {
                        "node_id": "b",
                        "agent_id": agent_b,
                        "message": "B",
                        "depends_on": ["a"],
                    },
                ],
            },
        )
        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertEqual(str(payload.get("error", {}).get("type")), "validation_error")


if __name__ == "__main__":
    unittest.main()
