# OpenAI API and subscription contract — 2026-09-24

Retrieved on **2026-09-24** through the OpenAI Developers documentation connector.
The pages below were fetched, including each listed model page. This is public
contract evidence, not a live credential, entitlement, or backend acceptance test.
The scope is GEODE's text/image-input agent models and their API/subscription routes;
specialized audio, image-generation, research-access, and cybersecurity models are
not generic replacements for an agent-loop model.

## Models and limits

All rows accept text and image input and produce text. Limits count tokens; output
includes reasoning. `gpt-5.6` remains the documented alias for `gpt-5.6-sol` and is
not a second picker entry. Published model context is distinct from a particular
Codex client's configured context budget or the account's model availability.

| Model | Context | Maximum input | Maximum output | Documented reasoning efforts |
| --- | ---: | ---: | ---: | --- |
| [gpt-6-astra](https://developers.openai.com/api/docs/models/gpt-6-astra) | 1,050,000 | 922,000 | 128,000 | low, medium, high, xhigh, max |
| [gpt-6-sol](https://developers.openai.com/api/docs/models/gpt-6-sol) | 1,050,000 | 922,000 | 128,000 | none, low, medium, high, xhigh, max |
| [gpt-6-luna](https://developers.openai.com/api/docs/models/gpt-6-luna) | 1,050,000 | 922,000 | 128,000 | none, low, medium, high, xhigh, max |
| [gpt-5.6-sol](https://developers.openai.com/api/docs/models/gpt-5.6-sol) | 1,050,000 | 922,000 | 128,000 | none, low, medium, high, xhigh, max |
| [gpt-5.6-terra](https://developers.openai.com/api/docs/models/gpt-5.6-terra) | 1,050,000 | 922,000 | 128,000 | none, low, medium, high, xhigh, max |
| [gpt-5.6-luna](https://developers.openai.com/api/docs/models/gpt-5.6-luna) | 1,050,000 | 922,000 | 128,000 | none, low, medium, high, xhigh, max |
| [gpt-5.5](https://developers.openai.com/api/docs/models/gpt-5.5) | 1,050,000 | Not separately stated | 128,000 | none, low, medium, high, xhigh |
| [gpt-5.4](https://developers.openai.com/api/docs/models/gpt-5.4) | 1,050,000 | Not separately stated | 128,000 | none, low, medium, high, xhigh |
| [gpt-5.4-mini](https://developers.openai.com/api/docs/models/gpt-5.4-mini) | 400,000 | 272,000 | 128,000 | none, low, medium, high, xhigh |
| [gpt-5.4-nano](https://developers.openai.com/api/docs/models/gpt-5.4-nano) | 400,000 | 272,000 | 128,000 | none, low, medium, high, xhigh |
| [gpt-5.3-codex](https://developers.openai.com/api/docs/models/gpt-5.3-codex) | 400,000 | 272,000 | 128,000 | low, medium, high, xhigh |
| [gpt-5.2](https://developers.openai.com/api/docs/models/gpt-5.2) | 400,000 | Not separately stated | 128,000 | none, low, medium, high, xhigh |
| [gpt-5-mini](https://developers.openai.com/api/docs/models/gpt-5-mini) | 400,000 | 272,000 | 128,000 | minimal, low, medium, high |
| [gpt-5-nano](https://developers.openai.com/api/docs/models/gpt-5-nano) | 400,000 | 272,000 | 128,000 | minimal, low, medium, high |
| [o3](https://developers.openai.com/api/docs/models/o3) | 200,000 | Not separately stated | 100,000 | low, medium, high |
| [o4-mini](https://developers.openai.com/api/docs/models/o4-mini) | 200,000 | Not separately stated | 100,000 | low, medium, high |

GPT-5 mini/nano efforts are explicitly listed for the original GPT-5 family in
[GPT-5 guidance](https://developers.openai.com/api/docs/guides/latest-model?model=gpt-5).
Current GPT-6 supports Responses and Chat Completions, but Astra tool calling
requires Responses. Sol/Luna Chat Completions function calling requires effort
`none`; reasoning with tools requires Responses. With active reasoning, sampling
parameters are unsupported. **Ultra is a Codex subagent execution mode, not an API
reasoning effort.** See [GPT-6 migration](https://developers.openai.com/api/docs/guides/latest-model#gpt-6-astra-update-api-and-model-parameters)
and [Codex model controls](https://learn.chatgpt.com/docs/models).

## API pricing

USD per million tokens, Standard speed, short context, from the fetched
[API pricing table](https://developers.openai.com/api/docs/pricing). A dash means
no separate published write price for that model, not a guessed missing value.

| Model | Uncached input | Cached input | Cache writes | Output |
| --- | ---: | ---: | ---: | ---: |
| gpt-6-astra | 10 | 1 | 12.50 | 50 |
| gpt-6-sol | 2 | 0.20 | 2.50 | 10 |
| gpt-6-luna | 0.10 | 0.01 | 0.125 | 0.50 |
| gpt-5.6 / gpt-5.6-sol | 4 | 0.40 | 5 | 20 |
| gpt-5.6-terra | 2 | 0.20 | 2.50 | 12 |
| gpt-5.6-luna | 0.20 | 0.02 | 0.25 | 1.20 |
| gpt-5.5 | 5 | 0.50 | — | 30 |
| gpt-5.4 | 2.50 | 0.25 | — | 15 |
| gpt-5.4-mini | 0.75 | 0.075 | — | 4.50 |
| gpt-5.4-nano | 0.20 | 0.02 | — | 1.25 |
| gpt-5.3-codex | 1.75 | 0.175 | — | 14 |
| gpt-5.2 | 1.75 | 0.175 | — | 14 |
| gpt-5-mini | 0.25 | 0.025 | — | 2 |
| gpt-5-nano | 0.05 | 0.005 | — | 0.40 |
| o3 | 2 | 0.50 | — | 8 |
| o4-mini | 1.10 | 0.275 | — | 4.40 |

For GPT-6, GPT-5.6, GPT-5.5 and GPT-5.4, requests above **272,000 input
tokens** use the long-context tier for the entire request: 2x input/cache rates,
1.5x output. GPT-6 and GPT-5.6 Batch/Flex prices are 50% of Standard and Fast
prices are 2x Standard. Older models have model-specific Fast rates: GPT-5.5 is
2.5x, so a universal multiplier would be wrong. Regional processing adds 10%
where available. GPT-6 EU residency is Standard-only. Sol's $4/$20 promotional
rates are documented as available at least through 2026-11-21.

[Prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching)
documents inclusive input counts: ordinary input = `input_tokens` minus
`input_tokens_details.cached_tokens` minus
`input_tokens_details.cache_write_tokens`. GPT-5.6+ writes cost 1.25x input and
reads 0.1x. Automatic implicit caching is already the default. New optional
controls are `prompt_cache_options.mode`, `ttl: "30m"`, explicit content
breakpoints, and cache prewarming. None was silently applied to the subscription
backend. The existing GEODE cache-write normalization already preserves those
counters; refreshed rates make them bill correctly.

## Subscription boundary and lifecycle

[Authentication](https://learn.chatgpt.com/docs/auth) distinguishes ChatGPT sign-in
from API-key usage. ChatGPT sign-in follows workspace entitlement, RBAC, retention,
and residency; API-key requests follow the API organization and API pricing.
`codex login` is the current CLI sign-in command. Enterprise access tokens are a
documented option for trusted noninteractive Codex workflows; they are not
general Platform API keys or proof of direct third-party backend support.

Credits per million tokens at Standard speed, from
[Codex pricing](https://learn.chatgpt.com/docs/pricing#token-rates):

| Model | Input credits | Cached input credits | Output credits |
| --- | ---: | ---: | ---: |
| gpt-6-astra | 250 | 25 | 1,250 |
| gpt-6-sol | 50 | 5 | 250 |
| gpt-6-luna | 2.5 | 0.25 | 12.5 |
| gpt-5.6-sol | 100 | 10 | 500 |
| gpt-5.6-terra | 50 | 5 | 300 |
| gpt-5.6-luna | 5 | 0.5 | 30 |
| gpt-5.5 | 125 | 12.5 | 750 |

Codex credits have no separate cache-write charge. GPT-6 Fast mode costs 2.5x
Standard credits where available. These rates do not determine included plan
usage limits and must not be converted into a PAYG charge. Account dashboards
remain authoritative for remaining allowance.

| Surface | Lifecycle on the audit date | GEODE treatment |
| --- | --- | --- |
| Codex GPT-6 Astra/Sol/Luna | Current; availability depends on account/client rollout | Offer documented models; do not promise entitlement |
| Codex GPT-5.6 Sol/Terra/Luna | Remain available during rollout | Retain |
| Codex GPT-5.5 | Announced retirement on 2026-10-14 | Remove from new choices; do not claim already retired |
| Codex GPT-5.4 / GPT-5.4-mini | Retired on 2026-08-31 | Reject that subscription pair; keep Platform API distinction |
| Codex GPT-5.2 / GPT-5.3-Codex | Already deprecated | Exclude subscription; exact API contracts remain separate |
| API GPT-5 mini/nano and o3 snapshots | Deprecated; shutdown 2026-12-11 | Exclude new choices; retain historical accounting |
| API o4-mini | Deprecated; shutdown 2026-10-23 | Exclude new choices; do not claim already shut down |
| API computer-use-preview | Shut down 2026-07-23 | Keep GA computer shape; never revive preview route |

Sources: [Codex models](https://learn.chatgpt.com/docs/models#deprecated-codex-models)
and [API deprecations](https://developers.openai.com/api/docs/deprecations).
The API catalog still lists retired models for reference; a catalog page alone
does not override an explicit retirement notice.

## Upstream comparison and implementation decisions

The local official `openai/codex` checkout was inspected at
`dad1db87bb5ad4b92af6b0f58502d12453681f81` (2026-08-11). It is a pinned design
reference, **not** fresh evidence for September models:

- [Model manager](https://github.com/openai/codex/blob/dad1db87bb5ad4b92af6b0f58502d12453681f81/codex-rs/models-manager/src/manager.rs)
  separates endpoint/auth transport from catalog selection, filters by auth,
  preserves an explicitly selected model, and uses TTL/ETag refresh.
- [Model cache](https://github.com/openai/codex/blob/dad1db87bb5ad4b92af6b0f58502d12453681f81/codex-rs/models-manager/src/cache.rs)
  defines freshness/version validation. The pinned manager still contains a
  provider-identity cache TODO, so it is not cited as proof of completed partitioning.
- Current [app-server model/list documentation](https://learn.chatgpt.com/docs/app-server#models)
  returns account/client-specific effort choices, defaults, hidden status, upgrade
  guidance, and input modalities. A static public catalog is not an account probe.

GEODE already has independent PAYG/OAuth clients, a shared Responses translator,
typed request/results, inline output/reasoning replay, and source-specific tool
gates. Reuse those boundaries. The minimal changes add the missing model specs,
published output caps, correct inherited effort constraints, and central
source-aware model choices. No new adapter factory or parallel provider registry
is needed.

The remaining opt-in surfaces need distinct semantics: API `configuration_update`
changes effort while preserving cached history, but has single-agent compatibility
limits; explicit cache breakpoints require preservation across history transforms;
Enterprise access tokens require their credential lifecycle. These are documented
capabilities, not implemented promises in this refresh. Existing June computer-use
acceptance restrictions remain until an authorized route-specific round trip can
replace that evidence. No paid request, login, credential read, service change, or
backend probe was run for this audit.

## SDK compatibility

The inspected environment has `openai==2.45.0`. Its `ResponsesModel` accepts
arbitrary string IDs; Responses streaming already supports reasoning,
`max_output_tokens`, `prompt_cache_options`, and cached/write usage fields. The
model additions therefore do not depend on a generated model-name enum update.

The official [latest Python release is 3.19.0](https://github.com/openai/openai-python/releases/tag/v3.19.0)
(release page published September 23; changelog dated September 22).
[3.18.0 added GPT-6 Sol/Luna model identifiers](https://github.com/openai/openai-python/releases/tag/v3.18.0).
[3.0.0 introduced HTTPX2](https://github.com/openai/openai-python/releases/tag/v3.0.0);
the [migration guide](https://github.com/openai/openai-python/blob/main/httpx2.md)
requires custom transport, timeout, hook, and mock objects to use the new HTTP
client family. GEODE constructs HTTPX clients for OpenAI, Codex and compatible
providers, so SDK major-version migration is a shared transport change rather
than a model-name edit. The installed 2.45.0 still types `priority`, not the new
`fast`/`ultrafast` spellings, and has no cache-prewarm option. Those facts describe
the inspected version; the release record does not establish backend acceptance.
