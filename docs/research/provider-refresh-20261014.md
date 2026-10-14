# Provider refresh, 2026-10-14

This refresh follows the [2026-09-24 audit](provider-refresh-20260924.md) and
changes only what current primary documentation changed. All sources below
were retrieved on 2026-10-14 from the official Markdown pages. They are
published contracts, not account entitlement, live acceptance or billing
evidence. No live or paid request was made to produce this note.

## Changes

| Change | Primary source | GEODE consequence |
|---|---|---|
| `gpt-6.1-sol` released for Platform and Codex | [GPT-6.1 Sol model page](https://developers.openai.com/api/docs/models/gpt-6.1-sol), [Codex models](https://learn.chatgpt.com/docs/models) | New offering on API and subscription; own `OpenAIModelSpec`, price and context rows |
| GPT-5.5 retired from ChatGPT/Codex sign-in on 2026-10-14; the API is unaffected | [Codex models, GPT-5.5 retirement](https://learn.chatgpt.com/docs/models#gpt-55-retirement) | Subscription requests rejected before credentials or network; Platform route, prices and records kept |
| GPT-5.3-Codex-Spark retired from Codex on 2026-09-14 | [Codex models, deprecated models](https://learn.chatgpt.com/docs/models#deprecated-codex-models) | Subscription lifecycle row added |
| `gpt-5.3-codex`, `gpt-5.1`, `gpt-5.4-nano` API-deprecated, shutdown 2027-04-01 | [OpenAI deprecations](https://developers.openai.com/api/docs/deprecations) | The `gpt-5.3-codex` and `gpt-5.4-nano` offerings stay selectable with the shutdown date in the label; `gpt-5.1` has no GEODE offering |
| `claude-sonnet-5-5` (2026-09-28) and `claude-haiku-5-5` (2026-10-07) released | [Sonnet 5.5](https://platform.claude.com/docs/en/models/sonnet-5-5/overview), [what's new](https://platform.claude.com/docs/en/models/sonnet-5-5/whats-new-sonnet-5-5); [Haiku 5.5](https://platform.claude.com/docs/en/models/haiku-5-5/overview), [what's new](https://platform.claude.com/docs/en/models/haiku-5-5/whats-new-haiku-5-5) | New `AnthropicModelSpec` rows; secondary/budget defaults move to them |
| `claude-sonnet-4-5-20250929` deprecated 2026-09-30, retiring 2026-11-30 | [Model deprecations](https://platform.claude.com/docs/en/about-claude/model-deprecations) | Still selectable with the date shown; not added to the retired table |
| Retired Sonnet families now name `claude-sonnet-5-5` as replacement | same | Rejection messages name the documented replacement |

## GPT-6.1 Sol by route

| Contract | Platform API (`openai-payg`) | Codex sign-in (`codex-oauth`) |
|---|---|---|
| Context | 1,050,000; max input 922,000 | Local client catalogue: 500,000 default, 872,000 ceiling |
| Output | 128,000 including reasoning | Server-managed; GEODE sends no output cap |
| `reasoning.effort` | `low`, `medium` (default), `high`, `xhigh`, `max`; `none`/`minimal` unsupported | Same native levels; Codex client default `low`. `ultra` is a Codex subagent mode and is never sent as an effort |
| Tools | Responses only; Chat Completions has no tool calling | Responses (the only GEODE route) |
| Price (USD/MTok) | 2 input, 0.10 cached input, 2.50 cache write, 10 output; prompts above 272K input pay 2x input/cache and 1.5x output for the full request | Plan credits, not these tariffs |
| Computer use | Listed in the Responses tool catalogue | Codex backend rejected the GA tool in the 2026-06-17 live test |

The Codex numbers come from a read-only selection of non-secret fields in the
local Codex 0.162.0 `models_cache.json` (`gpt-6.1-sol` listed,
`context_window` 500000, `max_context_window` 872000, default effort `low`,
efforts `low`..`max` plus the `ultra` execution mode). They describe that
client build, not a server limit or an account guarantee. Rollout covers
Plus, Pro, Business, Enterprise and Edu (Enterprise/Edu off until an admin
enables it); Free and Go are excluded at launch.

GEODE keeps GPT-6.1 Sol out of `_OPENAI_COMPUTER_USE_GA_MODELS`: the existing
rule requires a live Platform round trip before a catalogue listing becomes an
injected tool.

## Claude Sonnet 5.5 and Haiku 5.5

| Contract | Sonnet 5.5 | Haiku 5.5 |
|---|---|---|
| Context / output | 1M / 128K | 1M / 128K |
| Thinking | Adaptive by default; `disabled` is a 400, lowest mode is `between_tools` (low..high only, no `display`/`budget_tokens`/`block_binding`) | Adaptive by default; `disabled` allowed at `high` or below; manual budgets are a 400 |
| Effort | low..max, default `high` (recalibrated) | low..max, default `medium` |
| Forced `tool_choice` | `any`/`tool` are a 400 | Accepted; a forced turn has no thinking block |
| Sampling, prefill | Non-default `temperature`/`top_p`/`top_k` are a 400 | Same; assistant prefill is a 400 |
| Signed thinking | Bound to model, conversation prefix and account; `drop_block` binding control applies with adaptive thinking | Same |
| Text between tool calls | Notes longer than a sentence or two arrive as progress-update thinking blocks; text is empty at `display: "omitted"` | Responses can begin with thinking blocks |
| Computer use (direct API) | `computer_toolset_20260801` only | `computer_toolset_20260801` only |
| Tool search, context editing, threshold compaction | Listed | Listed |
| Price (USD/MTok) | 2 input, 2.50 5m write, 4 1h write, 0.10 cache read, 10 output | 0.10 / 0.125 / 0.20 / 0.01 / 0.50; if the prompt (input + cache reads + cache writes) exceeds 100,000 tokens every category is 5x for that request |

Sources: the model and what's-new pages above, the
[pricing page](https://platform.claude.com/docs/en/about-claude/pricing),
[effort](https://platform.claude.com/docs/en/build-with-claude/effort),
[preserved thinking](https://platform.claude.com/docs/en/build-with-claude/preserved-thinking),
[computer use](https://platform.claude.com/docs/en/agents-and-tools/tool-use/computer-use-tool),
[tool search](https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-search-tool),
[context editing](https://platform.claude.com/docs/en/build-with-claude/context-editing),
[threshold compaction](https://platform.claude.com/docs/en/build-with-claude/compaction-threshold),
[web search](https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-search-tool) and
[web fetch](https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-fetch-tool).
Haiku 5.5's variable price depends on prompt length, not on effort.

GEODE always sends adaptive thinking with `display: "summarized"` for these
rows, so neither `disabled` nor `between_tools` is ever serialized and progress
notes keep their summary text. GEODE has no thinking-off control, so none was
added. Signed blocks are replayed unchanged; the existing binding control and
transformation diagnostics now also count `organization_binding_mismatch`
drops, by reason and count only. Forced tool choice is rejected locally for
Sonnet 5.5 and preserved for Haiku 5.5. Hosted web fetch stays off for both,
matching Opus 5.5: the fetch page states support only as "Claude 4.6 and
later", without the per-model table the earlier decision required. Local
fetch is unaffected.

## Current general-purpose GPT set

The Platform catalog's general text-agent models are GPT-6 Astra, GPT-6.1 Sol,
GPT-6 Sol, GPT-6 Luna and GPT-5.6 Sol/Terra/Luna (no GPT-6.1 Astra or Luna
exists). All seven have offerings on both routes, their own `OpenAIModelSpec`
and price rows, 1.05M/922K-input/128K-output API limits, and a Codex client
window of 272K (500K for GPT-6.1 Sol) with an 872K ceiling.

| Model | API effort | Codex client default (0.162.0) | Price input / cached / write / output |
|---|---|---|---|
| gpt-6-astra | low..max | medium | 10 / 1 / 12.5 / 50 |
| gpt-6.1-sol | low..max | low | 2 / 0.10 / 2.5 / 10 |
| gpt-6-sol | none..max | medium | 2 / 0.20 / 2.5 / 10 |
| gpt-6-luna | none..max | medium | 0.10 / 0.01 / 0.125 / 0.50 |
| gpt-5.6-sol | none..max | low | 4 / 0.40 / 5 / 20 (promotional through at least 2026-11-21) |
| gpt-5.6-terra | none..max | medium | 2 / 0.20 / 2.5 / 12 |
| gpt-5.6-luna | none..max | medium | 0.20 / 0.02 / 0.25 / 1.20 |

The Codex client lists `low`..`max` (plus `ultra`) for every model. Its
omission of `none` is client UI evidence, not proof that the backend rejects
it, so GEODE keeps the API effort set on both routes. GPT-5.6 pages state the
long-context tier as "2x input and 1.5x output" without naming cached input;
GEODE keeps doubling cache rates as for GPT-6, an unverified reading.
Specialized audio, realtime, live, transcription, image, embedding,
moderation, deep-research, cyber (Daybreak, GPT-5.6 Cyber) and restricted
research (GPT-Rosalind) models are not interchangeable text-agent backends
and get no generic offering.

## Native evaluation providers

Petri's API-key bindings now use GEODE-owned inspect_ai providers,
`openai-platform/<model>` and `anthropic-platform/<model>`, alongside the
existing `openai-codex`. The installed inspect_ai 0.3.252 classifies OpenAI
reasoning models by the name `gpt-5`, so GPT-6 ids received Chat Completions
and lost their reasoning effort. On Anthropic models it dropped any explicit
`tool_choice` while thinking was on, sent `thinking: disabled` to Opus 5.5 and
Sonnet 5.5 (both reject it), and clamped unsupported effort. The owned
providers take model family, supported effort, thinking-off support (with the
Opus 5 and Haiku 5.5 high-effort limit) and forced-tool support from the
existing model specs. They reject unsupported explicit options and forced tool
use under manual (`enabled`) thinking before any request, and apply the
lifecycle owner at construction. The endpoint is resolved once at
construction, so unknown models and custom gateways keep stock behavior. Raw
`openai/<model>` and `anthropic/<model>` ids stay inspect_ai's stock providers,
an explicit escape hatch that bypasses these contracts.

Petri and seed-generation roles opt into current offerings with
`current_models = true`; their TOML lists hold only historical or alias ids,
and pinned `default_model` values are unchanged. Custom manifests keep their
exact `allowed_models`. Bare-id OAuth mapping follows the catalog's
subscription offerings and lifecycle rows instead of a `gpt-5*` prefix. Seed
voters without an explicit effort keep `none` where the model accepts it and
otherwise use the catalog default. The effort vocabulary and per-model
supported/default effort live in `core/llm/model_catalog.py`, which the picker
re-exports.

## Frontier comparison

Evidence: pinned Codex source
[`400f2356`](https://github.com/openai/codex/tree/400f2356d60c4663d46817a40b4d09c5c86f35ad),
an isolated `model/list` replay of the installed Codex 0.157.0 (no inference),
and a Claude Code 2.1.290 parser probe. The REA artifacts stay private; this is
a bounded comparison, not a reconstruction.

| Pattern | Evidence | GEODE decision |
|---|---|---|
| One model record feeds picker and request | [ModelInfo to ModelPreset](https://github.com/openai/codex/blob/400f2356d60c4663d46817a40b4d09c5c86f35ad/codex-rs/protocol/src/openai_models.rs#L954-L989), [picker](https://github.com/openai/codex/blob/400f2356d60c4663d46817a40b4d09c5c86f35ad/codex-rs/tui/src/chatwidget/model_popups.rs#L474-L520), [request effort](https://github.com/openai/codex/blob/400f2356d60c4663d46817a40b4d09c5c86f35ad/codex-rs/core/src/client.rs#L934-L948) | Adopted at the existing owners: model specs feed the picker, CLI, eval manifests, native providers and voters |
| Discovered catalogs scoped to endpoint identity | [manager](https://github.com/openai/codex/blob/400f2356d60c4663d46817a40b4d09c5c86f35ad/codex-rs/models-manager/src/manager.rs#L37-L81) | No discovery service added; one reviewed record keeps lifecycle authority, and an old listing (0.157.0 still shows gpt-5.5) cannot restore a retired route |
| Ultra maps to an underlying effort | [reasoning_effort.rs](https://github.com/openai/codex/blob/400f2356d60c4663d46817a40b4d09c5c86f35ad/codex-rs/protocol/src/openai_models/reasoning_effort.rs#L8-L39) | Ultra stays off the wire; GEODE's rejection does not implement Codex delegation |
| Claude Code ignores an unknown effort and uses the default | CLI parser probe | Rejected: GEODE fails on unsupported explicit options instead of falling back |

## Selection policy

New Claude defaults are `claude-sonnet-5-5` (secondary) and
`claude-haiku-5-5` (budget); Opus 5.5 stays primary. GPT defaults stay
`gpt-6-sol`, the documented GPT-5.5 replacement, because GPT-6.1 Sol's
subscription rollout excludes some plans and is admin-gated for Enterprise and
Edu. Explicit configuration keeps precedence, and nothing remaps a saved
selection. Deprecated but still served models stay selectable with their
retirement date in the label; only retired source routes are rejected.
Benchmark defaults that pin `gpt-5.5` remain for comparability and now fail
on the subscription route with the replacement named.

Partner-hosted (Bedrock, Google Cloud) lifecycle and computer-tool generations
are separate and are not inferred from these pages.

## Verification boundary

Offline regressions cover the serialized Responses request for both routes
through the real adapters and the AgenticLoop request assembly, effort
rejection before client access, route-specific context admission, tariffs and
the Haiku threshold, retirement before credentials, picker/login/default
consistency, and two-turn Claude replay over the SDK transport. Live
acceptance of `gpt-6.1-sol` on a signed-in subscription, Claude 5.5 API
acceptance and billed amounts are not established by these checks.
