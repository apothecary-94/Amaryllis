#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Validate developer quickstart contract for OpenAI-compatible local API "
            "(docs/examples + runtime integration check)."
        )
    )
    parser.add_argument(
        "--quickstart-doc",
        default="docs/developer-quickstart.md",
        help="Path to quickstart documentation file.",
    )
    parser.add_argument(
        "--examples-dir",
        default="examples/openai_compat",
        help="Path to quickstart examples directory.",
    )
    parser.add_argument(
        "--sdk-root",
        default="sdk",
        help="Path to SDK helpers root directory.",
    )
    parser.add_argument(
        "--token",
        default="dev-token",
        help="Auth token used for quickstart runtime checks.",
    )
    parser.add_argument(
        "--output",
        default="",
        help="Optional JSON report path.",
    )
    return parser.parse_args()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _resolve_path(repo_root: Path, raw: str) -> Path:
    path = Path(str(raw)).expanduser()
    if not path.is_absolute():
        path = repo_root / path
    return path.resolve()


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


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def main() -> int:
    args = _parse_args()
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    quickstart_doc = _resolve_path(repo_root, args.quickstart_doc)
    examples_dir = _resolve_path(repo_root, args.examples_dir)
    sdk_root = _resolve_path(repo_root, args.sdk_root)
    python_example = examples_dir / "python_quickstart.py"
    node_example = examples_dir / "node_quickstart.mjs"
    python_sdk = sdk_root / "python" / "amaryllis_openai_compat.py"
    javascript_sdk = sdk_root / "javascript" / "amaryllis_openai_compat.mjs"

    checks: list[dict[str, Any]] = []

    def add_check(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    if quickstart_doc.exists():
        doc_text = quickstart_doc.read_text(encoding="utf-8")
        add_check("quickstart_doc_exists", True, str(quickstart_doc))
        add_check(
            "quickstart_doc_openai_endpoint",
            "POST /v1/chat/completions" in doc_text,
            "docs must include OpenAI-compatible endpoint",
        )
        add_check(
            "quickstart_doc_examples_referenced",
            ("python_quickstart.py" in doc_text and "node_quickstart.mjs" in doc_text),
            "docs must reference python/node quickstart examples",
        )
        add_check(
            "quickstart_doc_sdk_referenced",
            ("sdk/python/amaryllis_openai_compat.py" in doc_text and "sdk/javascript/amaryllis_openai_compat.mjs" in doc_text),
            "docs must reference python/javascript SDK wrappers",
        )
    else:
        add_check("quickstart_doc_exists", False, f"missing: {quickstart_doc}")
        doc_text = ""

    if python_example.exists():
        text = python_example.read_text(encoding="utf-8")
        add_check("python_example_exists", True, str(python_example))
        add_check(
            "python_example_calls_chat_completions",
            "/v1/chat/completions" in text,
            "python example must call OpenAI-compatible chat endpoint",
        )
    else:
        add_check("python_example_exists", False, f"missing: {python_example}")

    if node_example.exists():
        text = node_example.read_text(encoding="utf-8")
        add_check("node_example_exists", True, str(node_example))
        add_check(
            "node_example_calls_chat_completions",
            "/v1/chat/completions" in text,
            "node example must call OpenAI-compatible chat endpoint",
        )
    else:
        add_check("node_example_exists", False, f"missing: {node_example}")

    if python_sdk.exists():
        text = python_sdk.read_text(encoding="utf-8")
        add_check("python_sdk_exists", True, str(python_sdk))
        add_check(
            "python_sdk_calls_chat_completions_endpoint",
            "/v1/chat/completions" in text,
            "python SDK helper must call OpenAI-compatible chat endpoint",
        )
    else:
        add_check("python_sdk_exists", False, f"missing: {python_sdk}")

    if javascript_sdk.exists():
        text = javascript_sdk.read_text(encoding="utf-8")
        add_check("javascript_sdk_exists", True, str(javascript_sdk))
        add_check(
            "javascript_sdk_calls_chat_completions_endpoint",
            "/v1/chat/completions" in text,
            "javascript SDK helper must call OpenAI-compatible chat endpoint",
        )
    else:
        add_check("javascript_sdk_exists", False, f"missing: {javascript_sdk}")

    tmp_dir = tempfile.TemporaryDirectory(prefix="amaryllis-quickstart-gate-")
    support_dir = Path(tmp_dir.name) / "support"
    token = str(args.token).strip() or "dev-token"

    os.environ["AMARYLLIS_AUTH_ENABLED"] = "true"
    os.environ["AMARYLLIS_AUTH_TOKENS"] = json.dumps(
        {
            token: {"user_id": "quickstart-user", "scopes": ["user"]},
            "quickstart-admin-token": {"user_id": "quickstart-admin", "scopes": ["admin", "user"]},
            "quickstart-service-token": {"user_id": "quickstart-service", "scopes": ["service"]},
        },
        ensure_ascii=False,
    )
    os.environ["AMARYLLIS_SUPPORT_DIR"] = str(support_dir)
    os.environ["AMARYLLIS_MEMORY_CONSOLIDATION_ENABLED"] = "false"
    os.environ["AMARYLLIS_MCP_ENDPOINTS"] = ""
    os.environ["AMARYLLIS_SECURITY_PROFILE"] = "production"
    os.environ["AMARYLLIS_COGNITION_BACKEND"] = "deterministic"
    os.environ["AMARYLLIS_AUTOMATION_ENABLED"] = "false"
    os.environ["AMARYLLIS_BACKUP_ENABLED"] = "false"
    os.environ["AMARYLLIS_BACKUP_RESTORE_DRILL_ENABLED"] = "false"
    os.environ["AMARYLLIS_REQUEST_TRACE_LOGS_ENABLED"] = "false"

    app = None
    try:
        from fastapi.testclient import TestClient  # noqa: PLC0415
        from runtime.server import create_app  # noqa: PLC0415

        app = create_app()
        with TestClient(app) as client:
            models = client.get("/v1/models", headers=_auth(token))
            add_check(
                "runtime_models_endpoint_ok",
                models.status_code == 200,
                f"status={models.status_code}",
            )
            payload = models.json() if models.headers.get("content-type", "").startswith("application/json") else {}
            active = payload.get("active") if isinstance(payload, dict) else {}
            active_provider = str(active.get("provider") if isinstance(active, dict) else "")
            add_check(
                "runtime_models_payload_has_active_provider",
                bool(active_provider),
                f"active_provider={active_provider}",
            )

            completion = client.post(
                "/v1/chat/completions",
                headers=_auth(token),
                json={
                    "messages": [
                        {"role": "system", "content": "You are concise."},
                        {"role": "user", "content": "Say hello"},
                    ],
                    "stream": False,
                },
            )
            add_check(
                "runtime_chat_completions_ok",
                completion.status_code == 200,
                f"status={completion.status_code}",
            )
            completion_payload = (
                completion.json()
                if completion.headers.get("content-type", "").startswith("application/json")
                else {}
            )
            choices = completion_payload.get("choices") if isinstance(completion_payload, dict) else None
            content = ""
            if isinstance(choices, list) and choices and isinstance(choices[0], dict):
                message = choices[0].get("message")
                if isinstance(message, dict):
                    content = str(message.get("content") or "")
            add_check(
                "runtime_chat_completions_has_content",
                bool(content.strip()),
                "chat completion must return non-empty assistant content",
            )
    except Exception as exc:
        add_check("quickstart_runtime_check_error", False, str(exc))
    finally:
        if app is not None:
            _shutdown_app(app)
        tmp_dir.cleanup()

    failed = [item for item in checks if not bool(item.get("ok"))]
    report = {
        "generated_at": _utc_now_iso(),
        "suite": "api_quickstart_compatibility_gate_v1",
        "summary": {
            "status": "pass" if not failed else "fail",
            "checks_total": len(checks),
            "checks_failed": len(failed),
        },
        "checks": checks,
    }

    if args.output:
        output_path = _resolve_path(repo_root, args.output)
        _write_json(output_path, report)

    if failed:
        print("[api-quickstart-gate] FAILED")
        for item in failed:
            print(f"- {item.get('name')}: {item.get('detail')}")
        return 1

    print(f"[api-quickstart-gate] OK checks={len(checks)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
