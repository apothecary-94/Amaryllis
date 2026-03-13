# Amaryllis Roadmap (to Osaurus-level)

This roadmap tracks execution quality, not feature count.
Percentages are based on production-relevant completeness: API surface, correctness, observability, and UX integration.

## Progress Snapshot (2026-03-13)

| Block | Status | Completion |
|---|---|---|
| Foundation Hardening | In progress | 82% |
| Provider-Agnostic Core | In progress | 76% |
| Memory 2.0 | In progress (advanced) | 88% |
| Agents + Work Mode | In progress | 68% |
| Tools + MCP Layer | In progress | 64% |
| Automation Layer | In progress | 58% |
| Desktop UX Parity | In progress | 62% |
| Security / Identity / Relay | Early stage | 24% |

## Completed Milestones

### Foundation Hardening
- Centralized API error envelope with request tracing.
- Provider health checks and diagnostics endpoint.
- SQLite migration framework and local structured telemetry.

### Provider-Agnostic Core
- Unified provider interfaces and adapters (MLX/Ollama/OpenAI/Anthropic/OpenRouter).
- Routing policies and failover traces.
- Session route pinning and provider diagnostics.

### Memory 2.0 (current major milestone)
- Four memory layers: working, episodic, semantic, profile.
- Extraction + conflict audit pipeline.
- Retrieval scoring with multi-factor ranking.
- Stronger consolidation:
  - same-value redundancy collapse
  - cross-value winner selection
- Profile confidence decay:
  - age/source-aware effective confidence
  - stale-preference overwrite protection
- Quality eval suites:
  - `core`: profile decay overwrite, consolidation strength, retrieval ranking, extraction coverage
  - `extended`: adds conflict-audit coverage
- Debug memory APIs for context/retrieval/extractions/conflicts/consolidation/decay/eval.

## Current Priority Queue

### Priority 1: Memory 2.0 Completion (quality gate)
Goal: make memory behavior measurable and stable under long sessions.
- Add CI gate for memory eval suites (`core` on each PR, `extended` nightly).
- Expand eval corpus with multilingual and long-horizon user profiles.
- Add memory drift metrics and threshold alarms in telemetry summaries.

### Priority 2: Agents Work Mode Reliability
Goal: high-success resumable multi-step execution.
- Add per-stage SLO metrics (success rate, retries, repair-loop hit rate).
- Add failure-class-aware retry policy and deterministic stop reasons.
- Add run-level budget controls (tokens/time/tool budget) with policy fail-fast.

### Priority 3: Tool Safety + MCP Reliability
Goal: predictable tool runtime for daily use.
- Add signed-manifest enforcement modes (`off`, `warn`, `strict`).
- Add tool sandbox presets with explicit risk tiers.
- Add MCP endpoint health scoring and automatic temporary quarantine.

### Priority 4: Desktop UX Daily-Driver Polish
Goal: stable operator workflow in the native app.
- Add dedicated diagnostics panel (provider + memory + run pipeline in one view).
- Add chat/run export bundle for reproducible bug reports.
- Improve long-run monitoring UX for automations and agent runs.

## Definition of Done (Osaurus-level baseline)

Amaryllis reaches this stage when:
- Local/cloud provider switching is transparent and observable.
- Memory can be evaluated objectively with stable scores across releases.
- Agents complete multi-step tasks with resumability and clear failure semantics.
- Tool execution is permissioned, policy-driven, and auditable end-to-end.
- Desktop app is robust for daily use without terminal fallback.
