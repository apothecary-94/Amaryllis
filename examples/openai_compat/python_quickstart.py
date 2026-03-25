from __future__ import annotations

import json
import os
from urllib import request


def main() -> None:
    endpoint = os.getenv("AMARYLLIS_ENDPOINT", "http://127.0.0.1:8000").rstrip("/")
    token = os.getenv("AMARYLLIS_TOKEN", "dev-token").strip()

    payload = {
        "messages": [
            {"role": "system", "content": "You are concise."},
            {"role": "user", "content": "Give one-line hello from local API."},
        ],
        "stream": False,
    }

    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url=f"{endpoint}/v1/chat/completions",
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
    )

    with request.urlopen(req, timeout=30) as response:
        raw = response.read().decode("utf-8")
    data = json.loads(raw)
    message = (
        data.get("choices", [{}])[0]
        .get("message", {})
        .get("content", "")
    )
    print(message)


if __name__ == "__main__":
    main()
