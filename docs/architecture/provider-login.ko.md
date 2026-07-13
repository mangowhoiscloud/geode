# Provider Login -- Architecture SOT

> [English](provider-login.md) | **한국어**

> GEODE의 LLM provider별 credential 획득 경로에 대한 정합 spec입니다.
> OpenAI(Codex CLI Plus)와 Anthropic(Claude subscription)의 OAuth flow는
> 동일한 owned-credential 패턴을 따릅니다. `~/.geode/auth.toml`이 SOT이고,
> GEODE가 직접 OAuth client 역할을 하며, claude CLI 같은 외부 binary
> 의존성은 없습니다.

## 1. 두 provider의 정합 -- owned-credential 패턴

```
사용자 → /login <provider>
            ↓
  core.cli.commands.login._login_oauth(provider)
            ↓
  ┌─────────────────────┬─────────────────────┐
  ↓                     ↓                     ↓
openai 분기          anthropic 분기        그 외 → warn
  ↓                     ↓
login_openai()      login_anthropic()
(device-code)       (PKCE + manual-paste)
  ↓                     ↓
  POST /v1/oauth/token (모두)
            ↓
  ~/.geode/auth.toml  ← GEODE-owned SOT
            ↓
  ProfileStore.add(AuthProfile(...))
            ↓
  reset_<provider>_client()  ← in-process cache invalidation
```

두 provider의 차이는 **OAuth grant type**뿐입니다. OpenAI = device-code,
Anthropic = PKCE + manual-paste. 그 외(storage, refresh, client reset)는
모두 정합합니다.

## 2. OpenAI flow (device-code grant) -- 기존

| 단계 | 동작 |
|---|---|
| 1 | GEODE가 `POST https://auth.openai.com/oauth/device/code` 호출 |
| 2 | response: `device_code`, `user_code`, `verification_uri` |
| 3 | console에 verification URL + user_code 표시. 사용자가 browser에서 입력 |
| 4 | GEODE가 background에서 `POST /oauth/token` poll (5초 간격) |
| 5 | response: `access_token` (JWT, `chatgpt_plan_type` 등 claim 보유), `refresh_token` |
| 6 | `_persist_oauth_to_authtoml(creds)` → `~/.geode/auth.toml` |
| 7 | `reset_codex_client()` -- in-process codex client cache 무효화 |

구현: `core/auth/oauth_login.py::login_openai`

## 3. Anthropic flow (PKCE + manual-paste) -- PR C3 + v0.99.1 fix

PR C3의 초기 구현은 loopback callback(`http://localhost:54123/callback`)을
시도했으나, OAuth client `9d1c250a-…`에 사전 등록된 redirect URI는 서버 측
`https://platform.claude.com/oauth/code/callback` 단 하나이며, loopback은
authorize 단계에서 거절된다는 사실이 v0.99.1에서 확인됐습니다. 우회가
불가능하므로 flow를 Claude Code의 manual-paste 패턴 1:1 미러로 교체했습니다.

| 단계 | 동작 |
|---|---|
| 1 | `code_verifier = base64url(secrets.token_bytes(96))` |
| 2 | `code_challenge = base64url(SHA256(code_verifier))` |
| 3 | `webbrowser.open("https://platform.claude.com/oauth/authorize?code=true&response_type=code&client_id=<CLAUDE_OAUTH_CLIENT_ID>&redirect_uri=https://platform.claude.com/oauth/code/callback&code_challenge=<challenge>&code_challenge_method=S256&scope=user:inference+user:profile+user:sessions:claude_code+user:mcp_servers&state=<random>")` |
| 4 | 사용자가 browser에서 Anthropic 로그인 + 동의 |
| 5 | Anthropic이 `/oauth/code/callback` 페이지에 `code#state` 형식으로 표시 |
| 6 | 사용자가 CLI의 `Paste authorization code:` 프롬프트에 붙여넣기 (URL, `code#state`, bare code 모두 허용 -- `_parse_pasted_code`) |
| 7 | GEODE가 state 검증 + `POST https://platform.claude.com/v1/oauth/token` (`Content-Type: application/json`, `anthropic-beta` header 없음 -- claude.exe binary의 `h6.post` 호출 site와 정합) -- JSON body: grant_type=authorization_code, code, redirect_uri, client_id, code_verifier, state |
| 8 | response: `access_token` (`sk-ant-oat01-...`), `refresh_token` (`sk-ant-ort01-...`), `expires_in`, `scopes` |
| 9 | `~/.geode/auth.toml`의 `[providers.anthropic]` section에 저장 |
| 10 | `reset_anthropic_client()` -- `inspect_ai` stock `AnthropicAPI`는 per-request라 cache가 없음. claude-code provider의 in-process state만 무효화 |

### 3.1 OAuth endpoints (Anthropic)

발견된 endpoint(`claude-code` native binary의 strings 분석):

| Endpoint | URL |
|---|---|
| Authorize | `https://platform.claude.com/oauth/authorize` |
| Token | `https://platform.claude.com/v1/oauth/token` |
| Manual redirect | `https://platform.claude.com/oauth/code/callback` |
| Override env | `CLAUDE_CODE_CUSTOM_OAUTH_URL` |

### 3.2 client_id

Claude Code의 public OAuth client입니다(PKCE, secret 없음). 코드 안에서는
`core.auth.oauth_login.CLAUDE_OAUTH_CLIENT_ID` 상수로 노출됩니다.

## 4. ToS 정합성 -- owned-Anthropic의 위치

이 architecture의 정책적 위치는 GEODE가 claude CLI의 OAuth client_id를
재사용하여 PKCE flow를 직접 수행한다는 의미이며, 아래 5단계 spectrum에서
**Tier 3(impersonation, 사용자 자기 책임)**에 해당합니다.

| Tier | Path | ToS 강도 |
|---|---|---|
| 0 | `ANTHROPIC_API_KEY` env + stock `anthropic/` provider | ✅ 명시 허용 |
| 1 | Anthropic API key + GEODE 직접 발급 (developer portal) | ✅ |
| 2 | claude CLI subprocess + keychain read-only (PR #1202) | ⚠️ third-party harness -- gray, low risk |
| **3** | **claude CLI의 client_id 재사용 + PKCE 직접 수행 (본 PR C3)** | ⚠️⚠️ **impersonation -- gray, medium risk** |
| 4 | User-Agent / IP spoofing | ❌ 명시 회피 -- 권장하지 않음 |

### 4.1 Tier 3의 정확한 trade-off

| 측면 | 이 path |
|---|---|
| Anthropic의 시각 | claude CLI의 OAuth client traffic으로 분류됨. 단, UA/IP 분석 시 GEODE임을 식별 가능 |
| 탐지 확률 | 본인 사용(single IP, normal cadence)에서는 매우 낮음 |
| Revocation risk | medium -- Anthropic이 이 client_id의 non-CLI traffic을 차단하면 이 path는 작동을 멈춤 |
| Mitigation | ① 첫 활성화 시 WARNING(`_warn_policy_once`)으로 사용자 자기 책임 인정 ② API key fallback 보장 ③ `production` / 외부 publish 시 Tier 0 권장 |

### 4.2 이 architecture의 fallback path

이 spec의 신뢰 보존을 위해:

1. Anthropic이 client_id를 revoke하면 → `login_anthropic()`이 명시적
   error message와 함께 Tier 0(API key)을 권장합니다
2. `~/.geode/auth.toml`의 anthropic profile 갱신이 실패하면 → 사용자가
   `ANTHROPIC_API_KEY` env 또는 `/login add` wizard의 PAYG path를
   사용합니다
3. PR #1202의 macOS keychain read도 backwards-compat으로 유지되어, 기존
   claude CLI 사용자가 즉시 사용할 수 있습니다

## 5. mismatch 분석 -- PR C3 이전 상태

| # | Mismatch | OpenAI | Anthropic (PR #1202 → C3 후) |
|---|---|---|---|
| M1 | OAuth client ownership | owned (GEODE) | borrowed (claude CLI) → **owned (GEODE, Tier 3)** |
| M2 | Token storage | `~/.geode/auth.toml` | macOS keychain → **`~/.geode/auth.toml`** |
| M3 | Cross-platform | 모든 OS | macOS only → **모든 OS** |
| M4 | Reset hook | `reset_codex_client()` | (없음) → **`reset_anthropic_client()`** |
| M5 | Token refresh | refresh_token + auth.toml 재기록 | claude CLI가 자체 refresh → **refresh_token + auth.toml 재기록** |

이 C3 PR 머지 후 5개 mismatch가 모두 해소됩니다.

## 6. 호환성 정책

| 시나리오 | 동작 |
|---|---|
| 기존 사용자 (PR #1202의 keychain token 보유) | `resolve_claude_oauth_token()`의 fallback path가 keychain을 먼저, auth.toml을 다음으로 확인. 두 source의 token이 동일하면 차이 없음 |
| 새 사용자 (auth.toml only) | `login_anthropic()`으로 새로 발급 → auth.toml |
| API key 사용자 | `anthropic_credential_source = "api_key"` routing 그대로 -- OAuth path를 거치지 않음 |
| `none` 사용자 | anthropic provider 비활성 -- error |

## 7. SOT

- 이 spec: `docs/architecture/provider-login.md`
- OpenAI 구현: `core/auth/oauth_login.py::login_openai` (PR #1133 이전)
- Anthropic 구현: `core/auth/oauth_login.py::login_anthropic` (PR C3, 예정)
- `/login` UI: `core/cli/commands/login.py`
- credential source picker: `core/cli/commands/login.py::_login_source` (PR #1209)
- routing: `plugins/petri_audit/models.py::to_inspect_model` (PR #1203)
- ToS 정책 위치: `plugins/petri_audit/claude_code_provider.py`의 module docstring (PR #1202)
