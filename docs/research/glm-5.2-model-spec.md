# GLM-5.2 — Model Spec & GEODE Exposure Surface

> Grounded in official Zhipu / Z.ai documentation, fetched 2026-06-23. Every
> numeric / capability claim carries a source URL. Items not confirmable on an
> official page are marked **UNVERIFIED** — not guessed.

## 1. Model spec (CONFIRMED, official)

| Field | Value | Source |
|-------|-------|--------|
| API model id | `glm-5.2` (text-only) | docs.z.ai/guides/llm/glm-5.2 · docs.bigmodel.cn/cn/guide/models/text/glm-5.2 |
| Vision model | **separate** — `glm-5v-turbo` (not "glm-5.2v") | docs.z.ai/guides/vlm/glm-5v-turbo |
| Context window | 1,000,000 (1M) on the model page; the plain id over the OpenAI-compatible API uses the standard window — `glm-5.2[1m]` (DevPack/Claude-Code routing form) unlocks the full 1M + `CLAUDE_CODE_AUTO_COMPACT_WINDOW=1000000` | docs.z.ai/guides/llm/glm-5.2 · docs.z.ai/devpack/tool/claude |
| Max output tokens | 131,072 (`max_tokens` max; default unstated) | docs.z.ai/api-reference/llm/chat-completion |
| Input price | $1.40 / 1M | docs.z.ai/guides/overview/pricing |
| Cached input price | $0.26 / 1M (storage free, limited-time) | docs.z.ai/guides/overview/pricing |
| Output price | $4.40 / 1M | docs.z.ai/guides/overview/pricing |
| Reasoning / thinking | Yes — `thinking={"type": "enabled"\|"disabled"}` (default `enabled`) + `reasoning_effort` ∈ {max,xhigh,high,medium,low,minimal,none} (default **max**, GLM-5.2-only) | docs.z.ai/api-reference/llm/chat-completion |
| Tool / function calling | Yes (max 128 fns; `tool_choice` = `"auto"` only) | docs.z.ai/api-reference/llm/chat-completion |
| Hosted web_search | Yes (`tools` type `web_search` / `retrieval` / `function`) | docs.z.ai/api-reference/llm/chat-completion |
| Structured output | `response_format` = `text` / `json_object` only — **no `json_schema` strict mode** | docs.z.ai/api-reference/llm/chat-completion |
| Vision (image input) | No (text-in only; use `glm-5v-turbo`) | docs.z.ai/guides/llm/glm-5.2 |
| Prompt caching | Implicit/automatic; `usage.prompt_tokens_details.cached_tokens` | docs.z.ai/api-reference/llm/chat-completion |
| API surface | OpenAI-compatible `POST /api/paas/v4/chat/completions` (api.z.ai intl / open.bigmodel.cn CN); Anthropic-compatible `api.z.ai/api/anthropic`; streaming yes | docs.z.ai/api-reference/llm/chat-completion · docs.z.ai/devpack/tool/claude |
| License / weights | MIT, open (~753B MoE total) | huggingface.co/zai-org/GLM-5.2 |
| Officially-stated bench | Terminal-Bench 2.1 81.0 (vs 5.1 62.0); SWE-bench Pro 62.1 (vs 5.1 58.4, GPT-5.5 58.6) | docs.z.ai/guides/llm/glm-5.2 |

**UNVERIFIED**: exact release date (press: ~2026-06-13/16), active-param count (~40B per blogs), default `max_tokens`, RPM/TPM, `glm-5.2-air`/`-flash` (do not exist — community-requested, unreleased).

## 2. Prompt-cache note ("prefix만 안정하면")

GLM uses **implicit prefix caching** (OpenAI-style, not Anthropic's explicit
`cache_control`): the engine auto-matches the longest byte-identical leading
prefix across requests and bills it at the cached rate. GEODE does **nothing**
on the GLM path — caching is automatic. The only requirement is that the static
leading prefix stays byte-stable across turns, which GEODE already satisfies via
the static→dynamic system-prompt ordering (`<dynamic_context>` boundary). No
`cache_control` / `prompt_cache_key` is sent or needed.

## 3. GEODE exposure surface (what adding `glm-5.2` touched)

GLM routing is **prefix-based** (`glm-` → provider `glm` at `routing.toml`), so
the adapter, dispatch, auth (`glm` profile / `ZAI_API_KEY`), and family guidance
(`model_guidance._GLM_SUPPORTED_RE`) accept a new GLM id automatically — no edit.
A new id only needs registration where code holds a literal set/menu of GLM ids:

| # | Surface | Edit | Class |
|---|---------|------|-------|
| 1 | `core/llm/model_pricing.toml` `[pricing.openai."glm-5.2"]` | input 1.40 / output 4.40 (no `cached_per_mtok` — see §4) | MUST (else cost = $0) |
| 2 | `core/llm/model_pricing.toml` `[context_windows]` | `"glm-5.2" = 202752` (see §4) | MUST (else 200K default) |
| 3 | `core/cli/commands/_state.py` `get_model_profiles()` | `ModelProfile("glm-5.2","glm","GLM-5.2","$")` | MUST for interactive `/model glm-5.2` (env `GEODE_MODEL=glm-5.2` bypasses) |
| 4 | `core/cli/effort_picker.py` `_GLM_ALWAYS_ON_MODELS` + `_MODEL_DESCRIPTIONS` | add id + blurb | OPTIONAL (classification / UX) |
| 5 | `core/cli/commands/login.py` GLM route hints (`set_routing` + `model_hints`) | add `glm-5.2` (flagship lead) | OPTIONAL (GLM Coding-Plan auto-pin) |
| 6 | `core/llm/strategies/plans.py` `GLM_CODING_TIERS` quota `model_weights` | add `"glm-5.2": 3.0` to all 3 tiers | OPTIONAL (Coding-Plan quota weight; default else) |

**No edit (auto):** `routing.toml` `"glm-" = "glm"`; `adapters/dispatch.py`
(routes by provider+source, model id passthrough); `provider_dispatch.py`;
`auth_toml.py` (`glm` profile via `ZAI_API_KEY`); `model_guidance.py`
(`_GLM_SUPPORTED_RE = glm-(\d+)`, min major 5); `is_model_allowed` (empty policy
= all allowed).

**Not a surface (avoid wasted edits):** `model_capabilities.py` (Anthropic-only);
`_openai_common.get_openai_model_spec` (OpenAI/Codex only — GLM adapters build
kwargs directly); `glm_payg.list_models()` (derives ids from config).

## 4. Deferred / caveats (not wired in this PR)

- **1M context**: the plain `glm-5.2` id over the PAYG OpenAI-compatible endpoint
  uses the standard window; the 1M form (`glm-5.2[1m]`) is a DevPack/Claude-Code
  routing convention GEODE's PAYG adapter does not use. Context window kept at the
  GLM-family `202752` (conservative — never over-claims headroom). Bump only if
  GEODE adopts the `[1m]` form.
- **`reasoning_effort` / `thinking`**: GLM-5.2 exposes both, but the GLM adapter
  (`glm_payg` / `glm_coding_plan`) sets `supports_thinking=False` and does not send
  them, so the model runs at the GLM server default (`reasoning_effort=max` = heavy
  thinking + token spend). Wiring the effort/thinking knob through the GLM adapter
  (and reclassifying `glm-5.2` from `_GLM_ALWAYS_ON_MODELS` to a hybrid set) is a
  follow-up — surfacing the knob before the adapter consumes it would be a
  picker-vs-adapter disconnect.
- **`json_schema`**: GLM-5.2 supports only `json_object`, not strict `json_schema`.
  GEODE's response-schema path falls back to prompt-engineered JSON for GLM (no
  change needed).
- **Default GLM model**: unchanged (`GLM_PRIMARY` = glm-5.1). Flipping the default
  to glm-5.2 is a one-line `routing.toml [model.defaults] glm` operator decision.
- **GLM cached-token accounting** (pre-existing, all GLM): `translate_chat_response`
  (`_openai_common.py`) builds `UsageSummary` from `prompt_tokens` / `completion_tokens`
  only — it never reads `usage.prompt_tokens_details.cached_tokens`, so the GLM cost
  path is blind to cached tokens. GLM-5.2's official cached rate is $0.26/MTok, but a
  `cached_per_mtok` in the pricing table would be parsed-but-never-applied, so it is
  omitted (family-consistent). Wiring it requires: (a) populate `cached_input_tokens`
  in `translate_chat_response`, AND (b) fix the openai-derive cost math so cached
  tokens are not double-charged (`prompt_tokens` already includes them, so
  `calculate_cost` must subtract cached from input before adding the cache-read rate —
  Anthropic splits them, OpenAI/GLM does not). A cross-cutting follow-up affecting
  every GLM (and OpenAI single-turn) model, deliberately out of this PR's scope.
