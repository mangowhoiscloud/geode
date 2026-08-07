# Event persistence contract

This is the current storage contract for session history, runtime telemetry,
portable run projections, evaluation trajectories, and their public releases.
The planes share correlation keys, but they do not share ownership.

## Invariants

1. `sessions.db:messages` owns resumable model context.
2. `sessions.db:session_events` owns append-only agent execution history.
3. `sessions.db:hook_events` owns bounded lifecycle, hook, middleware, and
   policy telemetry.
4. `sessions.db:collaboration_runs/collaboration_mailbox` owns mutable child
   control and delivery state. It is not a transcript or replay source.
5. `events.jsonl` is a bounded, portable projection. It is never the only copy
   of resumable dialogue.
6. `geode.trajectory@1` is an immutable derived evaluation artifact, not a hot
   runtime store.
7. `geode.trajectory-release@1` binds a reviewed public allowlist to immutable
   file digests; it never contains the runtime database or projection store.
8. `EvidenceLedger` owns claims and verifier judgments. A verdict is linked to
   execution by session/turn/call keys; it is not inserted into dialogue.
9. Persistence failure is visible and non-fatal to the agentic loop. A failed
   projection cannot roll back a canonical SQLite insert.

## Storage planes

| Plane | Destination | Mutability / retention | Purpose |
|---|---|---|---|
| Resume checkpoint | `sessions.db:sessions/messages` | mutable, session policy | reconstruct the next model request |
| Collaboration control | `sessions.db:collaboration_runs/collaboration_mailbox` | mutable latest-state rows plus bounded persist-before-ack delivery | explicit spawn/list/wait/interrupt/message/follow-up without duplicating child history |
| Session record | `sessions.db:session_events` | append-only; terminal sessions eligible after 180 days | reconstruct user, assistant, tool, sub-agent, usage, and terminal ordering |
| Runtime activity | `sessions.db:hook_events` | append-only; 7/30/180-day retention buckets plus row cap | query hooks, middleware, lifecycle, policy, and failures |
| Run projection | run/sub-agent `events.jsonl` | bounded to 16 MiB with an explicit `projection.truncated` row | `tail`, copy, artifact review, and offline exchange |
| Evaluation trajectory | immutable `trajectory.json` | artifact policy | replay, compare, verify, and score behavior |
| Public evaluation release | `geode-eval-artifacts/trajectories/<release-id>/` | immutable and append-only | privacy-reviewed trajectory allowlist plus digest manifest |
| LLM usage series | `~/.geode/usage/YYYY-MM.jsonl` | monthly ledger policy | per-call token and cost accounting |
| Judgment evidence | `~/.geode/evidence/<session>.jsonl` | append-only v2 rows | session/turn/call-correlated claims, citations, approvals, and verifier judgments |
| Domain ledgers | project/run JSONL | owning domain policy | autoresearch decisions, scheduler tails, and git-reviewable evidence |

Legacy `transcript.jsonl` and `dialogue.jsonl` are compatibility inputs only.
New readers prefer `events.jsonl`; recognized old rows can be imported with
`geode session migrate-records`. Import records the source SHA-256, is
idempotent, and never edits or deletes the source.

## Correlation and schemas

Four packaged Draft 2020-12 schemas define portable records and releases:

- `geode.session-event@1`
- `geode.run-event@1`
- `geode.trajectory@1`
- `geode.trajectory-release@1`

Canonical session rows carry stable `event_id`, database order, timestamp,
`session_id`, `session_generation`, `turn_id`, optional `call_id`, a closed
event kind, bounded payload, and payload hash. Tool call/result pairs reuse the
same `call_id`. A corrupt payload is returned as an explicit marker instead of
hiding the rest of the session.

Every trajectory recomputes data-quality facts rather than trusting producer
claims: event-ID uniqueness, contiguous ordinals, session/turn/call correlation
coverage, tool call/result pairing, orphan counts, and truncated/corrupt/omitted
payload counts. These live under `integrity.quality`. Missing call/turn
correlation or orphaned tools force `scope_complete=false`; lossy payload
markers force `replay_complete=false`. `complete` remains the conservative
replay-completeness compatibility alias, and both failure classes carry
explicit reasons.

The closed session history vocabulary is:

```text
session.started      session.ended
turn.completed
verification.decided verification.continued
verification.evidence verification.pending
message.user         message.assistant
tool.called          tool.completed
subagent.started     subagent.stopped
artifact.saved       usage.recorded
error.recorded       gui.step
preflight.recorded   handoff.triggered
legacy.imported
```

`legacy.imported` preserves an unrecognized old row without claiming a new
runtime meaning.

## Telemetry and lifecycle boundary

Lifecycle is a commit boundary; telemetry is an observation of that boundary.

- public `SessionStart` fires only after the initial or resumed checkpoint is
  durable;
- public `SessionEnd` and `session.ended` occur only at a true completed/error
  terminal state;
- a PostVerify candidate or paused turn is a checkpoint, not session
  termination;
- `PostCompact` fires only after compacted state persistence succeeds;
- public `SubagentStart` fires after the durable run becomes running, and
  `SubagentStop` fires after its terminal state and completion mail are committed;
- `hook_events` may describe extension invocation, blocking, handler error, or
  latency, while `session_events` records only the durable behavioral fact.

The runtime bus is storage-agnostic:

```text
RuntimeEventBus
  └── HookPersistenceSink
        ├── sessions.db:hook_events      canonical operational telemetry
        └── active events.jsonl          conditional portable projection

AgenticLoop / ToolExecutor
  └── SessionTimeline
        ├── sessions.db:session_events   canonical execution history
        └── run/sub-agent events.jsonl   conditional portable projection

SubAgentManager / AgenticLoop round boundary
  └── CollaborationStore
        ├── sessions.db:collaboration_runs      latest mutable control state
        └── sessions.db:collaboration_mailbox   bounded delivery, consumed_at
```

A hook dispatch produces at most one durable operational row. Compatibility
signals may still reach legacy subscribers, but the sink suppresses a duplicate
when a canonical event already owns the same transition.

## Bounds, privacy, and failure semantics

Both SQLite activity payloads and JSONL projections apply secret-pattern
redaction, string/collection/depth limits, and a total JSON-byte bound. Runtime
activity excludes raw prompts, complete tool bodies/results, screenshots,
base64 data, cognitive snapshots, and authentication material.

Collaboration mailbox payloads reuse the session payload bounds and secret
redaction. Run rows retain only bounded terminal summaries and errors; child
prompts, tool calls, hidden reasoning, and complete results remain in the child
checkpoint and append-only session record. Mailbox input is addressed to the
stable child id rather than a volatile generation. The loop peeks rows, saves a
stable `mailbox_id` marker in the checkpoint, and acknowledges only after that
save; restored markers suppress duplicates after a save/ack crash window. A
different process compares the owner's PID and process birth time before
recovering an orphaned active row; inaccessible process metadata is treated as
unknown/live, and the runtime never adopts or automatically restarts in-flight
work.

`SessionEventStore` and `HookEventStore` use short SQLite connections, WAL,
`busy_timeout`, additive schema creation, and explicit transactions.
Cross-process `RunTimeline` writers coordinate ordinal assignment and
compaction with a sidecar lock. A truncated projection begins with a valid
`projection.truncated` record rather than a broken partial object.

Canonical write and projection health are reported separately:

- canonical session write failure increments `record_failures`;
- JSONL failure sets `projection_failed` / `write_failed`;
- telemetry sink failure warns once per event class;
- none of these failures fabricates a successful row.

## Retention

- `hook_events`: high-volume 7 days, standard 30 days, audit 180 days, plus a
  database row cap.
- `session_events`: 180 days only after an explicit terminal
  `session.ended`. A stale active session is never inferred terminal and never
  pruned by this policy.
- `events.jsonl`: 16 MiB projection cap with explicit truncation metadata.
- collaboration control: terminal rows and consumed mailbox items retain seven
  days, with caps of 200 terminal runs, 1,000 consumed items, and 1,000 unread
  items per recipient. The latest terminal projection remains queryable until
  that policy expires; it is not transcript retention.
- trajectories and evidence: artifact/repository policy; immutable once
  published.

Use `geode session prune-records --retention-days 180` for explicit session
record maintenance.

## Evaluation artifact repository

`geode-eval-artifacts` is the durable public evidence store, not the runtime
database. `stage_trajectory_release()` accepts only schema-valid
`geode.trajectory@1` objects, always requires scope-complete and
privacy-reviewed artifacts, and requires replay completeness unless the
release admission record explicitly permits content-digested replay. It scans
for credential/path/identity patterns, verifies every referenced native
artifact against supplied source bytes, writes a
`geode.trajectory-release@1` manifest, and binds every file plus a structured
privacy review (`reviewer`, timestamp, method, scope, public attestation) by
SHA-256. The content-derived release ID is append-only and every staged byte is
read back before success.

The release contains normalized trajectories and the manifest only. It does
not contain `sessions.db`, WAL files, `events.jsonl`, checkpoints, hidden
reasoning, provider diagnostics, or general session stores. A remote
artifact-repository read-back and digest comparison remains required after its
PR merges; the local manifest records that obligation explicitly.

Historical artifact-repository releases using dated identifiers such as
`geode.trajectory@2026-07-31` remain immutable. The runtime accepts them through
`normalize_trajectory_artifact()`, which maps `sequence/timestamp` to
`ordinal/occurred_at` in memory and recomputes the v1 quality summary.

### External-loop compatibility

- **SIL**: `RunTimeline/events.jsonl` owns portable run lifecycle,
  mutation/attribution files remain domain ledgers, and Inspect `.eval` remains
  the scored Petri assay container. `RunTimeline` keeps legacy `event/seq/ts`
  aliases for existing readers. A published trajectory links these sources
  through `evidence_refs` and digests instead of replacing the promotion ledger
  or repackaging judge output as agent dialogue.
  `geode session export-trajectory --sil-eval <archive.eval>` creates the
  typed, digest-checked join today. This is intentionally an explicit
  promotion step, not automatic SIL run-finalization wiring; SIL remains free
  to finish or discard a campaign before admitting an evaluation artifact.
- **Crucible**: `crucible.evidence.v3`, the native tau2 result, frozen contract,
  and executable checks remain promotion authority. The GEODE trajectory is a
  replay sidecar with the raw artifact SHA-256 and Crucible snapshot/contract
  reference. It cannot convert an invalid arm into scored evidence.
- **MCPMark / tau2**: authoritative native receipts stay byte-identical in the
  private run store. The shared benchmark bridge emits a normalized
  SQLite-backed trajectory beside them. A public receipt copy may apply a
  reviewed path/identity redaction and therefore receives its own digest; the
  manifest records both the raw source digest and public disclosure digest.
  Publication machinery stays outside Crucible's bounded candidate surface.

## Migration and rollback

| Previous surface | Current surface | Compatibility |
|---|---|---|
| `SessionTranscript` | `SessionTimeline` | writer removed after v1.0.12 grace; legacy files remain importable |
| `RunTranscript` | `RunTimeline` | alias removed after v1.0.12 grace |
| global session JSONL | `sessions.db:session_events` | explicit digest-backed import; source unchanged |
| run `transcript.jsonl` | `events.jsonl` | new-first reader fallback |
| sub-agent `dialogue.jsonl` | `events.jsonl` | new-first reader fallback |
| hand-built evaluation JSON | `geode.trajectory@1` | K3 remains an output adapter |
| dated public trajectory | `geode.trajectory@1` | read-only in-memory normalizer |
| hand-built release manifest | `geode.trajectory-release@1` | shared stage/verify publisher |
| volatile sub-agent announce | `collaboration_mailbox` | in-process queue removed; durable child completion uses SQLite only |
| `delegate_task(background=true)` | `spawn_agent` | foreground `delegate_task` remains blocking |
| `manage_subagents(action=...)` | typed collaboration tools | list/wait/interrupt/message/follow-up each has one schema and effect |

The database migration is additive. Rolling back code leaves extra tables that
older releases ignore. It does not drop or rewrite `sessions`, `messages`,
`hook_events`, or legacy JSONL.

## Query and export

```bash
geode session export-trajectory <session-id> --out trajectory.json
geode session stage-trajectory-release trajectory.json \
  --destination releases --source geode --scope reviewed-run \
  --privacy-review privacy-review.json
geode session verify-trajectory-release <release-dir> \
  --expected-manifest-sha256 <independent-sha256>
geode session migrate-records --source old/transcript.jsonl
geode session prune-records --retention-days 180
```

MCPMark, tau2-bench, and the hook behavior E2E export through the same
trajectory builder and JSON-schema validator. Benchmark-native raw artifacts
remain byte-identical authoritative inputs and are bound to normalized
trajectories by SHA-256 rather than embedded or replaced. The `v1.0.11`
benchmark publication at artifact commit `16a54f08450d` was downloaded from
GitHub after merge and passed anchored manifest verification for 12
trajectories, 368 events, and 87 exact tool call/result pairs.
