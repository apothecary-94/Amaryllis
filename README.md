# Amaryllis v0.3

Modular runtime for executing AI modules with a clean single-node flow:
`HTTP request -> Context -> Module -> Result`.

This version is focused on a stable foundation:
- strict Pydantic models for request, context, and module output
- structured JSON errors with `request_id`
- in-memory session memory by `session_id`
- module isolation via subprocess execution

## What It Does

- accepts `POST /execute`
- generates `request_id` for every call
- loads module from local `./modules/<module_name>`
- validates `module.yaml` and `runtime_api == "1.0"`
- runs module in isolated subprocess (`python <entrypoint>`)
- passes context JSON through `stdin`
- reads module result JSON from `stdout`
- validates module output contract
- logs execution lifecycle and errors

## Current Boundaries

- linear pipeline only (one module per request)
- no DAG
- no distributed execution
- no registry/marketplace
- no billing

## Project Structure

```text
.
├── app
│   ├── context.py
│   ├── errors.py
│   ├── loader.py
│   ├── main.py
│   ├── models.py
│   └── runtime.py
├── modules
│   └── example_module
│       ├── main.py
│       └── module.yaml
├── Dockerfile
├── LICENSE
├── README.md
└── requirements.txt
```

## Requirements

- Docker (recommended) or Python 3.11+

## Run With Docker

```bash
docker build -t amaryllis:v0.3 .
docker run --rm -p 8000:8000 amaryllis:v0.3
```

API: `http://localhost:8000`

## Run Locally

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## API

### `POST /execute`

Request:

```json
{
  "module": "example_module",
  "user_id": "123",
  "session_id": "session-1",
  "input": {
    "text": "Hello from Amaryllis"
  }
}
```

Success response:

```json
{
  "request_id": "c4da3ec0-f8c2-4625-8e2f-195e7dc6f294",
  "module": "example_module",
  "output": {
    "echo": {
      "text": "Hello from Amaryllis"
    },
    "received_user_id": "123"
  },
  "memory_write": {
    "last_input": {
      "text": "Hello from Amaryllis"
    }
  },
  "execution_time_ms": 3
}
```

Error response:

```json
{
  "error": {
    "type": "ModuleExecutionError",
    "message": "Module subprocess returned non-JSON stdout.",
    "request_id": "c4da3ec0-f8c2-4625-8e2f-195e7dc6f294"
  }
}
```

## Module Contract

Module folder:

```text
modules/<module_name>/
  module.yaml
  main.py
```

`module.yaml`:

```yaml
name: example_module
version: 0.1.0
runtime_api: "1.0"
entrypoint: "main.py"
permissions:
  - network
resources:
  timeout_ms: 3000
  memory_mb: 128
```

Context passed to module (`stdin` JSON):

```json
{
  "request_id": "uuid4",
  "user_id": "123",
  "session_id": "session-1",
  "input": {},
  "memory": {},
  "metadata": {}
}
```

Module output (`stdout` JSON only):

```json
{
  "output": {},
  "memory_write": {}
}
```

Important subprocess rules:
- write only JSON to `stdout`
- write diagnostics to `stderr`
- return non-zero exit code on failure

## Session Memory (In-Memory)

If `session_id` is provided:
- runtime loads memory from in-process store
- module receives it in `context.memory`
- `memory_write` is merged and persisted for next calls

Store lifetime is process lifetime (no Redis yet).
