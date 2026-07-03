# Multi-agent Fleet View

Status: Stage 1 (data layer + turn-time summary) implemented. Stage 2 (interactive
full-screen view) and Stage 1.5 (child->parent live activity plumbing) are deferred.

## Problem

`delegate_task` fans out N sub-agents through `SubAgentManager.adelegate`. Today the
thin client only receives aggregate events: `subagent_dispatch` (dormant, no caller),
`subagent_progress` (completed/total + latest name/duration, **no task_id**), and
`subagent_complete` (count + elapsed). None of these carry per-agent identity, so the
client cannot answer "which sub-agents are running right now, for how long, and how
much have they each spent". A fleet view needs per-agent live state keyed by a stable
correlation id.

## Two-stage design

### Stage 1 (this change) — data layer + one-line summary

- **`subagent_state` IPC event** (additive; the existing three events are unchanged).
  Per-agent state transitions with a stable `task_id` correlation id.
- **`FleetRegistry`** (`core/ui/fleet.py`) — client-side, in-memory, keyed by
  `task_id`. Pure data, no rendering.
- **Turn-time fleet summary** — one compact line in the existing raw-ANSI activity
  live region: `◆ Fleet · 2 running · repo_researcher, patcher`. Rose GEODE mark
  for running, dim body, no emoji, truncated to terminal width. Shown only while
  >= 1 sub-agent is running; absent otherwise. Reuses the existing bottom-anchored
  activity region (`_render_activity_region` / `_render_activity_lines`) — no Rich
  Live, no full-screen app.

### Stage 2 (later) — interactive full-screen view

An interactive picker opened via a Ctrl-key / `/fleet`, listing every agent with
up/down selection and Enter to drill into one agent's detail (transcript tail,
tokens, elapsed). Built on `prompt_toolkit` (the same dependency Hermes uses for its
interactive surfaces) as a full-screen `Application` that reads `FleetRegistry.snapshot()`.
This is a separate stage: it is a new input-handling + layout surface, not a change to
the turn-time transcript, and it must not regress the raw-ANSI live region Stage 1 uses.

### Stage 1.5 (prerequisite for live per-agent activity) — child->parent plumbing

`current_activity` (a running child's current tool text) is **not available today**
and is deliberately left as `""` rather than faked. See "Plumbing reality" below.

## `subagent_state` event schema

Emitted by `emit_subagent_state(task_id, role, status, description, tokens, elapsed_s)`
in `core/ui/agentic_ui/render.py` (same writer pattern as the other emit/render helpers:
`writer.send_event(...)` when an IPC writer is bound, else a quiet console fallback for
terminal transitions only). Wired from the `delegate_task` path in
`core/agent/tool_executor/executor.py` (`_aexecute_delegate`) — the same place the
existing `render_subagent_progress` / `render_subagent_complete` UI emits already fire.

| Field | Type | Dispatch (`running`) | Completion (`done`/`error`/`timeout`) |
|-------|------|----------------------|----------------------------------------|
| `type` | str | `"subagent_state"` | `"subagent_state"` |
| `task_id` | str | stable correlation id | same id |
| `role` | str | `SubTask.role` (`""` if none) | same |
| `status` | str | `"running"` | `"done"` \| `"error"` \| `"timeout"` |
| `description` | str | `SubTask.description` | same |
| `tokens` | int | `0` (mid-run tokens not plumbed) | `prompt + completion` from `SubResult` (`0` for subscription/CLI calls — never faked) |
| `elapsed_s` | float | `0.0` | parent-measured wall clock |

The event is registered in the thin-client structured-event allowlist
(`core/cli/ipc_client.py`) so it routes to `EventRenderer.on_event` instead of being
treated as a terminal response.

## `FleetRegistry` contract

`FleetAgent` fields: `task_id`, `role`, `description`, `status`
(`running`|`done`|`error`|`timeout`), `start_ts`, `end_ts` (`None` until terminal),
`tokens` (int, best-effort), `current_activity` (str, `""` unless Stage 1.5 plumbs it).
Derived: `elapsed_s` (frozen at `end_ts` once terminal), `is_running`.

Methods:

- `on_dispatch(task_id, *, role, description, start_ts=None)` — register `running`;
  re-dispatch keeps the original `start_ts`.
- `on_state(task_id, *, role, status, description, tokens, elapsed_s, current_activity)`
  — authoritative feed for the `subagent_state` event; auto-creates an unseen
  `task_id` so a completion that races ahead of dispatch never drops state; pins
  `end_ts` from `elapsed_s` on terminal statuses.
- `on_complete(task_id, *, status, tokens, elapsed_s)` — terminal-transition
  convenience over `on_state`.
- `snapshot()` — all agents, running first then by `start_ts`, insertion order as the
  final deterministic tiebreak.
- `running()` — snapshot filtered to running agents; `clear()` — drop all.

The registry is owned by one `EventRenderer` instance and mutated only from the
single-threaded event-dispatch path, so it needs no lock.

## Plumbing reality — what exists vs what is deferred

Sub-agents execute as `python -m core.agent.worker` subprocesses launched by
`IsolatedRunner`. The worker protocol is: one `WorkerRequest` JSON line on stdin, one
`WorkerResult` JSON line on stdout **at exit**, stderr for logs. The child's
`AgenticLoop` runs with `quiet=True` ("parent handles UI"), so the child emits **no**
per-tool `tool_start`/`tool_end`/`tokens` IPC back to the parent's renderer.

- **Available now (Stage 1):** the `task_id` correlation id crosses the boundary in
  both `WorkerRequest` and `WorkerResult`; the parent knows each task's dispatch time,
  role, description, running/terminal status, wall-clock elapsed, and final token count
  (`WorkerResult.prompt_tokens + completion_tokens`, `0` for subscription/CLI).
- **NOT available (deferred to Stage 1.5):** a child's *current* tool and mid-run token
  count. There is no mid-run per-child event stream — the parent learns a task's final
  state only when the subprocess exits. Surfacing live per-agent tool text requires a
  child->parent activity side-channel (e.g. the worker forwarding `task_id`-tagged
  tool events over a structured multi-line protocol or a dedicated pipe, or relaxing
  `quiet=True` with a task-id-tagged event forwarder). `current_activity` is therefore
  `""` in Stage 1 and must not be fabricated.

## Deferred: Rich Live migration + sticky-plan widget

The turn-time surface today is a hand-rolled raw-ANSI bottom-anchored live region
(cursor-up erase + redraw). The eventual target is a single Rich `Live` region that
owns the plan checklist, the activity block, and the fleet summary as one renderable —
mirroring the Codex TUI's `insert_before` model (a fixed bottom viewport with scrollback
inserted above it; see the shimmer note in `core/ui/spinner_glyph.py` citing
`codex-rs/tui/src/shimmer.rs`). That migration is a separate later refactor: Stage 1
deliberately extends the existing region rather than introducing Rich Live, to keep the
fleet summary shippable without touching the plan/activity erase math.

## Tests

- `tests/core/ui/test_fleet.py` — `FleetRegistry` lifecycle (dispatch -> running ->
  complete), snapshot ordering (running first), status transitions, tokens/elapsed
  capture, `current_activity` stays `""`.
- `tests/core/ui/test_event_schema_v2.py` — `subagent_state` handler feeds the registry;
  the fleet summary line appears while running and is absent when none; the existing
  `subagent_dispatch`/`progress`/`complete` handlers still render unchanged;
  `subagent_state` is in the IPC allowlist.
