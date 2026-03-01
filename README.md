# Amaryllis v0.1 (MVP)

`Amaryllis` is a minimal runtime core for local execution of AI modules.

This version (`v0.1`) implements:
- HTTP API (`POST /execute`)
- Context creation
- Module loading from `./modules`
- Manifest validation (`module.yaml`)
- Module execution via `run(context)`
- Basic execution logging

## Requirements

- Docker (recommended) or Python 3.11+

## Project Structure

```text
.
├── app
│   ├── context.py
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

## Run With Docker

```bash
docker build -t amaryllis:v0.1 .
docker run --rm -p 8000:8000 amaryllis:v0.1
```

Service will be available at `http://localhost:8000`.

## Run Locally (without Docker)

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Example Request

```bash
curl -X POST http://localhost:8000/execute \
  -H "Content-Type: application/json" \
  -d '{
    "module": "example_module",
    "user_id": "123",
    "input": {
      "text": "Hello from Amaryllis"
    }
  }'
```

## Example Response

```json
{
  "request_id": "f2a34718-2f8e-44eb-9a7a-dfd7f2ff3184",
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
  "execution_time_ms": 1
}
```
