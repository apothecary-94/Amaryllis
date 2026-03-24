from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from models.model_artifact_admission import (
    sign_model_package_manifest,
    validate_model_package_manifest,
)


class ModelArtifactAdmissionTests(unittest.TestCase):
    def _base_manifest(self, *, artifact_rel_path: str, artifact_sha: str, artifact_bytes: int) -> dict:
        return {
            "schema_version": "amaryllis.model_package.v1",
            "artifact": {
                "model_id": "mlx-community/Qwen2.5-1.5B-Instruct-4bit",
                "provider": "mlx",
                "path": artifact_rel_path,
                "sha256": artifact_sha,
                "bytes": artifact_bytes,
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
                    "path": artifact_rel_path,
                    "sha256": artifact_sha,
                }
            ],
            "provenance": {
                "generated_at": "2026-03-25T00:00:00+00:00",
            },
        }

    def test_valid_manifest_passes_with_signature_and_hash_verification(self) -> None:
        with tempfile.TemporaryDirectory(prefix="amaryllis-model-artifact-") as tmp:
            root = Path(tmp)
            artifact = root / "models" / "qwen.gguf"
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_bytes(b"amaryllis-model-content")

            artifact_sha = hashlib.sha256(artifact.read_bytes()).hexdigest()
            manifest = self._base_manifest(
                artifact_rel_path="models/qwen.gguf",
                artifact_sha=artifact_sha,
                artifact_bytes=int(artifact.stat().st_size),
            )
            signed = sign_model_package_manifest(
                manifest,
                signing_key="fixture-model-signing-key",
                key_id="model-key-1",
                trust_level="managed",
            )

            decision = validate_model_package_manifest(
                signed,
                signing_key="fixture-model-signing-key",
                require_signing_key=True,
                require_managed_trust=True,
                artifact_root=root,
            )
            self.assertTrue(decision.get("ok"), msg=str(decision))
            self.assertEqual(decision.get("errors"), [])
            summary = dict(decision.get("summary") or {})
            self.assertTrue(bool(summary.get("signature_verified")))
            self.assertTrue(bool(summary.get("hash_verified")))

    def test_missing_quant_recipe_is_rejected(self) -> None:
        manifest = self._base_manifest(
            artifact_rel_path="models/qwen.gguf",
            artifact_sha="a" * 64,
            artifact_bytes=16,
        )
        manifest["quantization"].pop("recipe_id", None)
        signed = sign_model_package_manifest(
            manifest,
            signing_key="fixture-model-signing-key",
            key_id="model-key-1",
            trust_level="managed",
        )

        decision = validate_model_package_manifest(
            signed,
            signing_key="fixture-model-signing-key",
            require_signing_key=True,
            require_managed_trust=True,
        )
        self.assertFalse(decision.get("ok"))
        self.assertIn("quantization.recipe_id_missing", decision.get("errors", []))

    def test_signature_mismatch_is_rejected(self) -> None:
        manifest = self._base_manifest(
            artifact_rel_path="models/qwen.gguf",
            artifact_sha="b" * 64,
            artifact_bytes=32,
        )
        signed = sign_model_package_manifest(
            manifest,
            signing_key="fixture-model-signing-key",
            key_id="model-key-1",
            trust_level="managed",
        )
        signed["provenance"]["signature"]["value"] = "c" * 64

        decision = validate_model_package_manifest(
            signed,
            signing_key="fixture-model-signing-key",
            require_signing_key=True,
            require_managed_trust=True,
        )
        self.assertFalse(decision.get("ok"))
        self.assertIn("provenance.signature_mismatch", decision.get("errors", []))

    def test_signing_key_requirement_is_enforced(self) -> None:
        manifest = self._base_manifest(
            artifact_rel_path="models/qwen.gguf",
            artifact_sha="d" * 64,
            artifact_bytes=32,
        )
        signed = sign_model_package_manifest(
            manifest,
            signing_key="fixture-model-signing-key",
            key_id="model-key-1",
            trust_level="managed",
        )

        decision = validate_model_package_manifest(
            signed,
            signing_key=None,
            require_signing_key=True,
            require_managed_trust=True,
        )
        self.assertFalse(decision.get("ok"))
        self.assertIn("signing_key_missing", decision.get("errors", []))


if __name__ == "__main__":
    unittest.main()
