# Codex OAuth Request Spec — chatgpt.com/backend-api/codex/responses

> Production incident 2026-04-27: GEODE sent `max_output_tokens` and Codex returned 400 `"Unsupported parameter: max_output_tokens"`. This doc grounds the correct request shape against 3 reference implementations.

## Endpoint

- URL: `POST https://chatgpt.com/backend-api/codex/responses`
  - Base: `https://chatgpt.com/backend-api/codex` (Hermes `DEFAULT_CODEX_BASE_URL`, OpenClaw `OPENAI_CODEX_BASE_URL` minus `/codex`, Codex Rust `default_base_url` for `AuthMode::Chatgpt`).
  - Path suffix `/responses` (Codex Rust `RESPONSES_ENDPOINT`).
- Auth: `Authorization: Bearer <oauth_access_token>` from `~/.codex/auth.json` (or GEODE-issued profile). Token is the **raw** bearer access token; not prefixed.
- Refresh: long-lived `refresh_token` in same JSON; provider-side refresh on 401 (OpenClaw `refreshOpenAICodexOAuthCredential`, Hermes `auth.py`).

## Required headers

| Header | Value | Source |
|--------|-------|--------|
| `Authorization` | `Bearer <access_token>` | Codex Rust `AgentIdentityAuthProvider::add_auth_headers`; OpenClaw `provider-attribution.ts:357-361` |
| `originator` | `codex_cli_rs` (or vendor-specific) | Codex Rust `default_client.rs` `headers.insert("originator", originator().header_value)`; OpenClaw `OPENCLAW_ATTRIBUTION_ORIGINATOR`; GEODE already sets `"codex_cli_rs"` (`core/llm/providers/codex.py:119`) |
| `ChatGPT-Account-ID` | UUID from JWT `https://api.openai.com/auth.chatgpt_account_id` | Codex Rust `model-provider/src/auth.rs` `headers.insert("ChatGPT-Account-ID", header)`; GEODE `_extract_account_id` (`codex.py:37-51`) |
| `User-Agent` | `<originator>/<version> (<os> <ver>; <arch>) <suffix>` | Codex Rust `get_codex_user_agent()`; OpenClaw `formatOpenClawUserAgent` |
| `version` | client version string | OpenClaw `provider-attribution.ts:359`; Codex Rust derives from cargo |
| `OpenAI-Beta` | `responses_websockets=2026-02-06` (only for WS transport) | Codex Rust `RESPONSES_WEBSOCKETS_V2_BETA_HEADER_VALUE` — **not required** for plain SSE |
| `x-openai-internal-codex-residency` | `us` (Codex CLI sets it; not required by server) | Codex Rust `RESIDENCY_HEADER_NAME` |

Optional Codex CLI-only: `x-codex-installation-id`, `x-codex-window-id`, `x-codex-turn-state`, `x-codex-parent-thread-id`, `x-openai-subagent`. Server tolerates absence.

## Request body

Schema is `ResponsesApiRequest` in Codex Rust (`codex-rs/codex-api/src/common.rs:117-133`).

| Field | Type | Status | Notes | Source |
|-------|------|--------|-------|--------|
| `model` | string | REQUIRED | e.g. `gpt-5.3-codex`. Slug list maintained by OpenClaw `openai-codex-provider.ts:57-83`. | Rust `common.rs:118`; OpenClaw catalog |
| `instructions` | string | REQUIRED (skip if empty) | System prompt. Hermes extracts from `messages[0]` if not given (`agent/transports/codex.py:66-73`). `#[serde(skip_serializing_if = "String::is_empty")]`. | Rust `common.rs:119`; Hermes `codex.py:94` |
| `input` | array | REQUIRED | `Vec<ResponseItem>` — Responses-API input items (NOT Chat Completions messages). | Rust `common.rs:120`; Hermes `_chat_messages_to_responses_input` (`codex_responses_adapter.py`); OpenClaw `convertResponsesMessages` (`openai-transport-stream.ts:733`) |
| `tools` | array | REQUIRED (may be `[]`) | Responses function-tool schema, NOT Chat Completions schema. | Rust `common.rs:121`; Hermes `_responses_tools` |
| `tool_choice` | string | REQUIRED | Always `"auto"` in Codex Rust (`client.rs:851-923`); Hermes also hard-codes `"auto"` (`codex.py:97`). | Rust `client.rs`; Hermes `codex.py:97` |
| `parallel_tool_calls` | bool | REQUIRED | `true` per Hermes default (`codex.py:98`); Codex Rust forwards `prompt.parallel_tool_calls`. | Rust `client.rs`; Hermes `codex.py:98` |
| `store` | bool | REQUIRED | **`false`** for Codex backend (Plus quota does not support server-side state). Hermes `codex.py:99`; Codex Rust `provider.is_azure_responses_endpoint()` (false for chatgpt.com); OpenClaw `payloadPolicy.storeMode = "disable"` (`openai-transport-stream.ts:741`). | All 3 |
| `stream` | bool | REQUIRED | **`true`** — Codex backend rejects non-streaming. Hermes uses `client.responses.stream()` (`run_agent.py:4713`); GEODE already does `client.responses.stream(...)` (`codex.py:228`). | All 3 |
| `include` | array<string> | REQUIRED | `["reasoning.encrypted_content"]` when reasoning enabled, else `[]`. | Rust `common.rs:127`; Hermes `codex.py:107-117` |
| `reasoning` | object \| null | OPTIONAL | `{effort: "low"\|"medium"\|"high", summary: "auto"}`. Omitted when reasoning disabled. Hermes maps `effort=minimal -> low`. | Rust `common.rs:124`; Hermes `codex.py:80-90,114` |
| `prompt_cache_key` | string | OPTIONAL | Session/conversation id. `#[serde(skip_serializing_if = "Option::is_none")]`. | Rust `common.rs:129`; Hermes `codex.py:102-104` |
| `service_tier` | string | OPTIONAL | Only when `payloadPolicy.allowsServiceTier` (OpenClaw gates by Codex endpoint). | Rust `common.rs:128`; OpenClaw `provider-attribution.ts:575-579` |
| `text` | object | OPTIONAL | `TextControls` (verbosity / schema). | Rust `common.rs:130` |
| `client_metadata` | map<string,string> | OPTIONAL | e.g. `{installation_id: ...}`. | Rust `common.rs:131` |
| `metadata` | object | OPTIONAL | OpenClaw forwards turn-state metadata when present (`openai-transport-stream.ts:749`). | OpenClaw |
| `temperature` | float | OPTIONAL | Codex models commonly omit (Hermes consults `_fixed_temperature_for_model` and may strip — `run_agent.py:7228`). Safe to send if model accepts. | Hermes `codex.py:124-125` (only for non-Codex backend) — Hermes does NOT add temperature inside `build_kwargs` for codex backend either; it is set later only when not omitted. |
| `max_output_tokens` | int | **FORBIDDEN on chatgpt.com/backend-api/codex** | Hermes explicitly skips it: `if max_tokens is not None and not is_codex_backend: kwargs["max_output_tokens"] = max_tokens` (`agent/transports/codex.py:123-125`). Codex Rust `ResponsesApiRequest` has no such field at all (`codex-api/src/common.rs:117-133`). Production 2026-04-27: every request → 400 `"Unsupported parameter: max_output_tokens"`. | Hermes `transports/codex.py:124`; Codex Rust struct; production logs |
| `max_tokens` | int | FORBIDDEN | Not a Responses-API field on any backend. | Codex Rust struct (absent) |
| `top_p`, `presence_penalty`, `frequency_penalty`, `seed`, `n`, `stop`, `logprobs` | — | FORBIDDEN | None appear in `ResponsesApiRequest`; Plus backend rejects Chat-Completions-only fields. | Codex Rust struct |

Hermes `codex_responses_adapter._preflight_codex_api_kwargs` (`agent/codex_responses_adapter.py:466-565`) keeps an explicit allowlist: `{model, input, instructions, tools, tool_choice, parallel_tool_calls, store, stream, reasoning, include, max_output_tokens, temperature, ...}` — but the `max_output_tokens` branch is reachable only for non-Codex Responses endpoints because `build_kwargs` strips it before reaching the preflight when `is_codex_backend=True`.

## Reference implementations

### Hermes Agent — `agent/transports/codex.py`

Source: `/Users/mango/workspace/hermes-agent/agent/transports/codex.py:92-130`

```python
kwargs = {
    "model": model,
    "instructions": instructions,
    "input": _chat_messages_to_responses_input(payload_messages),
    "tools": _responses_tools(tools),
    "tool_choice": "auto",
    "parallel_tool_calls": True,
    "store": False,
}
if not is_github_responses and session_id:
    kwargs["prompt_cache_key"] = session_id
if reasoning_enabled and is_xai_responses:
    kwargs["include"] = ["reasoning.encrypted_content"]
elif reasoning_enabled:
    if is_github_responses:
        ...
    else:
        kwargs["reasoning"] = {"effort": reasoning_effort, "summary": "auto"}
        kwargs["include"] = ["reasoning.encrypted_content"]
elif not is_github_responses and not is_xai_responses:
    kwargs["include"] = []
max_tokens = params.get("max_tokens")
if max_tokens is not None and not is_codex_backend:   # <-- the gate
    kwargs["max_output_tokens"] = max_tokens
```

`stream=True` is implicit via `client.responses.stream(**kwargs)` in `run_agent.py:4713` / `:4827`.

### OpenClaw — `src/agents/openai-transport-stream.ts`

Source: `/Users/mango/workspace/openclaw/src/agents/openai-transport-stream.ts:724-778` (`buildOpenAIResponsesParams`).

```ts
const params: OpenAIResponsesRequestParams = {
  model: model.id,
  input: messages,
  stream: true,
  prompt_cache_key: cacheRetention === "none" ? undefined : options?.sessionId,
  prompt_cache_retention: getPromptCacheRetention(model.baseUrl, cacheRetention),
  ...(metadata ? { metadata } : {}),
};
if (options?.maxTokens) { params.max_output_tokens = options.maxTokens; }   // PAYG path
...
applyOpenAIResponsesPayloadPolicy(params, payloadPolicy);   // sets store:false for Codex
```

`payloadPolicy.storeMode = "disable"` (line 741) → `applyOpenAIResponsesPayloadPolicy` writes `store: false` (`openai-responses-payload-policy.ts:141-143`). Codex callers pass `options.maxTokens = undefined`, leaving `max_output_tokens` unset. Headers come from `provider-attribution.ts:365-383` (`originator`, `version`, `User-Agent`).

The plugin descriptor `extensions/openai/openai-codex-provider.ts:38` defines `OPENAI_CODEX_BASE_URL = "https://chatgpt.com/backend-api"`; transport appends `/codex/responses`.

### Codex CLI (Rust) — `codex-rs/codex-api/src/common.rs:117-133`

```rust
#[derive(Serialize, Debug)]
pub struct ResponsesApiRequest {
    pub model: String,
    #[serde(skip_serializing_if = "String::is_empty")]
    pub instructions: String,
    pub input: Vec<ResponseItem>,
    pub tools: Vec<serde_json::Value>,
    pub tool_choice: String,
    pub parallel_tool_calls: bool,
    pub reasoning: Option<Reasoning>,
    pub store: bool,
    pub stream: bool,
    pub include: Vec<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub service_tier: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub prompt_cache_key: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub text: Option<TextControls>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub client_metadata: Option<HashMap<String, String>>,
}
```

Build site: `codex-rs/core/src/client.rs:851-923` (`build_responses_request`). **No `max_output_tokens` / `max_tokens` field exists in the struct.** Headers: `default_client.rs` inserts `originator`, `User-Agent`; `model-provider/src/auth.rs` inserts `Authorization: Bearer …` and `ChatGPT-Account-ID`.

## GEODE current state

`core/llm/providers/codex.py:228-234` (post-hotfix v0.52.6):

```python
with client.responses.stream(
    model=m,
    instructions=system or "You are a helpful assistant.",
    input=resp_input or [{"role": "user", "content": "hello"}],
    store=False,
    temperature=temperature,
) as stream:
```

Identified gaps versus the 3 references:

| Field | Hermes | OpenClaw | Codex Rust | GEODE | Action |
|-------|--------|----------|------------|-------|--------|
| `tools` | sent | sent | sent | NOT sent (agentic loop calls without tool list) | Forward `tools` arg → convert to Responses tool schema |
| `tool_choice` | `"auto"` | (sdk default) | `"auto"` | not sent | Send `"auto"` when tools present |
| `parallel_tool_calls` | `True` | (sdk default) | from prompt | not sent | Send `True` |
| `include` | `["reasoning.encrypted_content"]` when reasoning | conditional | conditional | not sent | Send `["reasoning.encrypted_content"]` for reasoning models |
| `reasoning` | `{effort, summary:"auto"}` | same | same | not sent | Send for `gpt-5.x-codex` per `effort` arg |
| `prompt_cache_key` | session_id | session_id | conv_id | not sent | Optional: session_id from agentic loop context |
| `stream` | True (via `.stream()`) | True (explicit) | True | True (via `.stream()`) | OK |
| `store` | False | False | False (non-Azure) | False | OK |
| `instructions` | sent | sent | sent | sent | OK |
| `max_output_tokens` | stripped for codex | not set for codex | absent | removed in v0.52.6 | OK |

Also: GEODE drops `tools`/`tool_choice` arguments inside `agentic_call` — the agentic tool loop receives no Codex-side tool dispatch. This is a separate bug (function calling broken) but not the cause of the 400.

## Recommended request shape for GEODE

Minimum viable (matches Codex Rust struct):

```python
client.responses.stream(
    model=model,
    instructions=system or DEFAULT_INSTRUCTIONS,
    input=resp_input,
    tools=_to_responses_tools(tools),
    tool_choice="auto" if tools else "none",
    parallel_tool_calls=True,
    store=False,
    stream=True,                                    # implicit via .stream()
    include=["reasoning.encrypted_content"] if _is_reasoning(model) else [],
    reasoning={"effort": effort, "summary": "auto"} if _is_reasoning(model) else None,
    # Optional: prompt_cache_key=session_id,
    # NEVER: max_output_tokens, max_tokens, top_p, frequency_penalty, seed
)
```

Reasoning per field:

- `tools`/`tool_choice`/`parallel_tool_calls`: required by Codex agentic loop; absent → no function calling.
- `include`+`reasoning`: gpt-5.x-codex models return reasoning blocks; without `include` the encrypted reasoning is dropped, breaking multi-turn continuity.
- `store=False`: Plus backend has no server-state; `store=True` returns 400.
- `stream=True`: backend rejects non-streaming responses for Plus quota.
- omit `max_output_tokens`: server-managed quota; param triggers 400.
- omit `temperature` for `gpt-5.x-codex` (Hermes `_fixed_temperature_for_model` returns `OMIT_TEMPERATURE` for these). GEODE currently sends `temperature` unconditionally — low priority but should be model-gated.

## Sources

All retrieved 2026-04-27.

- Hermes Agent (local): `/Users/mango/workspace/hermes-agent/agent/transports/codex.py:14-130`, `/Users/mango/workspace/hermes-agent/agent/codex_responses_adapter.py:466-565`, `/Users/mango/workspace/hermes-agent/run_agent.py:4698-4827`, `/Users/mango/workspace/hermes-agent/hermes_cli/auth.py:70` (`DEFAULT_CODEX_BASE_URL`), `/Users/mango/workspace/hermes-agent/hermes_cli/providers.py:61`.
- OpenClaw (local): `/Users/mango/workspace/openclaw/extensions/openai/openai-codex-provider.ts:1-373`, `/Users/mango/workspace/openclaw/src/agents/openai-transport-stream.ts:724-778`, `/Users/mango/workspace/openclaw/src/agents/openai-responses-payload-policy.ts:91-162`, `/Users/mango/workspace/openclaw/src/agents/provider-attribution.ts:340-383, 460-606`.
- Codex CLI (Rust, GitHub `openai/codex@main`):
  - `codex-rs/codex-api/src/common.rs:117-133` — `ResponsesApiRequest` struct (https://github.com/openai/codex/blob/main/codex-rs/codex-api/src/common.rs)
  - `codex-rs/core/src/client.rs:851-923` — `build_responses_request` (https://github.com/openai/codex/blob/main/codex-rs/core/src/client.rs)
  - `codex-rs/login/src/auth/default_client.rs` — `originator`, `User-Agent` headers (https://github.com/openai/codex/blob/main/codex-rs/login/src/auth/default_client.rs)
  - `codex-rs/model-provider/src/auth.rs` — `Authorization` + `ChatGPT-Account-ID` headers (https://github.com/openai/codex/blob/main/codex-rs/model-provider/src/auth.rs)
  - `codex-rs/model-provider-info/src/lib.rs` — `default_base_url = "https://chatgpt.com/backend-api/codex"` for `AuthMode::Chatgpt` (https://github.com/openai/codex/blob/main/codex-rs/model-provider-info/src/lib.rs)
  - `codex-rs/codex-api/src/endpoint/responses.rs` — `RESPONSES_ENDPOINT = "/responses"` (https://github.com/openai/codex/blob/main/codex-rs/codex-api/src/endpoint/responses.rs)
- GEODE current (this repo): `core/llm/providers/codex.py:104-244`, `core/config.py:383-386`.
- Production incident: GEODE serve logs 2026-04-27 — every Codex call → 400 `"Unsupported parameter: max_output_tokens"`, all 4 retries × 3 fallback models → circuit breaker OPEN ~30s.
