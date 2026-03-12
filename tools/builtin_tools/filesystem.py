from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from tools.tool_registry import ToolRegistry

DEFAULT_ROOT = Path.cwd()
ALLOWED_ROOTS = [
    Path(item).expanduser().resolve()
    for item in os.getenv("AMARYLLIS_TOOL_FILESYSTEM_ROOTS", str(DEFAULT_ROOT)).split(",")
    if item.strip()
]
if not ALLOWED_ROOTS:
    ALLOWED_ROOTS = [DEFAULT_ROOT.resolve()]

MAX_READ_BYTES = max(1024, int(os.getenv("AMARYLLIS_TOOL_FILESYSTEM_MAX_READ_BYTES", "1048576")))
MAX_WRITE_BYTES = max(1024, int(os.getenv("AMARYLLIS_TOOL_FILESYSTEM_MAX_WRITE_BYTES", "262144")))


def _safe_path(raw_path: str) -> Path:
    incoming = Path(raw_path).expanduser()
    if incoming.is_absolute():
        candidate = incoming.resolve()
    else:
        candidate = (ALLOWED_ROOTS[0] / incoming).resolve()

    for root in ALLOWED_ROOTS:
        try:
            candidate.relative_to(root)
            return candidate
        except Exception:
            continue

    allowed = ", ".join(str(item) for item in ALLOWED_ROOTS)
    raise PermissionError(f"Path is outside allowed roots: {candidate}. allowed_roots={allowed}")


def _display_path(path: Path) -> str:
    for root in ALLOWED_ROOTS:
        try:
            return str(path.relative_to(root))
        except Exception:
            continue
    return str(path)


def _guard_existing_non_symlink(path: Path) -> None:
    if path.exists() and path.is_symlink():
        raise PermissionError(f"Symlinks are not allowed: {path}")


def _read_with_limit(path: Path) -> str:
    size = path.stat().st_size
    if size > MAX_READ_BYTES:
        raise ValueError(f"File is too large to read ({size} > {MAX_READ_BYTES} bytes)")
    return path.read_text(encoding="utf-8")


def _write_with_limit(path: Path, content: str) -> None:
    payload = content.encode("utf-8")
    size = len(payload)
    if size > MAX_WRITE_BYTES:
        raise ValueError(f"Content is too large to write ({size} > {MAX_WRITE_BYTES} bytes)")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _list_items_within_root(path: Path) -> list[str]:
    result: list[str] = []
    for item in sorted(path.iterdir()):
        _guard_existing_non_symlink(item)
        result.append(item.name)
    return result


def _filesystem_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    action = str(arguments.get("action", "")).strip().lower()
    path = str(arguments.get("path", ".")).strip()

    target = _safe_path(path)
    _guard_existing_non_symlink(target)

    if action == "list":
        if not target.exists() or not target.is_dir():
            raise FileNotFoundError(f"Directory not found: {target}")
        items = _list_items_within_root(target)
        return {"items": items}

    if action == "read":
        if not target.exists() or not target.is_file():
            raise FileNotFoundError(f"File not found: {target}")
        return {"content": _read_with_limit(target)}

    if action == "write":
        content = str(arguments.get("content", ""))
        _write_with_limit(target, content)
        return {"written": True, "path": _display_path(target)}

    raise ValueError("Unsupported action. Use one of: list, read, write")


def register(registry: ToolRegistry) -> None:
    registry.register(
        name="filesystem",
        description="Read, write, and list files inside allowed roots.",
        input_schema={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "read", "write"],
                },
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["action", "path"],
        },
        handler=_filesystem_handler,
        source="builtin",
        risk_level="medium",
        approval_mode="conditional",
        approval_predicate=lambda args: str(args.get("action", "")).strip().lower() == "write",
        isolation="workspace_allowlist",
    )
