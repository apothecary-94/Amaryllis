#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
import sys
from typing import Sequence


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Manage local runtime service lifecycle for Linux systemd user service "
            "and macOS launchd agent."
        )
    )
    parser.add_argument(
        "command",
        choices=("install", "uninstall", "start", "stop", "restart", "status", "rollback", "render"),
        help="Lifecycle command.",
    )
    parser.add_argument(
        "--target",
        required=True,
        choices=("linux-systemd", "macos-launchd"),
        help="Service target platform.",
    )
    parser.add_argument(
        "--service-name",
        default="amaryllis-runtime",
        help="Service/agent name.",
    )
    parser.add_argument(
        "--install-root",
        default=str(Path.home() / ".local" / "share" / "amaryllis"),
        help="Runtime install root.",
    )
    parser.add_argument(
        "--bin-dir",
        default=str(Path.home() / ".local" / "bin"),
        help="Launcher directory.",
    )
    parser.add_argument(
        "--channel",
        default="stable",
        choices=("stable", "canary"),
        help="Runtime channel.",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Runtime host.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Runtime port.",
    )
    parser.add_argument(
        "--working-directory",
        default="",
        help="Optional working directory override.",
    )
    parser.add_argument(
        "--label-prefix",
        default="org.amaryllis",
        help="launchd label prefix.",
    )
    parser.add_argument(
        "--environment",
        action="append",
        default=[],
        help="Extra environment KEY=VALUE (repeatable).",
    )
    parser.add_argument(
        "--manifest-dir",
        default="",
        help="Override manifest directory for install/uninstall/rollback.",
    )
    parser.add_argument(
        "--renderer-script",
        default="",
        help="Override renderer script path.",
    )
    parser.add_argument(
        "--renderer-python",
        default=sys.executable,
        help="Python executable for renderer script.",
    )
    parser.add_argument(
        "--command-timeout-sec",
        type=float,
        default=30.0,
        help="Timeout for lifecycle shell commands.",
    )
    parser.add_argument(
        "--systemctl-bin",
        default="systemctl",
        help="systemctl executable path/name for Linux target.",
    )
    parser.add_argument(
        "--launchctl-bin",
        default="launchctl",
        help="launchctl executable path/name for macOS target.",
    )
    parser.add_argument(
        "--skip-runtime-control",
        action="store_true",
        help="Skip systemctl/launchctl calls (manifest management only).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print actions without modifying files or invoking runtime commands.",
    )
    return parser.parse_args()


@dataclass(frozen=True)
class ServiceTarget:
    target: str
    service_name: str
    label: str
    manifest_path: Path
    launcher_path: Path

    @property
    def unit_name(self) -> str:
        if self.target == "linux-systemd":
            return f"{self.service_name}.service"
        return self.label

    @property
    def backup_path(self) -> Path:
        return Path(f"{self.manifest_path}.rollback.bak")


def _normalize_label(*, label_prefix: str, service_name: str) -> str:
    prefix = str(label_prefix or "org.amaryllis").strip().strip(".") or "org.amaryllis"
    normalized_service = str(service_name or "amaryllis-runtime").strip().replace(" ", "-")
    return f"{prefix}.{normalized_service}"


def _resolve_service_target(args: argparse.Namespace) -> ServiceTarget:
    service_name = str(args.service_name or "").strip()
    if not service_name:
        raise ValueError("--service-name must be non-empty")

    launcher_path = Path(args.bin_dir).expanduser() / service_name
    label = _normalize_label(label_prefix=str(args.label_prefix), service_name=service_name)

    override_dir = str(args.manifest_dir or "").strip()
    if override_dir:
        manifest_dir = Path(override_dir).expanduser()
    elif args.target == "linux-systemd":
        manifest_dir = Path.home() / ".config" / "systemd" / "user"
    else:
        manifest_dir = Path.home() / "Library" / "LaunchAgents"

    if args.target == "linux-systemd":
        manifest_path = manifest_dir / f"{service_name}.service"
    else:
        manifest_path = manifest_dir / f"{label}.plist"

    return ServiceTarget(
        target=str(args.target),
        service_name=service_name,
        label=label,
        manifest_path=manifest_path,
        launcher_path=launcher_path,
    )


def _renderer_script_path(args: argparse.Namespace) -> Path:
    override = str(args.renderer_script or "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return (Path(__file__).resolve().parent / "render_service_manifest.py").resolve()


def _render_manifest(args: argparse.Namespace, target: ServiceTarget) -> str:
    renderer = _renderer_script_path(args)
    command = [
        str(args.renderer_python),
        str(renderer),
        "--target",
        target.target,
        "--service-name",
        target.service_name,
        "--install-root",
        str(Path(args.install_root).expanduser()),
        "--bin-dir",
        str(Path(args.bin_dir).expanduser()),
        "--channel",
        str(args.channel),
        "--host",
        str(args.host),
        "--port",
        str(int(args.port)),
        "--label-prefix",
        str(args.label_prefix),
    ]
    working_directory = str(args.working_directory or "").strip()
    if working_directory:
        command.extend(["--working-directory", working_directory])
    for item in list(args.environment or []):
        command.extend(["--environment", str(item)])

    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        timeout=max(1.0, float(args.command_timeout_sec)),
    )
    if completed.returncode != 0:
        stderr = str(completed.stderr or "").strip()
        stdout = str(completed.stdout or "").strip()
        message = stderr or stdout or f"renderer exited with code {completed.returncode}"
        raise RuntimeError(f"manifest render failed: {message}")
    return str(completed.stdout or "")


def _run_shell_command(
    *,
    command: Sequence[str],
    timeout_sec: float,
    dry_run: bool,
    allow_failure: bool,
) -> int:
    printable = " ".join(command)
    print(f"+ {printable}")
    if dry_run:
        return 0

    completed = subprocess.run(
        list(command),
        capture_output=True,
        text=True,
        check=False,
        timeout=max(1.0, float(timeout_sec)),
    )
    if completed.stdout:
        print(completed.stdout.rstrip())
    if completed.stderr:
        print(completed.stderr.rstrip(), file=sys.stderr)
    if completed.returncode != 0 and not allow_failure:
        raise RuntimeError(f"command failed ({completed.returncode}): {printable}")
    return int(completed.returncode)


def _linux_commands(action: str, unit_name: str, systemctl_bin: str) -> list[list[str]]:
    if action == "start":
        return [[systemctl_bin, "--user", "start", unit_name]]
    if action == "stop":
        return [[systemctl_bin, "--user", "stop", unit_name]]
    if action == "restart":
        return [[systemctl_bin, "--user", "restart", unit_name]]
    if action == "status":
        return [[systemctl_bin, "--user", "status", unit_name, "--no-pager"]]
    return []


def _macos_commands(action: str, label: str, manifest_path: Path, launchctl_bin: str) -> list[list[str]]:
    if action == "start":
        return [[launchctl_bin, "start", label]]
    if action == "stop":
        return [[launchctl_bin, "stop", label]]
    if action == "restart":
        return [[launchctl_bin, "stop", label], [launchctl_bin, "start", label]]
    if action == "status":
        return [[launchctl_bin, "print", f"gui/{os.getuid()}/{label}"], [launchctl_bin, "print", label]]
    if action == "load":
        return [[launchctl_bin, "load", str(manifest_path)]]
    if action == "unload":
        return [[launchctl_bin, "unload", str(manifest_path)]]
    return []


def _run_control_action(args: argparse.Namespace, target: ServiceTarget, action: str) -> int:
    if args.skip_runtime_control:
        print(f"[runtime-lifecycle] skip runtime control action='{action}'")
        return 0

    timeout_sec = float(args.command_timeout_sec)
    if target.target == "linux-systemd":
        commands = _linux_commands(action, target.unit_name, str(args.systemctl_bin))
        for command in commands:
            _run_shell_command(
                command=command,
                timeout_sec=timeout_sec,
                dry_run=bool(args.dry_run),
                allow_failure=(action == "status"),
            )
        return 0

    if action == "status":
        primary, fallback = _macos_commands("status", target.label, target.manifest_path, str(args.launchctl_bin))
        code = _run_shell_command(
            command=primary,
            timeout_sec=timeout_sec,
            dry_run=bool(args.dry_run),
            allow_failure=True,
        )
        if code != 0:
            _run_shell_command(
                command=fallback,
                timeout_sec=timeout_sec,
                dry_run=bool(args.dry_run),
                allow_failure=True,
            )
        return 0

    for command in _macos_commands(action, target.label, target.manifest_path, str(args.launchctl_bin)):
        _run_shell_command(
            command=command,
            timeout_sec=timeout_sec,
            dry_run=bool(args.dry_run),
            allow_failure=False,
        )
    return 0


def _write_bytes_atomically(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp")
    temp.write_bytes(payload)
    temp.replace(path)


def _backup_manifest(args: argparse.Namespace, target: ServiceTarget) -> bool:
    if not target.manifest_path.exists():
        if target.backup_path.exists():
            if args.dry_run:
                print(f"[runtime-lifecycle] dry-run clear stale backup: {target.backup_path}")
            else:
                target.backup_path.unlink()
                print(f"[runtime-lifecycle] cleared stale backup: {target.backup_path}")
        return False

    if args.dry_run:
        print(
            "[runtime-lifecycle] dry-run backup current manifest "
            f"{target.manifest_path} -> {target.backup_path}"
        )
        return True

    _write_bytes_atomically(target.backup_path, target.manifest_path.read_bytes())
    print(f"[runtime-lifecycle] backup current manifest -> {target.backup_path}")
    return True


def _restore_manifest_from_backup(args: argparse.Namespace, target: ServiceTarget) -> bool:
    if not target.backup_path.exists():
        return False
    if args.dry_run:
        print(f"[runtime-lifecycle] dry-run restore manifest from backup: {target.backup_path}")
        return True
    _write_bytes_atomically(target.manifest_path, target.backup_path.read_bytes())
    print(f"[runtime-lifecycle] restored manifest from backup: {target.backup_path}")
    return True


def _run_install_runtime_control(args: argparse.Namespace, target: ServiceTarget) -> None:
    if target.target == "linux-systemd":
        _run_shell_command(
            command=[str(args.systemctl_bin), "--user", "daemon-reload"],
            timeout_sec=float(args.command_timeout_sec),
            dry_run=bool(args.dry_run),
            allow_failure=False,
        )
        _run_shell_command(
            command=[str(args.systemctl_bin), "--user", "enable", target.unit_name],
            timeout_sec=float(args.command_timeout_sec),
            dry_run=bool(args.dry_run),
            allow_failure=False,
        )
        _run_shell_command(
            command=[str(args.systemctl_bin), "--user", "restart", target.unit_name],
            timeout_sec=float(args.command_timeout_sec),
            dry_run=bool(args.dry_run),
            allow_failure=False,
        )
        return

    _run_shell_command(
        command=[str(args.launchctl_bin), "unload", str(target.manifest_path)],
        timeout_sec=float(args.command_timeout_sec),
        dry_run=bool(args.dry_run),
        allow_failure=True,
    )
    _run_shell_command(
        command=[str(args.launchctl_bin), "load", str(target.manifest_path)],
        timeout_sec=float(args.command_timeout_sec),
        dry_run=bool(args.dry_run),
        allow_failure=False,
    )


def _run_rollback_runtime_control(args: argparse.Namespace, target: ServiceTarget) -> None:
    if target.target == "linux-systemd":
        _run_shell_command(
            command=[str(args.systemctl_bin), "--user", "daemon-reload"],
            timeout_sec=float(args.command_timeout_sec),
            dry_run=bool(args.dry_run),
            allow_failure=False,
        )
        _run_shell_command(
            command=[str(args.systemctl_bin), "--user", "restart", target.unit_name],
            timeout_sec=float(args.command_timeout_sec),
            dry_run=bool(args.dry_run),
            allow_failure=False,
        )
        return

    _run_shell_command(
        command=[str(args.launchctl_bin), "unload", str(target.manifest_path)],
        timeout_sec=float(args.command_timeout_sec),
        dry_run=bool(args.dry_run),
        allow_failure=True,
    )
    _run_shell_command(
        command=[str(args.launchctl_bin), "load", str(target.manifest_path)],
        timeout_sec=float(args.command_timeout_sec),
        dry_run=bool(args.dry_run),
        allow_failure=False,
    )


def _install(args: argparse.Namespace, target: ServiceTarget) -> int:
    rendered = _render_manifest(args, target)
    print(f"[runtime-lifecycle] manifest target={target.manifest_path}")
    had_previous_manifest = _backup_manifest(args, target)

    if args.dry_run:
        print("[runtime-lifecycle] dry-run install; manifest preview:")
        print(rendered)
    else:
        _write_bytes_atomically(target.manifest_path, rendered.encode("utf-8"))
        print(f"[runtime-lifecycle] wrote manifest: {target.manifest_path}")

    if args.skip_runtime_control:
        print("[runtime-lifecycle] skip runtime control during install")
        print("[runtime-lifecycle] install OK")
        return 0

    try:
        _run_install_runtime_control(args, target)
    except RuntimeError as exc:
        print(f"[runtime-lifecycle] install failed; rollback attempt: {exc}", file=sys.stderr)
        rollback_applied = False
        if had_previous_manifest:
            rollback_applied = _restore_manifest_from_backup(args, target)
        else:
            if args.dry_run:
                print(f"[runtime-lifecycle] dry-run remove manifest after failure: {target.manifest_path}")
                rollback_applied = True
            elif target.manifest_path.exists():
                target.manifest_path.unlink()
                print(f"[runtime-lifecycle] removed manifest after failed first install: {target.manifest_path}")
                rollback_applied = True

        if target.target == "linux-systemd" and not args.skip_runtime_control:
            _run_shell_command(
                command=[str(args.systemctl_bin), "--user", "daemon-reload"],
                timeout_sec=float(args.command_timeout_sec),
                dry_run=bool(args.dry_run),
                allow_failure=True,
            )
        state = "rollback applied" if rollback_applied else "rollback not possible"
        raise RuntimeError(f"install failed ({state}): {exc}") from exc

    print("[runtime-lifecycle] install OK")
    return 0


def _uninstall(args: argparse.Namespace, target: ServiceTarget) -> int:
    if not args.skip_runtime_control:
        if target.target == "linux-systemd":
            _run_shell_command(
                command=[str(args.systemctl_bin), "--user", "stop", target.unit_name],
                timeout_sec=float(args.command_timeout_sec),
                dry_run=bool(args.dry_run),
                allow_failure=True,
            )
            _run_shell_command(
                command=[str(args.systemctl_bin), "--user", "disable", target.unit_name],
                timeout_sec=float(args.command_timeout_sec),
                dry_run=bool(args.dry_run),
                allow_failure=True,
            )
        else:
            _run_shell_command(
                command=[str(args.launchctl_bin), "unload", str(target.manifest_path)],
                timeout_sec=float(args.command_timeout_sec),
                dry_run=bool(args.dry_run),
                allow_failure=True,
            )
    else:
        print("[runtime-lifecycle] skip runtime control during uninstall")

    if args.dry_run:
        print(f"[runtime-lifecycle] dry-run remove manifest: {target.manifest_path}")
        if target.backup_path.exists():
            print(f"[runtime-lifecycle] dry-run remove backup: {target.backup_path}")
    else:
        if target.manifest_path.exists():
            target.manifest_path.unlink()
            print(f"[runtime-lifecycle] removed manifest: {target.manifest_path}")
        else:
            print(f"[runtime-lifecycle] manifest not found: {target.manifest_path}")
        if target.backup_path.exists():
            target.backup_path.unlink()
            print(f"[runtime-lifecycle] removed backup: {target.backup_path}")

    if target.target == "linux-systemd" and not args.skip_runtime_control:
        _run_shell_command(
            command=[str(args.systemctl_bin), "--user", "daemon-reload"],
            timeout_sec=float(args.command_timeout_sec),
            dry_run=bool(args.dry_run),
            allow_failure=True,
        )

    print("[runtime-lifecycle] uninstall OK")
    return 0


def _rollback(args: argparse.Namespace, target: ServiceTarget) -> int:
    if not target.backup_path.exists():
        raise RuntimeError(f"rollback backup not found: {target.backup_path}")

    _restore_manifest_from_backup(args, target)
    if args.skip_runtime_control:
        print("[runtime-lifecycle] skip runtime control during rollback")
        print("[runtime-lifecycle] rollback OK")
        return 0

    _run_rollback_runtime_control(args, target)
    print("[runtime-lifecycle] rollback OK")
    return 0


def main() -> int:
    args = _parse_args()

    if int(args.port) <= 0 or int(args.port) > 65535:
        print("[runtime-lifecycle] --port must be in [1, 65535]", file=sys.stderr)
        return 2

    try:
        target = _resolve_service_target(args)
    except ValueError as exc:
        print(f"[runtime-lifecycle] {exc}", file=sys.stderr)
        return 2

    command = str(args.command)
    if command == "render":
        try:
            text = _render_manifest(args, target)
        except RuntimeError as exc:
            print(f"[runtime-lifecycle] {exc}", file=sys.stderr)
            return 1
        print(text)
        return 0

    try:
        if command == "install":
            return _install(args, target)
        if command == "uninstall":
            return _uninstall(args, target)
        if command == "rollback":
            return _rollback(args, target)
        if command in {"start", "stop", "restart", "status"}:
            return _run_control_action(args, target, action=command)
    except RuntimeError as exc:
        print(f"[runtime-lifecycle] {exc}", file=sys.stderr)
        return 1

    print(f"[runtime-lifecycle] unsupported command: {command}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
