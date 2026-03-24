from __future__ import annotations

import hashlib
import importlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from models.model_artifact_admission import sign_model_package_manifest

try:
    from fastapi.testclient import TestClient
except Exception:  # pragma: no cover
    TestClient = None  # type: ignore[assignment]


@unittest.skipIf(TestClient is None, "fastapi dependency is not available")
class ModelArtifactAdmissionAPITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(prefix="amaryllis-tests-model-artifact-api-")
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
                "AMARYLLIS_MODEL_PACKAGE_SIGNING_KEY": "fixture-model-signing-key",
                "AMARYLLIS_MODEL_PACKAGE_REQUIRE_SIGNING_KEY": "true",
            },
            clear=False,
        )
        cls._env_patch.start()

        import runtime.server as server_module

        cls.server_module = importlib.reload(server_module)
        cls.client_cm = TestClient(cls.server_module.app)
        cls.client = cls.client_cm.__enter__()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client_cm.__exit__(None, None, None)
        cls._env_patch.stop()
        cls._tmp.cleanup()

    @staticmethod
    def _auth() -> dict[str, str]:
        return {"Authorization": "Bearer admin-token"}

    def _build_manifest(self, *, root: Path, include_quant_recipe: bool = True) -> dict[str, object]:
        artifact = root / "models" / "qwen.gguf"
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_bytes(b"api-model-artifact")
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        manifest: dict[str, object] = {
            "schema_version": "amaryllis.model_package.v1",
            "artifact": {
                "model_id": "mlx-community/Qwen2.5-1.5B-Instruct-4bit",
                "provider": "mlx",
                "path": "models/qwen.gguf",
                "sha256": digest,
                "bytes": int(artifact.stat().st_size),
            },
            "quantization": {
                "method": "int4",
                "bits": 4,
                "recipe_id": "qwen2.5-int4-v1",
                "converter": "mlx-lm",
                "converter_version": "0.20.1",
            },
            "materials": [
                {
                    "path": "models/qwen.gguf",
                    "sha256": digest,
                }
            ],
            "provenance": {
                "generated_at": "2026-03-25T00:00:00+00:00",
            },
        }
        if not include_quant_recipe:
            quant = manifest.get("quantization")
            if isinstance(quant, dict):
                quant.pop("recipe_id", None)
        return sign_model_package_manifest(
            manifest,
            signing_key="fixture-model-signing-key",
            key_id="model-key-1",
            trust_level="managed",
        )

    def test_admit_model_artifact_accepts_valid_manifest(self) -> None:
        root = Path(self._tmp.name) / "case-valid"
        manifest = self._build_manifest(root=root, include_quant_recipe=True)
        response = self.client.post(
            "/models/artifacts/admit",
            headers=self._auth(),
            json={
                "manifest": manifest,
                "strict": True,
                "artifact_root": str(root),
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(bool(payload.get("admitted")))
        summary = dict(payload.get("summary") or {})
        self.assertTrue(bool(summary.get("signature_verified")))
        self.assertTrue(bool(summary.get("hash_verified")))

    def test_admit_model_artifact_rejects_missing_quant_recipe(self) -> None:
        root = Path(self._tmp.name) / "case-invalid"
        manifest = self._build_manifest(root=root, include_quant_recipe=False)
        response = self.client.post(
            "/models/artifacts/admit",
            headers=self._auth(),
            json={
                "manifest": manifest,
                "strict": True,
                "artifact_root": str(root),
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(bool(payload.get("admitted")))
        self.assertIn("quantization.recipe_id_missing", payload.get("errors", []))


if __name__ == "__main__":
    unittest.main()
