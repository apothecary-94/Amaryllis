from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


def build_context(user_id: str, input_data: dict[str, Any]) -> dict[str, Any]:
    return {
        "request_id": str(uuid4()),
        "user_id": user_id,
        "input": input_data,
        "memory": {},
        "metadata": {
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
        },
    }
