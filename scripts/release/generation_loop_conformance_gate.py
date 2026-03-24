#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Validate generation-loop contract and provider conformance matrix "
            "for the local runtime."
        )
    )
    parser.add_argument(
        "--max-warning-providers",
        type=int,
        default=int(os.getenv("AMARYLLIS_GENLOOP_MAX_WARNING_PROVIDERS", "1000000")),
        help="Maximum allowed provider count with conformance status=warn.",
    )
    parser.add_argument(
        "--min-providers",
        type=int,
        default=int(os.getenv("AMARYLLIS_GENLOOP_MIN_PROVIDERS", "1")),
        help="Minimum required providers in conformance matrix.",
    )
    parser.add_argument(
        "--require-provider",
        action="append",
        default=[],
        help="Provider name that must exist in conformance matrix (repeatable).",
    )
    parser.add_argument(
        "--output",
        default="",
        help="Optional JSON report output path.",
    )
    return parser.parse_args()


def _shutdown_app(app: object) -> None:
    services = getattr(getattr(app, "state", None), "services", None)
    if services is None:
        return
    try:
        services.automation_scheduler.stop()
        if services.memory_consolidation_worker is not None:
            services.memory_consolidation_worker.stop()
        if services.backup_scheduler is not None:
            services.backup_scheduler.stop()
        services.agent_run_manager.stop()
        services.database.close()
        services.vector_store.persist()
    except Exception:
        pass


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    args = _parse_args()
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    tmp_dir = tempfile.TemporaryDirectory(prefix="amaryllis-genloop-gate-")
    support_dir = Path(tmp_dir.name) / "support"
    if not (os.getenv("AMARYLLIS_AUTH_TOKENS") or os.getenv("AMARYLLIS_API_TOKEN")):
        os.environ["AMARYLLIS_AUTH_TOKENS"] = json.dumps(
            {
                "gate-user-token": {"user_id": "gate-user", "scopes": ["user"]},
                "gate-admin-token": {"user_id": "gate-admin", "scopes": ["admin", "user"]},
                "gate-service-token": {"user_id": "gate-service", "scopes": ["service"]},
            },
            ensure_ascii=False,
        )
    os.environ.setdefault("AMARYLLIS_AUTH_ENABLED", "true")
    os.environ.setdefault("AMARYLLIS_SUPPORT_DIR", str(support_dir))
    os.environ.setdefault("AMARYLLIS_MEMORY_CONSOLIDATION_ENABLED", "false")
    os.environ.setdefault("AMARYLLIS_MCP_ENDPOINTS", "")
    os.environ.setdefault("AMARYLLIS_SECURITY_PROFILE", "production")

    try:
        from fastapi.testclient import TestClient  # noqa: PLC0415
        from runtime.server import create_app  # noqa: PLC0415
    except Exception as exc:  # pragma: no cover - defensive
        print(f"[generation-loop-gate] FAILED import_error={exc}")
        tmp_dir.cleanup()
        return 2

    app = create_app()
    errors: list[str] = []
    report: dict[str, Any] = {}

    try:
        with TestClient(app) as client:
            response = client.get(
                "/models/generation-loop/contract",
                headers={"Authorization": "Bearer gate-user-token"},
            )
            if response.status_code != 200:
                errors.append(f"endpoint_status={response.status_code}")
            payload = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
            if not isinstance(payload, dict):
                errors.append("payload_not_object")
                payload = {}

            contract_version = str(payload.get("contract_version") or "")
            if contract_version != "generation_loop_contract_v1":
                errors.append("contract_version_mismatch")

            providers_raw = payload.get("providers")
            providers = providers_raw if isinstance(providers_raw, dict) else {}
            provider_count = len(providers)
            if provider_count < max(0, int(args.min_providers)):
                errors.append("provider_count_below_min")

            missing_required: list[str] = []
            for required in [str(item).strip() for item in args.require_provider if str(item).strip()]:
                if required not in providers:
                    missing_required.append(required)
            if missing_required:
                errors.append(f"missing_required_providers:{','.join(sorted(missing_required))}")

            warning_count = 0
            for provider_name, provider_payload_raw in providers.items():
                provider_payload = provider_payload_raw if isinstance(provider_payload_raw, dict) else {}
                conformance_raw = provider_payload.get("conformance")
                conformance = conformance_raw if isinstance(conformance_raw, dict) else {}
                status = str(conformance.get("status") or "").strip().lower()
                if status == "warn":
                    warning_count += 1
                if status not in {"pass", "warn"}:
                    errors.append(f"invalid_status:{provider_name}")

            if warning_count > max(0, int(args.max_warning_providers)):
                errors.append(
                    f"warnings_exceeded:{warning_count}>{max(0, int(args.max_warning_providers))}"
                )

            report = {
                "suite": "generation_loop_conformance_gate_v1",
                "summary": {
                    "status": "pass" if not errors else "fail",
                    "errors": errors,
                    "provider_count": provider_count,
                    "warning_count": warning_count,
                    "max_warning_providers": max(0, int(args.max_warning_providers)),
                    "min_providers": max(0, int(args.min_providers)),
                },
                "contract_version": contract_version,
                "providers": sorted(providers.keys()),
            }
    finally:
        _shutdown_app(app)
        tmp_dir.cleanup()

    if args.output:
        output_path = Path(args.output)
        if not output_path.is_absolute():
            output_path = repo_root / output_path
        _write_json(output_path, report)

    if errors:
        print("[generation-loop-gate] FAILED")
        for err in errors:
            print(f"- {err}")
        return 1

    print(
        "[generation-loop-gate] OK "
        f"providers={report.get('summary', {}).get('provider_count', 0)} "
        f"warnings={report.get('summary', {}).get('warning_count', 0)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
