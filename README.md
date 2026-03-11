# Amaryllis

Amaryllis is an open-source local AI runtime and native macOS app.

It acts as a **local AI brain node**:
- runs local models
- supports agent execution
- provides tool calling
- stores memory
- exposes OpenAI-compatible API
- ships with a native SwiftUI desktop interface

This MVP is intentionally simple and modular, so it can evolve into a richer cognitive architecture later.

## Privacy and Anonymity

- no remote telemetry; runtime writes local telemetry file only
- no personal paths or machine-specific identifiers in repository files
- local-first runtime, data stays on your machine unless tools/providers call external services

## MVP Scope

Implemented in this version:
- FastAPI backend runtime
- native macOS UI (`SwiftUI`) with dark amaryllis theme
- OpenAI-compatible endpoint: `POST /v1/chat/completions`
- model manager with MLX primary provider, Ollama fallback, and optional cloud providers (OpenAI / Anthropic / OpenRouter)
- model APIs: list/download/load/capabilities
- agent APIs: create/list/chat
- memory layer v2 foundation: working + episodic + semantic + profile memory
- SQLite persistence
- vector search via FAISS (with local fallback behavior)
- tool registry/executor with builtin tools
- plugin discovery from `plugins/`
- sequential task loop: meta-controller -> planner -> reasoning -> tools -> response
- local runtime controls from the desktop app (start/stop/check)
- streaming chat UI
- model load/download progress indicators
- persistent local chat history (multi-chat sessions) in macOS app
- centralized structured API errors (`error.type`, `error.message`, `error.request_id`)
- provider diagnostics endpoint: `GET /health/providers`
- SQLite migration framework (`schema_migrations`)
- local structured telemetry (`telemetry.jsonl`)

Out of scope for MVP:
- distributed execution
- multi-node orchestration
- full production hardening

## Target Platform

Primary target:
- macOS (Apple Silicon)
- Python 3.11+

Model storage location:
- `~/Library/Application Support/amaryllis/models/`

Data storage location:
- `~/Library/Application Support/amaryllis/data/`

Local telemetry log:
- `~/Library/Application Support/amaryllis/data/telemetry.jsonl`

## Project Structure

```text
.
├── agents
│   ├── agent.py
│   ├── agent_manager.py
│   └── agent_run_manager.py
├── api
│   ├── agent_api.py
│   ├── chat_api.py
│   ├── memory_api.py
│   └── model_api.py
├── controller
│   └── meta_controller.py
├── memory
│   ├── extraction_service.py
│   ├── episodic_memory.py
│   ├── memory_manager.py
│   ├── models.py
│   ├── semantic_memory.py
│   ├── user_memory.py
│   └── working_memory.py
├── models
│   ├── model_manager.py
│   └── providers
│       ├── mlx_provider.py
│       ├── anthropic_provider.py
│       ├── openai_provider.py
│       ├── openrouter_provider.py
│       └── ollama_provider.py
├── macos
│   └── AmaryllisApp
│       ├── Package.swift
│       ├── Sources/AmaryllisApp
│       │   ├── AmaryllisMacApp.swift
│       │   ├── Core
│       │   ├── Models
│       │   ├── Services
│       │   └── Views
│       └── scripts
│           └── build_app.sh
├── planner
│   └── planner.py
├── plugins
│   └── .gitkeep
├── runtime
│   ├── config.py
│   └── server.py
├── storage
│   ├── database.py
│   └── vector_store.py
├── tasks
│   └── task_executor.py
├── tests
│   ├── test_agent_run_manager.py
│   └── test_memory_manager.py
├── tools
│   ├── builtin_tools
│   │   ├── filesystem.py
│   │   ├── python_exec.py
│   │   └── web_search.py
│   ├── tool_executor.py
│   └── tool_registry.py
├── LICENSE
├── README.md
└── requirements.txt
```

## Install

One command (from GitHub):

```bash
curl -fsSL https://raw.githubusercontent.com/intentionally-left-blank/Amaryllis/main/scripts/install_macos.sh | bash
```

One command (inside cloned repo):

```bash
./scripts/install_macos.sh
```

Manual backend setup:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
```

## Run

```bash
uvicorn runtime.server:app --host localhost --port 8000 --reload
```

Health check:

```bash
curl http://localhost:8000/health
```

Provider health:

```bash
curl http://localhost:8000/health/providers
```

## Native macOS App (.app)

Prerequisites:
- Xcode Command Line Tools installed (`xcode-select --install`)
- Xcode license accepted (`sudo xcodebuild -license accept`)

Build:

```bash
cd macos/AmaryllisApp
./scripts/build_app.sh
```

Result:

```text
macos/AmaryllisApp/dist/Amaryllis.app
```

Run:

```bash
open macos/AmaryllisApp/dist/Amaryllis.app
```

Build `.dmg`:

```bash
./scripts/build_dmg.sh
```

Output:

```text
macos/AmaryllisApp/dist/Amaryllis.dmg
```

In app settings:
- set `API Endpoint` (default `http://localhost:8000`)
- set `Runtime Directory` to your repository root
- set optional cloud provider URLs and API keys:
  - OpenAI (`https://api.openai.com/v1`)
  - OpenRouter (`https://openrouter.ai/api/v1`)
- use `Start Runtime` to run the Python backend from UI
- API keys entered in app settings are stored in macOS Keychain
- use `Memory Debug` section to inspect context/retrieval/extractions/conflicts directly from UI

Chat tab behavior:
- create multiple chats (`New Chat`)
- switch chats from the chat selector
- full chat history is saved automatically and restored after restart

Local chat file:
- `~/Library/Application Support/amaryllis/chat_sessions.json`

## Model Management API

### List models

```bash
curl http://localhost:8000/models
```

### Provider capability matrix

```bash
curl http://localhost:8000/models/capabilities
```

### Download model (MLX)

```bash
curl -X POST http://localhost:8000/models/download \
  -H "Content-Type: application/json" \
  -d '{
    "model_id": "mlx-community/Qwen2.5-1.5B-Instruct-4bit",
    "provider": "mlx"
  }'
```

Tip: `/models` now returns `suggested` model lists for both `mlx` and `ollama`, and UI shows quick download actions for them.

### Load model

```bash
curl -X POST http://localhost:8000/models/load \
  -H "Content-Type: application/json" \
  -d '{
    "model_id": "mlx-community/Qwen2.5-1.5B-Instruct-4bit",
    "provider": "mlx"
  }'
```

### Load remote OpenAI-compatible model (optional)

```bash
curl -X POST http://localhost:8000/models/load \
  -H "Content-Type: application/json" \
  -d '{
    "model_id": "gpt-4o-mini",
    "provider": "openai"
  }'
```

### Load remote OpenRouter model (optional)

```bash
curl -X POST http://localhost:8000/models/load \
  -H "Content-Type: application/json" \
  -d '{
    "model_id": "openai/gpt-4o-mini",
    "provider": "openrouter"
  }'
```

### Load remote Anthropic model (optional)

```bash
curl -X POST http://localhost:8000/models/load \
  -H "Content-Type: application/json" \
  -d '{
    "model_id": "claude-3-5-sonnet-latest",
    "provider": "anthropic"
  }'
```

## OpenAI-Compatible Chat API

`POST /v1/chat/completions`

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "mlx-community/Qwen2.5-1.5B-Instruct-4bit",
    "messages": [
      {"role": "system", "content": "You are a concise assistant."},
      {"role": "user", "content": "Explain what Amaryllis is."}
    ],
    "stream": false
  }'
```

Streaming mode:

```bash
curl -N -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "Hello"}],
    "stream": true
  }'
```

## Agent API

### Create agent

```bash
curl -X POST http://localhost:8000/agents/create \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Research Agent",
    "system_prompt": "You are a practical research assistant.",
    "model": "mlx-community/Qwen2.5-1.5B-Instruct-4bit",
    "tools": ["web_search", "filesystem"],
    "user_id": "user-001"
  }'
```

### List agents

```bash
curl "http://localhost:8000/agents?user_id=user-001"
```

### Chat with agent

```bash
curl -X POST http://localhost:8000/agents/<agent_id>/chat \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "user-001",
    "session_id": "session-001",
    "message": "Find 3 sources about MLX and summarize them."
  }'
```

### Work Mode: create async run

```bash
curl -X POST http://localhost:8000/agents/<agent_id>/runs \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "user-001",
    "session_id": "session-001",
    "message": "Find 3 sources about MLX and summarize them.",
    "max_attempts": 2
  }'
```

### Work Mode: list runs for agent

```bash
curl "http://localhost:8000/agents/<agent_id>/runs?user_id=user-001&limit=20"
```

### Work Mode: get run by id

```bash
curl "http://localhost:8000/agents/runs/<run_id>"
```

### Work Mode: cancel run

```bash
curl -X POST "http://localhost:8000/agents/runs/<run_id>/cancel"
```

### Work Mode: resume failed/canceled run

```bash
curl -X POST "http://localhost:8000/agents/runs/<run_id>/resume"
```

## Memory 2.0 Foundation (Current)

Implemented now:
- four memory layers in runtime context:
  - `working` (session-scoped short-term memory)
  - `episodic` (interaction timeline)
  - `semantic` (retrieval memory)
  - `profile` (user preferences/profile)
- typed memory context models (`memory/models.py`)
- extraction rules moved to dedicated service (`memory/extraction_service.py`)
- extraction records and conflict audit tables in SQLite
- conflict policy (`latest/high-confidence wins`) for profile and semantic facts
- semantic retrieval scoring (vector + recency + confidence + importance)
- local telemetry events for memory (`memory_extract`, `memory_conflict`, `memory_retrieval`, `memory_retrieval_debug`)
- backward-compatible memory manager API for existing agent loop

SQLite tables added in migration `v2`:
- `working_memory`
- `memory_extractions`
- `memory_conflicts`

## Agents Work Mode Foundation (Current)

Implemented now:
- async run queue for agents (`queued` -> `running` -> `succeeded|failed|canceled`)
- persistent run state in SQLite (`agent_runs`)
- run checkpoints (stage history)
- automatic retry until `max_attempts`
- manual cancel and resume APIs

Run status values:
- `queued`
- `running`
- `succeeded`
- `failed`
- `canceled`

## Memory Debug API

Get computed memory context for a user/session:

```bash
curl "http://localhost:8000/debug/memory/context?user_id=user-001&agent_id=<agent_id>&session_id=session-001&query=planning"
```

Get semantic retrieval trace with scoring components:

```bash
curl "http://localhost:8000/debug/memory/retrieval?user_id=user-001&query=my%20preferences&top_k=8"
```

Get extraction audit log:

```bash
curl "http://localhost:8000/debug/memory/extractions?user_id=user-001&limit=20"
```

Get conflict audit log:

```bash
curl "http://localhost:8000/debug/memory/conflicts?user_id=user-001&limit=20"
```

## Plugins

Plugins are auto-discovered from:
- `plugins/<plugin_name>/manifest.json`
- `plugins/<plugin_name>/tool.py`

`tool.py` must expose either:
- `register(registry, manifest)`
- or `register_tool(registry, manifest)`

## Tests

Run unit tests (memory + work mode runs):

```bash
~/Library/Application\ Support/amaryllis/runtime-src/.venv/bin/python -m unittest discover -s tests -p "test_*.py" -v
```

## Notes on MLX and Ollama

- MLX is the primary local inference provider.
- If fallback is enabled, runtime can automatically try local providers:
  - `mlx -> ollama` when MLX fails
  - `openai/anthropic/openrouter -> mlx/ollama` when cloud calls fail (for example `429` quota/rate-limit)
- You can optionally enable remote cloud providers: OpenAI, Anthropic and OpenRouter.
- Configure fallback via env:
  - `AMARYLLIS_OLLAMA_FALLBACK=true|false`
  - `AMARYLLIS_OLLAMA_URL=http://localhost:11434`
  - `AMARYLLIS_TELEMETRY_PATH=~/Library/Application Support/amaryllis/data/telemetry.jsonl`
  - `AMARYLLIS_OPENAI_BASE_URL=https://api.openai.com/v1`
  - `AMARYLLIS_OPENAI_API_KEY=<your_key>`
  - `AMARYLLIS_ANTHROPIC_BASE_URL=https://api.anthropic.com/v1`
  - `AMARYLLIS_ANTHROPIC_API_KEY=<your_key>`
  - `AMARYLLIS_OPENROUTER_BASE_URL=https://openrouter.ai/api/v1`
  - `AMARYLLIS_OPENROUTER_API_KEY=<your_key>`
  - `AMARYLLIS_RUN_WORKERS=2`
  - `AMARYLLIS_RUN_MAX_ATTEMPTS=2`

## Example Environment Variables

```bash
export AMARYLLIS_HOST=localhost
export AMARYLLIS_PORT=8000
export AMARYLLIS_DEFAULT_PROVIDER=mlx
export AMARYLLIS_DEFAULT_MODEL=mlx-community/Qwen2.5-1.5B-Instruct-4bit
export AMARYLLIS_OLLAMA_URL=http://localhost:11434
export AMARYLLIS_OLLAMA_FALLBACK=true
export AMARYLLIS_TELEMETRY_PATH=~/Library/Application\ Support/amaryllis/data/telemetry.jsonl
export AMARYLLIS_OPENAI_BASE_URL=https://api.openai.com/v1
export AMARYLLIS_OPENAI_API_KEY=replace_me
export AMARYLLIS_ANTHROPIC_BASE_URL=https://api.anthropic.com/v1
export AMARYLLIS_ANTHROPIC_API_KEY=replace_me
export AMARYLLIS_OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
export AMARYLLIS_OPENROUTER_API_KEY=replace_me
export AMARYLLIS_RUN_WORKERS=2
export AMARYLLIS_RUN_MAX_ATTEMPTS=2
```

## License

See `LICENSE`.
