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

## Public hooks

`HookRegistry` accepts only these `HookName` values. It has no wildcard
registration. Handlers run sequentially by priority, rewrites compose in
order, and a block or denial stops the chain.

| Hook | Boundary | Allowed decisions |
|---|---|---|
| `UserPromptSubmit` | Before user-input admission | continue, rewrite, block |
| `PreToolUse` | After `tool_request`, before policy/approval | continue, rewrite, block, request permission |
| `PermissionRequest` | Immediately before a real human prompt | allow, deny, ask |
| `PostToolUse` | After a result, before model context | continue, add context, block |
| `PreCompact` | Before runtime-owned compaction | continue, rewrite, soft defer |
| `PostCompact` | After the compacted state commits | continue |
| `SessionStart` | After durable create/resume succeeds | continue |
| `SessionEnd` | After durable terminal state succeeds | continue |
| `SubagentStart` | After child identity and isolation are fixed | continue |
| `SubagentStop` | After the terminal child result is fixed | continue |
| `PreVerify` | Before the built-in verifier | continue, strengthen |
| `PostVerify` | After immutable verifier output | accept, revise, escalate |
| `Stop` | Immediately before final delivery | finalize, bounded continue |

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

### Verification and external loops

Finalization is one state machine:

```text
candidate -> PreVerify -> built-in verifier -> PostVerify -> Stop -> persist/deliver
                                                |             |
                                                +-- revise ---+
```

`PreVerify` may only add requirements. `PostVerify` receives the immutable
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
tool_request transforms
  -> schema validation
  -> PreToolUse
  -> schema revalidation
  -> hard policy
  -> PermissionRequest / approval
  -> tool_execution onion
  -> TOOL_EXEC_STARTED
  -> one terminal executor invocation
  -> TOOL_EXEC_ENDED
  -> PostToolUse
```

Execution middleware cannot change the already-approved tool name or
arguments. Personal-data classification is monotone across request rewrites:
renaming cannot downgrade consent or retention policy. A short-circuit does
not emit `TOOL_EXEC_STARTED`.

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
