# Provider Login -- Architecture SOT

> **English** | [한국어](provider-login.ko.md)

> The alignment spec for GEODE's per-LLM-provider credential acquisition
> paths. The OAuth flows for OpenAI (Codex CLI Plus) and Anthropic (Claude
> subscription) follow the same owned-credential pattern: `~/.geode/auth.toml`
> is the SOT, GEODE acts as the OAuth client directly, with zero dependency
> on external binaries such as the claude CLI.

## 1. Alignment of the two providers -- the owned-credential pattern

```
User → /login <provider>
            ↓
  core.cli.commands.login._login_oauth(provider)
            ↓
  ┌─────────────────────┬─────────────────────┐
  ↓                     ↓                     ↓
openai branch        anthropic branch      others → warn
  ↓                     ↓
login_openai()      login_anthropic()
(device-code)       (PKCE + manual-paste)
  ↓                     ↓
  POST /v1/oauth/token (both)
            ↓
  ~/.geode/auth.toml  ← GEODE-owned SOT
            ↓
  ProfileStore.add(AuthProfile(...))
            ↓
  reset_<provider>_client()  ← in-process cache invalidation
```

The only difference between the two providers is the **OAuth grant type**:
OpenAI = device-code, Anthropic = PKCE + manual-paste. Everything else
(storage, refresh, client reset) is fully aligned.

## 2. OpenAI flow (device-code grant) -- pre-existing

| Step | Action |
|---|---|
| 1 | GEODE sends `POST https://auth.openai.com/oauth/device/code` |
| 2 | Response: `device_code`, `user_code`, `verification_uri` |
| 3 | The verification URL + user_code are shown on the console. The user enters them in a browser |
| 4 | GEODE background-polls `POST /oauth/token` (5-second interval) |
| 5 | Response: `access_token` (JWT, carrying claims such as `chatgpt_plan_type`), `refresh_token` |
| 6 | `_persist_oauth_to_authtoml(creds)` → `~/.geode/auth.toml` |
| 7 | `reset_codex_client()` -- invalidates the in-process codex client cache |

Implementation: `core/auth/oauth_login.py::login_openai`

## 3. Anthropic flow (PKCE + manual-paste) -- PR C3 + v0.99.1 fix

The initial implementation in PR C3 attempted a loopback callback
(`http://localhost:54123/callback`), but the only redirect URI pre-registered
for OAuth client `9d1c250a-…` is the server-side
`https://platform.claude.com/oauth/code/callback`; v0.99.1 confirmed that
loopback is rejected at the authorize step. Since no workaround exists, the
flow was replaced with a 1:1 mirror of Claude Code's manual-paste pattern.

| Step | Action |
|---|---|
| 1 | `code_verifier = base64url(secrets.token_bytes(96))` |
| 2 | `code_challenge = base64url(SHA256(code_verifier))` |
| 3 | `webbrowser.open("https://platform.claude.com/oauth/authorize?code=true&response_type=code&client_id=<CLAUDE_OAUTH_CLIENT_ID>&redirect_uri=https://platform.claude.com/oauth/code/callback&code_challenge=<challenge>&code_challenge_method=S256&scope=user:inference+user:profile+user:sessions:claude_code+user:mcp_servers&state=<random>")` |
| 4 | The user logs in to Anthropic in the browser and gives consent |
| 5 | Anthropic displays a `code#state`-formatted string on the `/oauth/code/callback` page |
| 6 | The user pastes it into the CLI's `Paste authorization code:` prompt (URL, `code#state`, or bare code all accepted -- `_parse_pasted_code`) |
| 7 | GEODE validates state + `POST https://platform.claude.com/v1/oauth/token` (`Content-Type: application/json`, no `anthropic-beta` header -- aligned with the `h6.post` call site in the claude.exe binary) -- JSON body: grant_type=authorization_code, code, redirect_uri, client_id, code_verifier, state |
| 8 | Response: `access_token` (`sk-ant-oat01-...`), `refresh_token` (`sk-ant-ort01-...`), `expires_in`, `scopes` |
| 9 | Stored in the `[providers.anthropic]` section of `~/.geode/auth.toml` |
| 10 | `reset_anthropic_client()` -- `inspect_ai`'s stock `AnthropicAPI` is per-request, so there is no cache. Only the claude-code provider's in-process state is invalidated |

### 3.1 OAuth endpoints (Anthropic)

Endpoints discovered (strings analysis of the `claude-code` native binary):

| Endpoint | URL |
|---|---|
| Authorize | `https://platform.claude.com/oauth/authorize` |
| Token | `https://platform.claude.com/v1/oauth/token` |
| Manual redirect | `https://platform.claude.com/oauth/code/callback` |
| Override env | `CLAUDE_CODE_CUSTOM_OAUTH_URL` |

### 3.2 client_id

Claude Code's public OAuth client (PKCE -- no secret). Exposed in code as the
`core.auth.oauth_login.CLAUDE_OAUTH_CLIENT_ID` constant.

## 4. ToS alignment -- where owned-Anthropic sits

The policy position of this architecture is that GEODE reuses the claude
CLI's OAuth client_id and performs the PKCE flow directly, which places it at
**Tier 3 (impersonation, user assumes responsibility)** on the following
5-step spectrum:

| Tier | Path | ToS strength |
|---|---|---|
| 0 | `ANTHROPIC_API_KEY` env + stock `anthropic/` provider | ✅ explicitly allowed |
| 1 | Anthropic API key + issued directly by GEODE (developer portal) | ✅ |
| 2 | claude CLI subprocess + keychain read-only (PR #1202) | ⚠️ third-party harness -- gray, low risk |
| **3** | **Reuse of the claude CLI's client_id + direct PKCE (this PR C3)** | ⚠️⚠️ **impersonation -- gray, medium risk** |
| 4 | User-Agent / IP spoofing | ❌ explicit evasion -- not recommended |

### 4.1 The exact trade-off of Tier 3

| Aspect | This path |
|---|---|
| Anthropic's view | Classified as traffic from the claude CLI's OAuth client -- but UA/IP analysis can identify it as GEODE |
| Detection probability | Very low for personal use (single IP, normal cadence) |
| Revocation risk | medium -- if Anthropic blocks non-CLI traffic on this client_id, this path stops working |
| Mitigation | ① a WARNING on first activation (`_warn_policy_once`) has the user acknowledge self-responsibility ② an API key fallback is guaranteed ③ Tier 0 is recommended for `production` / external publishing |

### 4.2 Fallback path of this architecture

To preserve trust in this spec:

1. If Anthropic revokes the client_id → `login_anthropic()` shows an explicit
   error message and recommends Tier 0 (API key)
2. If refreshing the anthropic profile in `~/.geode/auth.toml` fails → the
   user uses the `ANTHROPIC_API_KEY` env or the PAYG path of the
   `/login add` wizard
3. The macOS keychain read from PR #1202 is also kept for backwards compat --
   existing claude CLI users can use it immediately

## 5. Mismatch analysis -- state before PR C3

| # | Mismatch | OpenAI | Anthropic (PR #1202 → after C3) |
|---|---|---|---|
| M1 | OAuth client ownership | owned (GEODE) | borrowed (claude CLI) → **owned (GEODE, Tier 3)** |
| M2 | Token storage | `~/.geode/auth.toml` | macOS keychain → **`~/.geode/auth.toml`** |
| M3 | Cross-platform | all OSes | macOS only → **all OSes** |
| M4 | Reset hook | `reset_codex_client()` | (none) → **`reset_anthropic_client()`** |
| M5 | Token refresh | refresh_token + auth.toml rewrite | claude CLI refreshes on its own → **refresh_token + auth.toml rewrite** |

All 5 mismatches are resolved after this C3 PR is merged.

## 6. Compatibility policy

| Scenario | Behavior |
|---|---|
| Existing users (holding a keychain token from PR #1202) | The fallback path in `resolve_claude_oauth_token()` checks the keychain first, then auth.toml. Irrelevant when both sources hold the same token |
| New users (auth.toml only) | Freshly issued via `login_anthropic()` → auth.toml |
| API key users | The `anthropic_credential_source = "api_key"` routing is unchanged -- the OAuth path is never taken |
| `none` users | The anthropic provider is disabled -- error |

## 7. SOT

- This spec: `docs/architecture/provider-login.md`
- OpenAI implementation: `core/auth/oauth_login.py::login_openai` (predates PR #1133)
- Anthropic implementation: `core/auth/oauth_login.py::login_anthropic` (PR C3, planned)
- `/login` UI: `core/cli/commands/login.py`
- credential source picker: `core/cli/commands/login.py::_login_source` (PR #1209)
- routing: `plugins/petri_audit/models.py::to_inspect_model` (PR #1203)
- ToS policy position: the module docstring of `plugins/petri_audit/claude_code_provider.py` (PR #1202)
