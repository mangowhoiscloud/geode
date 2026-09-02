# Provider Login -- Architecture SOT

> [English](provider-login.md) | **한국어**

GEODE는 OpenAI Codex 구독 자격과 일반 PAYG API key를 지원합니다.
Anthropic과 OpenRouter의 내장 실행 경로는 API key뿐입니다.

## 현재 실행 경로

| Provider | Source | 인증 소유자 | 실행 경로 |
|---|---|---|---|
| OpenAI | `openai-codex` / 과거 `oauth` | GEODE/Codex profile | Codex Responses adapter |
| OpenAI | `api_key` | `OPENAI_API_KEY` | OpenAI PAYG adapter |
| Anthropic | `api_key` / `auto` | `ANTHROPIC_API_KEY` | Anthropic Messages adapter |
| OpenRouter | `api_key` | `OPENROUTER_API_KEY` | OpenRouter Chat Completions adapter |
| 모든 프로바이더 | `none` | 없음 | provider-disabled 오류로 fail closed |

퇴역한 Anthropic 값 `claude-cli`와 `oauth`는 기존 설정에 정확한 migration
오류를 보여주기 위해 파싱만 허용합니다. binary 실행, CLI credential 조회,
암묵적 PAYG 전환은 일어나지 않습니다. 다음처럼 설정하고
`ANTHROPIC_API_KEY`를 제공해야 합니다.

```toml
anthropic_credential_source = "api_key"
```

`/login anthropic`도 이제 API-key 경로를 설정합니다. 과거 `.eval`,
trajectory, receipt reader는 예전 source label을 판독하지만 실행 권한으로
해석하지 않습니다.

## Source of truth

- source 선택: `core/cli/commands/login.py`
- runtime 추론: `core/llm/adapters/_source_inference.py`
- legacy 차단 문구: `core/config/credential_source.py`
- OpenAI login: `core/auth/oauth_login.py::login_openai`
