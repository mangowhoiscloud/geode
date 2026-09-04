# R5.4 Call-stack convergence

> Historical implementation contract. Retry behavior was re-audited and
> superseded on 2026-09-03 by
> [`2026-09-03-frontier-retry-policy-alignment.md`](2026-09-03-frontier-retry-policy-alignment.md).
> The matrices below preserve the R5.4 baseline, not the current contract.

> Execution status is owned only by
> [`docs/architecture/extensibility-roadmap.md`](../architecture/extensibility-roadmap.md).
> This document records the implementation contract for `LLM-004`; it does
> not change the package status or replace the active claim.

## Problem

GEODE already shares the low-level error taxonomy, but retry authority is
split across four current paths:

| Path | Current policy owner | Required preservation |
|---|---|---|
| Interactive loop | `core/agent/loop/_phases.py` | Same model, five attempts, deterministic `2**n` delay capped at 30 seconds, terminal operator handoff on quota |
| Fail-fast pre-execution retry | `core/agent/loop/_provider_call.py` | One same-adapter connection retry; bounded empty-output retry; no completed-tool replay |
| Auxiliary model chain | `core/llm/router/calls/_failover.py` | Jitter, model allowlist, optional next-model traversal, `(None, None)` exhaustion contract |
| Provider compatibility retry | `core/llm/fallback.py` | Jitter, configured attempts, OAuth refresh, billing/request-fatal short circuit, stream replay guard, legacy callback shape |

`core/llm/adapters/dispatch.py` intentionally remains a strict
single-adapter connection retry. R5.4 must not turn it into model or provider
fallback.

## Frontier research summary

| System | Related pattern | Decision | Rationale |
|---|---|---|---|
| [Codex CLI](https://github.com/openai/codex/tree/main/codex-rs/codex-client) | Provider-neutral `RetryPolicy`, `RetryOn`, backoff, and request telemetry above the HTTP client | Adopt | A policy value should select retry behaviour without coupling the retry runner to one SDK |
| Codex Cloud | Internal retry implementation is not public | N/A | Do not infer a closed implementation from product behaviour |
| [OpenClaw](https://github.com/openclaw/openclaw/blob/main/docs/concepts/models.md) | Configured fallback and explicit user selection have different fallback strictness | Adapt | Preserve GEODE's operator-visible interactive terminal path and independently configured auxiliary fallback |
| [autoresearch](https://github.com/karpathy/autoresearch) | Fixed constraints and monotone verification | Adopt | Treat call count, delay, billing, stream replay, hook order, and model selection as frozen scorecard entries |

The convergent pattern is not one universal retry loop. It is one error
classification and telemetry substrate with explicit immutable policies for
the intentionally different consumers.

## Design contract

1. `RetryPolicy` is provider-neutral and immutable. It declares category
   actions, delay calculation, whether exhausted retryable errors may advance
   to another model, whether the final failed attempt sleeps, and whether one
   OAuth refresh is permitted.
2. `classify_retry_error()` is the only retry-category projection. It reuses
   `classify_llm_error()`, billing/request-fatal checks, connection cause-chain
   detection, and the existing generic 401 compatibility rule.
3. `RetryAttempt` is the shared bounded telemetry record. Interactive and
   auxiliary hooks retain their existing fields and add policy/category
   provenance without changing hook order.
4. `run_with_retry_policy()` owns the auxiliary attempt/model loops only.
   The interactive loop retains context recovery, checkpoints, UI, and
   termination assembly, but derives classification, action, delay, and retry
   telemetry from the same policy types.
5. The provider compatibility wrapper preserves its public signature and
   callback payload. Unknown exceptions remain terminal there; unknown errors
   retain next-model behaviour only in the historical model-failover path.
6. A successful callable result is distinct from exhaustion even when the
   result value is `None`.

## Frozen behaviour matrix

| Invariant | Interactive | Auxiliary model chain | Provider compatibility |
|---|---|---|---|
| Model fallback | Never | Only through the supplied ordered list | Only after retryable exhaustion and configured fallback list |
| Rate limit | Terminal operator handoff | Retry with jitter | Retry with jitter unless billing-fatal |
| Auth | Terminal | Terminal | One managed OAuth refresh on first attempt, otherwise terminal |
| Unknown error | Existing main-loop retry | Advance to next model | Raise immediately |
| Final failed-attempt sleep | Existing main-loop delay | No | Yes, preserving the legacy wrapper |
| Stream after visible output | N/A | N/A | `StreamInterruptedError`, no replay |
| Exhaustion | Structured operator result | `(None, None)` | Re-raise last retryable error |

## Verification

- Characterize policy validation, actions, delays, success/exhaustion, OAuth,
  billing, request-fatal, allowlist, model traversal, callback, and hook
  payloads.
- Preserve existing failover, billing, routing-policy, stream-replay, profile,
  candidate-sampling, reflection, self-improving, and AgenticLoop retry tests.
- Run repository static gates, package/install checks, generated-doc checks,
  and the full non-live suite before PR creation.
- Live provider calls are not required because R5.4 changes policy selection,
  not provider wire payloads; all provider exceptions are represented with
  deterministic fixtures.

## Non-goals

- No provider-profile, credential-route, transport, or adapter-registry change.
- No automatic cross-provider fallback or change to strict route selection.
- No context-recovery, checkpoint, hook-order, or stream replay redesign.
- No R6 protocol/trust work and no R8.3 evidence changes.
