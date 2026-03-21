# Mission Planner API

## Purpose

`POST /automations/mission/plan` builds a risk-aware automation mission plan before creating a scheduler entry.

It combines:

- dry-run simulation (`agent_manager.simulate_run`),
- cadence normalization (`workday/daily/hourly/weekly/watch_fs`),
- recommendation gate for immediate start based on mission risk.

`GET /automations/mission/templates` returns preset mission templates (`code_health`, `security_audit`, `release_guard`, `runtime_watchdog`) for low-friction planning.

## Endpoint

```bash
curl -X POST http://localhost:8000/automations/mission/plan \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "<agent_id>",
    "user_id": "user-001",
    "message": "Run autonomous daily code health mission",
    "cadence_profile": "workday",
    "timezone": "UTC",
    "start_immediately": true
  }'
```

## Request Fields

- `agent_id` (required): target agent.
- `user_id` (required): owner user id.
- `message` (optional if `template_id` is provided): mission instruction.
- `session_id` (optional): session context.
- `timezone` (default `UTC`): planner timezone.
- `cadence_profile` (optional): one of `hourly`, `daily`, `workday`, `weekly`, `watch_fs`.
- `start_immediately` (optional): requested immediate scheduling.
- `template_id` (optional): one of `code_health`, `security_audit`, `release_guard`, `runtime_watchdog`.
- `schedule_type`, `schedule`, `interval_sec` (optional): explicit schedule override.
- `max_attempts`, `budget` (optional): passed to dry-run simulation only.

## Response Shape

- `mission_plan`
  - normalized schedule (`schedule_type`, `schedule`, `interval_sec`, `next_run_at`),
  - `risk.overall` and `risk.requires_review`,
  - recommendation (`requested_start_immediately`, `effective_start_immediately`, checklist),
  - `apply_payload` compatible with `POST /automations/create`.
- `simulation`: full dry-run simulation payload.
- `template`: selected template metadata (`id`, `name`, `description`, `risk_tags`) if template was used.
- `apply_hint`: `{ endpoint: "/automations/create", payload: ... }`.

## Behavior

- High/critical/unknown mission risk forces `effective_start_immediately=false`.
- For low/medium risk, `effective_start_immediately` follows user request.
- `watch_fs` cadence requires explicit `schedule` payload with `path` and polling settings.
- Template defaults are used when fields are omitted; explicit request fields always override template values.

## Template Catalog

```bash
curl http://localhost:8000/automations/mission/templates
```

Each item includes:

- `id`
- `name`
- `description`
- `default_message`
- `cadence_profile`
- `start_immediately`
- `max_attempts`
- `budget`
- `risk_tags`

## Related Tests

- `tests/test_mission_planner.py`
- `tests/test_automation_mission_plan_api.py`
