# GEODE Hook System

> **English** | [한국어](hook-system.ko.md)

`core/hooks/` is GEODE's storage-agnostic runtime event bus. It exposes the
56-event `HookEvent` compatibility surface, ordered handlers,
interceptor/feedback modes, and post-dispatch sinks. Persistence policy is
documented separately in [`event-persistence.md`](event-persistence.md).
The 2026-07-14 taxonomy redesign (event collapse, naming alignment, dispatch
single-path, emit contract) is recorded in
[`../plans/2026-07-14-hook-taxonomy-redesign.md`](../plans/2026-07-14-hook-taxonomy-redesign.md).

## Core contract

1. Handlers run sequentially from lower to higher priority.
2. One handler failure does not stop later handlers.
3. Observer and feedback handlers each receive a top-level payload copy.
4. Only interceptor `modify` results explicitly flow into later handlers.
5. One trigger sends exactly one completed `HookDispatch` to every sink.
6. Name collisions never overwrite silently; intentional replacement requires
   `replace=True`.
7. `HookSystem.close()` deterministically releases registrations, global
   bindings, and sinks, and is idempotent. Each SQLite operation closes its
   connection before returning.

## Naming convention and legacy aliases

- Every `HookEvent` member satisfies `NAME == VALUE.upper()`; new event names
  use the past-participle form (`*_STARTED` / `*_ENDED` / `*_COMPLETED`).
  Pinned by `tests/core/hooks/test_hook_taxonomy.py`.
- Families whose only difference was a terminal state collapsed into one
  event with a payload discriminator: `SELF_IMPROVING_AUTO_TRIGGER`
  (`stage=fired|lock_busy|interval_blocked|runner_error|parse_error|max_generation_reached`)
  and `RULE_CHANGED` (`action=created|updated|deleted`).
- `TOOL_APPROVAL_GRANTED/DENIED` were deleted (zero handlers, zero
  persistence); `APPROVAL_TRANSITION` carries the granted/denied states.
- Stored event strings written before the value alignment resolve through
  `core.hooks.system.LEGACY_EVENT_VALUES` (old value to new value, 8 entries:
  `session_start`, `session_end`, `turn_complete`, `llm_call_start`,
  `llm_call_end`, `llm_call_retry`, `tool_exec_start`, `tool_exec_end`).
  Applied by `resolve_event_value()`, filesystem hook discovery, and
  `HookEventStore.read(event_filter=...)` expansion, so legacy SQLite rows
  and `.geode/hooks/` manifests keep working. The dialogue-transcript rail
  (`SessionTranscript` `session_start`/`session_end` markers) is a separate
  vocabulary and is unaffected.

## Emit path and payload contract

`core/hooks/dispatch.py` is the single emit implementation: `fire_hook`,
`fire_hook_async`, `fire_interceptor_async`, `fire_with_result_async`. Every
emit site delegates to it (approval workflow, tool-call processor, MCP
manager, LLM router, memory tools, self-improving loop, CLI, isolated
execution, seed-generation orchestrator) instead of re-implementing the
`if hooks is None / try / except` rail. The helpers add:

- graceful degradation — a failing dispatch logs WARNING once per event
  (then DEBUG) and never breaks the surrounding call;
- payload-contract validation — `core.hooks.catalog.REQUIRED_PAYLOAD_KEYS`
  maps an event to the payload keys its registered bootstrap handlers
  demonstrably require (`SESSION_ENDED`, `SUBAGENT_STARTED`,
  `SUBAGENT_COMPLETED`, `TOOL_EXEC_ENDED`). A missing key logs a WARNING
  naming the event, keys, and emitting caller — never raises.
  `LLM_CALL_ENDED` is deliberately not in the map: the one-off LLM router
  path legitimately has no session/usage context and the handler's
  empty-payload early return is by-design filtering (see the catalog
  comment).

`PROGRAM_MD_UNREADABLE` is a plain notify event: the runner fires it for
observability and fails loud. The former `trigger_with_result` override
contract (a handler could return a replacement `program.md` body) was
removed — no handler was ever registered. `trigger_with_result(_async)`
remain on `HookSystem` for their live feedback users
(`CONTEXT_OVERFLOW_ACTION`, `TOOL_RESULT_TRANSFORM`).

## Dispatch shape

```text
event source
  -> resolve exact + prefix handlers
  -> priority sort / name dedup
  -> handler chain
  -> HookDispatch(final data, results, block state, timing)
  -> post-dispatch sinks (once each)
       -> HookPersistenceSink
            -> sessions.db:hook_events
            -> active run transcript (selected mirror)
```

`HookSystem` does not import `core.observability`. Production bootstrap opts
into `HookPersistenceSink`; unit tests and embedded users may choose another
sink or no persistence at all.

## Trigger modes

| Meaning | Sync API | Async API | Result |
|---|---|---|---|
| Observe | `trigger()` | `trigger_async()` | `list[HookResult]` |
| Feedback | `trigger_with_result()` | `trigger_with_result_async()` | handler result dicts |
| Interceptor | `trigger_interceptor()` | `trigger_interceptor_async()` | `InterceptResult` |

Interceptor protocol:

```python
{"block": True, "reason": "policy"}
{"modify": {"tool_input": {"path": "safe.txt"}}}
None
```

`TOOL_RESULT_TRANSFORM` is the single tool-result feedback stage. It accepts
`transformed_result`, the migration key `updated_result`, and
`additional_context`; canonical `TOOL_EXEC_ENDED` fires afterward.
`TOOL_EXEC_FAILED` remains a handler compatibility signal but is not persisted
beside `TOOL_EXEC_ENDED(has_error=True)`.

## Registration and teardown

```python
subscription = hooks.register(
    HookEvent.SESSION_ENDED,
    on_session_end,
    name="session_index",
    priority=60,
)
subscription.cancel()  # idempotent
```

- `register_prefix("SUBAGENT", ...)` subscribes to `SUBAGENT_*`.
- `register_prefix("*", ...)` subscribes to all events.
- A different callable with the same name in overlapping exact/prefix scopes
  raises `DuplicateHookRegistrationError`.
- Tool matcher regexes compile at registration. Invalid patterns raise
  `ValueError` instead of failing open.
- A matcher-scoped handler does not run when `tool_name` is absent.

## Timeouts

Python cannot safely terminate an arbitrary synchronous function. A sync
interceptor with `timeout_s > 0` is therefore skipped and records
`HookTimeoutUnsupportedError`; no abandoned worker thread survives the
deadline. Async handlers use `asyncio.wait_for` and classify expiration as
`HookExecutionTimeoutError`.

## Production persistence

`build_hooks()` registers one post-dispatch sink instead of a wildcard JSONL
handler.

- Queryable operational events: `sessions.db:hook_events`
- Portable active autoresearch timeline: `transcript.jsonl`
- Compatibility duplicates: delivered to handlers, omitted from SQL/transcript
- Raw user input, prompts, tool inputs/results, cognitive snapshots, and auth
  headers: never persisted
- Payloads: bounded by depth, string length, collection size, total bytes, and
  secret redaction
- Retention: high-volume 7 days, standard 30 days, audit 180 days, global cap
  100,000 rows

Recent-run context now queries SQL `SESSION_ENDED` rows rather than scanning
legacy `runs/*.jsonl` files.

## Tool lifecycle

Every accepted tool attempt completes this pair, including blocks, recovery,
and executor exceptions:

```text
TOOL_EXEC_STARTED (interceptor)
  -> blocked | execute | adaptive recovery
  -> TOOL_RESULT_TRANSFORM (feedback, transient)
  -> TOOL_EXEC_ENDED (canonical terminal)
  -> TOOL_EXEC_FAILED (error compatibility signal only)
```

Final `has_error` is computed after transformation and the clarification guard.

## Plugins

Only `.geode/hooks/<name>/hook.py` or `hook.yaml` is auto-discovered. Built-ins
under `core/hooks/plugins/` are wired explicitly once, preventing duplicate
notification registration. Dynamic loader names are restored or removed from
`sys.modules` after load to avoid module retention across reloads.

## Lifecycle

`HookSystem.close()` blocks new registration, clears handler references, runs
cleanup callbacks in reverse order, then closes sinks in reverse order.
Owner-aware cleanups hold only a weak HookSystem reference, so registering
teardown cannot create a self-cycle. `HookEventStore` retains no database/WAL/
SHM descriptor between operations; sink close marks it unavailable to future
writers. Runtime, serve, worker, and one-shot commands close the HookSystem
they own.
