# Generation Loop Contract

## Purpose
Define a portable, testable contract for local generation loop behavior across CPU/GPU/NPU backends.

## Endpoint
- `GET /models/generation-loop/contract`
- `GET /v1/models/generation-loop/contract`

## Response Shape (v1)
- `contract_version`: `generation_loop_contract_v1`
- `generated_at`: UTC timestamp
- `active`: active provider/model
- `contract`: normalized loop semantics
- `modes`: supported routing modes
- `providers`: provider capability + conformance matrix
- `summary`: pass/warn counters

## Core Semantics
- stages: `prefill -> decode -> finalize`
- cache: KV cache is required and pressure signaling is standardized through telemetry
- fallback: deterministic ordered resolution for route selection and fallback chain
- streaming: SSE chunked stream is the portability baseline
- tool calling: grammar path is capability-gated and constrained by policy/sandbox

## Conformance Matrix
Each provider includes:
- capability declaration (`supports_stream`, `supports_tools`, `supports_load`, etc.)
- conformance checks
- status (`pass` or `warn`)
- issues list for non-conforming capabilities

This endpoint is the source of truth for Phase 4 portability checks (`P4-E01`).

## Conformance Gate
- Script: `/Users/bogdan/Amaryllis/scripts/release/generation_loop_conformance_gate.py`
- Example:
  - `python scripts/release/generation_loop_conformance_gate.py --min-providers 1 --max-warning-providers 2`
