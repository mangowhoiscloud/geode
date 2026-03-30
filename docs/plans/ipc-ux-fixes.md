# Plan: IPC UX Fixes — /model hot-swap + session cost + checkpoint resume

## Socratic Gate

### P0: /model hot-swap

| # | Question | Answer | Verdict |
|---|----------|--------|---------|
| Q1 | Already exists? | `update_model()` exists on AgenticLoop (L322-357). Wire-up missing. | Partial |
| Q2 | What breaks without? | User changes model, thinks it switched, but all LLM calls use old model. Silent failure. | Critical |
| Q3 | Measurable? | Test: call `_apply_model()`, assert `get_current_loop().model` changed. | Yes |
| Q4 | Simplest? | Add 4 lines in `_apply_model()` to call loop.update_model(). | Minimal |
| Q5 | Frontier pattern? | Claude Code /model switches immediately. Standard. | Yes |

### P1: /quit session cost relay

| # | Question | Answer | Verdict |
|---|----------|--------|---------|
| Q1 | Already exists? | Client handler `_handle_session_cost()` exists. Server never sends event. | Partial |
| Q2 | What breaks without? | User never sees cost summary on thin client /quit. Can't track spending. | Visible |
| Q3 | Measurable? | Test: /quit returns cost data. Verify event sent. | Yes |
| Q4 | Simplest? | Move /quit from _LOCAL_COMMANDS to server relay. Server already renders cost. | Minimal |
| Q5 | Frontier pattern? | Claude Code shows cost on exit. Standard. | Yes |

### P2: --continue/--resume

| # | Question | Answer | Verdict |
|---|----------|--------|---------|
| Q1 | Already exists? | Save works. Load works. CLI flags defined. All disconnected. | Partial |
| Q2 | What breaks without? | User loses context on disconnect. Can't resume multi-step work. | Important |
| Q3 | Measurable? | Test: save checkpoint → load → verify messages restored. | Yes |
| Q4 | Simplest? | Wire CLI flags → IPC resume message → CLIPoller checkpoint load. | Moderate |
| Q5 | Frontier pattern? | Claude Code --continue/--resume. Exact pattern. | Yes |

All 3 pass.

---

## Implementation Plan

### Fix 1: /model hot-swap (P0)

**Root Cause**: `_apply_model()` updates `settings.model` + `.env` but never calls `loop.update_model()`.

**Files Modified**:
- `core/cli/commands.py` — `_apply_model()` (L293-336)

**Change**:
After line 331 (`_upsert_env(...)`), add:
```python
from core.cli.session_state import get_current_loop
loop = get_current_loop()
if loop is not None:
    loop.update_model(selected.id)
```

**Why this is sufficient**:
- `update_model()` already handles: model sync, provider resolution, adapter refresh, ToolCallProcessor sync, UI update, hook firing, context adaptation
- `settings.model` is already updated (L330) — new sessions via reconnect will inherit
- `.env` is already updated (L331) — serve restart will inherit

### Fix 2: /quit session cost relay (P1)

**Root Cause**: `/quit` is in `_LOCAL_COMMANDS` → runs locally on thin client → `get_usage_accumulator()` returns empty client-side accumulator (real data is on serve).

**Files Modified**:
- `core/cli/__init__.py` — `_LOCAL_COMMANDS` set + `_thin_interactive_loop()` exit paths

**Change**:
1. Remove `/quit` from `_LOCAL_COMMANDS` (L830)
2. In the "bare exit/quit/q" path (L864-866): relay `/quit` to serve before breaking
3. Add `should_break` handling in the server relay section

**Flow after fix**:
```
User types /quit (or "quit")
→ Thin client relays /quit to serve
→ Server: _handle_command("/quit") → render_session_cost_summary() (real data) + "Goodbye"
→ Server: capture_output() captures ANSI cost summary
→ Thin client: receives command_result with output + should_break=true
→ Thin client: prints output, breaks loop
```

### Fix 3: --continue/--resume (P2)

**Root Cause**: CLI flags captured but unused. No resume path from thin client → serve.

**Files Modified**:
- `core/cli/__init__.py` — `main()` + `_thin_interactive_loop()` signature
- `core/cli/ipc_client.py` — `IPCClient.connect()` + new `request_resume()` method
- `core/gateway/pollers/cli_poller.py` — `_handle_client()` + `_process_message()` resume handler

**Protocol Extension**:
```json
// Client → Server (after connect, as first message)
{"type": "resume", "session_id": "s-xxxx"}        // --resume <id>
{"type": "resume", "continue": true}               // --continue (latest)

// Server → Client (response)
{"type": "resumed", "session_id": "s-xxxx", "round_idx": 5, "model": "...", "user_input": "..."}
{"type": "resume_error", "message": "Session not found"}
```

**Server-side resume logic** (CLIPoller._process_message):
1. Load checkpoint via `SessionCheckpoint.load(session_id)` or `.list_resumable()[0]`
2. Populate `conversation.messages` from checkpoint
3. Respond with resumed session info
4. Set AgenticLoop session_id to match checkpoint

**AgenticLoop change**:
- Add `session_id` parameter to `__init__()` (optional, overrides auto-generated)
- When provided, skip generating new `s-{uuid}` and use the given ID
- `create_session()` in SharedServices: pass `session_id` kwarg

---

## Test Plan

| Fix | Test | Method |
|-----|------|--------|
| P0 | `/model` updates live loop.model | Unit: mock loop, call _apply_model, assert model changed |
| P1 | `/quit` returns cost data via IPC | Unit: mock accumulator with data, verify output contains cost |
| P2 | Resume loads checkpoint messages | Unit: save checkpoint, resume, verify messages in context |
| P2 | --continue picks latest session | Unit: save 2 sessions, --continue loads most recent |
| All | Full suite regression | `pytest tests/ -m "not live"` — 3422+ pass |

## Execution Order

```
P0 (model hot-swap) → P1 (session cost) → P2 (resume) → Tests → Docs
```
