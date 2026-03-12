from __future__ import annotations

import os
import subprocess
import sys
from tempfile import TemporaryDirectory
from typing import Any

from tools.tool_registry import ToolRegistry

MAX_CODE_CHARS = max(100, int(os.getenv("AMARYLLIS_TOOL_PYTHON_EXEC_MAX_CODE_CHARS", "4000")))
MAX_TIMEOUT_SEC = max(1, int(os.getenv("AMARYLLIS_TOOL_PYTHON_EXEC_MAX_TIMEOUT_SEC", "10")))
MAX_OUTPUT_CHARS = max(256, int(os.getenv("AMARYLLIS_TOOL_PYTHON_EXEC_MAX_OUTPUT_CHARS", "20000")))

# Minimal static deny-list for obviously dangerous snippets.
FORBIDDEN_SNIPPET_TOKENS = (
    "import socket",
    "subprocess.",
    "os.system(",
    "pty.",
    "fork(",
)


def _python_exec_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    code = str(arguments.get("code", "")).strip()
    timeout = int(arguments.get("timeout", 8))

    if not code:
        raise ValueError("code is required")
    if len(code) > MAX_CODE_CHARS:
        raise ValueError(f"code is too large ({len(code)} > {MAX_CODE_CHARS})")
    if timeout > MAX_TIMEOUT_SEC:
        raise ValueError(f"timeout is too large ({timeout} > {MAX_TIMEOUT_SEC})")
    lowered = code.lower()
    for token in FORBIDDEN_SNIPPET_TOKENS:
        if token in lowered:
            raise ValueError(f"code contains forbidden token: {token}")

    with TemporaryDirectory(prefix="amaryllis-python-exec-") as sandbox_dir:
        completed = subprocess.run(
            [sys.executable, "-I", "-c", code],
            capture_output=True,
            text=True,
            timeout=max(1, timeout),
            cwd=sandbox_dir,
            env={
                "PYTHONUNBUFFERED": "1",
            },
        )

    return {
        "returncode": completed.returncode,
        "stdout": _truncate_text(completed.stdout),
        "stderr": _truncate_text(completed.stderr),
        "truncated": (
            len(completed.stdout or "") > MAX_OUTPUT_CHARS
            or len(completed.stderr or "") > MAX_OUTPUT_CHARS
        ),
    }


def _truncate_text(text: str) -> str:
    value = text or ""
    if len(value) <= MAX_OUTPUT_CHARS:
        return value
    return value[:MAX_OUTPUT_CHARS] + "\\n...[truncated]..."


def register(registry: ToolRegistry) -> None:
    registry.register(
        name="python_exec",
        description="Execute a short Python snippet in a subprocess.",
        input_schema={
            "type": "object",
            "properties": {
                "code": {"type": "string"},
                "timeout": {"type": "integer", "minimum": 1, "maximum": 60},
            },
            "required": ["code"],
        },
        handler=_python_exec_handler,
        source="builtin",
        risk_level="high",
        approval_mode="required",
        isolation="sandboxed_subprocess",
    )
