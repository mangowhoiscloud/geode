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
  proof of the provider's internal compute. New reflection, candidate and
  worker calls inherit the owning loop's effort; explicit worker overrides
  remain distinct. Wrap-up retains that effort rather than forcing `low`.
  Earlier reflection `medium` defaults remain part of their original evidence.
  Explicit worker overrides are retained by the existing collaboration record
  across queued and idle continuation. Legacy records have no recovered effort;
  like new workers without an override, they inherit their current caller's effort.
- Activity schema version 8 labels turn-final LLM judge and Reflexion calls
  `purpose=turn_verification`. They still use the existing loop accounting
  seam; do not count them twice. Version 7 could label these calls
  `agentic_loop`, so that label alone cannot split historical action and
  verification consumption. `candidate_judge` remains candidate selection,
  not turn-final verification.
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
  calls on supported OpenAI reasoning models now carry the inherited effort
  through the actual request and observation helper. Other capability backends
  retain their existing policies and unknown effort; no cross-provider effort
  equivalence is claimed. The direct Responses request path retains its
  model-switch clamp; for example, an unsupported `max` on GPT-5.5 can become
  `xhigh`. Its recorded requested effort is not wire-effort proof. Uniform
  studies must pin a compatible model (here `gpt-5.6-sol`), reject model drift,
  and retain request-level regression evidence. Earlier
  `recorded-agentic-loop-attempts-only` exports retain their
  original scope. Pairing describes retained events, not all dispatched
  calls: a lost start/end pair can evade that check. Final-result cost and
  durable token totals have different coverage and are not a reconciled invoice.
- Full-runtime coverage additionally requires the native producer inventory
  and background-writer shutdown checks. Wiring one callback does not prove
  its worker received the event bus or finished before the source snapshot.
  External capability consumers without an event bus remain outside this native
  Harbor measurement scope. IPC prompts now use the regular loop; the retired
  fast-chat bypass does not establish coverage for earlier runs.
- Each new canonical `session.ended` carries its own
  `runtime_observation_status`. Known child-sink failure or a missing child
  event bus makes the combined trajectory scope incomplete, even when the
  parent's retained LLM pairs match. Earlier absent status remains unknown;
  task success and observer health are separate facts.
- Canonical `session.ended` metrics not supplied by its caller remain null,
  not zero. Explicit zero and measured values retain their meaning. The
  terminal transition alone cannot establish duration, rounds, tokens or cost;
  these optional summaries do not replace durable per-call accounting or
  establish whole-runtime totals. Earlier terminal zeros are not retroactively
  reclassified. Legacy seed-generation/hub rollups still coerce missing summary
  values to zero and must not be treated as complete accounting.
- Native exports also reconcile known child handles and structured parent
  subagent events against canonical session inventory. A completed child with
  no surviving rows is missing evidence, not a zero-call session; it prevents
  a complete source snapshot even when the root's records look healthy.
- Cancellation does not itself decide evaluation validity. A canonical
  verifier-scored timeout may be a valid failed task; host-budget or auth
  interruption may be invalid. Apply the frozen suite rule.
- Turn verification persists the bounded error codes `judge_timeout` and
  `verification_time_budget_exhausted` on `turn.verify.failed`. Other
  verification infrastructure errors keep `verification_error`; judge prose
  is not copied into the durable error class. Unavailable verification remains
  a delivery hold with no automatic retry. Native Harbor exports retain
  `external_verification_required` and exit 1 without replacing that hold
  with a synthetic `RuntimeError`. This does not turn it into a success or a
  canonical Harbor timeout, and it does not recover cancelled provider usage.

## Cost and ratios

[`ModelPrice`](../../core/llm/pricing_loader.py) stores per-token rates and
`cache_inclusive_input`. For inclusive input, subtract reads and writes from
ordinary input before charging each separately. Subtract only categories
whose tariff is known, including an explicit zero; an absent rate retains the
existing full-input-rate fallback. Presence flags distinguish these states,
while positive rates constructed by legacy callers remain supported. For disjoint input, retain ordinary input and add
cache categories without subtraction.

The price catalogue owns exact model aliases and validates finite nonnegative
rates and positive integer context limits. Above a documented long-context
threshold, the entire request uses its input/cache and output multipliers;
the exact threshold remains in the standard tier. These are current standard
API estimates. Cache-write TTL splits, service tiers, regions and tool fees
are not retained by the legacy tracker. The 2026-09-24 model and source audit
lives in [the provider inventory](../research/provider-refresh-20260924.md).

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

Cognitive reflection now opts into the existing `TokenTracker` at the actual
adapter terminal. Completed usage reaches the root cost guard and terminal
tracker totals once, even when the model declines the reflection tool or its
payload is malformed. A completed response attached to `EmptyModelOutputError`
also retains its consumption. Middleware short-circuits and interrupted calls
without completed usage do not create tracker charges. Explicit provider zero
is distinct from wholly missing usage. Without a reported charge, the tracker
still estimates cost from its model catalog, while durable observation cost remains
provider-reported only; neither is an invoice or whole-runtime reconciliation.
Existing action-loop and final-judge tracking does not opt into this second
path and must not be counted twice. Historical tracker omissions are not repaired.

Activity schema version 9 identifies native text producers through the existing
`purpose` field: `learning_extraction`, `context_compaction` (also used by the
shared model-switch summarizer), `context_exhaustion`, and `memory_dreaming`.
The labels do not change provider requests or recover earlier attribution.
Legacy and unidentified callers retain `text_completion`; that category alone
cannot establish which helper ran. A producer label proves only a retained
attempt, not complete coverage or provider billing.

Activity schema version 10 adds `structured_decision` for nested classification
and extraction calls. The caller passes its event bus and session, turn and
tool-call correlation to `observe_llm_call`; `HookPersistenceSink` retains the
terminal purpose and usage before caller-side semantic validation. Explicit
zero, positive and missing counters remain distinct; an interrupted call without
a completed response retains unknown usage. Harbor's recorded-attempt projection
and observation validator preserve the same purpose. This label does not add a
legacy tracker charge or establish root execution or native-verifier success.

The opt-in [Jev handoff diagnostic](../eval/typesafe-decision-handoff.md#provider-observability-and-billing-reconciliation)
uses the existing response ID for provider correlation and an explicitly sourced
input-only tariff in USD and US cents. Output tokens remain observed usage even
when their rate is zero. Derived tariff value, account-credit consumption and
actual cash billing are separate authorities; missing provider charge stays null.

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
`test_agentic_ui.py`, `test_fullscreen_app.py`, `test_prompt_accounting.py`,
`test_cost_command.py`, and `test_harbor_geode_agent.py`. Provider presence,
positive/zero/unknown counts, per-turn reset, and primary-error preservation
must remain distinct cases. Deterministic checks require no live request.

Remaining scope limits: monthly/daily/history rollups do not show cache totals. These
legacy views and incomplete whole-runtime accounting must not be advertised
as complete billing or benchmark coverage.

## Retired IPC fast-chat bypass

`GEODE_FAST_CHAT` is no longer read. Short conversational prompts use the same
`AgenticLoop.arun()` path as other IPC prompts, with the configured identity,
conversation, tools and verification. This can increase latency and token use
relative to the removed compact text-only prompt; it is not a free-call mode.
The private router, separate prompt and `fast_chat_start` UI event are removed.
The IPC envelope version is unchanged: clients already ignore unknown events.

The omission began in [#2558](https://github.com/mangowhoiscloud/geode/pull/2558):
the early return preceded the loop's conversation, lifecycle and tracker
updates, and emitted UI tokens with literal `cost=0`. Making the route opt-in
did not repair it. [#3311](https://github.com/mangowhoiscloud/geode/pull/3311)
added cache counters to that UI event, but not durable accounting. The later
shared adapter observer also needed an event bus and correlation; this caller
passed neither. Tests replaced the whole dispatcher and checked visible
counters, so they could not detect the missing records.

The replacement regression enters through the IPC prompt handler and the real
loop, faking only provider completion. It checks retained conversation, durable
call identity and cache presence, tracker cost and UI counters even when the
retired environment variable is set. UI output alone is not accounting proof.
This fixes the future IPC path, not missing historical usage or legacy rollups.

### Research grounding (2026-09-20)

The pinned [Codex Responses parser](https://github.com/openai/codex/blob/dad1db87bb5ad4b92af6b0f58502d12453681f81/codex-rs/codex-api/src/sse/responses.rs)
passes completed usage to the [turn consumer](https://github.com/openai/codex/blob/dad1db87bb5ad4b92af6b0f58502d12453681f81/codex-rs/core/src/session/turn.rs)
and [session accumulator](https://github.com/openai/codex/blob/dad1db87bb5ad4b92af6b0f58502d12453681f81/codex-rs/core/src/session/mod.rs).
Borrow that shared ownership, not its field-defaulting behavior: this pin can
default absent cache detail to zero. GEODE retains its stricter presence flags.
This is a pinned implementation comparison, not a current Codex-wide audit.

The provider caching contracts above were rechecked: OpenAI input includes
cached categories; Anthropic ordinary input excludes them. Their totals need
different formulas. OpenAI's [Chat Completions streaming contract](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)
also warns that interruption can lose the final usage chunk. That is not proof
of zero consumption, nor a statement that every Responses or Anthropic stream
has the same event layout.

Keep the existing adapter-terminal observer as the common call seam, with
session/attempt identity and the caller's event bus. Preserve known usage on a
failed result and unknown usage on interruption; never let an observer failure
mask the original error. Test changed entry paths through the durable consumer,
not only the common helper or UI. Do not double-count calls already recorded
by the loop or infer whole-runtime coverage from paired retained events.
