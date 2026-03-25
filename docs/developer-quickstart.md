# Developer Quickstart (OpenAI-Compatible Local API)

## Goal

Run Amaryllis locally and send the first OpenAI-compatible request in under 15 minutes.

## 1. Start Runtime

```bash
export AMARYLLIS_SUPPORT_DIR="$HOME/.amaryllis-support"
export AMARYLLIS_AUTH_ENABLED=true
export AMARYLLIS_AUTH_TOKENS='dev-token:user-001:user'
export AMARYLLIS_COGNITION_BACKEND=deterministic

python -m uvicorn runtime.server:app --host 127.0.0.1 --port 8000
```

`deterministic` backend is the fastest local path for integration checks.

## 2. Health Check

```bash
curl -s http://127.0.0.1:8000/health
```

## 3. First OpenAI-Compatible Request

Endpoint: `POST /v1/chat/completions`

```bash
curl -X POST http://127.0.0.1:8000/v1/chat/completions \
  -H "Authorization: Bearer dev-token" \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [
      {"role": "system", "content": "You are concise."},
      {"role": "user", "content": "Say hello from local runtime"}
    ],
    "stream": false
  }'
```

## 4. SDK-Like Examples

- Python: `python examples/openai_compat/python_quickstart.py`
- Node.js: `node examples/openai_compat/node_quickstart.mjs`

Both examples call `POST /v1/chat/completions` and print the assistant reply.

## 5. Minimal SDK Wrappers

- Python helper: `sdk/python/amaryllis_openai_compat.py`
- JavaScript helper: `sdk/javascript/amaryllis_openai_compat.mjs`

Use these wrappers when you need quick integration without bringing a full external SDK.
