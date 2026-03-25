from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from typing import Any, Iterator
from unittest.mock import patch

from models.model_manager import ModelManager
from runtime.config import AppConfig
from storage.database import Database


class _CatalogProvider:
    def __init__(
        self,
        *,
        provider: str,
        local: bool,
        supports_download: bool,
        suggested: list[str],
        installed: list[str] | None = None,
    ) -> None:
        self.provider = provider
        self.local = local
        self.supports_download = supports_download
        self.suggested = list(suggested)
        self.installed_models: set[str] = set(installed or [])
        self.download_calls = 0
        self.load_calls = 0

    def list_models(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for model_id in sorted(self.installed_models):
            rows.append(
                {
                    "id": model_id,
                    "provider": self.provider,
                    "active": False,
                    "metadata": {"size_bytes": 1024},
                }
            )
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
        self.download_calls += 1
        self.installed_models.add(model_id)
        return {
            "status": "downloaded",
            "provider": self.provider,
            "model": model_id,
            "size_bytes": 1024,
        }

    def load_model(self, model_id: str) -> dict[str, Any]:
        self.load_calls += 1
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


class ModelPackageCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="amaryllis-tests-model-package-catalog-")
        self.base = Path(self._tmp.name)
        self._original_env = os.environ.copy()

        os.environ["AMARYLLIS_SUPPORT_DIR"] = str(self.base / "support")
        os.environ["AMARYLLIS_DATA_DIR"] = str(self.base / "support" / "data")
        os.environ["AMARYLLIS_MODELS_DIR"] = str(self.base / "support" / "models")
        os.environ["AMARYLLIS_PLUGINS_DIR"] = str(self.base / "plugins")
        os.environ["AMARYLLIS_DATABASE_PATH"] = str(self.base / "support" / "data" / "state.db")
        os.environ["AMARYLLIS_VECTOR_INDEX_PATH"] = str(self.base / "support" / "data" / "semantic.index")
        os.environ["AMARYLLIS_TELEMETRY_PATH"] = str(self.base / "support" / "data" / "telemetry.jsonl")
        os.environ["AMARYLLIS_DEFAULT_PROVIDER"] = "mlx"
        os.environ["AMARYLLIS_DEFAULT_MODEL"] = "mlx-community/Qwen2.5-1.5B-Instruct-4bit"
        os.environ["AMARYLLIS_AUTH_TOKENS"] = "token-1:user-1:user"

        self.config = AppConfig.from_env()
        self.config.ensure_directories()
        self.database = Database(self.config.database_path)
        self.manager = ModelManager(config=self.config, database=self.database)

        self.mlx = _CatalogProvider(
            provider="mlx",
            local=True,
            supports_download=True,
            suggested=[
                "mlx-community/Qwen2.5-1.5B-Instruct-4bit",
                "mlx-community/Llama-3.1-8B-Instruct-4bit",
            ],
            installed=[],
        )
        self.openai = _CatalogProvider(
            provider="openai",
            local=False,
            supports_download=False,
            suggested=["gpt-4o-mini", "gpt-5"],
            installed=[],
        )
        self.manager.providers = {"mlx": self.mlx, "openai": self.openai}
        self.manager.active_provider = "mlx"
        self.manager.active_model = "mlx-community/Qwen2.5-1.5B-Instruct-4bit"

    def tearDown(self) -> None:
        self.database.close()
        os.environ.clear()
        os.environ.update(self._original_env)
        self._tmp.cleanup()

    def test_catalog_exposes_requirements_and_install_contract(self) -> None:
        with patch.object(
            self.manager,
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
            payload = self.manager.model_package_catalog(
                profile="fast",
                include_remote_providers=True,
                limit=20,
            )

        self.assertEqual(str(payload.get("catalog_version")), "model_package_catalog_v1")
        self.assertEqual(str(payload.get("selected_profile")), "fast")
        packages = payload.get("packages", [])
        self.assertTrue(packages)
        row = packages[0]
        self.assertIn("package_id", row)
        self.assertIn("requirements", row)
        self.assertIn("compatibility", row)
        install = row.get("install", {})
        self.assertEqual(str(install.get("endpoint")), "/models/packages/install")
        self.assertIn("payload", install)

    def test_install_model_package_downloads_and_activates(self) -> None:
        package_id = "mlx::mlx-community/Qwen2.5-1.5B-Instruct-4bit"
        result = self.manager.install_model_package(package_id=package_id, activate=True)
        self.assertEqual(str(result.get("package_id")), package_id)
        self.assertEqual(self.mlx.download_calls, 1)
        self.assertEqual(self.mlx.load_calls, 1)
        active = result.get("active", {})
        self.assertEqual(str(active.get("provider")), "mlx")
        self.assertEqual(str(active.get("model")), "mlx-community/Qwen2.5-1.5B-Instruct-4bit")

    def test_install_model_package_skips_download_for_remote_provider(self) -> None:
        package_id = "openai::gpt-4o-mini"
        result = self.manager.install_model_package(package_id=package_id, activate=True)
        steps = result.get("steps", [])
        self.assertTrue(steps)
        self.assertEqual(str(steps[0].get("step")), "download")
        self.assertEqual(str(steps[0].get("status")), "skipped")
        self.assertEqual(str(steps[0].get("reason")), "provider_download_not_supported")
        self.assertEqual(self.openai.download_calls, 0)
        self.assertEqual(self.openai.load_calls, 1)


if __name__ == "__main__":
    unittest.main()
