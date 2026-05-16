# Provider Login — Architecture SOT

> GEODE 의 LLM provider 별 credential 획득 path 의 정합 spec. OpenAI
> (Codex CLI Plus) 와 Anthropic (Claude subscription) 의 OAuth flow 가
> 동일 owned-credential 패턴 — `~/.geode/auth.toml` 가 SOT, GEODE 가
> 직접 OAuth client, claude CLI 같은 외부 binary 의존성 0.

## 1. 두 provider 의 정합 — owned-credential 패턴

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
(device-code)       (PKCE redirect)
  ↓                     ↓
  POST /v1/oauth/token (모두)
            ↓
  ~/.geode/auth.toml  ← GEODE-owned SOT
            ↓
  ProfileStore.add(AuthProfile(...))
            ↓
  reset_<provider>_client()  ← in-process cache invalidation
```

두 provider 의 차이점은 **OAuth grant type** 만 — OpenAI = device-code,
Anthropic = PKCE redirect. 그 외 (storage, refresh, client reset) 는
모두 정합.

## 2. OpenAI flow (device-code grant) — 기존

| 단계 | 동작 |
|---|---|
| 1 | GEODE 가 `POST https://auth.openai.com/oauth/device/code` |
| 2 | response: `device_code`, `user_code`, `verification_uri` |
| 3 | console 에 verification URL + user_code 표시. 사용자가 browser 에서 입력 |
| 4 | GEODE 가 background poll `POST /oauth/token` (5초 간격) |
| 5 | response: `access_token` (JWT, `chatgpt_plan_type` 등 claim 보유), `refresh_token` |
| 6 | `_persist_oauth_to_authtoml(creds)` → `~/.geode/auth.toml` |
| 7 | `reset_codex_client()` — in-process codex client cache invalidate |

구현: `core/auth/oauth_login.py::login_openai`

## 3. Anthropic flow (PKCE redirect grant) — 신규 (PR C3)

| 단계 | 동작 |
|---|---|
| 1 | `code_verifier = base64url(secrets.token_bytes(96))` |
| 2 | `code_challenge = base64url(SHA256(code_verifier))` |
| 3 | GEODE 가 loopback HTTP server `:3000` 시작 (callback 받기 위해) |
| 4 | `webbrowser.open("https://platform.claude.com/oauth/authorize?response_type=code&client_id=<CLAUDE_OAUTH_CLIENT_ID>&redirect_uri=http://localhost:3000/callback&code_challenge=<challenge>&code_challenge_method=S256&scope=<space-separated>&state=<random>")` |
| 5 | 사용자 browser 에서 Anthropic 로그인 + 동의 |
| 6 | Anthropic 가 `GET http://localhost:3000/callback?code=...&state=...` |
| 7 | GEODE callback server 가 `code` 수신, browser 에 "로그인 완료" HTML |
| 8 | `POST https://api.anthropic.com/v1/oauth/token` (`anthropic-beta: oauth-2025-04-20` header) — grant_type=authorization_code, code, redirect_uri, client_id, code_verifier |
| 9 | response: `access_token` (`sk-ant-oat01-...`), `refresh_token` (`sk-ant-ort01-...`), `expires_in`, `scopes` |
| 10 | `~/.geode/auth.toml` 의 `[oauth.anthropic-claude-code]` section 에 저장 |
| 11 | `reset_anthropic_client()` — `inspect_ai` stock `AnthropicAPI` per-request 라 cache 없음. claude-code provider 의 in-process state 만 invalidate |

### 3.1 OAuth endpoints (Anthropic)

발견된 endpoint (`claude-code` native binary 의 strings 분석):

| Endpoint | URL |
|---|---|
| Authorize | `https://platform.claude.com/oauth/authorize` |
| Token | `https://api.anthropic.com/v1/oauth/token` |
| Hello (validation) | `https://api.anthropic.com/v1/oauth/hello` |
| Override env | `CLAUDE_CODE_CUSTOM_OAUTH_URL` |

### 3.2 client_id

Claude Code 의 public OAuth client (PKCE — no secret). 코드 안에서
`core.auth.oauth_login.CLAUDE_OAUTH_CLIENT_ID` 상수로 노출.

## 4. ToS 정합성 — owned-Anthropic 의 위치

본 architecture 의 정책적 위치는 GEODE 가 claude CLI 의 OAuth client_id
를 재사용하여 PKCE flow 를 직접 수행한다는 의미 — 다음 5 단계 spectrum
에서 **Tier 3 (impersonation, 사용자 자기-책임)**:

| Tier | Path | ToS 강도 |
|---|---|---|
| 0 | `ANTHROPIC_API_KEY` env + stock `anthropic/` provider | ✅ 명시 허용 |
| 1 | Anthropic API key + GEODE 직접 발급 (developer portal) | ✅ |
| 2 | claude CLI subprocess + keychain read-only (PR #1202) | ⚠️ third-party harness — gray, low risk |
| **3** | **claude CLI 의 client_id reuse + PKCE 직접 수행 (본 PR C3)** | ⚠️⚠️ **impersonation — gray, medium risk** |
| 4 | User-Agent / IP spoofing | ❌ 명시 회피 — 권장 X |

### 4.1 Tier 3 의 정확한 trade-off

| 측면 | 본 path |
|---|---|
| Anthropic 의 시각 | claude CLI 의 OAuth client 의 traffic 으로 분류 — 단 UA/IP 가 GEODE 임을 분석 시 식별 가능 |
| Detect 확률 | 본인 사용 (single IP, normal cadence) 에서는 매우 낮음 |
| Revocation risk | medium — Anthropic 측이 본 client_id 의 non-CLI traffic 을 block 시 본 path 작동 정지 |
| Mitigation | ① 첫 활성 WARNING (`_warn_policy_once`) 으로 사용자 자기-책임 인정 ② API key fallback 보장 ③ `production` / 외부 publish 시 Tier 0 권장 |

### 4.2 본 architecture 의 fallback path

본 spec 의 신뢰 보존을 위해:

1. Anthropic 측의 client_id revocation 시 → `login_anthropic()` 가 명시
   error message + Tier 0 (API key) 권장
2. `~/.geode/auth.toml` 의 anthropic profile 갱신 실패 시 → 사용자가
   `ANTHROPIC_API_KEY` env 또는 `/login add` wizard 의 PAYG path 사용
3. PR #1202 의 macOS keychain read 도 backwards-compat 으로 유지 —
   기존 claude CLI 사용자가 즉시 사용 가능

## 5. mismatch 분석 — PR C3 이전 상태

| # | Mismatch | OpenAI | Anthropic (PR #1202 → C3 후) |
|---|---|---|---|
| M1 | OAuth client ownership | owned (GEODE) | borrowed (claude CLI) → **owned (GEODE, Tier 3)** |
| M2 | Token storage | `~/.geode/auth.toml` | macOS keychain → **`~/.geode/auth.toml`** |
| M3 | Cross-platform | 모든 OS | macOS only → **모든 OS** |
| M4 | Reset hook | `reset_codex_client()` | (없음) → **`reset_anthropic_client()`** |
| M5 | Token refresh | refresh_token + auth.toml 재기록 | claude CLI 가 자체 refresh → **refresh_token + auth.toml 재기록** |

본 C3 PR 머지 후 모든 5 mismatch 해소.

## 6. 호환성 정책

| 시나리오 | 동작 |
|---|---|
| 기존 사용자 (PR #1202 의 keychain token 보유) | `resolve_claude_oauth_token()` 의 fallback path 가 keychain 먼저, auth.toml 차순. 두 source 의 token 동일 시 의미 X |
| 새 사용자 (auth.toml only) | `login_anthropic()` 로 새로 발급 → auth.toml |
| API key 사용자 | `anthropic_credential_source = "api_key"` 의 routing 그대로 — OAuth path 안 거침 |
| `none` 사용자 | anthropic provider 비활성 — error |

## 7. SOT

- 본 spec: `docs/architecture/provider-login.md`
- OpenAI 구현: `core/auth/oauth_login.py::login_openai` (PR #1133 이전)
- Anthropic 구현: `core/auth/oauth_login.py::login_anthropic` (PR C3, 예정)
- `/login` UI: `core/cli/commands/login.py`
- credential source picker: `core/cli/commands/login.py::_login_source` (PR #1209)
- routing: `plugins/petri_audit/models.py::to_inspect_model` (PR #1203)
- ToS 정책 위치: `plugins/petri_audit/claude_code_provider.py` 의 module docstring (PR #1202)
