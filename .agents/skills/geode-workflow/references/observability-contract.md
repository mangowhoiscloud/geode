# Observability Contract

Use this whenever a change touches schema, log, event, state, trajectory,
evidence, transcripts, tool results, or recovery.

For usage/cache/cost changes, read the
[usage accounting contract](../../../../docs/architecture/usage-accounting.md)
and trace its real producer/reader pair. Preserve units, denominator, scope,
zero versus missing, and cost authority; generic event parity does not prove
accounting completeness.

For a new or changed LLM entry path, trace admission → adapter terminal →
durable call record, then identify its tracker/UI consumers or documented
exclusions. Reuse the existing observation seam and pass its event bus and
session correlation explicitly; rendering token counters is not persistence.
Exercise the real entry and runtime with only the provider
boundary faked, including opt-in branches, missing/zero/positive usage, and
failure/cancellation. Do not mock away the accounting seam being checked.

For state replacement, distinguish candidate validation, live replacement,
artifact persistence, checkpoint commit and downstream acceptance. An emitted
success event does not establish an atomic transaction across stores. Verify
the owner's cancellation, stale-candidate and reentrant-mutation boundaries;
preserve newer input and already committed state according to that contract.
For conversation changes, read the existing
[compaction contract](../../../../docs/architecture/context-compaction.md).
Trace retained context through the next action and auxiliary requests, keeping
derived summaries, original user corrections and observed tool evidence distinct.

For client/daemon changes, trace the explicit request through the owning session
to its next actual consumer and the response rendered by the client. Distinguish
received, deferred, applied and persisted outcomes; transport acknowledgement or
saved defaults do not prove live adoption. Validate coupled values together and
compare explicit no-op requests with the target runtime, not stale defaults.
Keep session scope separate from project/global persistence and credential
ownership. Exercise the affected start, explicit-change, failure, reconnect/resume
and cross-session paths; preserve absent historical fields instead of inventing
restored values.
Verify auxiliary and worker readers as well as the primary request. Use the
existing protocol, configuration and lifecycle owners, with no secret-bearing
settings snapshot or process-global rebinding to emulate a session change.

For host diagnostics, preserve explicit request policy. Missing host-specific
startup state does not establish unavailable capability; resolve it through the
existing runtime owner and keep absent evidence distinct from a negative result.

For resumed verification, distinguish observations retained from earlier
requests from current checks; preserve their provenance and privacy boundaries.
Prior observations are not fresh checks, omitted evidence remains unknown, and
candidate prose does not establish an observed result. Check bounded rendering
against useful inputs/results from the actual caller, not only toy payloads.

For public hooks, follow [hook contracts](../../../../docs/architecture/hook-system.md)
for bounded decisions, trusted transforms and observations. Trace registration
and the actual caller; observers do not choose admission or recovery. Before
extending a payload, inspect its validator, readers and supported versions.
Reuse existing metadata where sufficient instead of adding a parallel schema.

## Required Surfaces

| Surface | Requirement |
|---|---|
| Transcript lifecycle | Stable event name, `action`, `entity_type`, `entity_id`, bounded payload |
| Evidence ledger | Schema version, timestamp, sequence/session identity, component, kind, summary, payload hash, redacted payload |
| Tool result | Structured success/failure data instead of prose-only output |
| GUI trajectory | Observation, action, classified failure, recovery, terminal evaluation |
| State | Durable state only; ephemeral context stays out of long-lived ledgers |

## Redaction Rules

Never persist:

- raw screenshots unless explicitly intended as a local artifact
- base64 image blobs in transcripts or evidence
- API keys, tokens, passwords, secret fragments
- full prompts or user text when a summary/hash is sufficient

Use existing redaction helpers where available.

## Consistency Audit

For new lifecycle emitters, grep or AST-check that required fields are present.

Useful search axes:

```bash
rg "record_lifecycle_event|append_jsonl|evidence|trajectory|schema_version" core tests
rg "action=.*entity_type=.*entity_id|entity_type=.*entity_id=.*action" core tests
```

If one subsystem uses a schema/log/event/state pattern, adjacent emitters should
conform unless an exemption is documented.

## Failure Semantics

Unsupported or unsafe paths should:

- return a structured unsupported/denied result
- include a human-readable reason
- avoid mutating persistent state
- avoid retry loops that repeat the same denied action
- leave enough evidence for post-run diagnosis
