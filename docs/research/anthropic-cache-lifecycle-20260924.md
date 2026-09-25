# Anthropic cache lifecycle audit — 2026-09-24

The audit found three defects at integration anchor `31ef2f778`: rolling markers
could target opaque thinking blocks, unbounded request options or pre-existing
markers could exceed the request limit, and one-hour writes were priced as
five-minute writes. These are request/accounting defects, not SDK connection
lifetime defects.

The offline reproduction used the actual Anthropic SDK and HTTPX MockTransport.
Its captured request contained a marker on `thinking` and `redacted_thinking`;
request option 4 yielded five total markers, while two pre-existing markers
plus the default yielded six. The original replay blocks were unchanged.
A parsed Opus 5.5 response with 1,000 one-hour write tokens produced a $0.005
estimate instead of the standard $0.008. No live model request established
these results.

## Corrected ownership

- `providers/anthropic.py` validates marker targets, available slots and TTL
  order. Existing markers and opaque replay remain unchanged; automatic
  additions use five minutes only after any explicit one-hour marker.
- `_anthropic_common.py` shapes the static prefix and validates the final
  request. The original static/dynamic boundary remains useful: dynamic edits
  preserve the earlier static prefix, while later message prefixes change.
- The adapter retains optional `UsageSummary.cache_write_1h_tokens` alongside
  total writes. Loop/tracker `cache_creation_1h_tokens`, monthly JSONL
  `cache_w_1h`, durable activity schema 11 and Harbor attempt metadata preserve
  that subset. The total is not increased by adding the subset again.
- The existing pricing owner adds the known one-hour premium. Missing legacy
  splits remain null with the prior five-minute estimate. A local estimate
  never becomes `reported_cost_usd`; provider-reported charge keeps priority.
  Harbor's native cache count remains reads only.

Cache selection is read at request construction. Cache policy changes, prompt
rebuilds and client invalidation do not prove cache retention or eviction:
provider prefixes have their own lifetime. A stable prompt is necessary but
not sufficient evidence of a cache hit; usage counters are the observation.
The conservative raw-block spacing heuristic remains a heuristic, not a
promise about the provider's current lookup implementation.

## Primary contract checked

[Anthropic prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)
documents cumulative tools → system → messages prefixes, four markers,
ineligible thinking blocks, one-hour-before-five-minute ordering, separate
TTL usage and token-based prices without a per-marker fee. The installed
Anthropic SDK `ContentBlockParam` types identify eligible marker targets.
Frequent hits refresh five-minute TTL without another write; a longer TTL
serves longer gaps, not a guaranteed per-turn saving.

[Z.AI context caching](https://docs.z.ai/guides/capabilities/cache) uses automatic
caching and `usage.prompt_tokens_details.cached_tokens`. An offline actual-SDK
completion and SSE fixture retained 800 cached tokens out of 1,200 prompt
tokens with cache-write absence still unknown. No GLM cache code change was
required by this audit; the fixture does not establish live hits or retention.

Regression evidence is
[`test_anthropic_cache_lifecycle.py`](../../tests/core/llm/adapters/test_anthropic_cache_lifecycle.py):
SDK request serialization, unknown/zero/mixed TTL response → runtime cost →
reopened SQLite and monthly records → Harbor, and pre-dispatch rejection of
invalid markers. Existing cache and provider checks remain in their owners.
Live E2E and Harbor acceptance are separate, after integration; this note does
not claim them or a subscription invoice.
