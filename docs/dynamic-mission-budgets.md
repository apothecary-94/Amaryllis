# Dynamic Mission Budgets

## Purpose

Mission runs enforce hard runtime budgets:

- `max_tokens`
- `max_duration_sec`
- `max_tool_calls`
- `max_tool_errors`

Budget usage is validated live during checkpoints and before each attempt.

## Guardrail Escalation Policy (current)

Budget breach behavior is deterministic:

1. first budget breach for run history:
   - run ends with `status=failed`
   - `stop_reason=budget_guardrail_paused`
   - checkpoint stage: `budget_guardrail_paused`
   - operator can fix scope/budget and call resume
2. repeated budget breach for same run history:
   - run ends with `status=canceled`
   - `stop_reason=budget_guardrail_kill_switch`
   - checkpoint stage: `budget_guardrail_escalated`
   - agent-scope kill switch is triggered for sibling `queued/running` runs
   - checkpoint stage: `budget_guardrail_kill_switch_scope`

Scope of escalation kill switch:

- same `user_id`
- same `agent_id`
- current run is excluded

## API Notes

- `POST /agents/{agent_id}/runs` accepts `budget` values.
- budget breach diagnostics are visible in:
  - `GET /agents/runs/{run_id}`
  - `GET /agents/runs/{run_id}/replay`
  - `GET /agents/runs/{run_id}/diagnostics`

## Test Coverage

- `tests/test_agent_run_manager.py::test_run_budget_tool_calls_exceeded_fails_fast`
- `tests/test_agent_run_manager.py::test_repeated_budget_breach_escalates_to_agent_scope_kill_switch`
