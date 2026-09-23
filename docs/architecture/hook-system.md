# GEODE Extension Surfaces

> **English** | [한국어](hook-system.ko.md)

GEODE separates extension authority into three surfaces. The split keeps the
Hermes-like user contract small while preserving GEODE's detailed operational
timeline.

| Surface | Canonical API | Authority | Audience |
|---|---|---|---|
| Public hooks | `HookName`, `HookRegistry` | Bounded decisions at 13 stable checkpoints | Users and plugins |
| Trusted middleware | `MiddlewareRegistry` | Request transforms and execution wrapping | In-process trusted extensions |
| Runtime events | `RuntimeEvent`, `RuntimeEventBus` | Observation, audit, and persistence only | Runtime and operators |

Compaction, approval, sub-agent execution, and verification remain domain
services. They own their state transitions and expose checkpoints; they are not
a fourth extension surface.

The design record and measured migration map live in
[`../plans/2026-07-30-hook-taxonomy-fold.md`](../plans/2026-07-30-hook-taxonomy-fold.md).
Persistence policy is documented in
[`event-persistence.md`](event-persistence.md).

## Contract ownership and naming

[Naming conventions](naming-conventions.md#25-constants-tools-and-events) own
the spelling rules; this document owns extension behavior. Python enum members
and wire names are separate identities, not interchangeable aliases.

| Contract | Code owner | Naming / API | Regression boundary |
|---|---|---|---|
| Public decisions | [public.py](../../core/hooks/public.py) | `HookName.PRE_TOOL_USE` → `PreToolUse`; `HookAction.ADD_CONTEXT` → `add_context` | [Schema, decisions, dispatch](../../tests/core/hooks/test_public_hooks.py) |
| Tool admission/result | [executor.py](../../core/agent/tool_executor/executor.py), [approval.py](../../core/agent/approval.py) | `PreToolUse`, `PermissionRequest`, `PostToolUse` | [Runtime wiring](../../tests/core/hooks/test_public_hook_wiring.py) |
| Trusted transforms/wrappers | [middleware.py](../../core/hooks/middleware.py) | `register_tool_request`, `register_tool_execution`, and LLM counterparts | [Composition and single invocation](../../tests/core/hooks/test_middleware.py) |
| Observation | [system.py](../../core/hooks/system.py) | `RuntimeEvent.TOOL_EXEC_STARTED` → `tool_exec_started`; `subscribe` / `emit` | [Subscriber lifecycle](../../tests/core/hooks/test_hook_system_lifecycle.py) |

Schema acceptance alone does not prove runtime wiring, permission enforcement,
or durable telemetry. Test the affected producer and consumer together.

### Boundary regression checks

| Boundary | Required behavior | Regression evidence |
|---|---|---|
| Observation → execution | Each subscriber receives a deep snapshot; nested edits cannot change admitted tool arguments, later subscribers, or persisted event data. | [Event isolation](../../tests/core/hooks/test_hook_system_lifecycle.py) |
| Model switch → compaction | Use `ContextWindowManager`, including `PreCompact` defer and `PostCompact` after commit; no direct summary bypass. | [Model-switch compaction](../../tests/core/agent/test_model_switch_guard.py) |
| Cancellation → audit | Foreground child cancellation emits one `SubagentStop`; hook/middleware audit failure cannot replace the original interruption. | [Child wiring](../../tests/core/hooks/test_public_hook_wiring.py), [middleware](../../tests/core/hooks/test_middleware.py) |
| Shared handler → session state | Learning quotas, cooldowns, tool counts and input cursors are keyed by session; only matching durable `SessionEnd` clears them. Legacy turn-end events do not delete shared offload files. | [Learning lifecycle](../../tests/core/hooks/test_auto_learn.py), [offload lifetime](../../tests/core/wiring/test_tool_offload_rewire.py) |
| MCP trace → content | Tracing never reads local files or modifies write content. Schema argument aliases remain separate from content. | [MCP invocation](../../tests/core/mcp/test_mcp_lifecycle.py) |

Offload retention remains TTL-based: recall rejects and removes an expired file;
the store also exposes explicit expired-file cleanup. This is not a periodic
disk sweeper or a new per-user authorization boundary.

Automatic LLM learning extraction and dreaming consume `TURN_COMPLETED` only
when the existing termination classifier admits a deliverable outcome:
`natural`, `forced_text`, or `actionable_partial`. Other, missing, and unknown
reasons return before extraction cursors, quotas, or model calls. This is not a
verifier-pass gate: a rejected candidate can still teach a useful lesson.
Explicit `DreamingService.dream_session()` remains available for deliberate
analysis of failed evidence. The producer-to-consumer contract is tested in
[learning extraction](../../tests/core/hooks/test_extract_learning_models_adapter.py)
and [explicit dreaming](../../tests/core/memory/test_context_artifacts_dreaming.py).

## Public hooks

`HookRegistry` accepts only these `HookName` values. It has no wildcard
registration. Handlers run sequentially by priority, rewrites compose in
order, and a block or denial stops the chain.

| Hook | Boundary | Allowed decisions |
|---|---|---|
| `UserPromptSubmit` | Before user-input admission | continue, rewrite, block |
| `PreToolUse` | After request transforms and admission checks, before final policy/approval | continue, rewrite, block, request_permission |
| `PermissionRequest` | Permission decision, including headless execution; human prompt is fallback | allow, deny, ask |
| `PostToolUse` | After a result, before model context | continue, add_context, block |
| `PreCompact` | Before runtime-owned compaction | continue, rewrite, defer |
| `PostCompact` | After the compacted state commits | continue |
| `SessionStart` | After durable create/resume succeeds | continue |
| `SessionEnd` | After durable terminal state succeeds | continue |
| `SubagentStart` | After child identity and isolation are fixed | continue |
| `SubagentStop` | After the terminal child result is fixed | continue |
| `PreVerify` | Before the built-in verifier | continue, strengthen |
| `PostVerify` | After immutable verifier output | accept, revise, escalate |
| `Stop` | Immediately before final delivery | finalize, continue |

Current invocations use the versioned `geode.public-hook.v2` envelope. The
unchanged v1 schema remains available for compatibility:

```python
from core.hooks import HookName, HookRegistry, public_hook_schema

hooks = HookRegistry()
schema = public_hook_schema(HookName.POST_VERIFY)
legacy_schema = public_hook_schema(
    HookName.POST_VERIFY,
    version="geode.public-hook.v1",
)
```

Inputs are JSON-safe, secret-redacted, depth/size bounded, and validated
against the hook-specific JSON Schema before and after rewrites. Raw provider
requests, authentication material, personal-tool arguments, screenshots,
base64 data, and unrestricted tool output are not public-hook payloads.
Public handlers have a 10-second default timeout. Synchronous handlers run in
an isolated worker thread so blocking extension code cannot freeze the
AgenticLoop event loop; async handlers remain directly cancellable. A timed-out
sync thread may finish its own work later, so side-effecting extensions must
still be idempotent.

Returning `None` means no decision: the handler is audited as `ok`, adds no
attributed decision, and leaves the domain owner's fallback intact. It is not
an implicit `continue` or permission grant. Cancellation is audited as `error`
with only its exception type as the reason, then the original cancellation is
re-raised. Audit metadata never substitutes for a control decision.

### Verification and external loops

`GEODE_VERIFY_MODE=llm_judge` selects an LLM assessment of the original
request, bounded recent tool observations, and candidate output. Its
`observation`, `lesson`, and `next_check` feedback travels through the existing
verification continuation and checkpoint, not a second memory store. Missing,
malformed, or timed-out judgments escalate rather than pass. The legacy
`reflexion` setting warns and resolves to `llm_judge`; it is no longer a
separate execution mode. Reflection feedback uses the shared lifecycle rather
than selecting a judgment engine. The default final check remains `rule_based`.
Mechanical empty/action-required checks remain; output length, keyword overlap
and recovered tool errors no longer veto semantic review. Reflexion can reuse
bounded image evidence already observed by the agent, without new file access.
Text uses the latest 12 tool observations; image evidence has its own window of
12 image-bearing calls from the current verification chain. At most two distinct
images per call are replayed, bounded to 7 MiB per image and 14 MiB in aggregate
(encoded payload size). The prompt labels prior/current observations and omitted
evidence; it does not treat old source material as a newly executed check.
Evidence precedes the candidate claim. The neutral verdict contract asks the
judge to distinguish source agreement from circular write/readback consistency.
Unresolved material ambiguity requests a permitted distinguishing check through
the existing repair path; no mandatory-tool heuristic or extra judge is added.

The existing policy allows at most two verification revisions. Each judge call
uses the configured judge model (otherwise the loop model), existing usage
accounting, no tools, and at most 120 seconds within the remaining loop budget.
Repairs share the original root-turn clock. Between model calls, bounded
LLM verification requests its first candidate when the final third (at most 300 seconds)
remains. An in-flight call can cross that threshold, so this is headroom policy,
not guaranteed repair time. Repair tools remain available until the ordinary
final cutoff. Per-session time budgets reach isolated workers; parent cancellation
still owns the outer deadline. An agent definition with no model inherits the
parent/default model; explicit task and agent model overrides remain authoritative.
The default remains mechanical `rule_based`; selecting an LLM judge consumes
additional model calls and does not guarantee a correct verdict.

Cognitive reflection retains its existing default-enabled setting and cadence;
the handoff entry points no longer force it off. It uses only the root turn's
remaining time. Personal/redacted tool results suppress auxiliary reflection
while that conversation context remains, including later user turns, final text
and verification continuations. The final LLM judge also fails closed with
`personal_data_omitted` instead of forwarding that output. A new user input does
not sanitize prior context or clear the guard. The existing checkpoint guard
state preserves it across resume. Invalid hypothesis lists preserve previous state;
an explicitly empty list still clears it. These protections neither choose Jev
nor change the configured LLM, effort, or credential source.
Legacy context/checkpoints recover the guard from known personal-tool records
or omission markers. Assistant-only private prose with all such provenance
removed cannot be identified retrospectively; this change does not certify or
rewrite old stored conversations. Clearing messages alone does not prove that
cognitive state is sanitized, so it does not release the current loop's guard.

LLM middleware receives the explicit, immutable request `purpose`; a transform
cannot erase or replace it. Evaluation receipts distinguish cognitive reflection
from root calls, so reflection cannot count as the root consuming a tool result.
The two purposes cannot share one logical call ID. Cognitive reflection records
completed usage at the actual adapter terminal through the existing tracker;
middleware short-circuits do not incur provider usage. See the
[accounting contract](usage-accounting.md) for missing-usage and cost limits.

This is Reflexion-inspired, within-task feedback-conditioned repair, not
cross-task learning or a weight update. `turn_verify.reason` retains concise
feedback; the repair hint is consumed once by the next continuation.
The advisory replanner receives the runtime failure instruction separately from
its bounded 1,500-character candidate observation. XML-escaped data cannot
replace those boundaries, and a long candidate cannot truncate the instruction.
Harbor's external verifier remains benchmark score authority. New measurements
must freeze this mode before execution, without supplying hidden test answers.
The Harbor host validates but preserves the requested verifier wire value;
the frozen bundle's runtime owns alias interpretation. Replaying an old
`reflexion` bundle must not silently substitute that revision's `llm_judge`.
Completed Codex calls retain a bounded `request_image_receipt` in the existing
LLM-call event: serialized image count, encoded bytes, and image/call digests.
No image bytes or URLs are persisted by this receipt. Missing receipts, including
calls without a completed result, remain unknown. Receipt completeness describes
the bounded metadata, not visual attention, full runtime coverage or task success.

Reference: [Reflexion: Language Agents with Verbal Reinforcement Learning](https://arxiv.org/abs/2303.11366).

Finalization is one state machine:

```text
candidate -> PreVerify -> built-in verifier -> PostVerify -> Stop -> persist/deliver
                                                |             |
                                                +-- revise ---+
```

`PreVerify` may only add requirements: `strengthen` must contain non-empty
`additional_misses`. An instruction alone is invalid and is reported in
`handler_errors`, not silently accepted as stronger verification. Invalid
decisions retain the registry's existing error-and-continue policy; they do
not themselves block finalization. `PostVerify` receives the immutable
built-in result and can:

- accept a passing result or strengthen its evidence;
- request a bounded revision with an explicit instruction;
- escalate a result that needs an external decision.

A hook cannot turn a built-in failure into a pass. Revision has a fixed
continuation budget and starts a follow-up turn without replaying completed
tool side effects. This makes `PostVerify` useful to evaluator, CI, or
human-review loops while preserving GEODE's verifier as the monotone authority.
When no external `PostVerify` handler returns a decision, the runtime applies
the same monotone default: pass → accept, retryable failure → revise, and
non-retryable failure → escalate. The revision instruction is injected once in
the dynamic system context; it is never represented as a user message or sent
through task decomposition. `verification.decided` binds the final policy and
each attributed handler decision to the candidate SHA-256 digest, root turn,
and verify attempt without copying candidate text.
Escalation is a delivery gate: GEODE parks the session with
`external_verification_required`, returns the withheld candidate as
`AgenticResult.pending_text` to the owning external loop, and does not create
a terminal `session.ended` record.
`Stop` is intentionally narrower: it decides final delivery versus one bounded
continuation after verification policy is satisfied.

## Trusted middleware

There is one `MiddlewareRegistry`, four typed registration methods, and no
`MiddlewareKind`, `MiddlewarePoint`, or separate pipeline object:

```python
registry.register_tool_request(tool_request_middleware)
registry.register_tool_execution(tool_execution_middleware)
registry.register_llm_request(llm_request_middleware)
registry.register_llm_execution(llm_execution_middleware)
```

Request middleware is an ordered N→N+1 transform over immutable snapshots.
Execution middleware is an async onion around the approved executor or
provider call. `next_call` is single-use; omitting it is an explicit
short-circuit; downstream exceptions and cancellation keep their identity.
Default limits are 10 seconds for request transforms, 300 seconds for tool
execution wrappers, and 900 seconds for LLM execution wrappers; an explicit
zero opts out. If a wrapper raises after `next_call` has completed, GEODE
preserves the completed tool/provider result instead of replaying a side effect
or rebilling a provider call.

The tool path is:

```text
original request policy checks
  -> tool_request transforms
  -> policy recheck + schema validation
  -> PreToolUse
  -> policy recheck + schema revalidation
  -> PermissionRequest / approval (when required)
  -> tool_execution onion
  -> TOOL_EXEC_STARTED
  -> one terminal executor invocation
  -> TOOL_EXEC_ENDED
  -> PostToolUse
```

Execution middleware cannot change the already-approved tool name or
arguments. Personal-data classification is monotone across request rewrites:
renaming cannot downgrade consent or retention policy. A short-circuit does
not emit `TOOL_EXEC_STARTED`. `PostToolUse.executed` means the terminal dispatch
was entered, not that its side effect succeeded; read `has_error` and the result
separately. A post-hook cannot undo a completed effect.
The sequence shows a new execution returning a result. Error results also emit
compatibility `TOOL_EXEC_FAILED`, without duplicate persistence. Admission
denials, completed-receipt replay, and propagated exceptions/cancellation skip
`PostToolUse`.

The LLM path is:

```text
assembled AdapterCallRequest
  -> llm_request transforms
  -> llm_execution onion
  -> LLMAdapter.acomplete()
```

It covers the main loop, reflection, candidate sampling, and API mutation.
Changing cache-sensitive prompt/messages/tools fields requires both a
registration capability and an explicit cache-invalidation reason.
Auxiliary calls allocate missing `llm_call_id` and `llm_attempt_id` before
request middleware so extension audit and call lifecycle records share the
same identity. Existing caller-provided IDs remain authoritative.

## Runtime events

`RuntimeEventBus.subscribe()` and `emit()` are the canonical observation API.
The 56 pre-existing stored values are unchanged; `EXTENSION_INVOKED` is the
single new audit event, bringing the internal vocabulary to 57. It records
bounded attribution (`surface`, checkpoint, extension, status, duration, and
correlation), not request/response content.

`HookEvent = RuntimeEvent` and `HookSystem = RuntimeEventBus` remain runtime
identity aliases during migration. The legacy feedback/interceptor methods
also remain for source compatibility, but production control paths no longer
call them. New control belongs to a public hook, trusted middleware, or the
owning domain service.
The unused context-action feedback handler is removed; the legacy event value
remains readable without an active control subscriber.

Internal `SESSION_STARTED/ENDED` rows retain their historical meaning for old
readers. Public `SessionStart/End` represent durable session lifetime and are
not projections of every turn boundary.

## Telemetry and lifecycle boundary

The event bus is storage-agnostic. Production wiring registers one
`HookPersistenceSink`:

```text
RuntimeEventBus
  -> HookPersistenceSink
       -> sessions.db:hook_events       canonical operational history
       -> active run events.jsonl       conditional portable projection
```

- SQLite is the canonical indexed history and does not depend on a JSONL projection.
- JSONL is written only when an active `RunTimeline` is bound.
- `EXTENSION_INVOKED` uses the audit retention bucket.
- Compatibility duplicates still reach legacy subscribers but are not written
  twice.
- Raw prompts, personal data, tool bodies/results, cognitive snapshots, and
  authentication material are excluded or reduced to bounded metadata.
- A telemetry sink failure never changes hook, middleware, or lifecycle
  correctness.

Lifecycle hooks follow commit boundaries: `SessionStart` fires only after the
initial/resume checkpoint succeeds; `SessionEnd` fires only after a completed
or error terminal state is durable. A paused turn does not end the session.
`PostCompact` likewise fires only after compacted state persistence succeeds.
Owners close through `amark_session_completed/error`, keeping durable state
and the public `SessionEnd` edge inside one awaited boundary.

### Live behavior evidence

The 2026-07-31 subscription-backed behavior E2E exercised all 13 public hooks
and all four middleware join points through their owning runtime paths. The
probe made three LLM calls and one admitted single-invocation tool call, persisted one real
compaction, and produced 22 matching `EXTENSION_INVOKED` rows in both SQLite
and the active JSONL projection. Tool start/end rows retained the same
session/turn correlation in both stores.

The reviewed, normalized 27-event decision/tool trajectory and its manifest
are published at the immutable
[hook/middleware behavior E2E artifact](https://github.com/mangowhoiscloud/geode-eval-artifacts/tree/3e5b35f4505a4a2dc76d595b24862e8e73e668ff/trajectories/geode-agenticloop-hook-middleware-behavior-e2e-20260731T001640Z-1326e99cb447).
Raw prompts, checkpoints, provider reasoning, databases, WAL files, usage
records, and diagnostics remain withheld runtime evidence.

## Migration map

| Legacy/control shape | Canonical owner | Compatibility |
|---|---|---|
| `HookEvent` | `RuntimeEvent` | Alias; stored values unchanged |
| `HookSystem` | `RuntimeEventBus` | Alias; sinks and subscribers unchanged |
| observer `register` / `trigger*` | `subscribe` / `emit*` | Legacy methods remain |
| `USER_INPUT_RECEIVED` interception | `UserPromptSubmit` | Internal event becomes observation |
| `TOOL_EXEC_STARTED` interception | `PreToolUse` + real start event | Start moves after approval |
| `TOOL_RESULT_TRANSFORM` feedback | `PostToolUse` | Legacy event remains non-canonical |
| `CONTEXT_OVERFLOW_ACTION` feedback | Compaction policy + Pre/PostCompact | Domain service owns hard invariants |
| approval control event | `PermissionRequest` + approval transition | Existing audit values remain readable |
| sub-agent event trio | `SubagentStart/Stop` projection | Internal outcomes remain |
| verify pass/fail events | `PreVerify`/`PostVerify` + internal outcome | Stored outcome values remain |
| direct executor/provider wrapping gap | tool/LLM execution middleware | No event alias |

Canonical names stop at `HookName`, `HookRegistry`, `MiddlewareRegistry`,
`RuntimeEvent`, and `RuntimeEventBus`, plus the four role-specific middleware
protocols. No service locator or fourth extension plane is introduced.

## Registration and teardown

Public-hook and middleware names cannot silently replace another registration.
The process-owned registries are injected into the main loop, tool executor,
approval workflow, context manager, and sub-agent manager. Runtime, serve, and
workers share one registry pair per process.

`RuntimeEventBus.close()` blocks new registrations, clears subscribers, runs
cleanup callbacks in reverse order, and closes sinks. SQLite connections are
closed after each operation; close is idempotent.

## Reference boundaries

- [Codex hooks](https://learn.chatgpt.com/docs/hooks): public checkpoint names
  and successful no-output handlers; not concurrency or security-boundary parity.
- [Dioxus agent guide](https://github.com/DioxusLabs/dioxus/blob/ada3b67c73c1c5484dd2e8408cb21c470b200423/AGENTS.md):
  task-to-owner navigation, not duplicated contracts.
- [Furiosa kernel-authoring skill](https://github.com/furiosa-ai/furiosa-opt/blob/9b9cf0fdc78df00cdc430eae725a5ad9084a735e/skills/furiosa-opt-kernel-authoring/SKILL.md):
  short execution guidance linked to one detailed contract; distinct evidence grades.
