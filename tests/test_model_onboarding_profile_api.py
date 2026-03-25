from __future__ import annotations

import importlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

try:
    from fastapi.testclient import TestClient
except Exception:  # pragma: no cover
    TestClient = None  # type: ignore[assignment]


class _FakeProvider:
    def __init__(
        self,
        *,
        model_ids: list[str],
        local: bool,
        requires_api_key: bool,
    ) -> None:
        self._model_ids = list(model_ids)
        self._local = bool(local)
        self._requires_api_key = bool(requires_api_key)
        self._loaded_model: str | None = None

    def list_models(self) -> list[dict[str, Any]]:
        rows = []
        for model_id in self._model_ids:
            rows.append(
                {
                    "id": model_id,
                    "metadata": {"source": "fixture"},
                    "active": model_id == self._loaded_model,
                }
            )
        return rows

    def suggested_models(self, limit: int = 100) -> list[dict[str, Any]]:
        return [{"id": model_id, "label": model_id} for model_id in self._model_ids[: max(1, limit)]]

    def capabilities(self) -> dict[str, Any]:
        return {
            "local": self._local,
            "supports_download": self._local,
            "supports_load": True,
            "supports_stream": True,
            "supports_tools": False,
            "requires_api_key": self._requires_api_key,
        }

    def download_model(self, model_id: str) -> dict[str, Any]:
        _ = model_id
        return {"status": "downloaded", "provider": "fixture", "model": model_id}

    def load_model(self, model_id: str) -> dict[str, Any]:
        self._loaded_model = model_id
        return {"status": "loaded", "provider": "fixture", "model": model_id}

    def chat(
        self,
        messages: list[dict[str, Any]],
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 512,
    ) -> str:
        _ = (temperature, max_tokens)
        prompt = ""
        for item in messages:
            if str(item.get("role")) == "user":
                prompt = str(item.get("content", "")).strip()
                break
        return f"fixture-ready:{model}:{prompt[:48]}"


@unittest.skipIf(TestClient is None, "fastapi dependency is not available")
class ModelOnboardingProfileAPITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(prefix="amaryllis-tests-model-onboarding-api-")
        support_dir = Path(cls._tmp.name) / "support"
        auth_tokens = {
            "admin-token": {
                "user_id": "admin",
                "scopes": ["admin", "user"],
            }
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
                "AMARYLLIS_DEFAULT_PROVIDER": "mlx",
                "AMARYLLIS_DEFAULT_MODEL": "mlx-community/Qwen2.5-1.5B-Instruct-4bit",
            },
            clear=False,
        )
        cls._env_patch.start()

        import runtime.server as server_module

        cls.server_module = importlib.reload(server_module)
        cls.client_cm = TestClient(cls.server_module.app)
        cls.client = cls.client_cm.__enter__()

        model_backend = cls.server_module.app.state.services.model_manager
        model_backend.providers = {
            "mlx": _FakeProvider(
                model_ids=[
                    "mlx-community/Qwen2.5-1.5B-Instruct-4bit",
                    "mlx-community/Llama-3.1-8B-Instruct",
                ],
                local=True,
                requires_api_key=False,
            ),
            "openai": _FakeProvider(
                model_ids=["gpt-4o-mini", "gpt-5"],
                local=False,
                requires_api_key=True,
            ),
        }
        model_backend.active_provider = "mlx"
        model_backend.active_model = "mlx-community/Qwen2.5-1.5B-Instruct-4bit"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client_cm.__exit__(None, None, None)
        cls._env_patch.stop()
        cls._tmp.cleanup()

    @staticmethod
    def _auth() -> dict[str, str]:
        return {"Authorization": "Bearer admin-token"}

    def test_onboarding_profile_endpoint_returns_recommendation_payload(self) -> None:
        backend = self.server_module.app.state.services.model_manager
        manager = getattr(backend, "manager", backend)
        with patch.object(
            manager,
            "_onboarding_hardware_snapshot",
            return_value={
                "platform": "darwin",
                "machine": "arm64",
                "cpu_count_logical": 4,
                "memory_bytes": 8 * 1024 * 1024 * 1024,
                "memory_gb": 8.0,
                "provider_count": 2,
                "local_provider_available": True,
                "cloud_provider_available": True,
            },
        ):
            response = self.client.get("/models/onboarding/profile", headers=self._auth())

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("request_id", payload)
        self.assertEqual(str(payload.get("recommended_profile")), "fast")
        profiles = payload.get("profiles", {})
        self.assertIsInstance(profiles, dict)
        self.assertEqual(set(profiles.keys()), {"fast", "balanced", "quality"})
        fast_selected = profiles.get("fast", {}).get("selected", {})
        self.assertEqual(str(fast_selected.get("provider")), "mlx")

    def test_onboarding_activation_plan_endpoint_returns_install_ready_payload(self) -> None:
        backend = self.server_module.app.state.services.model_manager
        manager = getattr(backend, "manager", backend)
        with patch.object(
            manager,
            "_onboarding_hardware_snapshot",
            return_value={
                "platform": "darwin",
                "machine": "arm64",
                "cpu_count_logical": 8,
                "memory_bytes": 16 * 1024 * 1024 * 1024,
                "memory_gb": 16.0,
                "provider_count": 2,
                "local_provider_available": True,
                "cloud_provider_available": True,
            },
        ):
            response = self.client.get(
                "/models/onboarding/activation-plan?profile=balanced&include_remote_providers=true&limit=20&require_metadata=false",
                headers=self._auth(),
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(str(payload.get("plan_version")), "onboarding_activation_plan_v1")
        self.assertEqual(str(payload.get("selected_profile")), "balanced")
        self.assertTrue(str(payload.get("selected_package_id", "")).strip())
        self.assertIn("license_admission", payload)
        self.assertIn("request_id", payload)

    def test_onboarding_activation_plan_endpoint_returns_blockers_when_denied(self) -> None:
        backend = self.server_module.app.state.services.model_manager
        manager = getattr(backend, "manager", backend)

        def _deny(*, package_id: str, require_metadata: bool | None = None) -> dict[str, Any]:
            _ = require_metadata
            return {
                "package_id": package_id,
                "provider": "mlx",
                "model": "blocked-model",
                "status": "deny",
                "admitted": False,
                "errors": ["license.spdx_denied"],
                "warnings": [],
                "summary": {"license_policy_id": "amaryllis.license_admission.v1"},
                "require_metadata": False,
            }

        with patch.object(manager, "model_package_license_admission", side_effect=_deny):
            response = self.client.get(
                "/models/onboarding/activation-plan?profile=balanced&require_metadata=false",
                headers=self._auth(),
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(bool(payload.get("ready_to_install")))
        self.assertEqual(str(payload.get("next_action")), "resolve_blockers")
        blockers = [str(item) for item in payload.get("blockers", [])]
        self.assertIn("license.spdx_denied", blockers)

    def test_onboarding_activate_endpoint_returns_activation_payload(self) -> None:
        response = self.client.post(
            "/models/onboarding/activate",
            headers=self._auth(),
            json={
                "profile": "balanced",
                "include_remote_providers": True,
                "limit": 20,
                "require_metadata": False,
                "activate": True,
                "run_smoke_test": True,
                "smoke_prompt": "ping",
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(str(payload.get("activation_version")), "onboarding_activate_v1")
        self.assertIn(str(payload.get("status")), {"activated", "activated_with_smoke_warning"})
        self.assertIn("selected_package_id", payload)
        self.assertIn("action_receipt", payload)
        self.assertTrue(bool((payload.get("action_receipt") or {}).get("signature")))
        self.assertIn("request_id", payload)

    def test_onboarding_activate_endpoint_returns_blocked_status_when_plan_is_blocked(self) -> None:
        backend = self.server_module.app.state.services.model_manager
        manager = getattr(backend, "manager", backend)
        blocked_plan = {
            "plan_version": "onboarding_activation_plan_v1",
            "selected_profile": "balanced",
            "selected_package_id": "mlx::blocked-model",
            "ready_to_install": False,
            "blockers": ["license.spdx_denied"],
            "active": {"provider": "mlx", "model": "mlx-community/Qwen2.5-1.5B-Instruct-4bit"},
        }
        with patch.object(manager, "onboarding_activation_plan", return_value=blocked_plan):
            response = self.client.post(
                "/models/onboarding/activate",
                headers=self._auth(),
                json={
                    "profile": "balanced",
                    "activate": True,
                    "run_smoke_test": True,
                },
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(str(payload.get("status")), "blocked")
        self.assertFalse(bool(payload.get("ready")))
        blockers = [str(item) for item in payload.get("blockers", [])]
        self.assertIn("license.spdx_denied", blockers)


if __name__ == "__main__":
    unittest.main()
