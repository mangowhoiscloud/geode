# GEODE Hook System

> **English** | [한국어](hook-system.md)

`core/hooks/` is GEODE's storage-agnostic runtime event bus. It exposes the
65-event `HookEvent` compatibility surface, ordered handlers,
interceptor/feedback modes, and post-dispatch sinks. Persistence policy is
documented separately in [`event-persistence.md`](event-persistence.md).

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
