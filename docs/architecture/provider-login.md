# Provider Login -- Architecture SOT

> **English** | [한국어](provider-login.ko.md)

GEODE supports OpenAI Codex subscription credentials and ordinary PAYG API
keys. Anthropic and OpenRouter have API-key-only built-in routes.

## Runtime paths

| Provider | Source | Authentication owner | Execution path |
|---|---|---|---|
| OpenAI | `openai-codex` / legacy `oauth` | GEODE/Codex profile | Codex Responses adapter |
| OpenAI | `api_key` | `OPENAI_API_KEY` | OpenAI PAYG adapter |
| Anthropic | `api_key` / `auto` | `ANTHROPIC_API_KEY` | Anthropic Messages adapter |
| OpenRouter | `api_key` | `OPENROUTER_API_KEY` | OpenRouter Chat Completions adapter |
| Any provider | `none` | none | fail closed as provider-disabled |

The retired Anthropic values `claude-cli` and `oauth` still parse so existing
configuration can receive an actionable migration error. They never invoke a
binary, inspect CLI credentials, or fall through to PAYG silently. Use:

```toml
anthropic_credential_source = "api_key"
```

and configure `ANTHROPIC_API_KEY`. `/login anthropic` now configures that
API-key route. Historical `.eval`, trajectory, and receipt readers continue to
recognize old source labels without making them executable.

## Source of truth

- source selection: `core/cli/commands/login.py`
- runtime inference: `core/llm/adapters/_source_inference.py`
- legacy rejection message: `core/config/credential_source.py`
- OpenAI login: `core/auth/oauth_login.py::login_openai`
