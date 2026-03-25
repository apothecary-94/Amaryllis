from __future__ import annotations

import json
from typing import Any
from urllib import error, request


class AmaryllisOpenAICompatClient:
    def __init__(
        self,
        *,
        endpoint: str = "http://127.0.0.1:8000",
        token: str = "dev-token",
        timeout_sec: float = 30.0,
    ) -> None:
        normalized_endpoint = str(endpoint or "").strip().rstrip("/")
        if not normalized_endpoint:
            raise ValueError("endpoint is required")
        self.endpoint = normalized_endpoint
        self.token = str(token or "").strip()
        self.timeout_sec = max(1.0, float(timeout_sec))

    def chat_completions(
        self,
        *,
        messages: list[dict[str, Any]],
        model: str | None = None,
        stream: bool = False,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not isinstance(messages, list) or not messages:
            raise ValueError("messages must be a non-empty list")
        payload: dict[str, Any] = {
            "messages": messages,
            "stream": bool(stream),
        }
        model_name = str(model or "").strip()
        if model_name:
            payload["model"] = model_name
        if extra:
            payload.update(extra)
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        req = request.Request(
            url=f"{self.endpoint}/v1/chat/completions",
            data=body,
            method="POST",
            headers=headers,
        )

        try:
            with request.urlopen(req, timeout=self.timeout_sec) as response:
                raw = response.read().decode("utf-8")
        except error.HTTPError as exc:  # pragma: no cover - network path
            detail = ""
            try:
                detail = exc.read().decode("utf-8")
            except Exception:
                detail = str(exc)
            raise RuntimeError(f"request failed status={exc.code} detail={detail}") from exc

        data = json.loads(raw)
        if not isinstance(data, dict):
            raise RuntimeError("response must be a JSON object")
        return data

    @staticmethod
    def assistant_content(payload: dict[str, Any]) -> str:
        if not isinstance(payload, dict):
            return ""
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            return ""
        first = choices[0]
        if not isinstance(first, dict):
            return ""
        message = first.get("message")
        if not isinstance(message, dict):
            return ""
        return str(message.get("content") or "")
