from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from runtime.api_compat import load_contract, validate_openapi_contract


class APICompatibilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="amaryllis-tests-api-compat-")
        support_dir = Path(self._tmp.name) / "support"
        auth_tokens = {
            "admin-token": {"user_id": "admin", "scopes": ["admin", "user"]},
            "user-token": {"user_id": "user-1", "scopes": ["user"]},
            "service-token": {"user_id": "svc-runtime", "scopes": ["service"]},
        }
        self._env_patch = patch.dict(
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
        self._env_patch.start()

        import runtime.server as server_module

        self.server_module = importlib.reload(server_module)
        self.openapi = self.server_module.app.openapi()

    def tearDown(self) -> None:
        services = self.server_module.app.state.services
        services.automation_scheduler.stop()
        if services.memory_consolidation_worker is not None:
            services.memory_consolidation_worker.stop()
        services.agent_run_manager.stop()
        services.database.close()
        services.vector_store.persist()
        self._env_patch.stop()
        self._tmp.cleanup()

    def test_openapi_matches_v1_contract(self) -> None:
        contract = load_contract(Path("contracts/api_compat_v1.json"))
        errors = validate_openapi_contract(openapi=self.openapi, contract=contract)
        self.assertEqual(errors, [])

    def test_validator_detects_missing_endpoint(self) -> None:
        contract = load_contract(Path("contracts/api_compat_v1.json"))
        tampered = json.loads(json.dumps(self.openapi))
        paths = tampered.get("paths")
        self.assertIsInstance(paths, dict)
        assert isinstance(paths, dict)
        paths.pop("/v1/models", None)
        errors = validate_openapi_contract(openapi=tampered, contract=contract)
        self.assertTrue(any("Missing path in OpenAPI schema: /v1/models" in item for item in errors))


if __name__ == "__main__":
    unittest.main()
