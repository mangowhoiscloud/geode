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
| OpenAI Responses in [`_openai_common.py`](../../core/llm/adapters/_openai_common.py) | `input_tokens` / `output_tokens` | `input_tokens_details.cached_tokens` / `input_tokens_details.cache_write_tokens` | `UsageSummary` |
| Anthropic in [`_anthropic_common.py`](../../core/llm/adapters/_anthropic_common.py) | `input_tokens` / `output_tokens` | `cache_read_input_tokens` / `cache_creation_input_tokens` | `UsageSummary` |
| [`UsageSummary`](../../core/llm/adapters/base.py) | `input_tokens` / `output_tokens` | `cached_input_tokens` / `cache_write_tokens` | Adapter translation and durable call events; each counter has a presence flag |
| [`ResponseUsage`](../../core/llm/agentic_response.py), then [`LLMUsage`](../../core/llm/token_tracker.py) | `input_tokens` / `output_tokens` | `cache_read_tokens` / `cache_creation_tokens` | Loop, accumulator, final result, UI |
| [`UsageRecord`](../../core/llm/usage_store.py) | `in` / `out` | `cache_r` / `cache_w` | Legacy monthly JSONL and usage history |
| [`tokens` IPC event](../../core/ui/agentic_ui/render.py) | `input` / `output` | `cache_read_tokens` / `cache_write_tokens` | Classic and fullscreen clients |
| [Harbor durable call projection](../../evals/platforms/harbor.py) | `n_input_tokens` / `n_output_tokens` | `n_cache_tokens` (reads only) | Native `AgentContext`; ATIF `total_cached_tokens` |

The provider's input convention is retained; identical field names do not
establish identical denominators. Reasoning is an output breakdown, not an
additional charge. Harbor's cache metric is reads, never reads plus writes.

## Zero, missing, and coverage

- `UsageSummary` presence flags distinguish an explicit provider zero from
  omitted input/output/cache/reasoning detail. Activity schema version 6
  preserves these unknowns in durable `llm.call.ended` payloads. Earlier
  input/output/reasoning zeros do not establish provider-reported presence.
- Activity schema version 7 adds call `purpose`, credential `source`, and
  requested `effort`. Missing legacy fields remain null. Request effort is not
  proof of the provider's internal compute. Root configuration does not label
  auxiliary calls: reflection keeps its existing `medium` request default.
- A completed Codex response rejected for empty visible output retains its
  known usage on that failed attempt. An identical retry gets another attempt
  ID and is counted separately, not substituted for the failed consumption.
  Interrupted streams without final usage remain unknown. This does not repair
  the legacy tracker's accounting for failed attempts.
- `ResponseUsage`, `LLMUsage` and the legacy JSONL still default or omit zero
  cache fields. They do not preserve field-level absence end to end.
- Harbor joins durable starts/ends by attempt ID within the exact session.
  Complete pairing and reported fields are required for its scoped totals;
  incomplete or missing fields remain null. `*_observed_sum` is partial
  evidence, not a fabricated final total.
- `observation_status=degraded` records known sink failure or observed LLM
  mapping anomalies, including loss of both members of a typed pair. Scoped
  totals then stay null even if the remaining pairs match. `no_known_faults`
  is not proof against hard process death, retention loss or unobserved calls.
- The Harbor scope is `recorded-runtime-llm-attempts-only`, explicitly
  `whole_runtime_complete=false`. Turn-final verification/reflexion calls
  already use the loop accounting seam and must not be added a second time.
  Cognitive reflection and candidate selection use the shared adapter-terminal
  observation path; parsing a declined or malformed response does not erase
  its usage. Native text/compaction, learning extraction and hosted search
  pass their event bus explicitly to the same observation helper. Capability
  calls without an exposed request effort keep that field unknown; it is not
  inferred from the root's setting. Earlier `recorded-agentic-loop-attempts-only` exports retain their
  original scope. Pairing describes retained events, not all dispatched
  calls: a lost start/end pair can evade that check. Final-result cost and
  durable token totals have different coverage and are not a reconciled invoice.
- Full-runtime coverage additionally requires the native producer inventory
  and background-writer shutdown checks. Wiring one callback does not prove
  its worker received the event bus or finished before the source snapshot.
  IPC fast-chat and external capability consumers without an event bus remain
  outside this native Harbor measurement scope.
- Each new canonical `session.ended` carries its own
  `runtime_observation_status`. Known child-sink failure or a missing child
  event bus makes the combined trajectory scope incomplete, even when the
  parent's retained LLM pairs match. Earlier absent status remains unknown;
  task success and observer health are separate facts.
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

The OpenAI guide's usage paths were rechecked on 2026-09-14. For its inclusive
input convention, aggregate cached-input coverage is `sum(cached_input_tokens)
/ sum(input_tokens)` over the same observed calls. A missing cache counter
excludes a call from complete-case cache ratios; it does not contribute zero.
State that population and its missing-call count next to any comparison.

New auxiliary observation rows keep cost unknown unless the adapter reports
it. Main-loop estimated costs retain the existing injected pricing behavior;
neither field is a reconciled subscription invoice. Do not sum unlike scopes
or infer a zero cost from an absent auxiliary estimate.

Learning, compaction, context-exhausted notices, model-switch summaries and
dreaming share `purpose=text_completion`. Their usage is retained, but this
field alone cannot separate their live cost or establish which helper ran.

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

Harbor's existing `usage` object also carries `recorded_attempts`: numeric
projections of retained canonical `llm.call.ended` events. Each row binds the
session/call/attempt IDs, source event ID and payload hash to the reported
counters. `occurred_at` uses Unix seconds in UTC; model/provider/adapter,
purpose/source/requested effort and error class are bounded metadata.
Missing values remain null, duplicate
terminals remain visible, and missing terminal events are not synthesized.
This list excludes prompts, tool content, responses and provider reasoning.
It is not another raw store or a whole-runtime billing ledger; publication
still requires exact-byte privacy review. Consumers can show recorded cache
values and their source without reopening the original session database.

An observed attempt is an invocation of the adapter completion method, not
necessarily one wire request: internal SDK or provider retries can remain
inside that invocation. Middleware short-circuits are not provider usage.
Neither source labels nor complete start/end pairing prove an invoice or
exhaustive whole-runtime coverage.

The canonical session JSON can retain `tool.called`/`tool.completed` timestamps
even when an ATIF or public Replay projection omits duration fields. Join by
session, turn and call ID, bind source hashes and event ordinals, and validate
timestamp offsets before deriving lifecycle elapsed. Overlapping intervals
need a separate union, not a summed wall-time claim. These intervals include
handler/wait/overhead; they cannot isolate CPU time or provider latency.

A fresh execution of a missing historical trace is a new run/attempt, not a
reconstruction of the original behavior. Keep historical absence and selected
reward unchanged; link the fresh trace through existing evidence references
and label it supplementary reexecution in Replay.

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
