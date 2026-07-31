# Session record contract — SQLite history, JSONL projection, trajectory schema

> Status note: this document is implementation detail for R6.2
> (`STORE-001`, `STORE-002`). Delivery status remains exclusively in
> [`extensibility-roadmap.md`](../architecture/extensibility-roadmap.md).

Date: 2026-07-31  
Implementation branch: `feature/codex-session-record-contract`  
Diagram: [`session-record-contract.html`](../diagrams/session-record-contract.html)

## 1. Outcome

GEODE will stop treating an unversioned `SessionTranscript` JSONL file as both
history and observability. The runtime and evaluation pipeline use six explicit
planes:

| Plane | Canonical owner | Mutability | Purpose |
|---|---|---:|---|
| session checkpoint | `sessions.db:sessions/messages` | mutable | resume the current model-visible context |
| session record | `sessions.db:session_events` | append-only | reconstruct what the agent did across turns |
| runtime activity | `sessions.db:hook_events` | bounded append | diagnose lifecycle, policy, middleware, and hooks |
| run projection | co-located `events.jsonl` | bounded/rebuildable | tail, copy, review, and publish a portable run artifact |
| evaluation trajectory | `trajectory.json` bundle | immutable derived artifact | replay, compare, verify, and score behavior |
| public evaluation release | `geode-eval-artifacts/trajectories/<release-id>/` | immutable, append-only | reviewed trajectory + content-bound release manifest |

`EvidenceLedger` remains a judgment sidecar. Its v2 rows carry session/turn/call
keys but are not interleaved with execution history because a verdict is not a
conversation event.

## 2. Grounded problem

Current `develop` has good pieces, but their ownership is ambiguous:

- `SessionCheckpoint` already reads conversation state from
  `sessions.db:messages` first and keeps `messages.json` as a recovery cache.
- `SessionTranscript` independently writes the same user/assistant/tool
  activity to global or run-scoped JSONL.
- the JSONL class calls itself append-only but tail-truncates at 5 MiB; a
  truncated file therefore cannot be the reconstruction source it claims to be;
- its `seq` is per Python object, not cross-process, and old rows have no
  `turn_id`;
- `SessionTranscript` mirrors selected rows into `RunTranscript`, mixing
  dialogue and pipeline lifecycle in a second file;
- `core/observability/trajectory.py` reads legacy transcript files and emits a
  K3-shaped adapter object, while evaluation scripts independently emit
  `geode.trajectory@2026-07-31`;
- `hook_events` is already a versioned, redacted, bounded SQLite plane, but
  transcript rows do not share its storage guarantees.

The result is duplicate bytes without a single, explicit history contract.

## 3. Frontier grounding

The comparison uses the locally updated source trees and exact heads:

| Runtime | Grounded storage shape | Applied lesson |
|---|---|---|
| Hermes `36e41c09e` | `state.db` schema v23 owns sessions and messages; optional JSON snapshots are off by default; message rows retain active/compacted state; batch/RL trajectories stay separate | SQLite owns resumable conversation truth; offline artifacts do not become a second hot-path truth |
| OpenClaw `90a22b4f5` | SQLite `transcript_events` and separate bounded `trajectory_runtime_events`; versioned `openclaw-trajectory` envelope; export produces a bundle; legacy JSONL is archive/import input | distinguish durable transcript, runtime telemetry, and exported trajectory; give every event a schema, sequence, lineage, and retention rule |
| Codex `578c1b223` | rollout JSONL remains durable history; SQLite `thread_turns/items` is an ordinal and byte-cursor projection; diagnostic rollout-trace bundles preserve raw payload references and compaction checkpoints | carry session → turn → call identity, contiguous ordinals, partial-line recovery, and explicit compaction boundaries |
| GEODE eval artifacts `9c00ecf4a3b5` | append-only public Git repository; historical dated trajectory envelopes; per-file byte/count/SHA-256 manifest; privacy/license review; remote read-back; runtime SQLite and general session dumps excluded | keep the producer schema stable, separate its release manifest, publish only allowlisted normalized views, and bind native evidence by digest |

There is no universal “SQLite always wins” frontier rule. Codex deliberately
keeps rollout JSONL canonical. Hermes and OpenClaw deliberately moved
interactive transcript truth into SQLite. GEODE is closer to Hermes in runtime
identity and already fixed project `sessions.db` as the queryable state SOT, so
this work keeps that decision and adopts Codex's correlation/replay rigor.

The artifact repository's checked-in `TRAJECTORIES.md` still describes the
historical dated envelope and `events[].sequence`. Before the first `@1`
publication merges there, its policy must add the stable
`geode.trajectory@1` + `events[].ordinal` producer contract while retaining the
dated files as immutable legacy inputs. GEODE's in-memory adapter already
implements that compatibility direction; an artifact-repository PR closes the
policy half.

## 4. Target event contract

### 4.1 `SessionEvent`

Every canonical history row uses `geode.session-event@1` and carries:

- `event_id`: stable UUID;
- `ordinal`: SQLite-assigned order within the database, queried by
  `(session_id, id)`;
- `occurred_at`;
- `session_id`, `session_generation`, `turn_id`, optional `call_id`;
- closed `kind`;
- optional `role`, `model`, `provider`, and `status`;
- redacted, bounded typed payload plus SHA-256;
- optional `parent_event_id` for explicit lineage.

Closed kinds:

```text
session.started     session.ended
turn.completed
verification.continued verification.evidence verification.pending
message.user        message.assistant
tool.called         tool.completed
subagent.started    subagent.stopped
artifact.saved      usage.recorded
error.recorded      gui.step
preflight.recorded  handoff.triggered
legacy.imported
```

Free-form pipeline markers do not enter this alphabet. They remain typed run
events or internal hook/runtime events.

### 4.2 Write semantics

- `SessionEventStore.append()` opens a short SQLite connection, enables WAL,
  applies `busy_timeout`, inserts one row transactionally, and closes it.
- payloads reuse the existing secret-redaction and structural bounds.
- history rows are append-only. Cleanup may prune only terminal sessions older
  than the declared retention window, never rewrite a surviving session.
- corrupt payload JSON reads as an explicit `_corrupt_payload` marker; one bad
  row does not hide the rest of the session.
- a failed record write is observable and does not corrupt the resume
  checkpoint. The final result reports record health in the session-end row.

### 4.3 JSONL projection

New run-scoped files are named `events.jsonl`, not `transcript.jsonl` or
`dialogue.jsonl`. Each line is `geode.run-event@1` and includes the same
correlation keys.

Rules:

- no global `~/.geode/transcripts/<cwd-slug>/` writes for new sessions;
- projection is enabled only for a bound run directory or an explicit path;
- writes are newline-delimited, bounded, and tolerate a partial final line;
- projection failure cannot roll back the canonical SQLite insert;
- an exporter can rebuild session dialogue from `session_events`;
- readers prefer `events.jsonl`, then accept legacy `transcript.jsonl` and
  `dialogue.jsonl` during the compatibility window;
- legacy files are never rewritten or silently deleted.

### 4.4 Trajectory

`geode.trajectory@1` is the public evaluation schema. It contains:

- source and coverage metadata;
- ordered session/turn/call events;
- dialogue/tool projections;
- runtime-event references;
- evidence/verifier references;
- redaction and incompleteness declarations;
- artifact digests.

K3 formatting becomes an adapter over this object, not a competing canonical
schema. MCPMark, tau2, hook E2E, and future replay tooling call the same
builder/validator.

The builder recomputes `integrity.quality` from event bytes rather than
accepting a producer assertion:

- unique event IDs and contiguous ordinals;
- session/turn/call correlation coverage;
- tool call/result counts, exact pairs, orphans, and missing call IDs;
- payloads marked truncated, corrupt, or omitted.

Any missing required turn/call correlation or orphan forces
`integrity.scope_complete=false`. Any lossy payload marker forces
`integrity.replay_complete=false`; `complete` remains its conservative
compatibility alias. Publication verifies those values again, checks
`record_count`, rejects duplicate digest paths, and rejects duplicate
trajectory IDs inside one release.

### 4.5 Public artifact release and outer-loop joins

`geode.trajectory-release@1` is a release manifest, not another event
envelope. `stage_trajectory_release()`:

1. validates and independently recomputes every `geode.trajectory@1`;
2. always requires `privacy.review_state=reviewed` and scope-complete
   trajectories; replay-complete is the default and a content-digested
   release must declare the weaker admission policy explicitly;
3. scans the serialized public surface for local homes, emails, bearer
   credentials, GitHub tokens, and OpenAI keys;
4. records every file's byte count, SHA-256, record count, trajectory ID, and
   completeness;
5. records aggregate event/evidence/runtime-reference counts and binds a
   structured reviewer/timestamp/method/scope privacy attestation;
6. derives an immutable release path from source, scope, UTC publication time,
   and manifest digest;
7. refuses overwrite and reads every staged byte back before success.

The actual public destination is the Git repository
`mangowhoiscloud/geode-eval-artifacts`, not a JFrog service. A fresh artifact
repository worktree/PR copies the staged directory; after merge, remote
read-back verifies the same digests and the GEODE ledger pins the artifact
commit and blob paths.

SIL and Crucible keep their own promotion authority:

- SIL keeps run lifecycle in `events.jsonl`, mutation/attribution in its domain
  ledgers, and scored Petri assays in Inspect `.eval`. A published trajectory
  links those artifacts through `evidence_refs`; it does not flatten judge
  output into dialogue or replace the mutation/promotion ledger. The current
  bridge is an explicit `export-trajectory --sil-eval` promotion step rather
  than an automatic SIL run-finalization hook.
- `crucible.evidence.v3`, the frozen experiment contract, native tau2 receipt,
  and executable verifier remain Crucible's SOT. The GEODE trajectory is a
  replay sidecar and cannot promote an invalid arm.
- MCPMark and tau2 native receipts remain byte-identical and are joined through
  `artifact_digests`; publication code stays outside Crucible's candidate
  mutation boundary.

## 5. Naming and migration map

| Old | New | Compatibility |
|---|---|---|
| `SessionTranscript` | `SessionTimeline` | deprecated import delegates for one release |
| `RunTranscript` | `RunTimeline` | deprecated alias; one implementation |
| `record_*` transcript methods | typed `SessionTimeline.record_*` | method signatures retained where practical |
| global session `*.jsonl` | `sessions.db:session_events` | read-only legacy discovery |
| run `transcript.jsonl` | run `events.jsonl` | readers prefer new, fall back to old |
| sub-agent `dialogue.jsonl` | sub-agent `events.jsonl` | bundle/hub readers accept both |
| `k3-shaped/1` root | `geode.trajectory@1` | `to_k3()` adapter retained |
| hand-built E2E trajectory dict | shared builder + validator | scripts supply events, not schema boilerplate |
| dated `geode.trajectory@YYYY-MM-DD` | stable `geode.trajectory@1` | read-only in-memory normalization; published source unchanged |
| hand-built trajectory manifest | `geode.trajectory-release@1` | shared stage/read-back publisher |
| embedded SIL/Crucible verdict | typed `evidence_refs` + artifact digest | outer-loop authority remains external |

Deprecation warnings are emitted at construction boundaries, not per event.
Removal is not part of R6.2; it requires a later compatibility-window GAP.

## 6. Implementation sequence

1. Add `session_events` schema, typed model, writer/reader, retention, and
   corruption behavior.
2. Add `SessionTimeline`; wire AgenticLoop session/message/tool/usage/error
   recording with session-generation, turn, and call correlation.
3. Add schema-backed `RunTimeline`, new `events.jsonl` paths, legacy aliases,
   and fallback readers.
4. Move trajectory generation to `geode.trajectory@1`; keep Codex import and K3
   export adapters.
5. Update seed-generation bundle, hub, cost aggregation, hook behavior E2E,
   MCPMark/tau2 artifact code, and public docs.
6. Migrate existing legacy JSONL into SQLite additively on explicit command;
   record source digest and never import the same file twice.
7. Stage reviewed trajectories through the release manifest, copy the
   append-only directory through an artifact-repository PR, and verify remote
   bytes before pinning the artifact commit.
   The same artifact-repository PR updates `TRAJECTORIES.md` for `@1`/ordinal
   before accepting the first stable-schema release.
8. Run corruption, concurrency, redaction, retention, migration, replay, hook,
   verifier, package, and subscription E2E gates.

## 7. Acceptance

- one fresh agent turn leaves canonical rows in `sessions.db:session_events`;
- all rows carry schema/session/turn correlation; tool pairs share `call_id`;
- no new global transcript JSONL is created;
- run-scoped `events.jsonl` is versioned and contains no forbidden raw secrets;
- SQLite-only replay reconstructs dialogue and tool ordering;
- a truncated JSONL tail and one corrupt SQLite payload degrade explicitly;
- concurrent writers produce unique event IDs and deterministic database order;
- migration is idempotent and legacy files remain byte-identical;
- trajectory validation is shared by hook E2E, MCPMark, and tau2 adapters;
- trajectory integrity facts are recomputed and false producer claims fail;
- one release cannot carry duplicate trajectory IDs or undeclared files;
- structured privacy attestation, secret scan, source/file digests, and
  anchored local/remote read-back gate public artifact publication;
- SIL run/mutation ledgers and `.eval`, plus Crucible evidence, remain
  authoritative and are joined by typed references/digests rather than copied
  into execution history;
- `Pre/PostCompact` boundaries and `PostVerify` outcomes can be represented
  without merging telemetry into lifecycle;
- full CI, installed-wheel smoke, GPT subscription behavior E2E, and artifact
  digest verification pass.

## 8. Rollback

The database change is additive. Rollback stops the new writer and leaves
`session_events` unread by the older release; existing `sessions/messages`,
`hook_events`, and legacy JSONL remain intact. No downgrade drops columns or
tables. JSONL path readers retain fallback support, so artifacts produced
before and during the migration stay inspectable.
Published dated trajectories are never rewritten; the adapter produces a v1
view in memory. A failed public staging attempt leaves no declared release, and
an already published release is corrected only by a new directory with a
`supersedes` pointer.

## 9. Verification evidence

The feature worktree passed:

```text
uv run ruff check core/ tests/ plugins/ scripts/
uv run ruff format --check core/ tests/ plugins/ scripts/
uv run mypy core/ plugins/
uv run lint-imports
uv run python scripts/architecture_baseline.py --check
uv run pytest tests/ -m "not live" -q
uv build
npm run build  # site/
```

The wheel was installed into a fresh temporary environment. `geode version`
reported `1.0.10`, and all four packaged Draft 2020-12 schemas loaded through
`importlib.resources`. The site generated all 236 static pages. The Next.js
build still reports the pre-existing broad seed-directory tracing warnings;
the Python suite still exposes pre-existing scheduler threads attempting to
write to pytest's closed capture stream. Neither produced a failed gate, and
neither is counted as evidence for this storage contract.

The subscription behavior E2E, artifact-repository policy/release PR, remote
digest read-back, and post-release MCPMark/tau2 runs intentionally happen after
the GEODE feature PR exists, so their immutable revision and artifact
identities can point to that reviewed change.
