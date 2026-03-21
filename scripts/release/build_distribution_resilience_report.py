#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build distribution resilience report from Linux parity + installer/rollback "
            "smoke artifacts, with optional runtime lifecycle source."
        )
    )
    parser.add_argument(
        "--linux-parity-report",
        default="artifacts/linux-parity-smoke-report.json",
        help="Path to linux parity smoke report JSON.",
    )
    parser.add_argument(
        "--linux-installer-report",
        default="artifacts/linux-installer-smoke-report.json",
        help="Path to linux installer smoke report JSON.",
    )
    parser.add_argument(
        "--runtime-lifecycle-report",
        default="",
        help="Optional path to runtime lifecycle smoke report JSON.",
    )
    parser.add_argument(
        "--max-linux-parity-error-rate-pct",
        type=float,
        default=float(os.getenv("AMARYLLIS_DISTRIBUTION_MAX_PARITY_ERROR_RATE_PCT", "0")),
        help="Maximum allowed linux parity error rate percent.",
    )
    parser.add_argument(
        "--max-linux-parity-p95-latency-ms",
        type=float,
        default=float(os.getenv("AMARYLLIS_DISTRIBUTION_MAX_PARITY_P95_MS", "2500")),
        help="Maximum allowed linux parity p95 request latency.",
    )
    parser.add_argument(
        "--output",
        default="artifacts/distribution-resilience-report.json",
        help="Output report path.",
    )
    return parser.parse_args()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_path(project_root: Path, raw_path: str) -> Path:
    path = Path(str(raw_path).strip())
    if not path.is_absolute():
        path = project_root / path
    return path


def _safe_float(value: Any, *, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON payload must be object: {path}")
    return payload


def _check(
    *,
    check_id: str,
    source: str,
    value: float,
    threshold: float,
    comparator: str,
    unit: str,
) -> dict[str, Any]:
    normalized = str(comparator).strip().lower()
    if normalized not in {"lte", "gte"}:
        raise ValueError(f"Unsupported comparator: {comparator}")
    passed = value <= threshold if normalized == "lte" else value >= threshold
    return {
        "id": check_id,
        "source": source,
        "value": round(float(value), 6),
        "threshold": round(float(threshold), 6),
        "comparator": normalized,
        "unit": unit,
        "passed": bool(passed),
    }


def _check_bool(
    *,
    check_id: str,
    source: str,
    passed: bool,
) -> dict[str, Any]:
    return _check(
        check_id=check_id,
        source=source,
        value=1.0 if bool(passed) else 0.0,
        threshold=1.0,
        comparator="gte",
        unit="bool",
    )


def _required_installer_checks() -> list[str]:
    return [
        "installer_exists",
        "rollback_script_exists",
        "upgrade_keeps_prior_release",
        "rollback_keeps_canary_release_history",
        "release_r2_channel_target",
        "release_r2_current_target",
        "canary_rollback_channel_target",
        "canary_rollback_channel_history",
        "canary_rollback_current_target",
    ]


def _installer_check_state(installer_report: dict[str, Any], name: str) -> bool:
    checks = installer_report.get("checks")
    if not isinstance(checks, list):
        return False
    for item in checks:
        if not isinstance(item, dict):
            continue
        if str(item.get("name") or "").strip() != name:
            continue
        return bool(item.get("ok"))
    return False


def _commands_failed_count(report: dict[str, Any]) -> int:
    commands = report.get("commands")
    if not isinstance(commands, list):
        return 0
    failed = 0
    for item in commands:
        if not isinstance(item, dict):
            continue
        if int(_safe_float(item.get("returncode"), default=0)) != 0:
            failed += 1
    return failed


def main() -> int:
    args = _parse_args()
    project_root = Path(__file__).resolve().parents[2]

    linux_parity_path = _resolve_path(project_root, str(args.linux_parity_report))
    linux_installer_path = _resolve_path(project_root, str(args.linux_installer_report))
    runtime_lifecycle_raw = str(args.runtime_lifecycle_report or "").strip()
    runtime_lifecycle_path = _resolve_path(project_root, runtime_lifecycle_raw) if runtime_lifecycle_raw else None

    for name, path in (
        ("linux_parity", linux_parity_path),
        ("linux_installer", linux_installer_path),
    ):
        if not path.exists():
            print(f"[distribution-resilience] missing report for {name}: {path}", file=sys.stderr)
            return 2

    if runtime_lifecycle_path is not None and not runtime_lifecycle_path.exists():
        print(
            f"[distribution-resilience] missing report for runtime_lifecycle: {runtime_lifecycle_path}",
            file=sys.stderr,
        )
        return 2

    try:
        linux_parity = _load_json_object(linux_parity_path)
        linux_installer = _load_json_object(linux_installer_path)
        runtime_lifecycle = (
            _load_json_object(runtime_lifecycle_path) if runtime_lifecycle_path is not None else None
        )
    except Exception as exc:
        print(f"[distribution-resilience] failed to load reports: {exc}", file=sys.stderr)
        return 2

    checks: list[dict[str, Any]] = []
    kpis: dict[str, Any] = {}

    parity_summary = linux_parity.get("summary") if isinstance(linux_parity.get("summary"), dict) else {}
    parity_error_rate = _safe_float(parity_summary.get("error_rate_pct"))
    parity_p95 = _safe_float(parity_summary.get("latency_ms", {}).get("p95"), default=0.0)
    parity_failed_checks = _safe_float(parity_summary.get("checks_failed"), default=0.0)
    checks.extend(
        [
            _check(
                check_id="linux_parity.error_rate_pct",
                source="linux_parity",
                value=parity_error_rate,
                threshold=float(args.max_linux_parity_error_rate_pct),
                comparator="lte",
                unit="pct",
            ),
            _check(
                check_id="linux_parity.p95_latency_ms",
                source="linux_parity",
                value=parity_p95,
                threshold=float(args.max_linux_parity_p95_latency_ms),
                comparator="lte",
                unit="ms",
            ),
            _check(
                check_id="linux_parity.checks_failed",
                source="linux_parity",
                value=parity_failed_checks,
                threshold=0.0,
                comparator="lte",
                unit="count",
            ),
        ]
    )
    kpis["linux_parity_error_rate_pct"] = round(parity_error_rate, 4)
    kpis["linux_parity_p95_latency_ms"] = round(parity_p95, 2)
    kpis["linux_parity_checks_failed"] = int(parity_failed_checks)

    installer_checks = linux_installer.get("checks")
    installer_failed_checks = 0
    if isinstance(installer_checks, list):
        installer_failed_checks = sum(
            1 for item in installer_checks if isinstance(item, dict) and not bool(item.get("ok"))
        )
    installer_commands_failed = _commands_failed_count(linux_installer)
    checks.extend(
        [
            _check(
                check_id="linux_installer.checks_failed",
                source="linux_installer",
                value=float(installer_failed_checks),
                threshold=0.0,
                comparator="lte",
                unit="count",
            ),
            _check(
                check_id="linux_installer.commands_failed",
                source="linux_installer",
                value=float(installer_commands_failed),
                threshold=0.0,
                comparator="lte",
                unit="count",
            ),
        ]
    )
    for check_name in _required_installer_checks():
        checks.append(
            _check_bool(
                check_id=f"linux_installer.{check_name}",
                source="linux_installer",
                passed=_installer_check_state(linux_installer, check_name),
            )
        )

    kpis["linux_installer_checks_failed"] = int(installer_failed_checks)
    kpis["linux_installer_commands_failed"] = int(installer_commands_failed)

    if isinstance(runtime_lifecycle, dict):
        runtime_summary = runtime_lifecycle.get("summary") if isinstance(runtime_lifecycle.get("summary"), dict) else {}
        runtime_targets_ok = bool(runtime_summary.get("targets_ok"))
        runtime_startup_ok = bool(runtime_summary.get("startup_ok"))
        runtime_checks_failed = _safe_float(runtime_summary.get("checks_failed"), default=0.0)
        checks.extend(
            [
                _check_bool(
                    check_id="runtime_lifecycle.targets_ok",
                    source="runtime_lifecycle",
                    passed=runtime_targets_ok,
                ),
                _check_bool(
                    check_id="runtime_lifecycle.startup_ok",
                    source="runtime_lifecycle",
                    passed=runtime_startup_ok,
                ),
                _check(
                    check_id="runtime_lifecycle.checks_failed",
                    source="runtime_lifecycle",
                    value=runtime_checks_failed,
                    threshold=0.0,
                    comparator="lte",
                    unit="count",
                ),
            ]
        )
        kpis["runtime_lifecycle_targets_ok"] = runtime_targets_ok
        kpis["runtime_lifecycle_startup_ok"] = runtime_startup_ok
        kpis["runtime_lifecycle_checks_failed"] = int(runtime_checks_failed)

    passed_checks = sum(1 for item in checks if bool(item.get("passed")))
    failed_checks = len(checks) - passed_checks
    score_pct = (float(passed_checks) / float(len(checks)) * 100.0) if checks else 0.0

    payload = {
        "generated_at": _utc_now_iso(),
        "suite": "distribution_resilience_report_v1",
        "sources": {
            "linux_parity": {
                "path": str(linux_parity_path),
                "suite": str(linux_parity.get("suite") or ""),
                "generated_at": str(linux_parity.get("generated_at") or ""),
            },
            "linux_installer": {
                "path": str(linux_installer_path),
                "suite": str(linux_installer.get("suite") or ""),
                "generated_at": str(linux_installer.get("generated_at") or ""),
            },
            "runtime_lifecycle": {
                "path": str(runtime_lifecycle_path) if runtime_lifecycle_path is not None else "",
                "suite": str(runtime_lifecycle.get("suite") or "") if isinstance(runtime_lifecycle, dict) else "",
                "generated_at": str(runtime_lifecycle.get("generated_at") or "")
                if isinstance(runtime_lifecycle, dict)
                else "",
                "included": bool(isinstance(runtime_lifecycle, dict)),
            },
        },
        "kpis": kpis,
        "checks": checks,
        "summary": {
            "checks_total": len(checks),
            "checks_passed": passed_checks,
            "checks_failed": failed_checks,
            "score_pct": round(score_pct, 4),
            "status": "pass" if failed_checks == 0 else "fail",
        },
    }

    output_path = _resolve_path(project_root, str(args.output))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"[distribution-resilience] report={output_path}")
    print(json.dumps(payload["summary"], ensure_ascii=False))
    if failed_checks > 0:
        print("[distribution-resilience] FAILED")
        return 1

    print("[distribution-resilience] OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
