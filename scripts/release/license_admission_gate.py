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
            "Run license admission policy regression scenarios for model onboarding."
        )
    )
    parser.add_argument(
        "--min-admission-score-pct",
        type=float,
        default=float(os.getenv("AMARYLLIS_LICENSE_ADMISSION_MIN_SCORE_PCT", "100")),
        help="Minimum required admission score for scenario suite (0..100).",
    )
    parser.add_argument(
        "--max-failed-scenarios",
        type=int,
        default=int(os.getenv("AMARYLLIS_LICENSE_ADMISSION_MAX_FAILED_SCENARIOS", "0")),
        help="Maximum allowed failed scenario count.",
    )
    parser.add_argument(
        "--require-scenario",
        action="append",
        default=[],
        help="Scenario id that must exist and pass (repeatable).",
    )
    parser.add_argument(
        "--license-policy-path",
        default=os.getenv("AMARYLLIS_LICENSE_POLICY_PATH", ""),
        help="Optional override path to license policy JSON.",
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


def _resolve_path(repo_root: Path, raw: str) -> Path:
    candidate = Path(str(raw or "").strip()).expanduser()
    if not candidate.is_absolute():
        candidate = repo_root / candidate
    return candidate.resolve()


def _scenarios() -> list[dict[str, Any]]:
    return [
        {
            "id": "allowed_license_admitted",
            "name": "Allowed SPDX license is admitted",
            "expected_admitted": True,
            "license": {
                "spdx_id": "apache-2.0",
                "source": "https://example.org/model-card",
                "allows_commercial_use": True,
                "allows_derivatives": True,
                "requires_share_alike": False,
                "restrictions": [],
            },
        },
        {
            "id": "share_alike_license_admitted",
            "name": "Allowed share-alike SPDX license is admitted",
            "expected_admitted": True,
            "license": {
                "spdx_id": "cc-by-sa-4.0",
                "source": "https://example.org/model-card",
                "allows_commercial_use": True,
                "allows_derivatives": True,
                "requires_share_alike": True,
                "restrictions": [],
            },
        },
        {
            "id": "denied_spdx_rejected",
            "name": "Denied SPDX license is rejected",
            "expected_admitted": False,
            "license": {
                "spdx_id": "gpl-3.0-only",
                "source": "https://example.org/model-card",
                "allows_commercial_use": True,
                "allows_derivatives": True,
                "requires_share_alike": False,
                "restrictions": [],
            },
        },
        {
            "id": "noncommercial_rejected",
            "name": "Non-commercial license flag is rejected",
            "expected_admitted": False,
            "license": {
                "spdx_id": "apache-2.0",
                "source": "https://example.org/model-card",
                "allows_commercial_use": False,
                "allows_derivatives": True,
                "requires_share_alike": False,
                "restrictions": ["non-commercial-use-only"],
            },
        },
        {
            "id": "no_derivatives_rejected",
            "name": "No-derivatives license flag is rejected",
            "expected_admitted": False,
            "license": {
                "spdx_id": "apache-2.0",
                "source": "https://example.org/model-card",
                "allows_commercial_use": True,
                "allows_derivatives": False,
                "requires_share_alike": False,
                "restrictions": ["no-derivatives"],
            },
        },
        {
            "id": "unknown_spdx_rejected",
            "name": "Unknown SPDX license is rejected",
            "expected_admitted": False,
            "license": {
                "spdx_id": "unknown-license",
                "source": "https://example.org/model-card",
                "allows_commercial_use": True,
                "allows_derivatives": True,
                "requires_share_alike": False,
                "restrictions": [],
            },
        },
    ]


def _run_scenarios(*, license_policy_path: str | None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    from models.model_artifact_admission import evaluate_license_admission  # noqa: PLC0415

    rows: list[dict[str, Any]] = []
    policy_summary: dict[str, Any] = {}
    for scenario in _scenarios():
        decision = evaluate_license_admission(
            scenario.get("license") if isinstance(scenario.get("license"), dict) else None,
            license_policy_path=license_policy_path,
            require_license_policy=True,
            require_license_metadata=True,
        )
        admitted = bool(decision.get("ok"))
        expected_admitted = bool(scenario.get("expected_admitted"))
        passed = admitted == expected_admitted
        summary = dict(decision.get("summary") or {})
        if not policy_summary:
            policy_summary = {
                "policy_id": str(summary.get("license_policy_id") or "").strip(),
                "metadata_required": bool(summary.get("license_metadata_required")),
            }
        rows.append(
            {
                "id": str(scenario.get("id") or ""),
                "name": str(scenario.get("name") or ""),
                "expected": {"admitted": expected_admitted},
                "observed": {
                    "admitted": admitted,
                    "errors": [str(item) for item in decision.get("errors", [])],
                    "warnings": [str(item) for item in decision.get("warnings", [])],
                    "summary": summary,
                },
                "status": "pass" if passed else "fail",
            }
        )
    return rows, policy_summary


def _build_report(
    *,
    args: argparse.Namespace,
    scenarios: list[dict[str, Any]],
    policy_summary: dict[str, Any],
) -> dict[str, Any]:
    total = len(scenarios)
    passed = sum(1 for item in scenarios if str(item.get("status") or "") == "pass")
    failed = total - passed
    admission_score_pct = (float(passed) / float(total) * 100.0) if total > 0 else 0.0

    required = [str(item).strip() for item in args.require_scenario if str(item).strip()]
    required_map = {
        str(item.get("id") or ""): str(item.get("status") or "")
        for item in scenarios
        if isinstance(item, dict)
    }

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
        "suite": "license_admission_gate_v1",
        "policy": {
            "path": str(args.license_policy_path or ""),
            "id": str(policy_summary.get("policy_id") or ""),
            "metadata_required": bool(policy_summary.get("metadata_required", True)),
        },
        "summary": {
            "status": "pass" if not errors else "fail",
            "scenario_count": total,
            "passed_scenarios": passed,
            "failed_scenarios": failed,
            "admission_score_pct": round(admission_score_pct, 4),
            "min_admission_score_pct": float(args.min_admission_score_pct),
            "max_failed_scenarios": int(args.max_failed_scenarios),
            "checks_total": total,
            "checks_passed": passed,
            "checks_failed": failed,
            "errors": errors,
        },
        "scenarios": scenarios,
    }


def main() -> int:
    args = _parse_args()
    if float(args.min_admission_score_pct) < 0 or float(args.min_admission_score_pct) > 100:
        print("[license-admission-gate] --min-admission-score-pct must be in range 0..100", file=sys.stderr)
        return 2
    if int(args.max_failed_scenarios) < 0:
        print("[license-admission-gate] --max-failed-scenarios must be >= 0", file=sys.stderr)
        return 2

    repo_root = Path(__file__).resolve().parents[2]
    policy_raw = str(args.license_policy_path or "").strip()
    policy_path = str(_resolve_path(repo_root, policy_raw)) if policy_raw else None

    try:
        scenarios, policy_summary = _run_scenarios(license_policy_path=policy_path)
    except Exception as exc:
        print(f"[license-admission-gate] FAILED import_or_runtime_error={exc}")
        return 2

    report = _build_report(args=args, scenarios=scenarios, policy_summary=policy_summary)

    if args.output:
        output_path = _resolve_path(repo_root, str(args.output))
        _write_json(output_path, report)

    if str(report.get("summary", {}).get("status")) != "pass":
        print("[license-admission-gate] FAILED")
        for err in report.get("summary", {}).get("errors", []):
            print(f"- {err}")
        return 1

    summary = report.get("summary", {})
    print(
        "[license-admission-gate] OK "
        f"admission_score_pct={summary.get('admission_score_pct')} "
        f"failed_scenarios={summary.get('failed_scenarios')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
