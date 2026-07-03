# Multi-agent Fleet View

Status: Stage 1 (data layer + turn-time summary) and Stage 1.5 (child->parent live
activity plumbing) implemented. Stage 2 (interactive full-screen view) is deferred.

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

**What Stage 2 now has (post Stage 1.5):** per-agent `FleetAgent.current_activity` (the
running child's live tool text) and a best-effort mid-run `tokens` count, in addition to
the Stage-1 identity / status / elapsed / final-token fields. The interactive detail view
can render each running agent's current tool without any further plumbing. (`tokens` is
`0` for subscription / CLI-routed calls, which expose no usage — honest, never faked.)

### Stage 1.5 (live per-agent activity) — child->parent plumbing (DONE)

`current_activity` (a running child's current tool text) plus a best-effort mid-run
token count now cross the worker IPC boundary. The worker→parent stdout protocol was
extended from "exactly one result line" to "**zero or more activity lines, then
exactly one result line (last)**":

| Line | Shape | Meaning |
|------|-------|---------|
| activity | `{"type":"activity","task_id":…,"tool":<current tool>,"tokens":<cumulative int>,"ts":…}` | mid-run live update, streamed before the result |
| result | bare legacy `WorkerResult` dict (**no `type` key**) — or a tagged `{"type":"result",…}` | the terminal line (last) |

**Compat rule (load-bearing).** The parent classifier
(`isolated_execution._classify_worker_line`) treats a line with `type=="activity"` as
a live update and *anything else that parses to a JSON object* — a bare result dict,
`type=="result"`, etc. — as the terminal result; blank / non-JSON / non-object lines
are skipped, never fatal. A worker that emits ONLY a bare result line (every
pre-Stage-1.5 / older / in-flight worker) has no `type` field, so it still parses as
the result. A parser that *required* `type` would have broken every such worker.

**`emit_activity` gate (fail-safe).** `WorkerRequest.emit_activity` (default `False`)
controls the child's emission. Only the interactive `delegate_task` turn path
(`ToolExecutor._aexecute_delegate` → `SubAgentManager.adelegate(on_activity=…)` →
`_build_worker_request(emit_activity=True)`) opts in; seed-generation / headless
`adelegate` calls leave it `False`, so their stdout stays a pure single result line
(mirrors how Stage 1 avoided seed-gen noise). When emission is off the parent never
reads activity and `current_activity` stays `""` — nothing is faked.

**Child emit path.** With the gate on, the worker installs a process-local activity
sink (`core/agent/activity_channel.py`); the child `AgenticLoop`'s single per-tool
dispatch boundary (`ToolExecutor.aexecute`, after the denylist) calls
`emit_tool_activity(tool_name)`, which — only when a sink is installed — reads the
cumulative token count from the process token tracker (fresh per subprocess; `0` for
subscription / CLI calls, never faked) and writes one throttled activity line to
stdout. The throttle skips consecutive duplicate tool names, so a same-tool batch
emits once. In the parent process no sink is ever installed, so `emit_tool_activity`
is a cheap no-op for the top-level loop.

**Parent read path.** `IsolatedRunner._aexecute_subprocess` reads the worker stdout
line-by-line (`_pump_worker`, replacing the single `communicate()`), draining stderr
concurrently, forwarding each activity line to the `on_activity` callback and keeping
the LAST result line as the `IsolationResult`. `_aexecute_delegate`'s `_on_activity`
re-emits the sub-agent's `running` state carrying the live tool in a new additive
`activity` field on the `subagent_state` event; `EventRenderer._handle_subagent_state`
feeds it into `FleetRegistry.on_state(current_activity=…)`.

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

## Plumbing reality — what exists

Sub-agents execute as `python -m core.agent.worker` subprocesses launched by
`IsolatedRunner`. The child's `AgenticLoop` still runs with `quiet=True` ("parent
handles UI") — it emits no `tool_start`/`tool_end` IPC to the parent's renderer. The
Stage 1.5 activity side-channel is deliberately NOT `quiet=False`: it is a dedicated,
gated, single-purpose stdout stream (current tool + cumulative tokens only), so it adds
live telemetry without turning on the full child UI or corrupting the result contract.

- **Stage 1:** the `task_id` correlation id crosses the boundary in both
  `WorkerRequest` and `WorkerResult`; the parent knows each task's dispatch time, role,
  description, running/terminal status, wall-clock elapsed, and final token count
  (`WorkerResult.prompt_tokens + completion_tokens`, `0` for subscription/CLI).
- **Stage 1.5 (done):** the child's *current* tool and a best-effort mid-run cumulative
  token count now cross the boundary via the activity-line protocol above, gated behind
  `WorkerRequest.emit_activity`. `current_activity` is populated live for the interactive
  path and stays `""` (never fabricated) whenever the gate is off (seed-gen / headless)
  or a call exposes no usage.

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
  capture; `current_activity` is `""` when not plumbed, is set from the live field on a
  running transition, is not clobbered by a blank update, and is cleared on terminal.
- `tests/core/ui/test_event_schema_v2.py` — `subagent_state` handler feeds the registry;
  the `activity` field surfaces as `FleetAgent.current_activity` and (single-running) in
  the summary line; a terminal transition clears it; the fleet summary line appears while
  running and is absent when none; the existing `subagent_dispatch`/`progress`/`complete`
  handlers still render unchanged; `subagent_state` is in the IPC allowlist.
- `tests/core/agent/test_fleet_activity_protocol.py` (Stage 1.5) — the parent line
  classifier + `parse_worker_stream` (legacy bare-result-only compat, activity-then-
  result, malformed-line-skipped, no-result-line, last-result-wins); the child
  `_make_activity_sink` (well-formed activity JSON, change-only throttle, empty-tool
  ignored); the `emit_activity` gate (roundtrip, default `False`, no-op emit without a
  sink, forward-to-installed-sink).
