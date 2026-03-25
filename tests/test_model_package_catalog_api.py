from __future__ import annotations

import importlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any, Iterator
from unittest.mock import patch

try:
    from fastapi.testclient import TestClient
except Exception:  # pragma: no cover
    TestClient = None  # type: ignore[assignment]


class _CatalogProvider:
    def __init__(
        self,
        *,
        provider: str,
        local: bool,
        supports_download: bool,
        suggested: list[str],
    ) -> None:
        self.provider = provider
        self.local = local
        self.supports_download = supports_download
        self.suggested = list(suggested)
        self.installed_models: set[str] = set()

    def list_models(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for model_id in sorted(self.installed_models):
            rows.append({"id": model_id, "provider": self.provider, "active": False, "metadata": {"size_bytes": 1024}})
        return rows

    def suggested_models(self, limit: int = 100) -> list[dict[str, Any]]:
        return [{"id": model_id, "label": model_id, "size_bytes": 1024} for model_id in self.suggested[: max(1, limit)]]

    def capabilities(self) -> dict[str, Any]:
        return {
            "local": self.local,
            "supports_download": self.supports_download,
            "supports_load": True,
            "supports_stream": True,
            "supports_tools": False,
            "requires_api_key": not self.local,
        }

    def health_check(self) -> dict[str, Any]:
        return {"status": "ok", "detail": "fixture"}

    def download_model(self, model_id: str) -> dict[str, Any]:
        if not self.supports_download:
            raise RuntimeError("download not supported")
        self.installed_models.add(model_id)
        return {
            "status": "downloaded",
            "provider": self.provider,
            "model": model_id,
            "size_bytes": 1024,
        }

    def load_model(self, model_id: str) -> dict[str, Any]:
        return {"status": "loaded", "provider": self.provider, "model": model_id}

    def chat(
        self,
        messages: list[dict[str, Any]],
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 512,
    ) -> str:
        _ = (messages, model, temperature, max_tokens)
        return "ok"

    def stream_chat(
        self,
        messages: list[dict[str, Any]],
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 512,
    ) -> Iterator[str]:
        _ = (messages, model, temperature, max_tokens)
        return iter(["ok"])


@unittest.skipIf(TestClient is None, "fastapi dependency is not available")
class ModelPackageCatalogAPITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(prefix="amaryllis-tests-model-package-api-")
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

        backend = cls.server_module.app.state.services.model_manager
        backend.providers = {
            "mlx": _CatalogProvider(
                provider="mlx",
                local=True,
                supports_download=True,
                suggested=[
                    "mlx-community/Qwen2.5-1.5B-Instruct-4bit",
                    "mlx-community/Llama-3.1-8B-Instruct-4bit",
                ],
            ),
            "openai": _CatalogProvider(
                provider="openai",
                local=False,
                supports_download=False,
                suggested=["gpt-4o-mini", "gpt-5"],
            ),
        }
        backend.active_provider = "mlx"
        backend.active_model = "mlx-community/Qwen2.5-1.5B-Instruct-4bit"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client_cm.__exit__(None, None, None)
        cls._env_patch.stop()
        cls._tmp.cleanup()

    @staticmethod
    def _auth() -> dict[str, str]:
        return {"Authorization": "Bearer admin-token"}

    def test_model_package_catalog_endpoint_returns_packages(self) -> None:
        backend = self.server_module.app.state.services.model_manager
        manager = getattr(backend, "manager", backend)
        with patch.object(
            manager,
            "_onboarding_hardware_snapshot",
            return_value={
                "platform": "darwin",
                "machine": "arm64",
                "cpu_count_logical": 8,
                "memory_bytes": 12 * 1024 * 1024 * 1024,
                "memory_gb": 12.0,
                "provider_count": 2,
                "local_provider_available": True,
                "cloud_provider_available": True,
            },
        ):
            response = self.client.get(
                "/models/packages?profile=fast&include_remote_providers=true&limit=20",
                headers=self._auth(),
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(str(payload.get("catalog_version")), "model_package_catalog_v1")
        self.assertEqual(str(payload.get("selected_profile")), "fast")
        self.assertIn("request_id", payload)
        packages = payload.get("packages", [])
        self.assertIsInstance(packages, list)
        self.assertTrue(packages)
        self.assertIn("package_id", packages[0])

    def test_model_package_install_endpoint_runs_install_flow(self) -> None:
        package_id = "mlx::mlx-community/Qwen2.5-1.5B-Instruct-4bit"
        response = self.client.post(
            "/models/packages/install",
            headers=self._auth(),
            json={"package_id": package_id, "activate": True},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(str(payload.get("package_id")), package_id)
        self.assertIn("steps", payload)
        self.assertIn("request_id", payload)


if __name__ == "__main__":
    unittest.main()
