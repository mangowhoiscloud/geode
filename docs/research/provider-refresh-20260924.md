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
live provider acceptance are separate evidence. The September 24 inventory
was source-only; subsequent live attempts have their own frozen source and
result records. Published limits are not proof that a particular account
admits that model.

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

## Effort exposure: frontier review on 2026-09-25

The comparison concerns choice construction and state changes, not model quality
or account entitlement. Codex source is pinned to the September 24 cutoff;
Claude Code documentation and the newer Hermes source were retrieved September 25.

| Harness | Primary evidence | GEODE decision |
|---|---|---|
| Codex | [Model-owned supported levels and separate defaults](https://github.com/openai/codex/blob/549455f3ec5a7f2a0489894543a0e49f307142a6/codex-rs/protocol/src/openai_models.rs#L942) feed the [reasoning picker](https://github.com/openai/codex/blob/549455f3ec5a7f2a0489894543a0e49f307142a6/codex-rs/tui/src/chatwidget/model_popups.rs#L476). Saved state does not create another advertised option. | Reuse the existing model specs for choices. Keep defaults separate from explicitly saved values. Do not copy Ultra/Persistent execution-mode aliases into native effort. |
| Claude Code | The [official model settings](https://code.claude.com/docs/en/model-config#adjust-effort-level) describe model-specific sliders and limits, plus automatic adjustment of unsupported levels. | Adopt bounded choices; reject automatic remapping because GEODE preserves explicit selections. Product UI choices do not establish third-party subscription eligibility. |
| Hermes | The [pinned menu](https://github.com/NousResearch/hermes-agent/blob/085d9ee608893bb0611c2fc339c19d8848af9f2b/hermes_cli/main_provider_setup.py#L571) uses model-specific efforts for Copilot but often exposes a global ladder elsewhere. Its [metadata parser](https://github.com/NousResearch/hermes-agent/blob/085d9ee608893bb0611c2fc339c19d8848af9f2b/hermes_cli/models_reasoning_caps.py#L39) distinguishes unknown capabilities from explicit non-support. | Do not copy the global ladder or infer support from missing metadata. Preserve the existing fixed/unknown-route boundary. |

GEODE already shares native effort specs between request shaping and the picker.
The remaining UI gap was rendering an incompatible saved value as the current
effort and returning it on Enter before application rejected it. The picker now
shows only supported choices; a stale selection requires an explicit arrow choice
before Enter or Space can confirm it. Cancellation preserves configuration, valid
existing choices remain unchanged, and roles without an effort control do not
offer one. Existing application and adapter validation remain necessary for
configuration, IPC and other inputs that bypass the picker.

Reflection inherits primary effort rather than exposing a separate control.
Staged role picks must be checked against their final combined candidate before
any model setting is saved; checking the current primary value while applying
each row can reject a valid batch or leave incompatible settings after a later
admission failure.

A client catalog's omission is not by itself proof that the native backend rejects
a value. API, subscription and relay capability differences require their own
evidence; no new support claim or remote catalog service follows from this review.

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
