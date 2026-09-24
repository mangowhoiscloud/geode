# Provider contracts checked on 2026-09-24

This audit covers GEODE's general-purpose agent models, API/subscription
routes, request controls, replay, token accounting and public configuration
guidance. Specialized audio/image generation, managed-agent products and
restricted research models are not interchangeable agent-loop backends.
The provider-specific inventories list the opened primary sources, current
and legacy models, limits, pricing, lifecycle and upstream comparisons:

- [OpenAI API and Codex](provider-refresh-20260924-openai.md)
- [Claude API and subscription boundary](provider-refresh-20260924-claude.md)
- [Z.AI API and Coding Plan](provider-refresh-20260924-zhipu.md)

Public documentation, deterministic request tests, account entitlement and
live provider acceptance are separate evidence. This refresh has no paid
inference or account-access test. Published limits are not proof that a
particular account admits that model.

## Runtime ownership

| Responsibility | Owner | Consumer and effect |
|---|---|---|
| Active model offerings | `core/llm/model_catalog.py::MODEL_OFFERINGS` | Picker, adapter diagnostics and login routing share provider/source rows |
| API prices and context limits | `core/llm/model_pricing.toml` | Validated `PricingCatalogue` feeds `TokenTracker` and context guards |
| Provider model controls | `OpenAIModelSpec`, `AnthropicModelSpec`, `GlmModelSpec` | Request builders and effort selection use exact supported controls |
| Account and transport identity | `ProviderProfile`, `CredentialRoute`, `TransportSpec` | Existing adapter registry composes independent model/auth/protocol contracts |
| Retired or unavailable source | `model_source_unavailable_reason` | Selection and dispatch reject the exact route with an explicit remedy |
| Actual usage | Existing adapter response translators | Preserve provider counters and missing-field flags before cost estimation |

These records serve different consumers; they are not another universal
provider framework. Wire-specific behavior remains with the adapter.
Equivalent JSON shape does not establish equivalent entitlement, replay,
capabilities or billing.

## Selection and lifecycle

New default choices are `claude-opus-5-5`, `gpt-6-sol` for Platform/Codex,
and `glm-5.3` for Z.AI PAYG. Explicit config/env/model selections retain
their precedence. Deprecated models leave new-choice lists, while still
active older models and explicit configured selections remain distinct.
Known retired routes fail locally; no model or billing-source substitution
is performed. Historical prices remain available for existing records.

Claude remains API-key only in GEODE. Anthropic's published subscription
OAuth restrictions do not admit a third-party harness. Z.AI Coding Plan
currently limits use to listed tools; GEODE admission is not established.
Its saved profiles remain readable, but direct subscription execution and
unsupported native search claims are disabled. PAYG must be selected
explicitly. Coding Plan now uses token credits; stale 80/240/600-call quotas
and model call weights no longer represent provider quota authority.

## Price semantics

Rates are USD per million tokens for standard synchronous API requests.
They are estimates, not ChatGPT/Coding Plan charges or invoices. OpenAI
inclusive input is split into ordinary input, cache reads and writes;
Anthropic reports these as disjoint categories. GLM now has its own price
section despite using the OpenAI-compatible protocol.

Fable 5.1 and Opus 5.5 require explicit cache-read rates instead of the
previous universal Anthropic 10% rule. GPT-6 and GPT-5.6 cache-write rates
are explicit. The published long-context threshold applies to the full
OpenAI request, including cached input: above 272,000 input tokens, input
and cache rates double and output rates multiply by 1.5 for the admitted
GPT-6/GPT-5.6/GPT-5.5/GPT-5.4 rows. Exactly 272,000 remains standard.
GPT-5.6 Sol's promotional standard price must be rechecked after the
provider's stated period (at least through 2026-11-21).

Anthropic's reported one-hour writes are retained as an optional subset of
total writes through the adapter, runtime accounting and persisted records.
The existing pricing owner applies the one-hour rate to that subset and the
five-minute rate to other writes, without counting the subset twice.
Historical records without a TTL split remain unknown and retain the prior
five-minute estimate; this does not establish their actual TTL or rewrite
their stored cost. See [usage accounting](../architecture/usage-accounting.md).

Service tiers, regional surcharges, batch discounts and tool fees remain
outside these estimates. Do not present the totals as an invoice or apply a
universal fast-mode multiplier. Provider-reported cost continues to take
precedence when available, including an explicit zero.

## Verification and integration

The [execution plan](../plans/2026-09-24-provider-storage-config-refresh.md)
separates pricing/catalogue, per-provider adapters, native computer actions,
selection/docs, persistence/config fixes and release preparation into
reviewable units. Narrow regressions cover tariff thresholds, exact-source
retirement, configured-selection preservation, supported efforts, output
limits, stream/non-stream parity and native history. Full CI and release
receipts are recorded only after they run on the corresponding revision.
