# Automation Mission Policy Overlays

## Goal

Enable per-automation reliability envelopes so each mission can enforce its own SLO posture instead of relying only on scheduler-global thresholds.

## API Surface

- `GET /automations/mission/policies`: list available policy profiles.
- `POST /automations/mission/plan`: accepts:
  - `mission_policy_profile` (optional),
  - `mission_policy` (optional overrides).
- `POST /automations/create`: accepts `mission_policy`.
- `POST /automations/{automation_id}/update`: accepts `mission_policy`.

## Policy Schema

`mission_policy` payload:

```json
{
  "profile": "balanced",
  "slo": {
    "warning_failures": 2,
    "critical_failures": 4,
    "disable_failures": 6,
    "backoff_base_sec": 5.0,
    "backoff_max_sec": 300.0,
    "circuit_failure_threshold": 4,
    "circuit_open_sec": 120.0
  }
}
```

Normalization guarantees:

- `warning_failures >= 1`
- `critical_failures >= warning_failures`
- `disable_failures >= critical_failures + 1`
- `backoff_base_sec >= 1.0`
- `backoff_max_sec >= backoff_base_sec`
- `circuit_failure_threshold >= 1`
- `circuit_open_sec >= 1.0`

## Built-in Profiles

- `balanced`
- `strict`
- `watchdog`
- `release`

## Scheduler Enforcement

On each automation queue failure, scheduler uses effective mission policy SLO values to compute:

- escalation level (`none` / `warning` / `critical`),
- auto-disable decision,
- exponential retry backoff window,
- circuit-open window.

This is applied per automation in `AutomationScheduler._trigger` and persisted in `automations.mission_policy_json`.

## Storage

Schema migration:

- `v18 automation_mission_policy_v1`
- adds column: `automations.mission_policy_json` (`TEXT`, default `{}`)
