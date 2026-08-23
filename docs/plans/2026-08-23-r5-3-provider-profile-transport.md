# R5.3 Provider profile × credential route × transport

> [!NOTE]
> Design evidence only. Execution status, dependencies, acceptance, and closure
> remain owned by
> [`docs/architecture/extensibility-roadmap.md`](../architecture/extensibility-roadmap.md)
> (`LLM-003`, package R5.3).

**Date:** 2026-08-23

**Topic:** composable provider/model identity, credential selection, and LLM
transport metadata without changing provider wire or retry behavior

**Keywords:** provider profile, credential route, transport, adapter registry,
Codex OAuth, Responses API

## Measured GAP

| Current writer | Current reader | Gap |
|---|---|---|
| `core.llm.registry.ProviderSpec` | `Plan`, `/login providers` | Model family, endpoint, auth convention, and headers share one record. |
| Built-in adapter fields | registry route matching, dispatch, CLI | `provider`, `source`, `billing_type`, and optional capability facts repeat the provider variant. |
| `_source_inference` maps | loop/server/worker/auxiliary callers | Settings fields and OAuth account provider are independent provider-name maps. |
| Adapter implementation literals | SDK request/client builders | API shape and endpoint are not inspectable beside the registered route. |

`Plan` and `AuthProfile` are deliberately not replacement records. They own
mutable quota/account state and secret material; immutable discovery snapshots
must contain only non-secret declarative identity.

## Frontier research

Commit-pinned local sources were inspected before design.

| System | Evidence | Adopt / adapt / reject |
|---|---|---|
| Codex CLI `dad1db87bb5a` | `codex-rs/model-provider-info/src/lib.rs` separates `WireApi` and `AuthMode` concepts, validates incompatible auth fields, then materializes an API provider. | **Adapt** fail-loud composition validation and non-secret metadata. **Reject** one broad record that also owns retry/timeouts and credential environment lookup. |
| Codex Cloud | No public provider-registry implementation is present in the inspected checkout. | **N/A**; do not infer an internal design. |
| OpenClaw `49b4841081c6` | `src/config/types.models.ts` keeps model/provider API configuration separate from `src/agents/auth-profiles/types.ts` credential payload and selection state. | **Adopt** separation of model/API declaration from credential account state. **Reject** its much larger config surface for GEODE's five built-ins. |
| Hermes Agent `eb8421ba9864` | `providers/base.py` supplies a declarative `ProviderProfile` consumed by transports; credentials/streaming remain elsewhere. | **Adapt** declarative transport-readable metadata. **Reject** the monolithic profile (auth, endpoints, request quirks, model catalog) and last-writer-wins registry. |
| autoresearch `228791fb499a` | `program.md` fixes the evaluator and keeps a change only when the measured result justifies complexity. It has no provider runtime. | **Adopt** frozen parity checks and the simplicity criterion. **N/A** for provider structure. |

### Pattern decision

Use the existing `core.llm.registry` as the sole provider-variant catalogue.
Split its current `ProviderSpec` payload into three frozen value records and
retain `ProviderSpec` as their compatibility composition:

- `ProviderProfile`: provider/model family, display identity, default-model key;
- `CredentialRoute`: concrete source, account provider/selector, auth and
  billing identity, explicit/automatic selection metadata, quota-policy owner;
- `TransportSpec`: API shape, default endpoint, optional native capabilities,
  retry-policy owner, non-secret header factory.

`AdapterRegistration` stores one composed `ProviderSpec` and resolves routes
from those records. Existing adapter attributes remain validated compatibility
aliases. A third-party adapter may provide a `provider_spec`; adapters without
one receive a conservative legacy composition, preserving the R5.2 entry-point
contract and requiring no central provider enum edit.

## Minimal implementation

1. Split `ProviderSpec` into the three records while preserving its current
   `id`, `display_name`, `default_base_url`, `auth_type`, and header properties.
2. Attach a provider composition to each adapter registration. Route uniqueness
   and `resolve_for()` use the composition, then return the existing adapter.
3. Replace `_source_inference`'s settings/account maps with the credential-route
   metadata for built-ins; retain the existing retired-source errors.
4. Show the composed API transport in the read-only adapter CLI.
5. Pin exact built-in compositions, legacy entry-point compatibility, source
   behavior, provider wire payloads, call counts, and retry/quota parity.

## Non-goals

- no credential secret in a registry snapshot;
- no generic SDK transport or client factory;
- no new provider enum/switch;
- no retry, backoff, fallback, quota, billing, hook-order, or call-count change
  (R5.4);
- no adapter rename or entry-point contract removal;
- no live provider call.

## Acceptance

- Five built-ins publish exact provider/profile, credential, and transport
  compositions; the Codex route is OpenAI model semantics + Codex OAuth account
  selection + Codex Responses transport.
- Adapter compatibility attributes match the composed records or registration
  fails before a session.
- Route collision detection keys on composed provider/source identity.
- Existing raw adapter entry points still load; an explicit third-party
  composition loads without editing GEODE's provider catalogue.
- `infer_source` retains all current explicit, automatic, disabled, and retired
  credential outcomes while reading account-selection metadata from the route.
- Existing Anthropic/OpenAI/Codex/GLM request-shape, retry, quota, billing, and
  fallback characterization remains byte/behavior equivalent.

## Verification

Run focused provider/adapter/plan/source/CLI tests first, then ruff, format,
mypy, import contracts, architecture/docs generators, package/install checks,
and the full non-live suite. Live provider tests remain excluded.
