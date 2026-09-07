---
title: Usage and cache accounting contract
status: living
authority: runtime-usage-contract
---

# Usage and cache accounting

This contract maps existing producers and readers. It does not create another
billing store or retroactively repair published benchmark evidence.

## Field and authority map

| Producer / owner | Input / output | Cache read / write | Reader |
|---|---|---|---|
| OpenAI Responses in [`_openai_common.py`](../../core/llm/adapters/_openai_common.py) | `input_tokens` / `output_tokens` | `input_tokens_details.cached_tokens` / `cache_write_tokens` | `UsageSummary` |
| Anthropic in [`_anthropic_common.py`](../../core/llm/adapters/_anthropic_common.py) | `input_tokens` / `output_tokens` | `cache_read_input_tokens` / `cache_creation_input_tokens` | `UsageSummary` |
| [`UsageSummary`](../../core/llm/adapters/base.py) | `input_tokens` / `output_tokens` | `cached_input_tokens` / `cache_write_tokens`, each with a presence flag | Adapter translation and durable call events |
| [`ResponseUsage`](../../core/llm/agentic_response.py), then [`LLMUsage`](../../core/llm/token_tracker.py) | `input_tokens` / `output_tokens` | `cache_read_tokens` / `cache_creation_tokens` | Loop, accumulator, final result, UI |
| [`UsageRecord`](../../core/llm/usage_store.py) | `in` / `out` | `cache_r` / `cache_w` | Legacy monthly JSONL and usage history |
| [`tokens` IPC event](../../core/ui/agentic_ui/render.py) | `input` / `output` | `cache_read_tokens` / `cache_write_tokens` | Classic and fullscreen clients |
| [Harbor durable call projection](../../evals/platforms/harbor.py) | `n_input_tokens` / `n_output_tokens` | `n_cache_tokens` (reads only) | Native `AgentContext`; ATIF `total_cached_tokens` |

The provider's input convention is retained; identical field names do not
establish identical denominators. Reasoning is an output breakdown, not an
additional charge. Harbor's cache metric is reads, never reads plus writes.

## Zero, missing, and coverage

- `UsageSummary` presence flags distinguish an explicit provider zero from
  omitted cache detail. Durable `llm.call.ended` payloads preserve unknowns.
- `ResponseUsage`, `LLMUsage` and the legacy JSONL still default or omit zero
  cache fields. They do not preserve field-level absence end to end.
- Harbor joins durable starts/ends by attempt ID within the exact session.
  Complete pairing and reported fields are required for its scoped totals;
  incomplete or missing fields remain null. `*_observed_sum` is partial
  evidence, not a fabricated final total.
- The Harbor scope is `recorded-agentic-loop-attempts-only`, explicitly
  `whole_runtime_complete=false`: reflection, judging, hosted search and text
  calls are not fully covered. Even complete attempt pairing does not remove
  this limitation. Final-result cost and durable token totals have different
  coverage and must not be treated as a reconciled invoice.
- Cancellation does not itself decide evaluation validity. A canonical
  verifier-scored timeout may be a valid failed task; host-budget or auth
  interruption may be invalid. Apply the frozen suite rule.

## Cost and ratios

[`ModelPrice`](../../core/llm/pricing_loader.py) stores per-token rates and
`cache_inclusive_input`. For inclusive input, subtract reads and writes from
ordinary input before charging each separately. Subtract only categories
whose configured rate is nonzero; an absent rate retains the existing
full-input-rate fallback. For disjoint input, retain ordinary input and add
cache categories without subtraction.

`TokenTracker.record()` preserves finite nonnegative `reported_cost_usd`,
including zero; otherwise it estimates from model prices. Its legacy output
does not retain the price revision or which cost source won. API-price
estimates are not subscription invoices. `UsageRecord.source` identifies a
producer, not the account's billing route.

The legacy `cache_hit_rate` is `read / (read + creation)`: a share of reported
cache activity, not prompt coverage. A read-only provider can yield 1.0 with
only a small cached prompt fraction. UI output therefore shows raw read/write
counts; a derived coverage ratio must name its provider-specific denominator.

Primary semantics checked 2026-09-08:
[OpenAI prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching/)
describes inclusive input; [Anthropic prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)
describes disjoint ordinary/read/creation counts. These sources do not prove
account entitlement or any universal model price.

## Existing data contracts and publication

Use the typed owners above and the existing
[evaluation data model](../eval/data-model.md),
[trajectory schema](../../core/observability/schemas/trajectory.schema.json),
[attempt schema](../eval/schemas/attempt.schema.json), and
[analysis schema](../eval/schemas/analysis.schema.json). Monthly usage JSONL is
legacy unversioned data; it lacks call IDs and stored price provenance. Do not
invent a schema ID or claim a call-level join from timestamps alone.

For retrospective accounting, bind selected original rows, source prefixes,
result bytes, producer revision and exact session IDs by digest. Separate
`petri_eval` aggregates from runtime calls. Require matching input and output
totals before claiming final historical reconciliation. Preserve missing
joins; accounting coverage is not the paired score denominator.

Supplementary accounting uses existing attempt `other` evidence. It never
replaces a frozen primary metric, raw result, verifier, or immutable
trajectory. Raw usage remains private until exact-byte review under the
[publication contract](../eval/external-artifact-repository.md).

## Verification and limits

Run the changed boundary's existing tests: `test_cache_cost_accounting.py`,
`test_cache_hit_rate.py`, `test_agentic_loop.py -k track_usage`,
`test_agentic_ui.py`, `test_fullscreen_app.py`, `test_fast_chat.py`,
`test_cost_command.py`, and `test_harbor_geode_agent.py`. Provider presence,
positive/zero/unknown counts, per-turn reset, and primary-error preservation
must remain distinct cases. Deterministic checks require no live request.

Remaining scope limits: opt-in fast-chat forwards counters but does not
record tracker/ledger usage and emits a zero cost placeholder (not free
execution); monthly/daily/history rollups do not show cache totals. These
legacy views and incomplete whole-runtime accounting must not be advertised
as complete billing or benchmark coverage.
