#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from typing import Any


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build adoption KPI snapshot from schema gate and source benchmark reports "
            "(user journey, API quickstart compatibility, distribution channel manifest, "
            "optional release quality dashboard parity)."
        )
    )
    parser.add_argument(
        "--schema-gate-report",
        default=str(
            os.getenv(
                "AMARYLLIS_ADOPTION_SCHEMA_GATE_REPORT",
                "artifacts/adoption-kpi-schema-gate-report.json",
            )
        ).strip(),
        help="Path to adoption KPI schema gate report JSON.",
    )
    parser.add_argument(
        "--user-journey-report",
        default=str(
            os.getenv(
                "AMARYLLIS_ADOPTION_USER_JOURNEY_REPORT",
                "artifacts/user-journey-benchmark-report.json",
            )
        ).strip(),
        help="Path to user journey benchmark report JSON.",
    )
    parser.add_argument(
        "--api-quickstart-report",
        default=str(
            os.getenv(
                "AMARYLLIS_ADOPTION_API_QUICKSTART_REPORT",
                "artifacts/api-quickstart-compat-report.json",
            )
        ).strip(),
        help="Path to API quickstart compatibility gate report JSON.",
    )
    parser.add_argument(
        "--distribution-channel-manifest-report",
        default=str(
            os.getenv(
                "AMARYLLIS_ADOPTION_DISTRIBUTION_MANIFEST_REPORT",
                "artifacts/distribution-channel-manifest-report.json",
            )
        ).strip(),
        help="Path to distribution channel manifest gate report JSON.",
    )
    parser.add_argument(
        "--quality-dashboard-report",
        default=str(os.getenv("AMARYLLIS_ADOPTION_QUALITY_DASHBOARD_REPORT", "")).strip(),
        help="Optional path to release quality dashboard report JSON for signal-surface parity.",
    )
    parser.add_argument(
        "--output",
        default="artifacts/adoption-kpi-snapshot.json",
        help="Output snapshot path.",
    )
    parser.add_argument(
        "--release-id",
        default="",
        help="Release identifier. Defaults to GITHUB_REF_NAME/GITHUB_SHA when available.",
    )
    parser.add_argument(
        "--release-channel",
        default="",
        help="Release channel label. Defaults to value inferred from GitHub ref.",
    )
    parser.add_argument(
        "--commit-sha",
        default="",
        help="Commit SHA. Defaults to GITHUB_SHA when available.",
    )
    return parser.parse_args()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_path(project_root: Path, raw_path: str) -> Path:
    path = Path(str(raw_path).strip()).expanduser()
    if not path.is_absolute():
        path = project_root / path
    return path


def _load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON payload must be object: {path}")
    return payload


def _safe_float(value: Any, *, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _metric_signal(
    *,
    metric_id: str,
    source: str,
    category: str,
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
        "metric_id": metric_id,
        "source": source,
        "category": category,
        "value": round(float(value), 6),
        "threshold": round(float(threshold), 6),
        "comparator": normalized,
        "unit": unit,
        "passed": bool(passed),
    }


def _schema_check_map(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    checks = payload.get("checks")
    if not isinstance(checks, list):
        return output
    for item in checks:
        if not isinstance(item, dict):
            continue
        check_id = str(item.get("id") or "").strip()
        if not check_id:
            continue
        output[check_id] = item
    return output


def _quality_signal_map(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    signals = payload.get("signals")
    if not isinstance(signals, list):
        return output
    for item in signals:
        if not isinstance(item, dict):
            continue
        metric_id = str(item.get("metric_id") or "").strip()
        if not metric_id:
            continue
        output[metric_id] = item
    return output


def _infer_release_context(args: argparse.Namespace) -> dict[str, str]:
    github_ref = str(os.getenv("GITHUB_REF") or "").strip()
    github_ref_name = str(os.getenv("GITHUB_REF_NAME") or "").strip()
    github_sha = str(os.getenv("GITHUB_SHA") or "").strip()

    release_id = str(args.release_id or "").strip()
    if not release_id:
        release_id = github_ref_name or github_sha or "local-dev"

    release_channel = str(args.release_channel or "").strip().lower()
    if not release_channel:
        if github_ref.startswith("refs/tags/v"):
            release_channel = "stable"
        elif github_ref.startswith("refs/pull/"):
            release_channel = "pr"
        elif github_ref.startswith("refs/heads/"):
            release_channel = "branch"
        else:
            release_channel = "local"

    commit_sha = str(args.commit_sha or "").strip() or github_sha or "unknown"
    return {
        "release_id": release_id,
        "release_channel": release_channel,
        "commit_sha": commit_sha,
    }


def main() -> int:
    args = _parse_args()
    project_root = Path(__file__).resolve().parents[2]

    schema_path = _resolve_path(project_root, str(args.schema_gate_report))
    journey_path = _resolve_path(project_root, str(args.user_journey_report))
    api_quickstart_path = _resolve_path(project_root, str(args.api_quickstart_report))
    distribution_manifest_path = _resolve_path(project_root, str(args.distribution_channel_manifest_report))
    quality_raw = str(args.quality_dashboard_report or "").strip()
    quality_path = _resolve_path(project_root, quality_raw) if quality_raw else None

    for label, path in (
        ("schema_gate", schema_path),
        ("user_journey", journey_path),
        ("api_quickstart", api_quickstart_path),
        ("distribution_channel_manifest", distribution_manifest_path),
    ):
        if not path.exists():
            print(f"[adoption-kpi-snapshot] missing report for {label}: {path}", file=sys.stderr)
            return 2
    if quality_path is not None and not quality_path.exists():
        print(f"[adoption-kpi-snapshot] missing report for quality_dashboard: {quality_path}", file=sys.stderr)
        return 2

    try:
        schema = _load_json_object(schema_path)
        journey = _load_json_object(journey_path)
        api_quickstart = _load_json_object(api_quickstart_path)
        distribution_manifest = _load_json_object(distribution_manifest_path)
        quality_dashboard = _load_json_object(quality_path) if quality_path is not None else None
    except Exception as exc:
        print(f"[adoption-kpi-snapshot] invalid report payload: {exc}", file=sys.stderr)
        return 2

    if str(schema.get("suite") or "").strip() != "adoption_kpi_schema_gate_v1":
        print("[adoption-kpi-snapshot] unexpected schema gate suite", file=sys.stderr)
        return 2
    if str(journey.get("suite") or "").strip() != "user_journey_benchmark_v1":
        print("[adoption-kpi-snapshot] unexpected user journey suite", file=sys.stderr)
        return 2
    if str(api_quickstart.get("suite") or "").strip() != "api_quickstart_compatibility_gate_v1":
        print("[adoption-kpi-snapshot] unexpected API quickstart suite", file=sys.stderr)
        return 2
    if str(distribution_manifest.get("suite") or "").strip() != "distribution_channel_manifest_gate_v1":
        print("[adoption-kpi-snapshot] unexpected distribution channel manifest suite", file=sys.stderr)
        return 2
    if (
        quality_dashboard is not None
        and str(quality_dashboard.get("suite") or "").strip() != "release_quality_dashboard_v1"
    ):
        print("[adoption-kpi-snapshot] unexpected quality dashboard suite", file=sys.stderr)
        return 2

    journey_summary = journey.get("summary") if isinstance(journey.get("summary"), dict) else {}
    journey_thresholds = (
        journey.get("config", {}).get("thresholds")
        if isinstance(journey.get("config"), dict)
        and isinstance(journey.get("config", {}).get("thresholds"), dict)
        else {}
    )
    api_summary = api_quickstart.get("summary") if isinstance(api_quickstart.get("summary"), dict) else {}
    manifest_summary = (
        distribution_manifest.get("summary")
        if isinstance(distribution_manifest.get("summary"), dict)
        else {}
    )
    schema_summary = schema.get("summary") if isinstance(schema.get("summary"), dict) else {}
    schema_checks = _schema_check_map(schema)

    api_checks_total = max(0.0, _safe_float(api_summary.get("checks_total")))
    api_checks_failed = max(0.0, _safe_float(api_summary.get("checks_failed")))
    api_checks_passed = max(0.0, api_checks_total - api_checks_failed)
    api_pass_rate = (
        (api_checks_passed / api_checks_total) * 100.0
        if api_checks_total > 0
        else (100.0 if str(api_summary.get("status") or "").strip().lower() == "pass" else 0.0)
    )

    manifest_checks_total = max(0.0, _safe_float(manifest_summary.get("checks_total")))
    manifest_checks_failed = max(0.0, _safe_float(manifest_summary.get("checks_failed")))
    manifest_checks_passed = max(0.0, manifest_checks_total - manifest_checks_failed)
    manifest_coverage_pct = (
        (manifest_checks_passed / manifest_checks_total) * 100.0
        if manifest_checks_total > 0
        else (100.0 if str(manifest_summary.get("status") or "").strip().lower() == "pass" else 0.0)
    )

    api_pass_rate_threshold = _safe_float(
        schema_checks.get("api_quickstart.pass_rate_pct", {}).get("threshold"),
        default=100.0,
    )
    manifest_coverage_threshold = _safe_float(
        schema_checks.get("distribution_channel_manifest.coverage_pct", {}).get("threshold"),
        default=100.0,
    )
    schema_status = str(schema_summary.get("status") or "").strip().lower() == "pass"
    schema_checks_failed = max(0.0, _safe_float(schema_summary.get("checks_failed")))

    signals: list[dict[str, Any]] = [
        _metric_signal(
            metric_id="adoption_schema_gate.status",
            source="adoption_schema_gate",
            category="adoption_contract",
            value=1.0 if schema_status else 0.0,
            threshold=1.0,
            comparator="gte",
            unit="bool",
        ),
        _metric_signal(
            metric_id="adoption_schema_gate.checks_failed",
            source="adoption_schema_gate",
            category="adoption_contract",
            value=schema_checks_failed,
            threshold=0.0,
            comparator="lte",
            unit="count",
        ),
        _metric_signal(
            metric_id="user_journey.activation_success_rate_pct",
            source="user_journey",
            category="user_adoption",
            value=_safe_float(journey_summary.get("activation_success_rate_pct")),
            threshold=_safe_float(
                journey_thresholds.get("min_activation_success_rate_pct"),
                default=_safe_float(journey_summary.get("activation_success_rate_pct")),
            ),
            comparator="gte",
            unit="pct",
        ),
        _metric_signal(
            metric_id="user_journey.activation_blocked_rate_pct",
            source="user_journey",
            category="user_adoption",
            value=_safe_float(journey_summary.get("activation_blocked_rate_pct")),
            threshold=_safe_float(
                journey_thresholds.get("max_blocked_activation_rate_pct"),
                default=_safe_float(journey_summary.get("activation_blocked_rate_pct")),
            ),
            comparator="lte",
            unit="pct",
        ),
        _metric_signal(
            metric_id="user_journey.install_success_rate_pct",
            source="user_journey",
            category="user_adoption",
            value=_safe_float(journey_summary.get("install_success_rate_pct")),
            threshold=_safe_float(
                journey_thresholds.get("min_install_success_rate_pct"),
                default=_safe_float(journey_summary.get("install_success_rate_pct")),
            ),
            comparator="gte",
            unit="pct",
        ),
        _metric_signal(
            metric_id="user_journey.retention_proxy_success_rate_pct",
            source="user_journey",
            category="user_adoption",
            value=_safe_float(journey_summary.get("retention_proxy_success_rate_pct")),
            threshold=_safe_float(
                journey_thresholds.get("min_retention_proxy_success_rate_pct"),
                default=_safe_float(journey_summary.get("retention_proxy_success_rate_pct")),
            ),
            comparator="gte",
            unit="pct",
        ),
        _metric_signal(
            metric_id="user_journey.feature_adoption_rate_pct",
            source="user_journey",
            category="user_adoption",
            value=_safe_float(journey_summary.get("feature_adoption_rate_pct")),
            threshold=_safe_float(
                journey_thresholds.get("min_feature_adoption_rate_pct"),
                default=_safe_float(journey_summary.get("feature_adoption_rate_pct")),
            ),
            comparator="gte",
            unit="pct",
        ),
        _metric_signal(
            metric_id="api_quickstart_compat.pass_rate_pct",
            source="api_quickstart_compat",
            category="developer_adoption",
            value=api_pass_rate,
            threshold=api_pass_rate_threshold,
            comparator="gte",
            unit="pct",
        ),
        _metric_signal(
            metric_id="distribution_channel_manifest.coverage_pct",
            source="distribution_channel_manifest",
            category="distribution_adoption",
            value=manifest_coverage_pct,
            threshold=manifest_coverage_threshold,
            comparator="gte",
            unit="pct",
        ),
        _metric_signal(
            metric_id="distribution_channel_manifest.checks_failed",
            source="distribution_channel_manifest",
            category="distribution_adoption",
            value=manifest_checks_failed,
            threshold=0.0,
            comparator="lte",
            unit="count",
        ),
    ]

    if isinstance(quality_dashboard, dict):
        quality_signals = _quality_signal_map(quality_dashboard)
        expected_quality_metrics = (
            "user_journey.activation_success_rate_pct",
            "user_journey.install_success_rate_pct",
            "user_journey.retention_proxy_success_rate_pct",
            "user_journey.feature_adoption_rate_pct",
            "api_quickstart_compat.pass_rate_pct",
            "distribution_channel_manifest.coverage_pct",
        )
        required_present = all(metric_id in quality_signals for metric_id in expected_quality_metrics)
        required_passed = all(
            bool(quality_signals.get(metric_id, {}).get("passed")) for metric_id in expected_quality_metrics
        )
        signals.extend(
            [
                _metric_signal(
                    metric_id="quality_dashboard.required_adoption_signals_present",
                    source="quality_dashboard",
                    category="adoption_surface",
                    value=1.0 if required_present else 0.0,
                    threshold=1.0,
                    comparator="gte",
                    unit="bool",
                ),
                _metric_signal(
                    metric_id="quality_dashboard.required_adoption_signals_passed",
                    source="quality_dashboard",
                    category="adoption_surface",
                    value=1.0 if required_passed else 0.0,
                    threshold=1.0,
                    comparator="gte",
                    unit="bool",
                ),
            ]
        )

    signals_total = len(signals)
    signals_passed = sum(1 for signal in signals if bool(signal.get("passed")))
    signals_failed = max(0, signals_total - signals_passed)
    adoption_score_pct = (float(signals_passed) / float(signals_total) * 100.0) if signals_total else 0.0
    status = "pass" if signals_failed == 0 else "fail"

    snapshot = {
        "generated_at": _utc_now_iso(),
        "suite": "adoption_kpi_snapshot_v1",
        "release": _infer_release_context(args),
        "sources": {
            "adoption_schema_gate": {
                "path": str(schema_path),
                "suite": str(schema.get("suite") or ""),
                "generated_at": str(schema.get("generated_at") or ""),
            },
            "user_journey": {
                "path": str(journey_path),
                "suite": str(journey.get("suite") or ""),
                "generated_at": str(journey.get("generated_at") or ""),
            },
            "api_quickstart_compat": {
                "path": str(api_quickstart_path),
                "suite": str(api_quickstart.get("suite") or ""),
                "generated_at": str(api_quickstart.get("generated_at") or ""),
            },
            "distribution_channel_manifest": {
                "path": str(distribution_manifest_path),
                "suite": str(distribution_manifest.get("suite") or ""),
                "generated_at": str(distribution_manifest.get("generated_at") or ""),
            },
            "quality_dashboard": {
                "path": str(quality_path) if quality_path is not None else "",
                "suite": str(quality_dashboard.get("suite") or "") if isinstance(quality_dashboard, dict) else "",
                "generated_at": str(quality_dashboard.get("generated_at") or "")
                if isinstance(quality_dashboard, dict)
                else "",
            },
        },
        "signals": signals,
        "kpis": {
            "adoption_schema_checks_failed": round(schema_checks_failed, 4),
            "journey_activation_success_rate_pct": round(
                _safe_float(journey_summary.get("activation_success_rate_pct")),
                4,
            ),
            "journey_activation_blocked_rate_pct": round(
                _safe_float(journey_summary.get("activation_blocked_rate_pct")),
                4,
            ),
            "journey_install_success_rate_pct": round(
                _safe_float(journey_summary.get("install_success_rate_pct")),
                4,
            ),
            "journey_retention_proxy_success_rate_pct": round(
                _safe_float(journey_summary.get("retention_proxy_success_rate_pct")),
                4,
            ),
            "journey_feature_adoption_rate_pct": round(
                _safe_float(journey_summary.get("feature_adoption_rate_pct")),
                4,
            ),
            "api_quickstart_pass_rate_pct": round(api_pass_rate, 4),
            "distribution_channel_manifest_coverage_pct": round(manifest_coverage_pct, 4),
            "distribution_channel_manifest_checks_failed": round(manifest_checks_failed, 4),
        },
        "summary": {
            "signals_total": signals_total,
            "signals_passed": signals_passed,
            "signals_failed": signals_failed,
            "adoption_score_pct": round(adoption_score_pct, 4),
            "status": status,
        },
    }

    output_path = _resolve_path(project_root, str(args.output))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[adoption-kpi-snapshot] snapshot={output_path}")
    print(json.dumps(snapshot["summary"], ensure_ascii=False))

    if status != "pass":
        print("[adoption-kpi-snapshot] FAILED")
        return 1

    print("[adoption-kpi-snapshot] OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
