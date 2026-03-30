# Plan: Structured IPC Events — Client-Side Direct Rendering

## Frontier Research Summary

| System | Pattern | Adoption |
|--------|---------|----------|
| Claude Code | Direct terminal rendering (no IPC) | Adapt — client renders from structured events |
| Codex | Item-based streaming (typed events) | Adopt — each UI element is a discrete event |
| OpenClaw | System Events Queue (coalescing) | Adapt — event protocol over Unix socket |

## Problem

Current thin client mixes two rendering modes:
1. **Raw stream** (`{"type":"stream","data":"ANSI..."}`) — serve console output piped to client
2. **Structured events** (`tool_start/tool_end`) — client renders with spinners

Raw stream has no semantic structure — client can't distinguish token usage from headers from spinner frames. Client-side rendering (spinners, in-place updates, timing) is impossible for raw-streamed elements.

## Design

Replace raw stream for ALL agentic UI elements with typed events. Keep raw stream ONLY for Rich Panels/Tables (pipeline output).

### Event Protocol

| Event | Fields | Client Renders |
|-------|--------|---------------|
| `round_start` | `round: int` | `● AgenticLoop` header (first round only) |
| `thinking_start` | `model: str, round: int` | Spinner: `✢ Thinking... (round N)` |
| `thinking_end` | | Stop spinner |
| `tool_start` | `id, name, args_preview` | `▸ name(args) ⠋` with spinner |
| `tool_end` | `name, summary, error, duration_s` | In-place `✓ name → summary (Ns)` |
| `tokens` | `model, input, output, cost` | `✢ model · ↓in ↑out · $cost` |
| `turn_end` | `rounds, tools, elapsed_s, cost` | `──── 3 rounds · 8 tools · 4.2s ────` |
| `context_event` | `action, before, after` | `⟳ Context compacted: 45 → 12` |
| `subagent_dispatch` | `task_id, description` | `▸ delegate_task(desc)` |
| `subagent_progress` | `completed, total, name, duration_s` | `✓ name (Ns) [1/3]` |
| `subagent_complete` | `count, elapsed_s` | `✓ N sub-agents completed (Ns)` |
| `session_cost` | `calls, input, output, cost, breakdown` | Cost summary on /quit |
| `stream` | `data` | Raw ANSI passthrough (Pipeline panels) |
| `result` | `text, rounds, ...` | Final Markdown response |

### Changes

**Serve side** (`core/agent/`, `core/cli/ui/agentic_ui.py`):
- OperationLogger: all methods send events via `_ipc_writer_local` when set
- AgenticLoop: wrap spinner start/stop, LLM token recording as events
- Session cost: send `session_cost` event on disconnect

**Client side** (`core/cli/ui/event_renderer.py` — NEW):
- `EventRenderer` class: handles all event types
- Manages ToolCallTracker (existing), thinking spinner, token line, turn summary
- `_on_event(event)` dispatcher replaces current `_on_stream` + `_on_event` split

**IPC** (`core/cli/ipc_client.py`):
- `send_prompt(on_event=)` — already supports structured events

## Phases

1. Serve: emit structured events for C1-C7, D1-D3
2. Client: EventRenderer with all event handlers
3. Serve: emit events for E1-E3 (sub-agent)
4. Serve: emit session_cost on disconnect (G1)
5. Tests + E2E
