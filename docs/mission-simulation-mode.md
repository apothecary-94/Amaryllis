# Mission Simulation Mode

## Purpose

`POST /agents/{agent_id}/runs/simulate` gives a dry-run preview before autonomous execution.

The runtime does not execute tools and does not create a run in this step.

## What You Get

- strategy selected by meta-controller
- plan steps with:
  - `risk_level`
  - `risk_tags`
  - `rollback_hints`
- tool preview with:
  - known/unknown tools
  - approval requirement
  - blocked reason (if policy blocks tool)
- `risk_summary` for the full mission
- `run_preview` with normalized `max_attempts` and `budget`
- `apply_hint` payload for `POST /agents/{agent_id}/runs`
- signed `dry_run_receipt` for audit trail

## Simple User Flow

1. User writes goal: "Find notes and prepare action plan."
2. Client calls `POST /agents/{agent_id}/runs/simulate`.
3. User reviews risks, tool usage, and rollback hints.
4. If acceptable, client sends `simulation.apply_hint.payload` to `POST /agents/{agent_id}/runs`.
5. Run starts in queue and is executed by run workers.

## Example Request

```bash
curl -X POST http://localhost:8000/agents/<agent_id>/runs/simulate \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "user-001",
    "session_id": "session-001",
    "message": "Investigate latest failures and draft remediation plan",
    "max_attempts": 3,
    "budget": {
      "max_tokens": 18000,
      "max_duration_sec": 240,
      "max_tool_calls": 8,
      "max_tool_errors": 2
    }
  }'
```

## Safety and Scope

- tenant ownership checks are enforced (cross-tenant simulation is denied)
- simulation payload is deterministic for the same input/agent/tool state (`simulation_id`)
- unknown tools are flagged with `risk_level=unknown` and explicit rollback guidance
