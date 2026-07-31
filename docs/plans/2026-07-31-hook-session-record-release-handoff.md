# Handoff — public hooks, session records, and evaluation artifacts

Date: 2026-07-31

Runtime release: GEODE `v1.0.11`

Runtime commit: `686ff37257fc7dd655025049dccee7a10d6ef340`

Artifact commit: `16a54f08450db771c02e30c73bdc3867f6282f83`

Read §1 for the shipped state, §2 for the final hook surface, §3 for storage
and Artifactory publication, and §4 for SIL/Crucible compatibility. Later
sections contain verification and follow-up details.

## 1. Shipped state

The hook/middleware and session-record work is released, not merely planned:

| Change | Evidence |
|---|---|
| implementation into `develop` | [`GEODE #2850`](https://github.com/mangowhoiscloud/geode/pull/2850), squash `dc8b9175525db50ff23d8460e4c89316b16767cf` |
| release metadata into `develop` | [`GEODE #2851`](https://github.com/mangowhoiscloud/geode/pull/2851), squash `7b988ffd944f2080efb53c0023f5596e4c6c3a39` |
| `develop` into `main` | [`GEODE #2852`](https://github.com/mangowhoiscloud/geode/pull/2852), merge `686ff37257fc7dd655025049dccee7a10d6ef340` |
| package | [`v1.0.11`](https://github.com/mangowhoiscloud/geode/releases/tag/v1.0.11), PyPI `geode-agent==1.0.11` |
| public hook behavior | [`geode-eval-artifacts #8`](https://github.com/mangowhoiscloud/geode-eval-artifacts/pull/8), commit `b979268d7e64c99ca27b51c025a2cd25022cc1a5` |
| post-release benchmarks | [`geode-eval-artifacts #9`](https://github.com/mangowhoiscloud/geode-eval-artifacts/pull/9), commit `16a54f08450db771c02e30c73bdc3867f6282f83` |

The package wheel SHA-256 is
`63c4811cf992c0c797bff25abb6faea57dbc1467c73cf370827585e759e369b9`;
the sdist SHA-256 is
`d5f02a15d52e963a03930dd8546a6f8b4d8895dd9c44316e28dd9153cb6af88f`.
GitHub and PyPI served the same wheel bytes.

## 2. Final hook and middleware surface

### 2.1 Exposure levels

GEODE no longer presents one flat vocabulary as if every internal event were a
stable extension point:

| Level | Surface | Stability / authority |
|---|---|---|
| public control hooks | 13 `HookName` values | versioned, redacted, bounded payloads; closed actions |
| trusted execution middleware | 4 named join points | in-process immutable transforms or exactly-once async wrappers |
| runtime events | 57-member internal `RuntimeEvent` vocabulary | observability and wiring; not a public compatibility promise |

This avoids exposing every telemetry detail while still retaining internal
diagnostic resolution. `MiddlewareKind` was not introduced: one
`MiddlewareRegistry` already has four type-specific registration and execution
methods, so a second enum would duplicate the type system and fragment naming.

### 2.2 Public hook contract

| Hook | Allowed decisions | Control point |
|---|---|---|
| `UserPromptSubmit` | `continue`, `rewrite`, `block` | before the submitted prompt enters the loop |
| `PreToolUse` | `continue`, `rewrite`, `block`, `request_permission` | after request middleware, before policy/permission/execution |
| `PermissionRequest` | `allow`, `deny`, `ask` | explicit tool permission decision |
| `PostToolUse` | `continue`, `add_context`, `block` | after the executor returns |
| `PreCompact` | `continue`, `rewrite`, `defer` | before compaction |
| `PostCompact` | `continue` | after compaction persistence |
| `SessionStart` | `continue` | new/resumed session boundary |
| `SessionEnd` | `continue` | terminal session boundary |
| `SubagentStart` | `continue` | child execution starts |
| `SubagentStop` | `continue` | child execution ends |
| `PreVerify` | `continue`, `strengthen` | before the executable verifier |
| `PostVerify` | `accept`, `revise`, `escalate` | after verifier evidence exists, before delivery |
| `Stop` | `finalize`, `continue` | final delivery/continuation gate |

`PostVerify.revise` requires an instruction. `PostVerify.escalate` withholds
ordinary delivery and terminates with
`external_verification_required`; it does not silently turn the run into a
success or automatic retry.

### 2.3 Trusted middleware contract

| Join point | Shape | What it controls |
|---|---|---|
| `tool_request` | `ToolCallRequest -> ToolCallRequest` | effective tool arguments before public hook, guardrail, permission, and execution |
| `tool_execution` | `(ToolCallRequest, next_call) -> result` | actual executor call as an async onion |
| `llm_request` | `LlmCallRequest -> LlmCallRequest` | assembled provider-agnostic adapter request |
| `llm_execution` | `(LlmCallRequest, next_call) -> result` | actual provider call as an async onion |

Inputs are cloned/immutable, middleware names are unique per join point,
priority ordering is deterministic, and execution wrappers may call
`next_call` exactly once. Tool and LLM execution have independent timeouts.
This closes the former partial `tool_request`/`TOOL_EXEC_STARTED` overlap and
the missing executor/provider wrapper seams.

### 2.4 Why `PostVerify` is public

An external loop normally needs a decision after executable checks, not only a
notification that generation stopped. `PostVerify` exposes that exact
boundary:

- `accept` releases a verifier-backed candidate;
- `revise` returns a bounded instruction to the agent loop;
- `escalate` pauses delivery for an operator, SIL policy, Crucible gate, or
  another external authority;
- typed `evidence_refs` preserve who judged what, under which schema, without
  copying the judge payload into agent dialogue.

This makes an outside loop able to control delivery without becoming coupled
to GEODE's internal `RuntimeEvent` taxonomy. The hook controls flow; it does
not inherit SIL or Crucible promotion authority.

## 3. Storage and Artifactory publication

### 3.1 Plane separation

```mermaid
flowchart LR
    U[User / external loop] --> H[13 public hooks]
    H --> M[4 trusted middleware seams]
    M --> L[AgenticLoop + tools + provider]
    L --> V[Executable verifier]
    V --> PV[PostVerify]
    PV -->|accept / revise / escalate| U

    H -. diagnostic .-> RE[RuntimeEvent]
    M -. diagnostic .-> RE
    L -. lifecycle .-> SE[SessionEvent]
    V -. evidence / pending .-> SE

    RE --> HE[(sessions.db<br/>hook_events)]
    SE --> DB[(sessions.db<br/>session_events)]
    DB --> RJ[run events.jsonl<br/>bounded projection]
    DB --> T[geode.trajectory@1<br/>immutable derived view]
    RJ -. portable lifecycle .-> SIL[SIL run ledger]
    T --> RM[geode.trajectory-release@1<br/>digest manifest]
    RM --> AR[geode-eval-artifacts<br/>Git PR + immutable commit]

    SIL -->|Inspect .eval + mutation/attribution| ER[typed evidence_refs]
    C[Crucible v3 + frozen contract<br/>native receipt + verifier] --> ER
    ER --> T
```

| Plane | Stored elements | Role |
|---|---|---|
| checkpoint | SQLite `sessions`, `messages` | mutable model-visible resume state |
| lifecycle record | SQLite `session_events`, `geode.session-event@1` | append-only reconstruction across session/turn/call |
| telemetry | SQLite `hook_events`, `geode.observer.v1` | bounded hook/middleware/runtime diagnostics |
| run projection | co-located `events.jsonl`, `geode.run-event@1` | bounded, rebuildable tail/copy/exchange view |
| evaluation | `trajectory.json`, `geode.trajectory@1` | immutable behavior projection with quality and evidence joins |
| publication | trajectory plus `geode.trajectory-release@1` manifest | allowlisted, privacy-reviewed public evidence |

The telemetry/lifecycle boundary is therefore explicit. A middleware timing or
hook dispatch observation remains telemetry. A user message, tool call/result,
verification evidence, pending external decision, or terminal session state is
lifecycle. Telemetry is not required to reconstruct the conversation.

The old `SessionTranscript` and `RunTranscript` names remain deprecated
compatibility shims over `SessionTimeline` and `RunTimeline`. New runtime
history does not create a competing global transcript store. Legacy
`transcript.jsonl` and `dialogue.jsonl` are accepted as read-only fallback
inputs; `events.jsonl` is the new run projection.

### 3.2 What is in one trajectory

Each `geode.trajectory@1` carries:

- schema, trajectory, source, and coverage identity;
- ordered event IDs and ordinals;
- session, generation, turn, and call correlation keys;
- dialogue/tool projections and runtime-event references;
- typed evidence/verifier references;
- payload digests and declared redaction/omission state;
- recomputed integrity quality, not a trusted producer assertion.

The validator recomputes unique IDs, contiguous ordinals, required correlation,
tool call/result counts, exact pairs, orphan calls/results, missing call IDs,
truncation, corruption, and omitted content. Missing correlation or an orphan
sets `scope_complete=false`; lossy payloads set `replay_complete=false`.

### 3.3 How it “goes to Artifactory”

There is no JFrog Artifactory upload. GEODE uses the append-only public Git
repository
[`mangowhoiscloud/geode-eval-artifacts`](https://github.com/mangowhoiscloud/geode-eval-artifacts):

1. preserve authoritative native run bytes in the private ignored
   `artifacts/` tree;
2. validate the trajectory schema and recompute quality;
3. resolve and SHA-256-check every native `artifact_digests` reference;
4. require a structured privacy review and scan the exact public bytes for
   paths, identity, email, bearer credentials, GitHub/OpenAI tokens, duplicate
   IDs, and undeclared files;
5. stage a content-addressed, non-overwriting release directory containing only
   trajectories and a manifest;
6. copy allowlisted native receipt views and stable releases into a fresh
   artifact-repository branch/worktree;
7. merge by PR;
8. download the exact merge commit from GitHub and verify manifest SHA-256,
   file bytes, counts, trajectory IDs, source digests, and scans again;
9. pin the artifact commit and immutable paths in GEODE docs.

The stable release itself excludes `sessions.db`, WAL files, general
`events.jsonl`, checkpoints, hidden reasoning, provider diagnostics, and
credentials.

### 3.4 Data-quality result

The post-release publication at artifact commit `16a54f08450d` raised the
evidence bar from “a transcript file exists” to an independently recomputed and
remotely read-back contract:

| Release | Trajectories | Events | Exact tool pairs | Missing correlation / orphans | Manifest SHA-256 |
|---|---:|---:|---:|---:|---|
| MCPMark v1.0.11 filesystem/easy | 10 | 226 | 78 | 0 / 0 | `82fe94b01a25e7e9f8c504d511f018129cb058ad532dbcbc315de9c6819db0fb` |
| Tau2 v1.0.11 mock + Telecom | 2 | 142 | 9 | 0 / 0 | `a71155f7006c8dd412af8d1471e7d2380e5f072cc8f0495924fa86f26d69a9a2` |

All 368 events matched the isolated canonical SQLite event sets by event ID,
session, turn, call, and kind. Both releases are scope-complete and explicitly
replay-incomplete because non-public bodies are digested rather than leaked.
All configured secret/identity/credential/path scan classes returned zero.

Native authority and public disclosure identity are kept separate:

- MCPMark public receipt set: 31 files, 554,366 bytes, path-set digest
  `3ffcdeebc39be91f5d957b66f1a5e48bd1408645f83120e84346bba7beef6417`;
- Tau2 public receipt set: 4 files, 114,004 bytes, path-set digest
  `a5d2a2f6b8dd719f22f050e16afe4ad8bf65345c35a65552e5467745b3eeda5f`;
- Telecom raw native receipt:
  `eda3cdbdb9cd0c2f993db3f9fe2e813cdbc06fe9cf112e23ba60c7ea9d98a45b`;
- Telecom public redacted copy:
  `506f906cfa1d6e8e4320ba284be1aa0f7ec26ea2fc47b43e7b36f69e3643a9d4`.

The different Telecom digests are intentional and disclosed: synthetic
phone/email fields were removed from the public copy.

## 4. Frontier and external-loop alignment

The comparison was rerun on locally pulled exact source heads:

| System | Exact head and grounded source | GEODE alignment |
|---|---|---|
| Hermes | `98105f31f46d`; `docs/middleware/README.md`, `docs/observability/README.md`, `state.db` session paths | same four middleware seams and SQLite-centric interactive state; GEODE adds immutable request contracts and exactly-once async `next_call` |
| OpenClaw | `49b4841081c6`; `src/config/sessions/session-accessor.sqlite-transcript-store.ts`, `trajectory_runtime_events` schema/tests | separate durable transcript/lifecycle and bounded runtime telemetry; exported/serialized artifacts are not another hot-path truth |
| Codex | `f0c30e528a54`; hook names in `codex-rs/analytics/src/events.rs` and hook runtime/config | same 11 public lifecycle/tool hooks, with GEODE's deliberate `PreVerify`/`PostVerify` extension |

The result is not a union of every frontier event. It is:

```text
Codex public 11
+ GEODE PreVerify / PostVerify
+ Hermes four middleware seams
+ Hermes/OpenClaw SQLite state ownership
+ Codex correlation and replay rigor
```

### SIL

SIL keeps three authorities separate:

- `RunTimeline/events.jsonl` for portable run lifecycle;
- mutation and attribution ledgers for the self-improvement process;
- Inspect `.eval` for scored Petri assays.

`geode session export-trajectory --sil-eval <archive.eval>` creates a typed
`inspect_ai.eval@native` evidence reference and checks its source digest. This
is an explicit promotion action, not automatic SIL finalization. SIL may
discard a campaign without publishing a GEODE trajectory.

### Crucible

Crucible keeps `crucible.evidence.v3`, the frozen experiment contract, native
tau2 result, verifier, and promotion state as authority. GEODE contributes
stable session/turn/call correlation and a replay sidecar. It cannot make an
invalid or unfrozen arm valid.

The current tau2 snapshots are intentionally marked
`promotion_authority=none` and `candidate_surface=unfrozen_git`. The public
copy can be privacy-transformed, while the raw receipt digest remains the
Crucible join key. This is compatible with a future frozen Crucible campaign
without changing the trajectory schema.

## 5. Behavior E2E and benchmarks

### Hook behavior

The GPT subscription behavior E2E used `gpt-5.6-sol`, effort `high`:

- all 13 public hooks executed;
- middleware counts were `tool_request=1`, `tool_execution=1`,
  `llm_request=3`, `llm_execution=3`;
- SQLite and JSONL each contained all 22 hook/middleware extension rows;
- the public trajectory contained 27 events and one exact tool pair;
- scope was complete, replay was deliberately incomplete, and secret scans
  returned zero.

Artifact:
[`d418e55ff8aa`](https://github.com/mangowhoiscloud/geode-eval-artifacts/tree/b979268d7e64c99ca27b51c025a2cd25022cc1a5/trajectories/geode-agenticloop-hook-middleware-behavior-e2e-20260731T091808Z-d418e55ff8aa).

### MCPMark

Released `v1.0.11`, `filesystem/easy`, `gpt-5.6-sol` subscription/high:

- official verifier: 10/10;
- 596.580 seconds, 56 turns;
- 700,719 input, 12,164 output, 206,848 cache-read tokens;
- recorded cost estimate $2.937699, not subscription billing;
- 226 events and 78 exact tool pairs.

The earlier uppercase failure now passes.

### Tau2

Released `v1.0.11`, agent and user both `gpt-5.6-sol`
subscription/high:

- mock `create_task_1`: 0/1; genuine exact-comparator failure because the model
  supplied unrequested `description=""`;
- first Telecom-small task: 1/1; DB, `toggle_roaming`, mobile-data, and speed
  assertions all passed;
- no provider, quota, or adapter exception in either run.

Report:
[`2026-07-31-gpt56-v1011-benchmark.md`](https://github.com/mangowhoiscloud/geode-eval-artifacts/blob/16a54f08450db771c02e30c73bdc3867f6282f83/reports/e2e-validation/2026-07-31-gpt56-v1011-benchmark.md).

## 6. Quality gates and anti-deception findings

Release gates passed:

- ruff check and format;
- mypy over 542 source files;
- four import contracts over 430 files / 1,537 dependencies;
- architecture, llms index, and slop ratchets;
- 10,434 non-live tests;
- 236-page static site build;
- source distribution and wheel build;
- installed-wheel smoke from outside the source tree;
- main CI, smoke, Pages, GitHub release, and PyPI verification.

Four apparently green paths were rejected before becoming evidence:

1. a wheel smoke run from the repository inherited source-tree imports; it was
   rerun from `/tmp` against site-packages;
2. the first PyPI verification observed a Simple API propagation race after
   upload; failed jobs were rerun idempotently and verified published bytes;
3. an MCPMark command initially shadowed the release source with the harness
   checkout; exact release-tree import preflight corrected it;
4. the tau2 environment had a stale editable GEODE `1.0.9`; it was replaced by
   the public `1.0.11` package before scoring.

These are evidence-quality improvements: environment identity and remote bytes
are now proven rather than inferred from a successful process exit.

## 7. Deliberate non-expansions and remaining work

The implementation avoided the following fragmentation:

- no public exposure of all 57 internal runtime events;
- no `MiddlewareKind` enum beside four typed methods;
- no second canonical transcript beside SQLite;
- no K3-specific or benchmark-specific canonical trajectory schema;
- no embedded SIL/Crucible verdict that could steal outer-loop authority;
- no automatic copy of the whole private artifact tree.

One genuine behavior gap remains: tau2 mock can fail when the model supplies an
empty optional `description`. The result was retained as 0/1. Fixing it should
be evaluated as tool-schema/action-normalization behavior, not hidden in the
artifact bridge or relabeled as infrastructure failure.
