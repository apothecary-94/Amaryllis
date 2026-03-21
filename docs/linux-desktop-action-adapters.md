# Linux Desktop Action Adapters

## Purpose

Provide policy-gated desktop control primitives for Linux-first "Jarvis on PC" workflows:

- notifications
- clipboard read/write
- app launch
- window list

## Tool Contract

Tool name: `desktop_action`

Supported actions:

- `notify`
- `clipboard_read`
- `clipboard_write`
- `app_launch`
- `window_list`

Request fields:

- `action` (required)
- `title` (optional, for `notify`)
- `message` (optional, for `notify`)
- `text` (optional; required for `clipboard_write`)
- `target` (optional; required for `app_launch`)
- `timeout_sec` (optional)
- `metadata` (optional)

## Runtime Behavior

- Linux hosts use `LinuxDesktopActionAdapter`.
- Non-Linux hosts use `StubDesktopActionAdapter` for staging/testing parity.

Command usage on Linux:

- notifications: `notify-send`
- clipboard write: `wl-copy` -> `xclip` -> `xsel`
- clipboard read: `wl-paste` -> `xclip` -> `xsel`
- app launch: `gtk-launch` (desktop id) or `xdg-open` fallback
- window list: `wmctrl -l`

When required system commands are missing, tool returns `status=unavailable` with explicit reason.

## Policy and Trust Boundary

- Registered as `risk_level=medium`, `approval_mode=conditional`.
- Conditional approval applies to mutating actions:
  - `notify`
  - `clipboard_write`
  - `app_launch`
- Existing autonomy and isolation guardrails remain active.

## Invocation

Use existing invoke surface:

- `POST /mcp/tools/desktop_action/invoke`

Example payload:

```json
{
  "user_id": "user-001",
  "session_id": "session-001",
  "arguments": {
    "action": "clipboard_read"
  }
}
```
