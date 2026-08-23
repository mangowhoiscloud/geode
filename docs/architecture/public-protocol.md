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
The v1 fields are additive, so an old peer can ignore them:

```json
{"type":"session","session_id":"cli-1234","version":"1.0.23","protocol_version":"geode.ipc.v1","features":["bounded_json","request_correlation","stable_events"]}
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
failure. Integration tests pin old field-less compatibility and exact request
correlation through a real Unix socket. Gateway tests pin envelope bounds and
processor correlation; public-hook tests pin exact names and both schema
versions.
