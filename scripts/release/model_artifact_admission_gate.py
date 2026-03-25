#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run secure model package + quant passport admission regression scenarios."
        )
    )
    parser.add_argument(
        "--min-admission-score-pct",
        type=float,
        default=float(os.getenv("AMARYLLIS_MODEL_ADMISSION_MIN_SCORE_PCT", "100")),
        help="Minimum required admission score for the scenario suite (0..100).",
    )
    parser.add_argument(
        "--max-failed-scenarios",
        type=int,
        default=int(os.getenv("AMARYLLIS_MODEL_ADMISSION_MAX_FAILED_SCENARIOS", "0")),
        help="Maximum allowed failed scenario count.",
    )
    parser.add_argument(
        "--require-scenario",
        action="append",
        default=[],
        help="Scenario id that must be present and pass (repeatable).",
    )
    parser.add_argument(
        "--output",
        default="",
        help="Optional JSON report output path.",
    )
    return parser.parse_args()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _base_manifest(*, artifact_rel_path: str, artifact_sha: str, artifact_bytes: int) -> dict[str, Any]:
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
        "license": {
            "spdx_id": "apache-2.0",
            "source": "https://example.org/model-card",
            "allows_commercial_use": True,
            "allows_derivatives": True,
            "requires_share_alike": False,
            "restrictions": [],
        },
        "provenance": {
            "generated_at": "2026-03-25T00:00:00+00:00",
        },
    }


def _evaluate(
    *,
    scenario_id: str,
    name: str,
    expected_admitted: bool,
    manifest: dict[str, Any],
    artifact_root: Path,
    signing_key: str,
    validate_fn: Any,
) -> dict[str, Any]:
    decision = validate_fn(
        manifest,
        signing_key=signing_key,
        require_signing_key=True,
        require_managed_trust=True,
        artifact_root=str(artifact_root),
    )
    admitted = bool(decision.get("ok"))
    passed = admitted == bool(expected_admitted)
    return {
        "id": scenario_id,
        "name": name,
        "expected": {"admitted": bool(expected_admitted)},
        "observed": {
            "admitted": admitted,
            "errors": [str(item) for item in decision.get("errors", [])],
            "warnings": [str(item) for item in decision.get("warnings", [])],
            "summary": dict(decision.get("summary") or {}),
        },
        "status": "pass" if passed else "fail",
    }


def _run_scenarios() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    from models.model_artifact_admission import (  # noqa: PLC0415
        sign_model_package_manifest,
        validate_model_package_manifest,
    )

    signing_key = "fixture-model-artifact-signing-key"
    scenarios: list[dict[str, Any]] = []
    quantization_reference: dict[str, Any] = {}

    with tempfile.TemporaryDirectory(prefix="amaryllis-model-admission-gate-") as tmp:
        root = Path(tmp)
        artifact = root / "models" / "qwen.gguf"
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_bytes(b"amaryllis-model-artifact")
        artifact_sha = hashlib.sha256(artifact.read_bytes()).hexdigest()
        artifact_bytes = int(artifact.stat().st_size)

        valid = _base_manifest(
            artifact_rel_path="models/qwen.gguf",
            artifact_sha=artifact_sha,
            artifact_bytes=artifact_bytes,
        )
        quant_payload = valid.get("quantization")
        if isinstance(quant_payload, dict):
            quantization_reference = {
                "method": str(quant_payload.get("method") or "").strip(),
                "bits": int(quant_payload.get("bits") or 0),
                "recipe_id": str(quant_payload.get("recipe_id") or "").strip(),
                "converter": str(quant_payload.get("converter") or "").strip(),
                "converter_version": str(quant_payload.get("converter_version") or "").strip(),
            }
        valid_signed = sign_model_package_manifest(
            valid,
            signing_key=signing_key,
            key_id="model-key-1",
            trust_level="managed",
        )
        scenarios.append(
            _evaluate(
                scenario_id="valid_manifest_admitted",
                name="Valid signed model package manifest is admitted",
                expected_admitted=True,
                manifest=valid_signed,
                artifact_root=root,
                signing_key=signing_key,
                validate_fn=validate_model_package_manifest,
            )
        )

        missing_quant = json.loads(json.dumps(valid))
        quant = missing_quant.get("quantization")
        if isinstance(quant, dict):
            quant.pop("recipe_id", None)
        missing_quant_signed = sign_model_package_manifest(
            missing_quant,
            signing_key=signing_key,
            key_id="model-key-1",
            trust_level="managed",
        )
        scenarios.append(
            _evaluate(
                scenario_id="missing_quant_recipe_rejected",
                name="Missing quant recipe is rejected",
                expected_admitted=False,
                manifest=missing_quant_signed,
                artifact_root=root,
                signing_key=signing_key,
                validate_fn=validate_model_package_manifest,
            )
        )

        bad_signature = json.loads(json.dumps(valid_signed))
        provenance = bad_signature.get("provenance")
        if isinstance(provenance, dict):
            signature = provenance.get("signature")
            if isinstance(signature, dict):
                signature["value"] = "f" * 64
        scenarios.append(
            _evaluate(
                scenario_id="signature_mismatch_rejected",
                name="Signature mismatch is rejected",
                expected_admitted=False,
                manifest=bad_signature,
                artifact_root=root,
                signing_key=signing_key,
                validate_fn=validate_model_package_manifest,
            )
        )

        sha_mismatch = json.loads(json.dumps(valid))
        artifact_payload = sha_mismatch.get("artifact")
        if isinstance(artifact_payload, dict):
            artifact_payload["sha256"] = "0" * 64
        materials = sha_mismatch.get("materials")
        if isinstance(materials, list) and materials and isinstance(materials[0], dict):
            materials[0]["sha256"] = "0" * 64
        sha_mismatch_signed = sign_model_package_manifest(
            sha_mismatch,
            signing_key=signing_key,
            key_id="model-key-1",
            trust_level="managed",
        )
        scenarios.append(
            _evaluate(
                scenario_id="artifact_hash_mismatch_rejected",
                name="Artifact hash mismatch is rejected",
                expected_admitted=False,
                manifest=sha_mismatch_signed,
                artifact_root=root,
                signing_key=signing_key,
                validate_fn=validate_model_package_manifest,
            )
        )

        development_trust_signed = sign_model_package_manifest(
            valid,
            signing_key=signing_key,
            key_id="model-key-1",
            trust_level="development",
        )
        scenarios.append(
            _evaluate(
                scenario_id="development_trust_rejected",
                name="Development trust signature is rejected in strict mode",
                expected_admitted=False,
                manifest=development_trust_signed,
                artifact_root=root,
                signing_key=signing_key,
                validate_fn=validate_model_package_manifest,
            )
        )

        denied_license = json.loads(json.dumps(valid))
        license_payload = denied_license.get("license")
        if isinstance(license_payload, dict):
            license_payload["spdx_id"] = "gpl-3.0-only"
        denied_license_signed = sign_model_package_manifest(
            denied_license,
            signing_key=signing_key,
            key_id="model-key-1",
            trust_level="managed",
        )
        scenarios.append(
            _evaluate(
                scenario_id="denied_license_rejected",
                name="Denied SPDX license is rejected by policy",
                expected_admitted=False,
                manifest=denied_license_signed,
                artifact_root=root,
                signing_key=signing_key,
                validate_fn=validate_model_package_manifest,
            )
        )

    return scenarios, quantization_reference


def _build_report(
    *,
    args: argparse.Namespace,
    scenarios: list[dict[str, Any]],
    quantization_reference: dict[str, Any],
) -> dict[str, Any]:
    total = len(scenarios)
    passed = sum(1 for item in scenarios if str(item.get("status")) == "pass")
    failed = total - passed
    admission_score_pct = (float(passed) / float(total) * 100.0) if total > 0 else 0.0

    required = [str(item).strip() for item in args.require_scenario if str(item).strip()]
    required_map = {str(item.get("id")): str(item.get("status")) for item in scenarios}

    errors: list[str] = []
    if admission_score_pct < float(args.min_admission_score_pct):
        errors.append(
            "admission_score_below_min:"
            f"{round(admission_score_pct, 4)}<{float(args.min_admission_score_pct)}"
        )
    if failed > int(args.max_failed_scenarios):
        errors.append(f"failed_scenarios_exceeded:{failed}>{int(args.max_failed_scenarios)}")

    missing_required: list[str] = []
    failed_required: list[str] = []
    for scenario_id in required:
        status = required_map.get(scenario_id)
        if status is None:
            missing_required.append(scenario_id)
        elif status != "pass":
            failed_required.append(scenario_id)
    if missing_required:
        errors.append(f"missing_required_scenarios:{','.join(sorted(missing_required))}")
    if failed_required:
        errors.append(f"required_scenarios_failed:{','.join(sorted(failed_required))}")

    return {
        "generated_at": _utc_now_iso(),
        "suite": "model_artifact_admission_gate_v1",
        "quantization_reference": quantization_reference,
        "summary": {
            "status": "pass" if not errors else "fail",
            "scenario_count": total,
            "passed_scenarios": passed,
            "failed_scenarios": failed,
            "admission_score_pct": round(admission_score_pct, 4),
            "min_admission_score_pct": float(args.min_admission_score_pct),
            "max_failed_scenarios": int(args.max_failed_scenarios),
            "errors": errors,
        },
        "scenarios": scenarios,
    }


def main() -> int:
    args = _parse_args()
    if float(args.min_admission_score_pct) < 0 or float(args.min_admission_score_pct) > 100:
        print("[model-admission-gate] --min-admission-score-pct must be in range 0..100", file=sys.stderr)
        return 2
    if int(args.max_failed_scenarios) < 0:
        print("[model-admission-gate] --max-failed-scenarios must be >= 0", file=sys.stderr)
        return 2

    try:
        scenarios, quantization_reference = _run_scenarios()
    except Exception as exc:
        print(f"[model-admission-gate] FAILED import_or_runtime_error={exc}")
        return 2

    report = _build_report(
        args=args,
        scenarios=scenarios,
        quantization_reference=quantization_reference,
    )

    if args.output:
        repo_root = Path(__file__).resolve().parents[2]
        output_path = Path(args.output)
        if not output_path.is_absolute():
            output_path = repo_root / output_path
        _write_json(output_path, report)

    if str(report.get("summary", {}).get("status")) != "pass":
        print("[model-admission-gate] FAILED")
        for err in report.get("summary", {}).get("errors", []):
            print(f"- {err}")
        return 1

    summary = report.get("summary", {})
    print(
        "[model-admission-gate] OK "
        f"admission_score_pct={summary.get('admission_score_pct')} "
        f"failed_scenarios={summary.get('failed_scenarios')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
