from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from models.model_manager import ModelManager
from runtime.config import AppConfig
from storage.database import Database


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

    def list_models(self) -> list[dict[str, Any]]:
        return [{"id": model_id, "metadata": {"source": "fixture"}} for model_id in self._model_ids]

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


class ModelOnboardingProfileTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="amaryllis-tests-model-onboarding-")
        self.base = Path(self._tmp.name)
        self._original_env = os.environ.copy()
        os.environ["AMARYLLIS_SUPPORT_DIR"] = str(self.base / "support")
        os.environ["AMARYLLIS_DATA_DIR"] = str(self.base / "support" / "data")
        os.environ["AMARYLLIS_MODELS_DIR"] = str(self.base / "support" / "models")
        os.environ["AMARYLLIS_PLUGINS_DIR"] = str(self.base / "plugins")
        os.environ["AMARYLLIS_DATABASE_PATH"] = str(self.base / "support" / "data" / "state.db")
        os.environ["AMARYLLIS_VECTOR_INDEX_PATH"] = str(self.base / "support" / "data" / "semantic.index")
        os.environ["AMARYLLIS_TELEMETRY_PATH"] = str(self.base / "support" / "data" / "telemetry.jsonl")
        os.environ["AMARYLLIS_AUTH_TOKENS"] = "token-1:user-1:user"
        os.environ["AMARYLLIS_DEFAULT_PROVIDER"] = "mlx"
        os.environ["AMARYLLIS_DEFAULT_MODEL"] = "mlx-community/Qwen2.5-1.5B-Instruct-4bit"

        self.config = AppConfig.from_env()
        self.config.ensure_directories()
        self.database = Database(self.config.database_path)
        self.manager = ModelManager(config=self.config, database=self.database)
        self.manager.providers = {
            "mlx": _FakeProvider(
                model_ids=[
                    "mlx-community/Qwen2.5-1.5B-Instruct-4bit",
                    "mlx-community/Llama-3.1-8B-Instruct",
                ],
                local=True,
                requires_api_key=False,
            ),
            "openai": _FakeProvider(
                model_ids=[
                    "gpt-4o-mini",
                    "gpt-5",
                ],
                local=False,
                requires_api_key=True,
            ),
        }
        self.manager.active_provider = "mlx"
        self.manager.active_model = "mlx-community/Qwen2.5-1.5B-Instruct-4bit"

    def tearDown(self) -> None:
        self.database.close()
        os.environ.clear()
        os.environ.update(self._original_env)
        self._tmp.cleanup()

    def test_low_resource_hardware_prefers_fast_profile(self) -> None:
        with patch.object(
            self.manager,
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
            payload = self.manager.recommend_onboarding_profile()

        self.assertEqual(str(payload.get("recommended_profile")), "fast")
        reason_codes = payload.get("reason_codes", [])
        self.assertIn("low_memory", reason_codes)
        profiles = payload.get("profiles", {})
        fast = profiles.get("fast", {})
        selected = fast.get("selected", {})
        self.assertEqual(str(fast.get("route_mode")), "local_first")
        self.assertEqual(str(selected.get("provider")), "mlx")

    def test_high_resource_hardware_prefers_quality_profile(self) -> None:
        with patch.object(
            self.manager,
            "_onboarding_hardware_snapshot",
            return_value={
                "platform": "darwin",
                "machine": "arm64",
                "cpu_count_logical": 12,
                "memory_bytes": 64 * 1024 * 1024 * 1024,
                "memory_gb": 64.0,
                "provider_count": 2,
                "local_provider_available": True,
                "cloud_provider_available": True,
            },
        ):
            payload = self.manager.recommend_onboarding_profile()

        self.assertEqual(str(payload.get("recommended_profile")), "quality")
        reason_codes = payload.get("reason_codes", [])
        self.assertIn("high_compute_headroom", reason_codes)
        profiles = payload.get("profiles", {})
        quality = profiles.get("quality", {})
        selected = quality.get("selected", {})
        self.assertEqual(str(quality.get("route_mode")), "quality_first")
        self.assertEqual(str(selected.get("provider")), "openai")
        self.assertEqual(str(selected.get("model")), "gpt-5")

    def test_falls_back_to_active_model_when_no_candidates_available(self) -> None:
        self.manager.providers = {}
        self.manager.active_provider = "mlx"
        self.manager.active_model = "fallback-model"
        with patch.object(
            self.manager,
            "_onboarding_hardware_snapshot",
            return_value={
                "platform": "darwin",
                "machine": "arm64",
                "cpu_count_logical": 8,
                "memory_bytes": 16 * 1024 * 1024 * 1024,
                "memory_gb": 16.0,
                "provider_count": 1,
                "local_provider_available": True,
                "cloud_provider_available": False,
            },
        ):
            payload = self.manager.recommend_onboarding_profile()

        balanced = payload.get("profiles", {}).get("balanced", {})
        selected = balanced.get("selected", {})
        self.assertEqual(str(selected.get("provider")), "mlx")
        self.assertEqual(str(selected.get("model")), "fallback-model")
        self.assertEqual(str(selected.get("reason")), "fallback_active_model")


if __name__ == "__main__":
    unittest.main()
