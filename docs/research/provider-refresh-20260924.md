# Provider catalogue audit — 2026-09-24

Scope: GEODE agent-model prices, context limits and source-aware current
choices. Requests, account entitlement, adapter features and paid acceptance
remain separate contracts. No live inference or credential inspection ran.

## Source inventories

- [OpenAI model/price/API/Codex inventory](provider-refresh-20260924-openai.md)
- [Z.AI model/price/Coding Plan inventory](provider-refresh-20260924-zhipu.md)
- [Claude current models](https://platform.claude.com/docs/en/models/overview)
- [Claude pricing](https://platform.claude.com/docs/en/about-claude/pricing)
- [Claude lifecycle](https://platform.claude.com/docs/en/about-claude/model-deprecations)

All primary pages were retrieved on 2026-09-24. Current Claude additions:

| Model | Context | Output | Input / cached / output USD per million |
|---|---:|---:|---|
| claude-fable-5-1 | 1,000,000 | 128,000 | 10 / 0.25 / 50 |
| claude-opus-5-5 | 1,000,000 | 128,000 | 4 / 0.20 / 20 |
| claude-opus-5 | 1,000,000 | 128,000 | 5 / 0.50 / 25 |
| claude-sonnet-5 | 1,000,000 | 128,000 | 2 / 0.20 / 10 |

Older active models retain their own entries. GLM-5.1, GLM-5 and the GLM-4.7
family use the published 200,000-token context limit; the former 202,752 value
had no current first-party basis. See the [GLM-5.1](https://docs.z.ai/guides/llm/glm-5.1),
[GLM-5](https://docs.z.ai/guides/llm/glm-5) and
[GLM-4.7](https://docs.z.ai/guides/llm/glm-4.7) specifications. A new model is not grounds to
claim an older API retired. Source-specific retirement and account admission
are independent; stored configured model IDs are never automatically remapped.

## Ownership and accounting

`model_catalog.MODEL_OFFERINGS` owns documented active provider/source rows.
`model_pricing.toml` owns current standard API rates and context limits.
`PricingCatalogue` validates rates and keeps GLM provider identity separate
from its OpenAI-compatible protocol. The existing `TokenTracker` consumes
these data; no new billing store or registry is added.

Anthropic input is disjoint from cached reads/writes; OpenAI and GLM input
includes cached categories. Explicit Claude cache rates supersede the generic
10% default where required. OpenAI GPT-6/GPT-5.6/GPT-5.5/GPT-5.4 input above
272,000 tokens selects the full-request long-context tariff, including cached
input: 2x input/cache and 1.5x output. Exactly 272,000 remains standard.
GPT-5.6 Sol's promotional rate must be rechecked after the documented period,
at least through 2026-11-21.

These are estimates, not subscription invoices. The legacy tracker does not
retain Anthropic cache-write TTL splits, service tier, region or tool fees;
its Anthropic write estimate is the 5-minute rate. Provider-reported cost still
wins when present. Old records and published evaluation bytes are unchanged.

## Integration boundary

The catalogue precedes separate adapter, UI/default and public-guide PRs.
A metadata entry does not itself enable a route or mutate operator settings.
The source-reason helper identifies Claude third-party subscription OAuth as
unsupported and GLM Coding Plan admission for GEODE as unestablished under
its current supported-tools policy. Enforcement at all adapter and selection
entry points is reviewed in the corresponding provider PRs.

Checks target context consumers, distinct provider input denominators,
explicit cache overrides, the strict long-context boundary, invalid price
rejection and source-specific lifecycle. These local checks do not establish
remote CI, paid API acceptance or publication.
