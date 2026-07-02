# Observability Contract

Use this whenever a change touches schema, log, event, state, trajectory,
evidence, transcripts, tool results, or recovery.

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
