from __future__ import annotations

from typing import Any


def run(context: dict[str, Any]) -> dict[str, Any]:
    input_payload = context.get("input", {})
    user_id = context.get("user_id", "")

    return {
        "output": {
            "echo": input_payload,
            "received_user_id": user_id,
        },
        "memory_write": {
            "last_input": input_payload,
        },
    }
