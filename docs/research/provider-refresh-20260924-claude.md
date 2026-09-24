# Claude public surface refresh — 2026-09-24

Retrieved on 2026-09-24 from the official pages below. The latest dated
Claude Platform release entry observed is 2026-09-22. These are published
contracts, not a live account-entitlement or billing verification. No paid
request or subscription credential was used.

## Public API model inventory

USD per million tokens; standard global synchronous Messages API. Prices do
not represent a Claude subscription invoice. Older active models remain
available even when their model pages label them legacy.

| API model | Context | Output | Input | Output price | Cache read |
|---|---:|---:|---:|---:|---:|
| `claude-fable-5-1` | 1M | 128K | 10 | 50 | 0.25 |
| `claude-fable-5` | 1M | 128K | 10 | 50 | 1.00 |
| `claude-opus-5-5` | 1M | 128K | 4 | 20 | 0.20 |
| `claude-opus-5` | 1M | 128K | 5 | 25 | 0.50 |
| `claude-opus-4-8` | 1M | 128K | 5 | 25 | 0.50 |
| `claude-opus-4-7` | 1M | 128K | 5 | 25 | 0.50 |
| `claude-opus-4-6` | 1M | 128K | 5 | 25 | 0.50 |
| `claude-opus-4-5-20251101` | 200K | 64K | 5 | 25 | 0.50 |
| `claude-sonnet-5` | 1M | 128K | 2 | 10 | 0.20 |
| `claude-sonnet-4-6` | 1M | 128K | 3 | 15 | 0.30 |
| `claude-sonnet-4-5-20250929` | 200K | 64K | 3 | 15 | 0.30 |
| `claude-haiku-4-5-20251001` | 200K | 64K | 1 | 5 | 0.10 |

Sources: [model overview](https://platform.claude.com/docs/en/models/overview),
[pricing](https://platform.claude.com/docs/en/about-claude/pricing),
[Sonnet 4.6](https://platform.claude.com/docs/en/models/sonnet-4-6/overview),
[Opus 4.5](https://platform.claude.com/docs/en/models/opus-4-5/overview).
Cache writes cost 1.25× input for 5 minutes and 2× for 1 hour. The former
universal 0.1× cache-read multiplier is wrong for Fable 5.1 and Opus 5.5.
Sonnet 5's $2/$10 price became permanent; the announced September increase
was canceled. Fast mode, batches, geography modifiers, and restricted Mythos
access are separate contracts and must not be inferred from standard prices.

[Lifecycle](https://platform.claude.com/docs/en/about-claude/model-deprecations)
marks Opus 4.1 retired August 5, 2026; Opus 4 and Sonnet 4 retired June 15;
Haiku 3 retired April 20; Sonnet 3.7 and Haiku 3.5 retired February 19.
These dates govern Anthropic-operated endpoints, not partner retirement
schedules. Mythos 5/5.1 are invitation-only and are not generally selectable
GEODE models. Fable 5 and the listed 4.5–4.8 models remain active.

## Request contract and evidence

| Surface | Published contract | Implementation consequence |
|---|---|---|
| New models | Fable 5.1 released September 1; Opus 5.5 September 22; Opus 5 July 24; Sonnet 5 June 30 | Add exact IDs and separate cache rates |
| Thinking | Fable 5.1 and Opus 5.5 always adaptive; Sonnet 5 rejects manual budget mode | Use model records to shape create and stream consistently |
| Effort | New models support low/medium/high/xhigh/max; Opus 5.5 default medium; other new models high | Preserve explicit effort; never escalate unsupported xhigh to max |
| Forced tools | Fable 5.1 and Opus 5.5 reject `any` and `tool`; `auto`/`none` remain valid | Fail locally without retry/model substitution |
| Structured JSON | `output_config.format` is the current GA field; old `output_format` is transitional | Merge format with effort and preserve caller schema |
| Signed thinking | New accounts enforce the prefix check for Fable 5.1 and Opus 5.5 | Send binding controls and diagnose provider-confirmed drops when GEODE edits dynamic context |
| Tool search | Published compatibility table lists new Opus/Fable but omits Sonnet 5 | Keep Sonnet 5 definitions eager pending explicit evidence |
| Hosted web tools | Latest search/fetch tags are `20260318`; fetch's dynamic compatibility list omits Opus 5/5.5 | Refresh tags; keep hosted fetch off for those two pending evidence; ordinary local fetch remains available |
| Context editing | Available on all supported Claude models | Haiku supports clearing but not threshold compaction |
| Threshold compaction | New Opus/Fable/Sonnet models supported; 4.5 excluded | Retain the supported `compact-2026-01-12` contract |
| Computer use | Opus 5.5 direct API requires client toolsets | Never assume an unknown model accepts the previous computer generation |

Primary evidence:

- [Release notes](https://platform.claude.com/docs/en/release-notes/overview)
- [Fable 5.1](https://platform.claude.com/docs/en/models/fable-5-1/overview)
- [Opus 5.5](https://platform.claude.com/docs/en/models/opus-5-5/overview)
- [Opus 5](https://platform.claude.com/docs/en/models/opus-5/overview)
- [Sonnet 5](https://platform.claude.com/docs/en/models/sonnet-5/overview)
- [Effort](https://platform.claude.com/docs/en/build-with-claude/effort)
- [Structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)
- [Preserved thinking](https://platform.claude.com/docs/en/build-with-claude/preserved-thinking)
- [Tool search](https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-search-tool)
- [Context editing](https://platform.claude.com/docs/en/build-with-claude/context-editing)
- [Threshold compaction](https://platform.claude.com/docs/en/build-with-claude/compaction-threshold)
- [Computer use](https://platform.claude.com/docs/en/agents-and-tools/tool-use/computer-use-tool)
- [Web search](https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-search-tool)
- [Web fetch](https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-fetch-tool)

## Frontier adapter decisions

[Claude Code model configuration](https://code.claude.com/docs/en/model-config)
separates model capability, explicit effort, organization caps, and account
defaults. Unsupported effort clamps downward: xhigh becomes high on Opus
4.6. GEODE adopts this bounded behavior instead of increasing cost to max.
An immutable `AnthropicModelSpec` record now owns the adapter rules and feeds
the existing capability-set consumers; no additional adapter hierarchy is
needed.

[Claude Code authentication policy](https://code.claude.com/docs/en/legal-and-compliance)
limits subscription OAuth to ordinary native Anthropic application use.
Third-party products should use API keys or supported cloud authentication;
Claude.ai login/subscription credentials are not a GEODE provider route.
Existing PAYG-only admission remains the correct boundary.

Preserved-thinking controls use
`thinking-binding-controls-2026-08-01` and
`thinking.block_binding.prefix_mismatch_behavior = "drop_block"` only for
the models enforcing prefix binding. GEODE retains raw signed blocks and
logs bounded `input_transformations` reasons/counts. This repairs API
compatibility when dynamic context changes; it does not claim to preserve
all reasoning or the prompt cache after those edits. An append-only
mid-conversation system-message design requires a separate history-owner
change.

Opus 5.5 uses `computer_toolset_20260801` with raw toolset identity retained
through response, local dispatch and tool-result replay. GEODE requests serial
tool calls, validates native coordinates and parameters before desktop input,
and withholds `zoom`, `hold_key`, `left_mouse_down` and `left_mouse_up`, which
its local driver does not implement. Known older models retain their documented
computer schema and unknown models remain guarded.

## Verification boundary

Offline request/response regressions cover new model controls, shared
stream/create shaping, signed-block preservation, prefix-drop diagnostics,
forced-tool rejection, structured JSON, output limits, native computer translation
and unsupported-action rejection. Streaming preserves
final tool calls, signed content, and full usage through the same response owner. Live provider
acceptance, desktop action outcomes, account availability, subscription
policy exceptions, and external billing are unverified.
