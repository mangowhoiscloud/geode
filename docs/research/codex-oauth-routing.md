# Codex OAuth Token Routing — Cross-Codebase Research

> GEODE, OpenClaw, Hermes Agent 3개 코드베이스 실측 기반

## 핵심 발견

**Codex OAuth 토큰은 `api.openai.com`에 직접 호출할 수 없다.**
`aud=api.openai.com/v1`이지만 scope가 제한되어 `model.request`, `api.responses.write` 등 누락.
**대신 `chatgpt.com/backend-api` 경유로 Plus 쿼터를 사용한다.**

## Token 구조

```
JWT Claims:
  aud: ["https://api.openai.com/v1"]   ← 타겟은 openai이지만...
  iss: https://auth.openai.com
  scope: (제한됨 — model.request 없음)  ← ...scope 부족으로 직접 호출 불가
```

## 실측: api.openai.com 직접 호출 결과

```
GET  /v1/models           → 403 (Missing scopes: api.model.read)
POST /v1/chat/completions → 403 (Missing scopes: model.request)
POST /v1/responses        → 403 (Missing scopes: api.responses.write)
```

## 각 코드베이스의 해법

### OpenClaw — Base URL 리라이팅

**파일**: `extensions/openai/openai-codex-provider.ts:38-112`

```typescript
const OPENAI_CODEX_BASE_URL = "https://chatgpt.com/backend-api";

// Codex 토큰 감지 시 자동 리라이팅
function normalizeCodexTransport(model) {
  const api = "openai-codex-responses";      // ← API 프로토콜 변경
  const baseUrl = OPENAI_CODEX_BASE_URL;     // ← 엔드포인트 변경
}
```

| 조건 | api | baseUrl |
|------|-----|---------|
| API Key | `openai-responses` | `https://api.openai.com/v1` |
| Codex Token | `openai-codex-responses` | `https://chatgpt.com/backend-api` |

**사용량 조회**: `chatgpt.com/backend-api/wham/usage` (WHAM endpoint)

### Hermes Agent — 별도 세션 + Cloudflare 헤더

**파일**: `hermes_cli/auth.py:118-123`, `runtime_provider.py:587-605`

```python
"openai-codex": ProviderConfig(
    id="openai-codex",
    auth_type="oauth_external",
    inference_base_url="https://chatgpt.com/backend-api/codex",  # ← 핵심
)
```

**차이점**:
1. `~/.hermes/auth.json`에 별도 세션 유지 (refresh token 충돌 방지)
2. `api_mode = "codex_responses"` → `client.responses.stream()` 사용
3. Cloudflare 우회 헤더 주입:

```python
# agent/auxiliary_client.py:198-240
headers = {
    "User-Agent": "codex_cli_rs/0.0.0 (Hermes Agent)",
    "originator": "codex_cli_rs",
    "ChatGPT-Account-ID": <JWT에서 추출>,
}
```

### GEODE — 현재 상태 (미구현)

```python
# 현재: api.openai.com으로 직접 호출 시도 → scope 부족 → 401
# fallback: openai:default (API key)로 자동 전환
```

## 비교 매트릭스

| 항목 | OpenClaw | Hermes Agent | GEODE (현재) |
|------|----------|-------------|-------------|
| **토큰 저장** | `~/.codex/auth.json` 읽기 | `~/.hermes/auth.json` (별도) | `~/.codex/auth.json` 읽기 |
| **base_url** | `chatgpt.com/backend-api` | `chatgpt.com/backend-api/codex` | `api.openai.com/v1` (실패) |
| **API 프로토콜** | `openai-codex-responses` | `codex_responses` | `openai` (호환 안 됨) |
| **Cloudflare 헤더** | 자체 처리 | `_codex_cloudflare_headers()` | 없음 |
| **Plus 쿼터 사용** | 가능 | 가능 | **불가** (API key fallback) |
| **refresh 충돌** | 가능성 있음 | 별도 세션으로 방지 | 가능성 있음 |

## GEODE 적용 방향

Codex OAuth로 Plus 쿼터를 사용하려면:

1. **base_url 리라이팅**: `api.openai.com` → `chatgpt.com/backend-api/codex`
2. **API 프로토콜**: Chat Completions → Responses API (`client.responses`)
3. **Cloudflare 헤더**: `ChatGPT-Account-ID` + `originator` 주입
4. **provider 분리**: `openai` vs `openai-codex` 구분 (OpenClaw/Hermes 공통 패턴)

### 복잡도 평가

| 작업 | 난이도 | 이유 |
|------|--------|------|
| base_url 리라이팅 | 낮음 | config에 base_url 추가 |
| Responses API 지원 | **높음** | 현재 OpenAI SDK Chat Completions만 사용, Responses API 어댑터 필요 |
| Cloudflare 헤더 | 중간 | JWT 파싱 + 헤더 주입 |
| provider 분리 | 중간 | config.py + provider_dispatch.py 수정 |

### 대안: Codex MCP 서버 경유 (현재 방식)

```
GEODE (Anthropic/API key) → codex MCP 서버 → Plus 쿼터
```

이미 `.geode/config.toml`에 `[mcp.servers.codex]` 등록됨.
메인 루프는 API key로, 코드 생성은 Codex MCP로 위임하는 하이브리드 방식.
