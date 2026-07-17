# GEODE Hook/Persistence Wiring Audit Matrix

> [!NOTE]
> Historical wiring snapshot. Executable hook counts may have changed; current
> architecture-program status and generated-baseline work are owned by
> [`extensibility-roadmap.md`](extensibility-roadmap.md) under GOV-002,
> PROTO-001, and STORE-001.
>
> Current wiring snapshot for the 65-event HookSystem compatibility surface.
> The executable sources of truth are `core/hooks/system.py`,
> `core/hooks/catalog.py`, `core/observability/hook_persistence.py`, and
> `core/wiring/bootstrap.py`.

## 1. Dispatch boundaries

| Boundary | Registration | Result contract | Durable observation |
|---|---|---|---|
| Observer | `register()` / `register_prefix()` | ordered handlers; top-level payload copies | one completed `HookDispatch` per trigger |
| Feedback | `trigger_with_result*()` | handler dictionaries returned to caller | one completed `HookDispatch` per trigger |
| Interceptor | `trigger_interceptor*()` | sequential `modify` / `block` propagation | final payload and block status only |
| Sink | `register_sink()` | synchronous post-dispatch consumer | canonical persistence sink is registered once |
| Teardown | `HookSubscription.cancel()` / `HookSystem.close()` | idempotent resource release | sinks and owner cleanups close once |

Registration names are unique within a matching scope. Exact/prefix overlap
with the same name and a different handler fails loudly. Intentional
replacement requires `replace=True`; a stale subscription cannot cancel the
replacement generation.

## 2. Persistence coverage

| Class | Events | Default retention | SQL policy |
|---|---:|---:|---|
| High volume | 13 | 7 days | persisted, bounded payload |
| Standard | 32 | 30 days | persisted, bounded payload |
| Audit | 14 | 180 days | persisted, bounded payload |
| Compatibility/transient | 6 | none | dispatched to handlers, not persisted |

The project-local `sessions.db:hook_events` table is the operational event
SoT. It is capped at 100,000 rows and pruned every 256 writes by default.
Payloads are structurally bounded, secret-redacted, and stripped of raw user,
prompt, tool-input, tool-result, body, image, and credential fields. SQLite
connections are operation-scoped so retained HookSystem objects do not retain
database/WAL/SHM descriptors.

## 3. Deduplicated compatibility events

| Compatibility event | Canonical durable event |
|---|---|
| `LLM_CALL_FAILED` | `LLM_CALL_ENDED` with failure fields |
| `TOOL_EXEC_FAILED` | `TOOL_EXEC_ENDED` with `has_error=True` |
| `TOOL_RESULT_TRANSFORM` | `TOOL_EXEC_ENDED` after the single transform stage |
| `TOOL_APPROVAL_REQUESTED` | `APPROVAL_TRANSITION` |
| `TOOL_APPROVAL_GRANTED` | `APPROVAL_TRANSITION` |
| `TOOL_APPROVAL_DENIED` | `APPROVAL_TRANSITION` |

These six signals remain public for third-party listeners but never create a
second SQL row or transcript mirror.

## 4. SQL/JSONL boundary

| Data | Storage | Reason |
|---|---|---|
| Hook lifecycle, failures, approvals, feedback | `sessions.db:hook_events` | indexed filtering, retention, dedup |
| Agent cumulative state and lineage | `sessions.db` relational tables | mutable keyed state and joins |
| Active autoresearch/seed run transcript | run-scoped JSONL | ordered replay artifact owned by the run |
| Scheduler job attempts | bounded per-job JSONL (`JobRunLog`) | isolated append-only job history |
| Monthly usage ledger | monthly JSONL | append-only billing export/accounting boundary |
| Project journal and audit manifests | domain-owned JSONL | portable operator artifact / external format |
| Legacy `~/.geode/runs/*.jsonl` | read-only operator archive | no import, rewrite, or duplicate writer |

## 5. Auth profile wiring

| Item | Previous | Current | Reference |
|---|---|---|---|
| `mark_used()` | `credentials.py:31` | unchanged | - |
| `mark_success()` | not called | called after fallback success | OpenClaw `markAuthProfileGood` |
| `mark_failure()` | not called | called after fallback failure | OpenClaw `markAuthProfileFailure` |
| `mark_failure(is_auth_error=True)` | not called | called after auth-error classification | Hermes `_is_auth_error` |
| Profile tracking | none | `_last_profile[provider]` | OpenClaw `lastGood[provider]` |
| 401 auto-refresh | definition only | `_try_managed_refresh()` via `mark_failure` | Hermes `handle_401` |
| Proactive refresh | definition only | re-read 120 seconds before expiry in `resolve()` | Hermes `REFRESH_SKEW` |

## 6. Credential scrubbing

| Pattern | Example | Applied at |
|---|---|---|
| `sk-*` | `sk-proj-abc123...` | tool errors, LLM router, event payload bounds |
| `ghp_*` | `ghp_1234567890abcdef` | same |
| `Bearer` | `Bearer eyJhbG...` | same |
| `xoxb-*` | `xoxb-1234-5678-abc...` | same |
| `token=`, `key=`, `password=` | URL query parameters | same |

## 7. Cross-codebase grounding

| GEODE implementation | Hermes Agent reference | OpenClaw reference |
|---|---|---|
| `_notify_success()` | `_reset_server_error()` | `markAuthProfileGood()` |
| `_notify_failure()` | `_bump_server_error()` | `markAuthProfileFailure()` |
| `_is_auth_error()` | `_is_auth_error()` | `classifyFailoverReason()` |
| `_resolve_rotator_provider()` | N/A | `resolveAuthProfileOrder()` |
| `scrub_credentials()` | `_CREDENTIAL_PATTERN` | N/A |
| `register_refresher()` | `handle_401()` | `refreshProviderOAuthCredentialWithPlugin()` |
