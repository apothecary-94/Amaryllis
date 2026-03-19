# Autonomy Levels (L0-L5)

## Runtime Contract

- Config key: `autonomy_level`
- Environment variable: `AMARYLLIS_AUTONOMY_LEVEL`
- Allowed values: `l0`, `l1`, `l2`, `l3`, `l4`, `l5`
- Default: `l3`

This level is enforced at the tool execution boundary (`ToolExecutor.execute`) before action dispatch.

## Behavior Matrix

| Level | Low Risk | Medium Risk | High Risk | Critical Risk |
|---|---|---|---|---|
| `l0` | blocked | blocked | blocked | blocked |
| `l1` | approval required | blocked | blocked | blocked |
| `l2` | allowed | approval required | blocked | blocked |
| `l3` | allowed | allowed | approval required | blocked |
| `l4` | allowed | allowed | approval required | approval required |
| `l5` | allowed | allowed | allowed (policy-driven) | allowed (policy-driven) |

Notes:
- Isolation policy, signing policy, sandbox, and tool approval controls remain active at every level.
- `l5` does not bypass security controls; it only removes extra autonomy-level restrictions.

## Debug Visibility

Tool guardrails debug endpoint includes current autonomy policy snapshot:

```text
GET /v1/debug/tools/guardrails
```

Response includes:
- `autonomy_policy.level`
- `autonomy_policy.rules`
