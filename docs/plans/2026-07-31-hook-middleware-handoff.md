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

- Full non-live suite: 10,345 passed, 23 skipped, 1 deselected.
- Official docs: 645 links, 236 static pages, 73 Markdown twins.
- Two isolated live runs used `gpt-5.6-sol` through `codex-oauth` subscription
  billing with no pay-as-you-go fallback.
- The live tool path observed
  `UserPromptSubmit -> SessionStart -> PreToolUse -> PostToolUse -> PreVerify
  -> PostVerify -> Stop -> SessionEnd` and all four middleware join points.
- The first run wrote 18 matching extension records to SQLite and the active
  JSONL projection. It exposed missing tool-event correlation; the shared
  executor boundary now retains the request session/turn IDs, and the second
  live run completed with zero activity-registry identifier warnings.
- A transient provider overload was recovered by the existing subscription
  adapter retry.
