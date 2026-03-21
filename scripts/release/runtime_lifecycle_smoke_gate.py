#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import traceback
from typing import Any


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run blocking runtime lifecycle smoke checks (install/start/stop/rollback/uninstall) "
            "and startup SLO probes."
        )
    )
    parser.add_argument(
        "--output",
        default=os.getenv("AMARYLLIS_RUNTIME_LIFECYCLE_SMOKE_OUTPUT", ""),
        help="Optional JSON report output path.",
    )
    parser.add_argument(
        "--max-startup-slo-latency-ms",
        type=float,
        default=float(os.getenv("AMARYLLIS_RUNTIME_LIFECYCLE_MAX_STARTUP_SLO_MS", "3000")),
        help="Maximum allowed startup probe latency for /service/observability/slo.",
    )
    parser.add_argument(
        "--command-timeout-sec",
        type=float,
        default=float(os.getenv("AMARYLLIS_RUNTIME_LIFECYCLE_COMMAND_TIMEOUT_SEC", "45")),
        help="Timeout for each lifecycle CLI command.",
    )
    return parser.parse_args()


def _write_report(path: str, payload: dict[str, Any]) -> None:
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _mark_check(report: dict[str, Any], *, name: str, ok: bool, detail: str) -> None:
    checks = report.setdefault("checks", [])
    assert isinstance(checks, list)
    checks.append({"name": name, "ok": bool(ok), "detail": detail})


def _run_cmd(
    report: dict[str, Any],
    *,
    label: str,
    cmd: list[str],
    cwd: Path,
    timeout_sec: float,
) -> subprocess.CompletedProcess[str]:
    started = time.perf_counter()
    completed = subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=max(5.0, float(timeout_sec)),
        check=False,
    )
    elapsed_ms = round((time.perf_counter() - started) * 1000.0, 2)
    commands = report.setdefault("commands", [])
    assert isinstance(commands, list)
    commands.append(
        {
            "label": label,
            "cmd": cmd,
            "returncode": int(completed.returncode),
            "duration_ms": elapsed_ms,
            "stdout_tail": (completed.stdout or "")[-1200:],
            "stderr_tail": (completed.stderr or "")[-1200:],
        }
    )
    return completed


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _lifecycle_smoke_target(
    report: dict[str, Any],
    *,
    project_root: Path,
    target: str,
    timeout_sec: float,
) -> bool:
    manage_script = project_root / "scripts" / "runtime" / "manage_service.py"
    service_name = "amaryllis-runtime"

    with tempfile.TemporaryDirectory(prefix=f"amaryllis-runtime-lifecycle-{target}-") as tmp:
        root = Path(tmp)
        install_root = root / "install-root"
        bin_dir = root / "bin"
        if target == "linux-systemd":
            manifest_dir = root / "systemd-user"
            manifest_path = manifest_dir / f"{service_name}.service"
            previous_payload = (
                "[Unit]\n"
                "Description=Previous Runtime\n"
                "[Service]\n"
                "ExecStart=/tmp/previous-runtime/amaryllis-runtime\n"
            ).encode("utf-8")
        else:
            manifest_dir = root / "launchagents"
            manifest_path = manifest_dir / f"org.amaryllis.{service_name}.plist"
            previous_payload = b"<?xml version=\"1.0\"?><plist><dict><key>Label</key><string>legacy</string></dict></plist>"
        backup_path = Path(f"{manifest_path}.rollback.bak")
        manifest_dir.mkdir(parents=True, exist_ok=True)
        manifest_path.write_bytes(previous_payload)

        ok = True

        def run_manage(label: str, *args: str) -> subprocess.CompletedProcess[str]:
            return _run_cmd(
                report,
                label=f"{target}:{label}",
                cmd=[sys.executable, str(manage_script), *args, "--command-timeout-sec", str(timeout_sec)],
                cwd=project_root,
                timeout_sec=timeout_sec,
            )

        install = run_manage(
            "install",
            "install",
            "--target",
            target,
            "--service-name",
            service_name,
            "--manifest-dir",
            str(manifest_dir),
            "--install-root",
            str(install_root),
            "--bin-dir",
            str(bin_dir),
            "--skip-runtime-control",
        )
        if install.returncode != 0:
            _mark_check(
                report,
                name=f"{target}_install",
                ok=False,
                detail=f"install failed rc={install.returncode}",
            )
            return False
        _mark_check(report, name=f"{target}_install", ok=True, detail="install command succeeded")

        if not manifest_path.exists():
            _mark_check(report, name=f"{target}_manifest_written", ok=False, detail=f"missing manifest: {manifest_path}")
            ok = False
        else:
            _mark_check(report, name=f"{target}_manifest_written", ok=True, detail=str(manifest_path))

        if not backup_path.exists():
            _mark_check(report, name=f"{target}_backup_written", ok=False, detail=f"missing backup: {backup_path}")
            ok = False
        elif backup_path.read_bytes() != previous_payload:
            _mark_check(report, name=f"{target}_backup_content", ok=False, detail="backup payload mismatch")
            ok = False
        else:
            _mark_check(report, name=f"{target}_backup_content", ok=True, detail=str(backup_path))

        rollback = run_manage(
            "rollback",
            "rollback",
            "--target",
            target,
            "--service-name",
            service_name,
            "--manifest-dir",
            str(manifest_dir),
            "--skip-runtime-control",
        )
        if rollback.returncode != 0:
            _mark_check(report, name=f"{target}_rollback", ok=False, detail=f"rollback failed rc={rollback.returncode}")
            ok = False
        else:
            _mark_check(report, name=f"{target}_rollback", ok=True, detail="rollback command succeeded")

        if manifest_path.read_bytes() != previous_payload:
            _mark_check(report, name=f"{target}_rollback_content", ok=False, detail="manifest not restored from backup")
            ok = False
        else:
            _mark_check(report, name=f"{target}_rollback_content", ok=True, detail="manifest restored from backup")

        for action in ("status", "start", "stop", "restart"):
            action_run = run_manage(
                action,
                action,
                "--target",
                target,
                "--service-name",
                service_name,
                "--manifest-dir",
                str(manifest_dir),
                "--skip-runtime-control",
            )
            action_ok = action_run.returncode == 0
            _mark_check(
                report,
                name=f"{target}_{action}",
                ok=action_ok,
                detail=f"rc={action_run.returncode}",
            )
            ok = ok and action_ok

        uninstall = run_manage(
            "uninstall",
            "uninstall",
            "--target",
            target,
            "--service-name",
            service_name,
            "--manifest-dir",
            str(manifest_dir),
            "--skip-runtime-control",
        )
        if uninstall.returncode != 0:
            _mark_check(report, name=f"{target}_uninstall", ok=False, detail=f"uninstall failed rc={uninstall.returncode}")
            ok = False
        else:
            _mark_check(report, name=f"{target}_uninstall", ok=True, detail="uninstall command succeeded")

        if manifest_path.exists():
            _mark_check(report, name=f"{target}_manifest_removed", ok=False, detail=f"manifest still exists: {manifest_path}")
            ok = False
        else:
            _mark_check(report, name=f"{target}_manifest_removed", ok=True, detail="manifest removed")

        if backup_path.exists():
            _mark_check(report, name=f"{target}_backup_removed", ok=False, detail=f"backup still exists: {backup_path}")
            ok = False
        else:
            _mark_check(report, name=f"{target}_backup_removed", ok=True, detail="backup removed")

        return ok


def _startup_slo_probe(
    report: dict[str, Any],
    *,
    project_root: Path,
    max_startup_slo_latency_ms: float,
) -> bool:
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    try:
        from fastapi.testclient import TestClient
    except Exception as exc:
        _mark_check(report, name="startup_probe_import_fastapi", ok=False, detail=f"fastapi testclient unavailable: {exc}")
        return False

    with tempfile.TemporaryDirectory(prefix="amaryllis-runtime-lifecycle-startup-") as tmp:
        support_dir = Path(tmp) / "support"
        auth_tokens = {
            "admin-token": {"user_id": "admin", "scopes": ["admin", "user"]},
            "user-token": {"user_id": "user-1", "scopes": ["user"]},
            "service-token": {"user_id": "svc-runtime", "scopes": ["service"]},
        }
        env_updates = {
            "AMARYLLIS_SUPPORT_DIR": str(support_dir),
            "AMARYLLIS_AUTH_ENABLED": "true",
            "AMARYLLIS_AUTH_TOKENS": json.dumps(auth_tokens, ensure_ascii=False),
            "AMARYLLIS_MEMORY_CONSOLIDATION_ENABLED": "false",
            "AMARYLLIS_MCP_ENDPOINTS": "",
            "AMARYLLIS_SECURITY_PROFILE": "production",
        }
        previous_values = {key: os.environ.get(key) for key in env_updates}
        for key, value in env_updates.items():
            os.environ[key] = value

        try:
            import runtime.server as server_module
            server_module = importlib.reload(server_module)
            app = server_module.app
            with TestClient(app) as client:
                started = time.perf_counter()
                health = client.get("/service/health", headers=_auth("service-token"))
                health_ms = round((time.perf_counter() - started) * 1000.0, 2)
                if health.status_code != 200:
                    _mark_check(
                        report,
                        name="startup_probe_health_status",
                        ok=False,
                        detail=f"/service/health status={health.status_code}",
                    )
                    return False
                _mark_check(report, name="startup_probe_health_status", ok=True, detail=f"latency_ms={health_ms}")

                started = time.perf_counter()
                slo = client.get("/service/observability/slo", headers=_auth("service-token"))
                slo_ms = round((time.perf_counter() - started) * 1000.0, 2)
                if slo.status_code != 200:
                    _mark_check(
                        report,
                        name="startup_probe_slo_status",
                        ok=False,
                        detail=f"/service/observability/slo status={slo.status_code}",
                    )
                    return False

                payload = {}
                try:
                    payload = dict(slo.json())
                except Exception:
                    payload = {}
                has_slo_signal = bool(payload) and (
                    "snapshot" in payload
                    or "profiles" in payload
                    or "quality_budget" in payload
                    or "slo" in payload
                    or "status" in payload
                    or "runtime_profile" in payload
                )
                _mark_check(
                    report,
                    name="startup_probe_slo_payload",
                    ok=has_slo_signal,
                    detail=f"keys={sorted(payload.keys())[:8]}",
                )
                latency_ok = float(slo_ms) <= float(max_startup_slo_latency_ms)
                _mark_check(
                    report,
                    name="startup_probe_slo_latency",
                    ok=latency_ok,
                    detail=f"observed_ms={slo_ms} max_ms={float(max_startup_slo_latency_ms)}",
                )
                return bool(has_slo_signal and latency_ok)
        finally:
            for key, old_value in previous_values.items():
                if old_value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = old_value


def main() -> int:
    args = _parse_args()
    project_root = Path(__file__).resolve().parents[2]
    report: dict[str, Any] = {
        "suite": "runtime_lifecycle_smoke_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "max_startup_slo_latency_ms": float(args.max_startup_slo_latency_ms),
        "command_timeout_sec": float(args.command_timeout_sec),
        "checks": [],
        "commands": [],
    }

    targets_ok = True
    for target in ("linux-systemd", "macos-launchd"):
        target_ok = _lifecycle_smoke_target(
            report,
            project_root=project_root,
            target=target,
            timeout_sec=float(args.command_timeout_sec),
        )
        targets_ok = targets_ok and target_ok

    startup_ok = _startup_slo_probe(
        report,
        project_root=project_root,
        max_startup_slo_latency_ms=float(args.max_startup_slo_latency_ms),
    )

    checks = report.get("checks", [])
    failed = [item for item in checks if isinstance(item, dict) and not bool(item.get("ok"))]
    report["summary"] = {
        "targets_ok": bool(targets_ok),
        "startup_ok": bool(startup_ok),
        "checks_total": len(checks) if isinstance(checks, list) else 0,
        "checks_failed": len(failed),
    }

    if args.output:
        _write_report(str(args.output), report)
        print(f"[runtime-lifecycle-smoke] report={args.output}")

    if failed:
        print(f"[runtime-lifecycle-smoke] FAILED checks={len(failed)}")
        for item in failed[:20]:
            if isinstance(item, dict):
                print(f"- {item.get('name')}: {item.get('detail')}")
        return 1

    print("[runtime-lifecycle-smoke] OK")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)
