from __future__ import annotations

import copy
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
from typing import Any

_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
_SPDX_RE = re.compile(r"^[a-z0-9.\-+]+$", re.IGNORECASE)
_DEFAULT_LICENSE_POLICY: dict[str, Any] = {
    "policy_id": "amaryllis.license_admission.v1",
    "allow_spdx_ids": [
        "apache-2.0",
        "mit",
        "bsd-2-clause",
        "bsd-3-clause",
        "mpl-2.0",
        "cc-by-4.0",
        "cc-by-sa-4.0",
        "cc0-1.0",
    ],
    "deny_spdx_ids": [
        "agpl-3.0",
        "agpl-3.0-only",
        "agpl-3.0-or-later",
        "gpl-3.0",
        "gpl-3.0-only",
        "gpl-3.0-or-later",
        "gpl-2.0",
        "gpl-2.0-only",
        "gpl-2.0-or-later",
    ],
    "allow_unknown_spdx": False,
    "allow_noncommercial": False,
    "allow_no_derivatives": False,
    "allow_share_alike": True,
}


def validate_model_package_manifest(
    manifest: dict[str, Any],
    *,
    signing_key: str | None = None,
    require_signing_key: bool = False,
    require_managed_trust: bool = True,
    artifact_root: str | Path | None = None,
    license_policy: dict[str, Any] | None = None,
    license_policy_path: str | Path | None = None,
    require_license_policy: bool = True,
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []

    payload = manifest if isinstance(manifest, dict) else {}
    if not isinstance(manifest, dict):
        errors.append("manifest_must_be_object")

    schema_version = str(payload.get("schema_version") or "").strip()
    if schema_version != "amaryllis.model_package.v1":
        errors.append("schema_version_mismatch")

    artifact_raw = payload.get("artifact")
    artifact = artifact_raw if isinstance(artifact_raw, dict) else {}
    if not artifact:
        errors.append("artifact_missing")

    model_id = str(artifact.get("model_id") or "").strip()
    if not model_id:
        errors.append("artifact.model_id_missing")

    artifact_sha = _normalized_sha256(artifact.get("sha256"))
    if artifact_sha is None:
        errors.append("artifact.sha256_invalid")

    artifact_bytes: int | None = None
    try:
        if artifact.get("bytes") is not None:
            artifact_bytes = int(artifact.get("bytes"))
            if artifact_bytes <= 0:
                errors.append("artifact.bytes_invalid")
    except Exception:
        errors.append("artifact.bytes_invalid")

    materials_raw = payload.get("materials")
    materials = materials_raw if isinstance(materials_raw, list) else []
    if not materials:
        errors.append("materials_missing")
    else:
        for index, item in enumerate(materials):
            if not isinstance(item, dict):
                errors.append(f"materials[{index}]_must_be_object")
                continue
            item_path = str(item.get("path") or "").strip()
            if not item_path:
                errors.append(f"materials[{index}].path_missing")
            if _normalized_sha256(item.get("sha256")) is None:
                errors.append(f"materials[{index}].sha256_invalid")

    quant_raw = payload.get("quantization")
    quant = quant_raw if isinstance(quant_raw, dict) else {}
    if not quant:
        errors.append("quantization_missing")

    quant_method = str(quant.get("method") or "").strip()
    if not quant_method:
        errors.append("quantization.method_missing")

    quant_recipe = str(quant.get("recipe_id") or "").strip()
    if not quant_recipe:
        errors.append("quantization.recipe_id_missing")

    quant_converter = str(quant.get("converter") or "").strip()
    if not quant_converter:
        errors.append("quantization.converter_missing")

    quant_converter_version = str(quant.get("converter_version") or "").strip()
    if not quant_converter_version:
        errors.append("quantization.converter_version_missing")

    quant_bits: int | None = None
    try:
        if quant.get("bits") is None:
            errors.append("quantization.bits_missing")
        else:
            quant_bits = int(quant.get("bits"))
            if quant_bits <= 0:
                errors.append("quantization.bits_invalid")
    except Exception:
        errors.append("quantization.bits_invalid")

    provenance_raw = payload.get("provenance")
    provenance = provenance_raw if isinstance(provenance_raw, dict) else {}
    if not provenance:
        errors.append("provenance_missing")

    generated_at = str(provenance.get("generated_at") or "").strip()
    if not generated_at:
        errors.append("provenance.generated_at_missing")

    signature_raw = provenance.get("signature")
    signature = signature_raw if isinstance(signature_raw, dict) else {}
    if not signature:
        errors.append("provenance.signature_missing")

    signature_algorithm = str(signature.get("algorithm") or "").strip().lower()
    if signature_algorithm != "hmac-sha256":
        errors.append("provenance.signature.algorithm_invalid")

    signature_key_id = str(signature.get("key_id") or "").strip()
    if not signature_key_id:
        errors.append("provenance.signature.key_id_missing")

    signature_value = _normalized_sha256(signature.get("value"))
    if signature_value is None:
        errors.append("provenance.signature.value_invalid")

    signature_trust_level = str(signature.get("trust_level") or "").strip().lower()
    if not signature_trust_level:
        errors.append("provenance.signature.trust_level_missing")
    elif signature_trust_level not in {"managed", "development"}:
        errors.append("provenance.signature.trust_level_invalid")
    elif require_managed_trust and signature_trust_level != "managed":
        errors.append("provenance.signature.trust_level_not_managed")

    signature_verified = False
    if signature_value is not None:
        if signing_key:
            expected = _sign_canonical_manifest(payload=payload, signing_key=signing_key)
            if hmac.compare_digest(expected, signature_value):
                signature_verified = True
            else:
                errors.append("provenance.signature_mismatch")
        else:
            if require_signing_key:
                errors.append("signing_key_missing")
            else:
                warnings.append("signing_key_missing_signature_not_verified")

    hash_verified = False
    artifact_path = _resolve_artifact_path(artifact=artifact, artifact_root=artifact_root)
    if artifact_path is not None:
        if not artifact_path.exists() or not artifact_path.is_file():
            errors.append("artifact.path_not_found")
        else:
            actual_sha = _sha256_file(artifact_path)
            actual_bytes = int(artifact_path.stat().st_size)
            if artifact_sha is not None and actual_sha != artifact_sha:
                errors.append("artifact.sha256_mismatch")
            if artifact_bytes is not None and actual_bytes != artifact_bytes:
                errors.append("artifact.bytes_mismatch")
            if artifact_sha is not None and (artifact_bytes is None or actual_bytes == artifact_bytes):
                if actual_sha == artifact_sha:
                    hash_verified = True
    elif str(artifact.get("path") or "").strip():
        warnings.append("artifact.path_present_but_artifact_root_missing")

    license_errors_start = len(errors)
    resolved_license_policy = _resolve_license_policy(
        license_policy=license_policy,
        license_policy_path=license_policy_path,
        require_license_policy=require_license_policy,
        errors=errors,
        warnings=warnings,
    )

    license_raw = payload.get("license")
    license_payload = license_raw if isinstance(license_raw, dict) else {}
    if not license_payload:
        errors.append("license_missing")

    license_spdx = _normalized_spdx_id(license_payload.get("spdx_id"))
    if license_spdx is None:
        errors.append("license.spdx_id_invalid_or_missing")

    license_source = str(license_payload.get("source") or "").strip()
    if not license_source:
        errors.append("license.source_missing")

    allows_commercial_use = _required_bool(
        payload=license_payload,
        key="allows_commercial_use",
        errors=errors,
        missing_error="license.allows_commercial_use_missing",
        invalid_error="license.allows_commercial_use_invalid",
    )
    allows_derivatives = _required_bool(
        payload=license_payload,
        key="allows_derivatives",
        errors=errors,
        missing_error="license.allows_derivatives_missing",
        invalid_error="license.allows_derivatives_invalid",
    )
    requires_share_alike = _optional_bool(
        payload=license_payload,
        key="requires_share_alike",
        errors=errors,
        invalid_error="license.requires_share_alike_invalid",
        default=False,
    )
    license_restrictions = _normalized_string_list(license_payload.get("restrictions"))

    policy_allow = set(_normalized_string_list(resolved_license_policy.get("allow_spdx_ids")))
    policy_deny = set(_normalized_string_list(resolved_license_policy.get("deny_spdx_ids")))

    if license_spdx:
        if license_spdx in policy_deny:
            errors.append("license.spdx_denied")
        elif not bool(resolved_license_policy.get("allow_unknown_spdx")) and license_spdx not in policy_allow:
            errors.append("license.spdx_not_allowed")

    if allows_commercial_use is False and not bool(resolved_license_policy.get("allow_noncommercial")):
        errors.append("license.commercial_use_prohibited")
    if allows_derivatives is False and not bool(resolved_license_policy.get("allow_no_derivatives")):
        errors.append("license.derivatives_prohibited")
    if requires_share_alike and not bool(resolved_license_policy.get("allow_share_alike")):
        errors.append("license.share_alike_not_allowed")

    license_checks_failed = max(0, len(errors) - license_errors_start)

    quant_metadata_complete = all(
        [
            bool(quant_method),
            bool(quant_recipe),
            bool(quant_converter),
            bool(quant_converter_version),
            isinstance(quant_bits, int) and quant_bits > 0,
        ]
    )
    hash_metadata_complete = bool(artifact_sha) and bool(materials)
    has_signature = bool(signature_value)

    return {
        "ok": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "summary": {
            "schema_version": schema_version or None,
            "model_id": model_id or None,
            "quant_metadata_complete": quant_metadata_complete,
            "hash_metadata_complete": hash_metadata_complete,
            "has_signature": has_signature,
            "signature_verified": signature_verified,
            "hash_verified": hash_verified,
            "license_policy_id": str(resolved_license_policy.get("policy_id") or "").strip() or None,
            "license_spdx_id": license_spdx,
            "license_source": license_source or None,
            "license_restrictions": license_restrictions,
            "license_checks_failed": int(license_checks_failed),
            "checks_failed": len(errors),
            "checks_warning": len(warnings),
        },
    }


def sign_model_package_manifest(
    manifest: dict[str, Any],
    *,
    signing_key: str,
    key_id: str,
    trust_level: str = "managed",
) -> dict[str, Any]:
    payload = copy.deepcopy(manifest if isinstance(manifest, dict) else {})
    provenance = payload.get("provenance")
    if not isinstance(provenance, dict):
        provenance = {}
        payload["provenance"] = provenance

    canonical_signature = _sign_canonical_manifest(payload=payload, signing_key=signing_key)
    provenance["signature"] = {
        "algorithm": "hmac-sha256",
        "key_id": str(key_id).strip() or "unknown",
        "trust_level": str(trust_level).strip().lower() or "managed",
        "value": canonical_signature,
    }
    return payload


def _sign_canonical_manifest(*, payload: dict[str, Any], signing_key: str) -> str:
    canonical = _canonical_manifest_for_signing(payload=payload)
    return hmac.new(
        str(signing_key).encode("utf-8"),
        canonical.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _canonical_manifest_for_signing(*, payload: dict[str, Any]) -> str:
    unsigned_payload = copy.deepcopy(payload if isinstance(payload, dict) else {})
    provenance = unsigned_payload.get("provenance")
    if isinstance(provenance, dict):
        provenance["signature"] = {}
    return json.dumps(unsigned_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _normalized_sha256(value: Any) -> str | None:
    text = str(value or "").strip().lower()
    if not text or not _HEX64_RE.fullmatch(text):
        return None
    return text


def _normalized_spdx_id(value: Any) -> str | None:
    text = str(value or "").strip().lower()
    if not text or not _SPDX_RE.fullmatch(text):
        return None
    return text


def _normalized_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    output: list[str] = []
    for item in value:
        normalized = str(item or "").strip().lower()
        if normalized:
            output.append(normalized)
    return output


def _required_bool(
    *,
    payload: dict[str, Any],
    key: str,
    errors: list[str],
    missing_error: str,
    invalid_error: str,
) -> bool | None:
    if key not in payload:
        errors.append(missing_error)
        return None
    value = payload.get(key)
    if isinstance(value, bool):
        return value
    errors.append(invalid_error)
    return None


def _optional_bool(
    *,
    payload: dict[str, Any],
    key: str,
    errors: list[str],
    invalid_error: str,
    default: bool,
) -> bool:
    if key not in payload:
        return bool(default)
    value = payload.get(key)
    if isinstance(value, bool):
        return value
    errors.append(invalid_error)
    return bool(default)


def _default_license_policy_path() -> Path:
    return (Path(__file__).resolve().parents[1] / "policies" / "license" / "default.json").resolve()


def _resolve_license_policy(
    *,
    license_policy: dict[str, Any] | None,
    license_policy_path: str | Path | None,
    require_license_policy: bool,
    errors: list[str],
    warnings: list[str],
) -> dict[str, Any]:
    if isinstance(license_policy, dict):
        return _normalize_license_policy(license_policy)

    raw_path = str(license_policy_path or os.getenv("AMARYLLIS_LICENSE_POLICY_PATH", "")).strip()
    policy_path = Path(raw_path).expanduser() if raw_path else _default_license_policy_path()
    if not policy_path.is_absolute():
        policy_path = (Path.cwd() / policy_path).resolve()

    if not policy_path.exists():
        if require_license_policy:
            errors.append("license.policy_missing")
        else:
            warnings.append("license.policy_missing_using_builtin_defaults")
        return _normalize_license_policy({})

    try:
        payload = json.loads(policy_path.read_text(encoding="utf-8"))
    except Exception:
        errors.append("license.policy_load_failed")
        return _normalize_license_policy({})
    if not isinstance(payload, dict):
        errors.append("license.policy_invalid")
        return _normalize_license_policy({})
    return _normalize_license_policy(payload)


def _normalize_license_policy(payload: dict[str, Any]) -> dict[str, Any]:
    policy = dict(_DEFAULT_LICENSE_POLICY)
    if not isinstance(payload, dict):
        return policy

    policy_id = str(payload.get("policy_id") or "").strip()
    if policy_id:
        policy["policy_id"] = policy_id

    allow = _normalized_string_list(payload.get("allow_spdx_ids"))
    deny = _normalized_string_list(payload.get("deny_spdx_ids"))
    if allow:
        policy["allow_spdx_ids"] = allow
    if deny:
        policy["deny_spdx_ids"] = deny

    for key in ("allow_unknown_spdx", "allow_noncommercial", "allow_no_derivatives", "allow_share_alike"):
        value = payload.get(key)
        if isinstance(value, bool):
            policy[key] = value
    return policy


def _resolve_artifact_path(*, artifact: dict[str, Any], artifact_root: str | Path | None) -> Path | None:
    raw_path = str(artifact.get("path") or "").strip()
    if not raw_path:
        return None
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        if artifact_root is None:
            return None
        candidate = Path(artifact_root).expanduser() / candidate
    try:
        return candidate.resolve()
    except Exception:
        return None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            if chunk:
                digest.update(chunk)
    return digest.hexdigest()
