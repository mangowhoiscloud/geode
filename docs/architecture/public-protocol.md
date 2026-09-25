# Public protocol boundaries

> **English** | [한국어](public-protocol.ko.md)

GEODE exposes three deliberately separate public envelopes. Internal
`RuntimeEvent`, `HookEvent`, transport SDK objects, and dataclasses do not become
public merely because they gain a field or enum member.

| Surface | Current version | Stable authority | Bounds and correlation |
|---|---|---|---|
| CLI IPC | `geode.ipc.v1` | `core/ipc_protocol.py` | 1 MiB JSON line; request ID on stream, event, and terminal response |
| Gateway input | `geode.gateway.v1` | `core/messaging/models.py` | 64 KiB content; 32 KiB JSON metadata; platform message ID |
| Extension hooks | `geode.public-hook.v2` | `core/hooks/public.py` | 32 KiB redacted payload; typed hook correlation; v1 schema query |

## CLI IPC

The thin CLI and `CLIPoller` keep the existing flat line-delimited JSON shape.
The v1 envelope remains additive; applying session model settings requires the
negotiated `session_model_config` feature:

```json
{"type":"session","session_id":"cli-1234","version":"1.0.23","protocol_version":"geode.ipc.v1","features":["bounded_json","request_correlation","stable_events","session_model_config"]}
```

The client answers with the same version and its offered feature list in
`client_capability`. The daemon selects the known intersection. A greeting
without `protocol_version` is the legacy `geode.ipc.v0` contract; an unknown
explicit version fails closed. Unknown fields are retained by the codec and
ignored by readers that do not own them. Unknown client message types receive
an explicit error. Unknown streamed event names are ignored by the client and
cannot be emitted through the server's public event writer until added to the
stable `IPC_EVENT_TYPES` vocabulary.

Every new client request carries an opaque `request_id`. The server attaches
that same ID to streaming text, approvals, structured events, and the final
response. Legacy responses without an ID remain readable; mismatched IDs are
never delivered to the active request.

The socket is local and mode `0600`. User prompts and model results therefore
remain intact rather than being redacted in transit. The envelope and receive
buffers are capped at 1 MiB to prevent unbounded allocation.

### Session model settings

The initial `client_capability.model_config` contains the bounded, non-secret
`core/config/session.py:SessionModelConfig`: primary model, native effort,
concrete adapter source, explicit reflection/judge model and source, reflection
output limit, action/reflection temperatures, and judgment preferences. Credential
source policies and key material are not concrete sources or IPC payload fields.
Empty auxiliary model/source pairs inherit the current primary route.

`CLIPoller` resolves and validates the complete candidate before applying it to
one loop. It replies `ack` with `status: applied` and the actual `model_config`
only after adoption succeeds. The reply also identifies the existing `workspace`
and `checkpoint_directory`. A sibling/outside workspace or a nested project is
rejected; an ordinary descendant uses the daemon's root, without changing cwd.
Clients without the feature must restart/upgrade and reconnect; codec-level v0
readability does not authorize a session with silently ignored settings.

Named, picker, and fullscreen `/model` choices use the same `command` envelope
and a bounded `model_config` patch. The existing session lane serializes changes;
`command_result.status: applied` precedes client-side default persistence. Rejected
admission writes no defaults. A later disk-write failure reports that the live
selection was applied but saving defaults failed. `project`/`global` scope selects
future defaults, never an implicit broadcast to other live sessions. Mutator
choices retain their separate next-run owner. Cancellation sends no patch, and
terminal capability refreshes contain no model policy, so a following prompt
cannot reapply stale client defaults.

Model/tool publication restores its previous route and tool bindings if projection
fails. Context adaptation may have already committed a valid compaction using the
previous route; this is not a promise to roll back history or external effects.
Auxiliary readers consume the loop's immutable model policy and existing credential
owners. A resumed checkpoint carries that same non-secret record in
`state.json.model_settings`. Resume admits it before history/identity/reopen,
then returns actual `model_config` and `model_config_origin: checkpoint|current`.
The client adopts the returned selection. Legacy absence keeps the current
validated selection; malformed present data rejects resume instead of silently
mixing historical model metadata with current defaults. The existing JSON IPC
envelope and negotiated feature remain unchanged.

## Gateway input

Slack, Discord, and Telegram receivers select only the fields GEODE uses into
`InboundMessage`; they never forward an SDK payload wholesale. The envelope
validates finite timestamps, bounded identifiers and content, and JSON-safe
bounded metadata before routing. The upstream message identifier becomes
`message_id` and is forwarded in processor metadata for correlation. A stable
hash is used only by direct/internal callers that lack a platform identifier.

Unknown upstream fields are ignored by construction. Message content is user
input and is not redacted before the model. Tokens and platform credentials
remain outside the envelope; durable activity and public-hook projections
apply their own redaction contracts.

## Extension events

The extension boundary remains `HookName` plus `HookRegistry`; see
[Hook architecture](hook-system.md). Its 13 names, hook-specific JSON Schemas,
closed decisions, secret redaction, payload limits, and v1/v2 compatibility
already satisfy the public extension contract. Internal event growth does not
expand that ABI.

## Compatibility evidence

Golden v0/v1 IPC greetings live under `tests/fixtures/protocol/`. Protocol
tests pin negotiation, unknown-field preservation, event names, and size
failure. Integration tests pin explicit unsupported-peer rejection, successful and failed
session adoption, and exact request correlation through a real Unix socket. Gateway tests pin envelope bounds and
processor correlation; public-hook tests pin exact names and both schema
versions.
