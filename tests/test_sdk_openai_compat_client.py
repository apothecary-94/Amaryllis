from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


class _DummyResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return json.dumps(self._payload, ensure_ascii=False).encode("utf-8")

    def __enter__(self) -> "_DummyResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        _ = (exc_type, exc, tb)


class SDKOpenAICompatClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        sdk_python = repo_root / "sdk" / "python"
        if str(sdk_python) not in sys.path:
            sys.path.insert(0, str(sdk_python))

    def test_chat_completions_success(self) -> None:
        from amaryllis_openai_compat import AmaryllisOpenAICompatClient

        captured: dict[str, object] = {}

        def _fake_urlopen(req, timeout=30):  # type: ignore[no-untyped-def]
            captured["url"] = req.full_url
            captured["timeout"] = timeout
            captured["method"] = req.get_method()
            captured["body"] = req.data.decode("utf-8") if isinstance(req.data, bytes) else ""
            return _DummyResponse(
                {
                    "choices": [
                        {"message": {"role": "assistant", "content": "hello"}}
                    ]
                }
            )

        with patch("amaryllis_openai_compat.request.urlopen", side_effect=_fake_urlopen):
            client = AmaryllisOpenAICompatClient(
                endpoint="http://127.0.0.1:8000",
                token="dev-token",
                timeout_sec=7,
            )
            payload = client.chat_completions(
                messages=[{"role": "user", "content": "hi"}],
                model="deterministic-v1",
            )

        self.assertEqual(str(captured.get("url")), "http://127.0.0.1:8000/v1/chat/completions")
        self.assertEqual(str(captured.get("method")), "POST")
        self.assertEqual(int(float(captured.get("timeout", 0))), 7)
        body = str(captured.get("body"))
        self.assertIn('"messages"', body)
        self.assertIn('"model": "deterministic-v1"', body)
        self.assertEqual(
            AmaryllisOpenAICompatClient.assistant_content(payload),
            "hello",
        )

    def test_chat_completions_requires_messages(self) -> None:
        from amaryllis_openai_compat import AmaryllisOpenAICompatClient

        client = AmaryllisOpenAICompatClient()
        with self.assertRaises(ValueError):
            client.chat_completions(messages=[])


if __name__ == "__main__":
    unittest.main()
