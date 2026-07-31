# Handoff — public hooks and runtime middleware

This is the consumer-facing handoff for PR #2836. The detailed contracts and
migration table remain canonical in
[`docs/architecture/hook-system.ko.md`](../architecture/hook-system.ko.md) and
[`docs/architecture/hook-system.md`](../architecture/hook-system.md).

## Final shape

GEODE now has three extension surfaces. They are deliberately not
interchangeable.

| Surface | Size | Owner | Intended consumer |
|---|---:|---|---|
| Public hooks | 13 | `HookRegistry` | bounded external extensions |
| Trusted middleware | 4 join points | `MiddlewareRegistry` | in-process request/execution control |
| Runtime events | 57 events | `RuntimeEventBus` | internal observation and telemetry |

`HookEvent` and `HookSystem` remain source-compatible aliases for
`RuntimeEvent` and `RuntimeEventBus`. Stored event values are unchanged.

### Public hook ABI

| Domain | Hook | Allowed decisions |
|---|---|---|
| Prompt | `UserPromptSubmit` | continue, rewrite, block |
| Tool | `PreToolUse` | continue, rewrite, block, request permission |
| Tool | `PermissionRequest` | allow, deny, ask |
| Tool | `PostToolUse` | continue, add context, block |
| Context | `PreCompact` | continue, rewrite, defer |
| Context | `PostCompact` | continue |
| Session | `SessionStart` | continue |
| Session | `SessionEnd` | continue |
| Sub-agent | `SubagentStart` | continue |
| Sub-agent | `SubagentStop` | continue |
| Verification | `PreVerify` | continue, strengthen |
| Verification | `PostVerify` | accept, revise, escalate |
| Termination | `Stop` | finalize, continue |

All public payloads use `geode.public-hook.v1`. Dispatch bounds collection
depth and size, removes secret-bearing fields, isolates handler copies, and
accepts payload changes only with an explicit rewrite decision.

### Trusted middleware

| Join point | Position | Authority |
|---|---|---|
| `tool_request` | before approval | transform the immutable tool request |
| `tool_execution` | around the approved executor | wrap the real call through exactly-once `next_call` |
| `llm_request` | before adapter dispatch | transform the assembled adapter request |
| `llm_execution` | around provider execution | wrap the real provider call through exactly-once `next_call` |

Tool rewrites are reclassified and re-approved using the effective identity.
LLM request transforms preserve cache boundaries unless the registration has
the explicit cache-invalidation capability.

## Verification and outer loops

The finalization order is:

```text
candidate -> PreVerify -> built-in verifier -> PostVerify -> Stop -> persist/deliver
```

`PostVerify` receives immutable built-in verifier output. It cannot erase a
built-in failure. `revise` re-enters the bounded finalization path without
replaying tool side effects. `escalate` withholds delivery, stores the
candidate as `AgenticResult.pending_text`, and pauses the session as
`external_verification_required`, allowing an evaluator, CI job, or human
review loop to resume it safely.

## Lifecycle and telemetry

Lifecycle correctness stays with the owning domain service, not with hook
handlers or telemetry sinks:

- `SessionStart` fires only after the initial or resumed session checkpoint is
  durable.
- `SessionEnd` fires only after a completed/error terminal state is durable;
  a paused turn does not end the session.
- `PostCompact` fires only after compacted state persistence succeeds.

`sessions.db:hook_events` is the canonical indexed event history. Extension
invocations use one bounded `EXTENSION_INVOKED` audit event. An active
`RunTranscript` may mirror the same record to `transcript.jsonl`; absence or
failure of that optional JSONL projection never changes lifecycle or
execution. Conversation replay remains a separate `SessionTranscript`
concern.

## Consumer migration

- External control code registers a `HookName` handler with `HookRegistry`.
- Trusted request/execution control registers the matching role-specific
  protocol with `MiddlewareRegistry`.
- Internal observers subscribe to `RuntimeEventBus`; they must not use an
  event callback as an authorization or rewrite point.
- New consumers must not depend on the optional JSONL mirror for correctness.
- Existing `HookEvent`/`HookSystem` imports can migrate without rewriting
  persisted rows. Remove the aliases only after the documented deprecation
  window and observed external usage reach zero.

Do not add another extension plane or a replacement service locator. The
canonical public names end at `HookName`, `HookRegistry`,
`MiddlewareRegistry`, `RuntimeEvent`, and `RuntimeEventBus`.

## Closure evidence

- The final isolated behavior E2E used `gpt-5.6-sol` through
  `codex-oauth` subscription billing with no pay-as-you-go fallback.
- Owning runtime paths covered all 13 public hooks and all four middleware
  join points: the real `AgenticLoop`, client compaction, and
  `SubAgentManager`.
- The run made three LLM calls, executed one tool exactly once, persisted one
  compaction, and wrote 22 matching extension records to SQLite and the active
  JSONL projection.
- The E2E exposed a storage projection defect: typed activity mapping dropped
  opaque `session_id`/`turn_id` correlation before both sinks. The shared
  projection now preserves those identifiers, with a SQLite/JSONL regression
  test.
- Audit-extra full non-live suite: 10,347 passed, 23 skipped, 1 deselected.
- Official docs: 645 links, 236 static pages, 73 Markdown twins.
- Package build: wheel 607 files, sdist 609 files; metadata, package-content,
  clean-wheel install, and `GEODE v1.0.9` smoke passed.
- The reviewed public artifact contains a 27-event normalized decision/tool
  trajectory and manifest only. Raw prompts, checkpoints, provider reasoning,
  databases/WAL, JSONL, usage, and diagnostics remain withheld.
- Immutable artifact:
  [`geode-agenticloop-hook-middleware-behavior-e2e-20260731T001640Z-1326e99cb447`](https://github.com/mangowhoiscloud/geode-eval-artifacts/tree/3e5b35f4505a4a2dc76d595b24862e8e73e668ff/trajectories/geode-agenticloop-hook-middleware-behavior-e2e-20260731T001640Z-1326e99cb447).
- SHA-256: manifest
  `1326e99cb447b916046733a89e135cb08ca9e3d6581fb3e417bc5a151dd3d719`;
  trajectory
  `b34ec7b07d73c47b105a6c3b651618b426e1ee02d72ed7ab4ccd982310719850`.
- A Codex read-only review found four release-gate defects in the first
  harness; all were fixed and the live run repeated. The follow-up review
  returned no actionable findings.
