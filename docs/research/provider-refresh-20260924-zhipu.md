# Z.AI public API and Coding Plan audit — 2026-09-24

Scope: current international Z.AI public surfaces used by GEODE's GLM adapters.
All links below were opened on 2026-09-24. These are public-document findings,
not funded API observations. Domestic `open.bigmodel.cn` product entitlement is
not inferred from international `api.z.ai` documentation. No credentials were
read and no model, search, subscription, or paid API calls were made.

## Current contract

| Surface | Verified public contract | Primary source |
| --- | --- | --- |
| Flagship | `glm-5.3`; text input/output, 1M context, 128K output; only enabled thinking; effort `low`, `high`, `max` (default `max`) | [GLM-5.3](https://docs.z.ai/guides/llm/glm-5.3) |
| Flash models | `glm-5.3-flash`, `glm-5.3-flashx`; image/video/file/text input and text output; 1M context, 128K output; same text controls as 5.3; FlashX not available on Coding Plan | [Flash/FlashX](https://docs.z.ai/guides/vlm/glm-5.3-flash) |
| Exact output bound | `max_tokens` range 1–131072; model-specific prose describes 128K. GLM-5.3/5.2/5.1/5/4.7/4.6 support that output class | [Chat Completion](https://docs.z.ai/api-reference/llm/chat-completion) |
| General API | Bearer API key; Chat Completions base `https://api.z.ai/api/paas/v4` | [API reference](https://docs.z.ai/api-reference/llm/chat-completion) |
| Additional protocols | Published bases include Anthropic Messages `/api/anthropic` and Responses `/api/v1`; these are separate protocol surfaces, not interchangeable base URLs | [Integration](https://docs.z.ai/devpack/tool/others), [Codex integration](https://docs.z.ai/devpack/tool/codex) |
| Coding Plan model identity | All tiers expose 5.3 and 5.3-Flash. Older requests 5.2/5.1 route to 5.3; 4.7 routes to 5.3-Flash | [Plan overview](https://docs.z.ai/devpack/overview) |
| Subscription entitlement | Restricted to supported tools; GEODE is absent from the published list | [Usage policy](https://docs.z.ai/devpack/usage-policy), [supported tools](https://docs.z.ai/devpack/tool/others) |
| Subscription search | Separate remote MCP server, `webSearchPrime`, at `https://api.z.ai/api/mcp/web_search_prime/mcp` | [Web Search MCP](https://docs.z.ai/devpack/mcp/search-mcp-server) |

The usage policy says “Use limited to supported tools.” The integration page
defines a specific list; being able to serialize the same HTTP protocol does
not establish GEODE admission. Existing profile records are retained, but
direct Coding Plan execution is rejected locally before credential lookup or
network activity. PAYG selection remains explicit.

The model API section of the 5.3 guide says accounts that previously subscribed
to Coding Plan, including expired subscriptions, currently have only Chat
Completions access. Coding Plan's own integration guides advertise Messages
and Responses. The documents appear to distinguish account/product contexts
but do not provide a complete executable entitlement matrix. GEODE therefore
keeps its documented Chat Completions API route; no inferred protocol upgrade
or account-wide availability claim is made.

## Pricing and limits

USD per million tokens, in input / cached input / output order:

| Model | Input | Cached input | Output |
| --- | ---: | ---: | ---: |
| GLM-5.3 | 1.40 | 0.26 | 4.40 |
| GLM-5.3-Flash | 0.15 | 0.03 | 0.50 |
| GLM-5.3-FlashX | 0.37 | 0.075 | 1.25 |
| GLM-5.2 / GLM-5.1 | 1.40 | 0.26 | 4.40 |
| GLM-5 | 1.00 | 0.20 | 3.20 |
| GLM-4.7 / GLM-4.6 / GLM-4.5 | 0.60 | 0.11 | 2.20 |
| GLM-4.7-FlashX | 0.07 | 0.01 | 0.40 |
| GLM-4.5-X | 2.20 | 0.45 | 8.90 |
| GLM-4.5-Air | 0.20 | 0.03 | 1.10 |
| GLM-4.5-AirX | 1.10 | 0.22 | 4.50 |
| GLM-4-32B-0414-128K | 0.10 | Unlisted | 0.10 |
| GLM-4.7-Flash / GLM-4.5-Flash | Free | Free | Free |

The [pricing page](https://docs.z.ai/guides/overview/pricing) marks cached-input
storage as temporarily free, separately from token rates; native web search
costs $0.01/use. The listed text-model token rates have no published context
tier on this page. Older listed models are not declared retired solely because
newer IDs exist. `glm-5-turbo` and `glm-5v-turbo` are absent from the current
international price/API tables; no retirement date was established.

Coding Plan is now token-credit based: Lite/Pro/Max provide respectively
2,000/12,000/28,000 credits per 5 hours and 10,000/60,000/140,000 weekly.
GLM-5.3 input/cache/output multipliers are 6.9/1.7/24; Flash uses 2.3/0.56/8,
divided by 10,000 tokens. MCP calls consume 1.2 credits each. Model off-peak
usage is half rate; weekday peak hours are 14:00–18:00 Singapore time.
The overview advertises plans from $18/month; full current checkout prices
were not exposed by the public rendered subscribe page. Historic transition
examples are not current price authority. [Plan overview](https://docs.z.ai/devpack/overview)

The date-specific September 25–October 7 promotion was announced but is not
effective on this September 24 snapshot. Legacy unlimited-weekly plans are
being phased out with paid-period preservation, rather than immediate removal.
[Migration notice](https://docs.z.ai/devpack/transition)

## Runtime decisions and frontier comparison

GLM-5.3 migration requires the runtime to preserve reasoning content and
stream-concatenate indexed tool-call arguments. Stream and non-stream request
builders must carry the same tools and effort. [Migration guide](https://docs.z.ai/guides/overview/migrate-to-glm-new)

Existing GEODE reasoning replay already binds opaque state to provider,
adapter, and model. This remains the authority; the request builder is shared
by both GLM adapters rather than duplicating provider rules. `GlmModelSpec`
holds exact model controls, output bounds, and vision support. Prefix matches
do not grant future models capabilities. GLM-5.3 generic GEODE efforts
`none/minimal`, `medium`, and `xhigh` normalize to `low`, `high`, and `max`
with a warning. Those mappings are GEODE policy, not extra native values.

[OpenCode transform source](https://github.com/anomalyco/opencode/blob/610df0b56674fa0ebcae89093ada08b98731bea6/packages/opencode/src/provider/transform.ts#L1258)
was pinned to commit `610df0b56674fa0ebcae89093ada08b98731bea6`. Its GLM
OpenAI-compatible branch enables thinking and sets `clear_thinking=false`;
its effort variants separately account for protocol. GEODE adopts exact
model/protocol policy separation, while retaining existing replay validation.
Upstream implementation is comparison evidence, not provider entitlement.

Z.AI documents preserved thinking as enabled by default for Coding Plan and
disabled for PAYG. PAYG enables it explicitly with `thinking.clear_thinking=false`
and requires full, ordered, unmodified prior reasoning. GEODE keeps its
existing default rather than turning on cross-turn preservation merely
because another harness does. [Thinking mode](https://docs.z.ai/guides/capabilities/thinking-mode)

Caching reports `usage.prompt_tokens_details.cached_tokens` as a subset of
prompt tokens; uncached input, cached input, and output use separate rates.
Existing normalized usage accounting is preserved. [Context caching](https://docs.z.ai/guides/capabilities/cache)

## Original gaps and acceptance

| Original owner | Gap | Resolution / acceptance |
| --- | --- | --- |
| `core/llm/providers/glm.py` | Reasoning allowed only 5.2; prefix inferred capability; request effort ignored | Exact typed 5.2/5.3 contracts and shared request builder; unknown model suffix receives no invented controls |
| `core/llm/adapters/glm_payg.py` | Text path omitted effort; stream path omitted tools and reasoning | Text uses adapter completion; stream uses same builder and preserves thinking/tool arguments |
| `core/llm/adapters/glm_coding_plan.py` | Claimed PAYG search parity without route evidence | Native search rejects explicitly; subscription calls use source admission before client lookup |
| `core/llm/providers/glm.py` auxiliary client | Bare API key defaulted to Coding Plan endpoint | Explicit PAYG default; selected subscription source cannot bypass admission |
| `core/llm/model_pricing.toml`, catalog and picker | 5.3/Flash absent and 5.2 old context assumption | Central catalog owner updates rates/specs/listing; preserve historical evidence |
| `core/llm/strategies/plans.py` | 80/240/600 call budgets modeled stale quota | Remove obsolete built-in call-count authority; provider credit balance remains provider-owned |

Local acceptance uses fake SDK responses and tests request precedence,
always-enabled reasoning, exact-model matching, split streaming arguments,
strict source admission, and PAYG endpoint selection. No local test proves
account entitlement or a funded live response.
