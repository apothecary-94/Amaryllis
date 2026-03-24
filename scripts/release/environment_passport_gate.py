#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
from typing import Any


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build runtime environment passport (host/runtime/toolchain/quant metadata) "
            "and enforce completeness thresholds for reproducible release/nightly artifacts."
        )
    )
    parser.add_argument(
        "--runtime-profile",
        default=str(os.getenv("AMARYLLIS_RUNTIME_PROFILE", "release")).strip() or "release",
        help="Runtime profile id to load from runtime profiles directory.",
    )
    parser.add_argument(
        "--slo-profile",
        default=str(os.getenv("AMARYLLIS_SLO_PROFILE", "")).strip(),
        help="Optional SLO profile id override. Defaults to runtime profile mapping.",
    )
    parser.add_argument(
        "--runtime-profiles-dir",
        default=str(os.getenv("AMARYLLIS_RUNTIME_PROFILE_DIR", "runtime/profiles")).strip(),
        help="Path to runtime profile manifests.",
    )
    parser.add_argument(
        "--slo-profiles-dir",
        default=str(os.getenv("AMARYLLIS_SLO_PROFILE_DIR", "slo_profiles")).strip(),
        help="Path to SLO profile manifests.",
    )
    parser.add_argument(
        "--toolchain-manifest",
        default=str(os.getenv("AMARYLLIS_TOOLCHAIN_MANIFEST", "runtime/toolchains/core.json")).strip(),
        help="Path to toolchain manifest JSON.",
    )
    parser.add_argument(
        "--model-artifact-admission-report",
        default="",
        help="Optional path to model artifact admission report (for quantization reference metadata).",
    )
    parser.add_argument(
        "--min-completeness-score-pct",
        type=float,
        default=float(os.getenv("AMARYLLIS_ENV_PASSPORT_MIN_COMPLETENESS_PCT", "100")),
        help="Minimum required completeness score in percent (0..100).",
    )
    parser.add_argument(
        "--max-missing-required",
        type=int,
        default=int(os.getenv("AMARYLLIS_ENV_PASSPORT_MAX_MISSING_REQUIRED", "0")),
        help="Maximum allowed missing required field count.",
    )
    parser.add_argument(
        "--output",
        default="",
        help="Optional JSON report output path.",
    )
    return parser.parse_args()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_path(repo_root: Path, raw_path: str) -> Path:
    path = Path(str(raw_path).strip()).expanduser()
    if not path.is_absolute():
        path = repo_root / path
    return path.resolve()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON payload must be object: {path}")
    return payload


def _to_int_or_none(value: Any) -> int | None:
    try:
        parsed = int(value)
    except Exception:
        return None
    return parsed


def _run_git(repo_root: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return ""
    return str(proc.stdout or "").strip()


def _detect_memory_total_bytes() -> int | None:
    try:
        page_size = os.sysconf("SC_PAGE_SIZE")
        page_count = os.sysconf("SC_PHYS_PAGES")
        if isinstance(page_size, int) and isinstance(page_count, int) and page_size > 0 and page_count > 0:
            return int(page_size * page_count)
    except Exception:
        pass

    if platform.system().lower() == "darwin":
        proc = subprocess.run(
            ["sysctl", "-n", "hw.memsize"],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode == 0:
            return _to_int_or_none(str(proc.stdout or "").strip())
    return None


def _hash_file(path: Path) -> tuple[str, int] | None:
    if not path.exists() or not path.is_file():
        return None
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            if chunk:
                digest.update(chunk)
    return digest.hexdigest(), int(path.stat().st_size)


def _collect_quantization(*, model_admission_report: Path | None) -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = []
    quantization = {
        "source": "environment",
        "method": str(os.getenv("AMARYLLIS_QUANT_METHOD", "int4")).strip() or "int4",
        "bits": _to_int_or_none(os.getenv("AMARYLLIS_QUANT_BITS", "4")),
        "recipe_id": str(os.getenv("AMARYLLIS_QUANT_RECIPE_ID", "default-int4-v1")).strip() or "default-int4-v1",
        "converter": str(os.getenv("AMARYLLIS_QUANT_CONVERTER", "mlx-lm")).strip() or "mlx-lm",
        "converter_version": str(os.getenv("AMARYLLIS_QUANT_CONVERTER_VERSION", "unknown")).strip() or "unknown",
    }

    if model_admission_report is None:
        return quantization, warnings

    if not model_admission_report.exists():
        warnings.append(f"model_artifact_admission_report_missing:{model_admission_report}")
        return quantization, warnings

    try:
        payload = _load_json_object(model_admission_report)
    except Exception as exc:
        warnings.append(f"model_artifact_admission_report_invalid:{exc}")
        return quantization, warnings

    reference = payload.get("quantization_reference")
    if not isinstance(reference, dict):
        warnings.append("model_artifact_admission_report_missing_quantization_reference")
        return quantization, warnings

    bits = _to_int_or_none(reference.get("bits"))
    quantization = {
        "source": "model_artifact_admission_report",
        "method": str(reference.get("method") or "").strip(),
        "bits": bits,
        "recipe_id": str(reference.get("recipe_id") or "").strip(),
        "converter": str(reference.get("converter") or "").strip(),
        "converter_version": str(reference.get("converter_version") or "").strip(),
    }
    return quantization, warnings


def _build_passport(*, args: argparse.Namespace, repo_root: Path) -> tuple[dict[str, Any], list[str]]:
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    from runtime.profile_loader import load_runtime_profile, load_slo_profile  # noqa: PLC0415

    runtime_profiles_dir = _resolve_path(repo_root, str(args.runtime_profiles_dir))
    slo_profiles_dir = _resolve_path(repo_root, str(args.slo_profiles_dir))
    toolchain_manifest_path = _resolve_path(repo_root, str(args.toolchain_manifest))
    model_admission_raw = str(args.model_artifact_admission_report or "").strip()
    model_admission_report = (
        _resolve_path(repo_root, model_admission_raw) if model_admission_raw else None
    )

    runtime_manifest = load_runtime_profile(str(args.runtime_profile), profiles_dir=runtime_profiles_dir)
    selected_slo_profile = str(args.slo_profile or "").strip() or runtime_manifest.slo_profile
    slo_manifest = load_slo_profile(selected_slo_profile, profiles_dir=slo_profiles_dir)
    toolchain_manifest = _load_json_object(toolchain_manifest_path)

    quantization, warnings = _collect_quantization(model_admission_report=model_admission_report)
    lock_path = _resolve_path(repo_root, "requirements.lock")
    lock_hash = _hash_file(lock_path)
    mem_total = _detect_memory_total_bytes()

    host_payload = {
        "system": str(platform.system() or "").strip(),
        "release": str(platform.release() or "").strip(),
        "version": str(platform.version() or "").strip(),
        "machine": str(platform.machine() or "").strip(),
        "processor": str(platform.processor() or "").strip(),
        "hostname": str(platform.node() or "").strip(),
        "cpu": {
            "logical_count": _to_int_or_none(os.cpu_count()),
            "memory_total_bytes": mem_total,
        },
    }

    runtime_payload = {
        "python": {
            "version": str(platform.python_version() or "").strip(),
            "implementation": str(platform.python_implementation() or "").strip(),
            "executable": str(sys.executable or "").strip(),
        },
        "virtual_env": {
            "enabled": bool(str(os.getenv("VIRTUAL_ENV", "")).strip()),
            "path": str(os.getenv("VIRTUAL_ENV", "")).strip() or None,
        },
        "profiles": {
            "runtime_profile": runtime_manifest.profile,
            "runtime_profile_path": str(runtime_manifest.source_path),
            "runtime_profile_schema_version": runtime_manifest.schema_version,
            "slo_profile": slo_manifest.profile,
            "slo_profile_path": str(slo_manifest.source_path),
            "slo_profile_schema_version": slo_manifest.schema_version,
        },
    }

    toolchain_python = toolchain_manifest.get("python")
    toolchain_ci = toolchain_manifest.get("ci")
    passport = {
        "schema_version": "amaryllis.environment_passport.v1",
        "generated_at": _utc_now_iso(),
        "repository": {
            "commit": _run_git(repo_root, "rev-parse", "HEAD") or "unknown",
            "branch": _run_git(repo_root, "rev-parse", "--abbrev-ref", "HEAD") or "unknown",
            "dirty": bool(_run_git(repo_root, "status", "--porcelain")),
        },
        "host": host_payload,
        "runtime": runtime_payload,
        "toolchain": {
            "manifest_path": str(toolchain_manifest_path),
            "manifest_version": str(toolchain_manifest.get("manifest_version") or "").strip(),
            "schema_version": _to_int_or_none(toolchain_manifest.get("schema_version")),
            "python": {
                "version": str(toolchain_python.get("version") or "").strip()
                if isinstance(toolchain_python, dict)
                else "",
                "bootstrap_binary": str(toolchain_python.get("bootstrap_binary") or "").strip()
                if isinstance(toolchain_python, dict)
                else "",
            },
            "ci_runner": str(toolchain_ci.get("runner") or "").strip()
            if isinstance(toolchain_ci, dict)
            else "",
        },
        "dependencies_lock": {
            "path": str(lock_path),
            "sha256": lock_hash[0] if lock_hash is not None else "",
            "size_bytes": lock_hash[1] if lock_hash is not None else None,
        },
        "quantization": quantization,
        "drivers": {
            "nvidia_driver_version": str(os.getenv("NVIDIA_DRIVER_VERSION", "")).strip() or None,
            "cuda_version": str(os.getenv("CUDA_VERSION", "")).strip() or None,
            "rocm_version": str(os.getenv("ROCM_VERSION", "")).strip() or None,
            "metal_version": str(os.getenv("METAL_VERSION", "")).strip() or None,
        },
    }
    return passport, warnings


def _required_checks(passport: dict[str, Any]) -> dict[str, bool]:
    host = passport.get("host") if isinstance(passport.get("host"), dict) else {}
    cpu = host.get("cpu") if isinstance(host.get("cpu"), dict) else {}
    runtime = passport.get("runtime") if isinstance(passport.get("runtime"), dict) else {}
    python_runtime = runtime.get("python") if isinstance(runtime.get("python"), dict) else {}
    profiles = runtime.get("profiles") if isinstance(runtime.get("profiles"), dict) else {}
    toolchain = passport.get("toolchain") if isinstance(passport.get("toolchain"), dict) else {}
    deps_lock = (
        passport.get("dependencies_lock")
        if isinstance(passport.get("dependencies_lock"), dict)
        else {}
    )
    quant = passport.get("quantization") if isinstance(passport.get("quantization"), dict) else {}

    bits = _to_int_or_none(quant.get("bits"))
    cpu_count = _to_int_or_none(cpu.get("logical_count"))

    return {
        "host.system": bool(str(host.get("system") or "").strip()),
        "host.machine": bool(str(host.get("machine") or "").strip()),
        "host.cpu.logical_count": isinstance(cpu_count, int) and cpu_count > 0,
        "runtime.python.version": bool(str(python_runtime.get("version") or "").strip()),
        "runtime.python.executable": bool(str(python_runtime.get("executable") or "").strip()),
        "runtime.profile": bool(str(profiles.get("runtime_profile") or "").strip()),
        "runtime.slo_profile": bool(str(profiles.get("slo_profile") or "").strip()),
        "toolchain.manifest_version": bool(str(toolchain.get("manifest_version") or "").strip()),
        "dependencies_lock.sha256": bool(str(deps_lock.get("sha256") or "").strip()),
        "quantization.method": bool(str(quant.get("method") or "").strip()),
        "quantization.bits": isinstance(bits, int) and bits > 0,
        "quantization.recipe_id": bool(str(quant.get("recipe_id") or "").strip()),
        "quantization.converter": bool(str(quant.get("converter") or "").strip()),
        "quantization.converter_version": bool(str(quant.get("converter_version") or "").strip()),
    }


def _build_report(
    *,
    args: argparse.Namespace,
    passport: dict[str, Any],
    warnings: list[str],
) -> dict[str, Any]:
    checks = _required_checks(passport)
    required_total = len(checks)
    required_present = sum(1 for present in checks.values() if bool(present))
    missing_fields = sorted([field for field, present in checks.items() if not bool(present)])
    completeness_score_pct = (
        float(required_present) / float(required_total) * 100.0
        if required_total > 0
        else 0.0
    )

    errors: list[str] = []
    if completeness_score_pct < float(args.min_completeness_score_pct):
        errors.append(
            "completeness_score_below_min:"
            f"{round(completeness_score_pct, 4)}<{float(args.min_completeness_score_pct)}"
        )
    if len(missing_fields) > int(args.max_missing_required):
        errors.append(f"missing_required_fields_exceeded:{len(missing_fields)}>{int(args.max_missing_required)}")

    return {
        "generated_at": _utc_now_iso(),
        "suite": "environment_passport_gate_v1",
        "passport": passport,
        "summary": {
            "status": "pass" if not errors else "fail",
            "required_fields_total": required_total,
            "required_fields_present": required_present,
            "missing_required_fields_count": len(missing_fields),
            "missing_required_fields": missing_fields,
            "completeness_score_pct": round(completeness_score_pct, 4),
            "min_completeness_score_pct": float(args.min_completeness_score_pct),
            "max_missing_required": int(args.max_missing_required),
            "warnings": warnings,
            "errors": errors,
        },
        "checks": [
            {"field": field, "present": bool(present)}
            for field, present in sorted(checks.items(), key=lambda item: item[0])
        ],
    }


def main() -> int:
    args = _parse_args()
    if float(args.min_completeness_score_pct) < 0 or float(args.min_completeness_score_pct) > 100:
        print("[environment-passport] --min-completeness-score-pct must be in range 0..100", file=sys.stderr)
        return 2
    if int(args.max_missing_required) < 0:
        print("[environment-passport] --max-missing-required must be >= 0", file=sys.stderr)
        return 2

    repo_root = Path(__file__).resolve().parents[2]
    try:
        passport, warnings = _build_passport(args=args, repo_root=repo_root)
    except Exception as exc:
        print(f"[environment-passport] FAILED import_or_runtime_error={exc}")
        return 2

    report = _build_report(args=args, passport=passport, warnings=warnings)
    output_raw = str(args.output or "").strip()
    if output_raw:
        output_path = _resolve_path(repo_root, output_raw)
        _write_json(output_path, report)

    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    if str(summary.get("status") or "") != "pass":
        print("[environment-passport] FAILED")
        for error in summary.get("errors", []):
            print(f"- {error}")
        return 1

    print(
        "[environment-passport] OK "
        f"completeness_score_pct={summary.get('completeness_score_pct')} "
        f"missing_required_fields={summary.get('missing_required_fields_count')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
