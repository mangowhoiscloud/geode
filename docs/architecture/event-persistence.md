# Event persistence contract

This document is the storage and lifecycle contract for `HookSystem` events.
It separates the runtime event bus from its durable sinks and makes the
SQLite/JSONL boundary explicit.

## Invariants

1. A hook dispatch invokes each registered handler at most once and produces
   at most one durable operational event row.
2. Operational event persistence never stores the raw hook payload. It stores
   the typed, redacted, bounded activity projection only.
3. SQLite is the source of truth for queryable runtime events. JSONL is kept
   only where line-oriented portability, `tail -F`, or a git-reviewable domain
   ledger is the primary requirement.
4. Every runtime-owned sink and handler resource has deterministic teardown.
5. Compatibility events may still reach third-party handlers, but they are not
   duplicated into durable storage when a canonical event already represents
   the same transition.
6. Persistence failure is visible and non-fatal to the agentic loop.

## Destination matrix

| Data | Destination | Retention | Reason |
|---|---|---|---|
| Hook lifecycle/telemetry events | `sessions.db:hook_events` | bounded by age and row count | query/filter/aggregate across sessions |
| Session, message, runtime, cognitive state | existing `sessions.db` tables | subsystem policy | mutable/queryable application state |
| Active run activity timeline | per-run `transcript.jsonl` | run artifact lifetime | ordered human inspection and `tail -F` |
| Agent/sub-agent dialogue | per-session `dialogue.jsonl` | session artifact lifetime | explicit local conversation artifact |
| Self-improving mutation/results/baseline ledgers | tracked or run-scoped JSONL | domain policy | append-only experiment provenance and git review |
| Project journal | project-scoped JSONL materialized view | bounded by project policy | portable project history |
| Scheduler job log | bounded per-job JSONL | size/line cap | job-owned tail/export; no cross-job query requirement |
| Legacy `~/.geode/runs/*.jsonl` | operator archive | existing layout TTL archive policy | writer and specialized reader retired; no SQL import or deletion |

Approval summaries are represented by canonical `APPROVAL_TRANSITION` rows in
`hook_events`; the legacy `approval_history.jsonl` writer/reader is retired.
Existing files remain operator archives. Cognitive snapshots remain in
`cognitive_events`; the generic hook row contains only the bounded activity
projection and therefore does not duplicate the snapshot body.

## SQL event envelope

`hook_events` uses schema version 1 and stores:

- occurrence timestamp, runtime `session_key`, and `run_id`;
- event name, dispatch mode, status, retention class, and handler counts;
- activity classification (`actor`, `action`, `entity`, task, level);
- a canonical JSON object containing typed activity details;
- a SHA-256 hash of that persisted JSON object.

The table does not store handler return values, full tool inputs/results,
prompts, raw user input, cognitive snapshots, approval raw input, screenshots,
or base64 data.

## Bounds and redaction

Before either SQLite or the activity transcript receives a hook event, the
activity registry projects the payload into its declared details model. A
second generic bound applies defense in depth:

- secret-pattern redaction on every persisted string;
- bounded string length, collection cardinality, nesting depth, and total JSON
  bytes;
- explicit truncation markers instead of silent clipping.

High-volume events have a shorter age window than standard events. Audit-class
events have a longer window. A global row cap remains the final disk bound.
Pruning runs incrementally from the writer and is also exposed as an explicit
maintenance operation.

## Dispatch and teardown

`HookSystem` owns handler/sink registrations, but it does not import an
observability backend. Bootstrap registers one persistence sink. The sink runs
once after dispatch, so it can record handler failure or interceptor blocking
without duplicating logic across sync/async trigger variants.

`HookSystem.close()` is idempotent. It clears subscriptions, runs registered
cleanup callbacks, and closes sinks. `HookEventStore` itself retains no SQLite
descriptor: schema setup and every append/read/prune operation close their
connection before returning. Runtime shutdown still closes the store to reject
future operations after background producers have stopped. Owner-aware cleanup
callbacks use a weak HookSystem reference so teardown registration does not
create a self-cycle.

Sync handlers cannot be forcibly stopped by Python threads. Therefore a
non-zero per-handler timeout is supported only for awaitable handlers. A sync
handler under a timeout contract is skipped with an explicit failed
`HookResult`; GEODE does not create abandoned worker threads.

## Migration and rollback

- New runtime events go only to SQLite plus an active per-run transcript.
- Existing run-log JSONL remains ordinary line-delimited JSON. It is not
  imported into SQL or deleted; the existing layout migrator may relocate old
  files into its TTL archive. The disconnected specialized `RunLog` API was
  removed.
- SQLite schema creation is additive and idempotent through the same
  `SessionManager` bootstrap used by the other `sessions.db` tables.
- Rolling back code leaves an extra table that older releases ignore. No
  existing table or JSONL schema is rewritten.
- A future explicit data migration may import recognized legacy hook rows and
  archive their source files, but it must remain lossless and idempotent.

## Non-goals

This refactor does not move git-tracked autoresearch ledgers, dialogue bodies,
or scheduler job history into SQLite. Those formats have different portability
and ownership requirements and need independent reader/writer migrations.
