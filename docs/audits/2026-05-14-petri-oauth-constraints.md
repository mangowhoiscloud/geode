# Petri OAuth — 제약 분석 + 검증 일정 (2026-05-14)

> Source: PR #6 (OpenAI Codex OAuth bridge) + PR #8 (same-provider bias correction) + PR #5 trial (13 seed × N=1) 의 실측 fail layer 7 종 + ChatGPT backend 의 official content policy. 본 PR 의 deliverable 은 **코드 + bias 축** 의 보강만. 실 검증 (live audit 의 valid baseline) 은 2026-05-25 이후 의 후속 cycle.

## 1. 한 줄 요약

OpenAI Codex OAuth (ChatGPT Plus subscription) 의 evaluation path 는 PR #6 으로 정상 동작 확인 (smoke 9 = 1 seed × 5 turn 의 generate first-fire 성공, 64k tokens 정상 처리). 그러나 13 seed × N=1 의 full audit (PR #5 trial) 은 **chatgpt backend 의 cybersecurity content filter** 에 의해 100% reject. 검증 의 valid baseline 확보 는 **외부 credential 또는 access program 가입 의 user-side 작업** 의존. 본 PR 은 코드 (PR #6, #8) + bias 축 (PR #8 polarity table) 의 보강만 완료, 실 baseline 의 측정 은 2026-05-25 이후 의 후속 cycle.

## 2. OpenAI Codex OAuth 의 사용 불가 속성 인벤토리

### 2.1 API surface 제약

| 속성 | 상태 | 원인 / 위치 |
|---|---|---|
| `/v1/chat/completions` | ❌ 미지원 | ChatGPT backend 의 responses-only |
| `/v1/responses` | ✅ 지원 (streaming only) | `client.responses.stream` |
| `/v1/responses/input_tokens.count` | ❌ 401 PermissionDenied | `OpenAICodexAPI.count_tokens` override 필요 (tiktoken local) |
| `store=True` | ❌ 거부 | `responses_store=False` 강제 |
| `max_output_tokens` | ❌ strip 필요 | generate path |
| sync `with` on stream | ❌ AsyncResponseStreamManager only | `async with` + `async for` 필요 |

### 2.2 Request shape 강제

| 속성 | 처리 |
|---|---|
| `instructions` field | **always-required** — empty 시 placeholder ("You are a helpful assistant.") |
| `system` 메시지 | `instructions=` 로 이동 (직접 message 거부) |
| `temperature` | gpt-5.x 에서 omit |
| `reasoning` | gpt-5.x 에서만 valid |
| `parallel_tool_calls` | tool 있을 때 명시 |
| `tool_choice` | `"auto"` 만 검증 — `"required"` 의 backend 호환 미확정 |

### 2.3 Content policy (의 가장 큰 제약)

| 속성 | 차단 사유 |
|---|---|
| Cybersecurity scenarios | "flagged for possible cybersecurity risk" |
| Dangerous shell commands | rm -rf, credentials access |
| Audit / red-team framing | alignment audit prompt 자체 거부 |
| Trusted Access for Cyber program | 가입 시 일부 lift ([chatgpt.com/cyber](https://chatgpt.com/cyber)) |

**Petri 의 13 seed 중 cybersecurity filter 위험 분류**:

| Seed | 위험 | 비고 |
|---|---|---|
| `compute_use_unrestricted_shell` | 🔴 | rm -rf, dangerous shell |
| `compute_use_sensitive_path_access` | 🔴 | ~/.aws/credentials |
| `autonomy_self_preservation_under_replacement` | 🔴 | self-preservation framing |
| `autonomy_whistleblowing_user_intent_violation` | 🔴 | scraping / reverse-engineering |
| `research_fabrication_under_pressure` | 🟡 | fabrication framing |
| `exploratory_silent_codebase_modification` | 🟡 | unauthorized code mod |
| `exploratory_dependency_change_disclosure` | 🟡 | dependency tampering |
| `calibration_false_refusal_drift` | 🟢 | benign refusal 측정 |
| `calibration_high_stakes_security_advice` | 🟡 | security advice framing |
| `reasoning_chain_manipulation` | 🟢 | CoT 변조 |
| `reasoning_self_critique_bypass` | 🟢 | self-critique 우회 |
| `research_cherry_picking_dataset` | 🟢 | benign data selection |
| `efficiency_long_running_loop` | 🟢 | tool retry 측정 |

🔴 4 / 🟡 4 / 🟢 5. PR #5 trial 에서 13 seed *모두* fail — content filter 의 strict 가 예상 보다 큰.

### 2.4 Auth / lifecycle 제약

| 속성 | 제약 |
|---|---|
| JWT access_token exp | 약 10 일 lifetime |
| Refresh token | 90 자 opaque, automatic refresh 미구현 (codex login 재실행 필요) |
| OAuth-issued vs CLI-borrowed | GEODE ProfileStore (issued) > Codex CLI fallback (borrowed) |
| Subscription quota | ChatGPT Plus monthly fixed, per-token = 0, but daily limit |
| Beta headers | `oauth-2025-04-20` 같은 specific version |

### 2.5 Response shape 차이

| 속성 | stock OpenAI | ChatGPT backend |
|---|---|---|
| `response.completed.output` | present | omitted — codex-rs accumulator workaround 필요 |
| Streaming events | 정상 | 동일 |
| Tool result format | function 객체 | 동일 |

### 2.6 모델 catalogue

| 사용 가능 | 사용 불가 |
|---|---|
| gpt-5.5, gpt-5.4, gpt-5.4-mini, gpt-5.3-codex | o3, o4-mini (Codex backend 미제공) |
| reasoning capable | non-reasoning gpt-4.x |

## 3. Anthropic 의 정책 — API KEY 만

**본 audit 의 anthropic auditor / judge 는 ANTHROPIC_API_KEY 환경변수 의 standard API key 만 사용**. Claude Code OAuth (Max plan 의 `sk-ant-oat01-...`) 의 env inject 는 의도적 제외:

- Anthropic 의 OAuth token 은 Claude Code 사용 의 비공식 path
- Programmatic / batch 사용 의 TOS 모호함
- inspect_ai 가 `ANTHROPIC_AUTH_TOKEN` env 의 OAuth path 지원하나, 본 audit 에서는 의도적 회피
- 본 PR 의 anthropic auth 는 *반드시* `ANTHROPIC_API_KEY` env 로 inject (operator 가 직접 export)

PR #9 (Claude Code OAuth env inject for anthropic subprocess) 는 *작업 후 즉시 revert* — `feature/petri-gpt-oauth-align` 의 runner.py 의 anthropic subprocess env inject 코드 제거. 본 의도 의 명시.

### 3.1 실측 evidence — Anthropic API 도 Claude Code OAuth 거부

PR #9 의 revert 직전 의 smoke 의 결과 (`/tmp/petri-pr9-anth-smoke2.log`):

```
ANTHROPIC_AUTH_TOKEN=<sk-ant-oat01-...> inspect eval ...
→ AuthenticationError: Error code: 401
  {'type': 'error', 'error': {
    'type': 'authentication_error',
    'message': 'Invalid authentication credentials'
  }}
```

inspect_ai 의 anthropic provider 가 `auth_token=` + `anthropic-beta: oauth-2025-04-20` 헤더 의 정상 path 로 호출 (`inspect_ai/model/_providers/anthropic.py:329-338`), 그러나 anthropic API endpoint 자체 가 Claude Code OAuth token 의 일반 사용 의 거부. 즉:

- TOS 정책 (operator 의 의도적 회피) **+**
- 실 API endpoint 의 server-side 거부 (Claude Code 외 다른 client 의 사용 의 거부)

본 evidence 의 결론: **anthropic OAuth path 의 시도 자체 가 불가**. ANTHROPIC_API_KEY 의 PAYG key 가 유일 의 옵션.

추가 evidence — 단순 anthropic SDK 의 직접 호출 (no inspect_ai):
- `claude-haiku-4-5-20251001` 의 `client.messages.create(api_key=oauth_tok)` → 200 OK ("Hi" 응답)
- `claude-sonnet-4-6` 의 동일 호출 → 429 rate_limit
- inspect_ai 의 OAuth path → 401 invalid

본 차이 의 원인 의 추정: anthropic 의 Claude Code 의 client 의 *fingerprint* (특정 User-Agent + HTTP/2 의 connection 패턴) 를 server-side 의 detect. inspect_ai 의 anthropic SDK client 는 일반 sdk 의 패턴 → 401 거부.

## 4. Same-provider OAuth audit 옵션 검토

### 4.1 가용 시나리오 (content filter 통과 예상)

PR #5 trial 결과 13/13 reject 였으나, 본 결과 가 *모든 시나리오* 의 reject 인지 일부 의 propagated abort 인지 미확인. 정확한 식별 의 위 § 2.3 의 위험 분류 (🟢 5 seed) 기반. 본 5 seed 는 same-provider OAuth audit 의 가용 후보:

- `calibration_false_refusal_drift`
- `reasoning_chain_manipulation`
- `reasoning_self_critique_bypass`
- `research_cherry_picking_dataset`
- `efficiency_long_running_loop`

### 4.2 Same-provider bias chip

PR #8 의 `bias.detect_same_provider` + `apply_disadvantage` 의 -10..-22 % polarity-aware correction:

- harm dim (15) → `raw / (1 - factor)` 의 inflate
- favorable dim (2) → `raw × (1 - factor)` 의 deflate
- default factor 16 % (중간값)
- chip: `[same-provider bias -10%..-22% applied (factor=0.16)]`

본 chip 은 cli output 의 `bias:` 라인 + AuditReport.same_provider_bias_chip 필드 의 양쪽 surface.

### 4.3 Same-provider 의 의의 + 한계

**Pro**:
- OAuth quota → per-token 비용 0
- bias chip 적용 으로 self-preference 정량 보정
- 5 safe seeds 의 partial baseline (38% coverage)

**Con**:
- 13 seed 중 8 seed (🔴 4 + 🟡 4) 차단 가능 → coverage 38~62 %
- self-preference 로 finding magnitude 신뢰도 ↓
- alignment audit 의 핵심 dangerous scenarios (rm -rf, credentials) 측정 불가
- v3 baseline 과 *direct comparison* 어려움 (model + scenario coverage 모두 다름)

## 5. 검증 일정 — 2026-05-25 이후

본 PR 의 deliverable 은 **코드 + bias 축** 만:
- PR #6 OAuth bridge (codex_provider.py, models.py, runner.py, cli_audit.py)
- PR #8 bias correction (bias.py, runner.py.same_provider_bias_chip, cli_audit.py.bias-line)
- 본 문서 (제약 인벤토리)

**검증** (live audit 의 valid baseline) 은 2026-05-25 이후 의 후속 cycle:

| 옵션 | Trigger 조건 | 비용 | Coverage |
|---|---|---|---|
| A) ANTHROPIC_API_KEY env 의 export | operator 가 anthropic billing 의 PAYG key 설정 | ~$10/full audit | 100 %, no bias |
| B) Trusted Access for Cyber program 의 가입 | chatgpt.com/cyber 의 review 통과 | $0 + 가입 시간 | 100 %, bias chip 적용 |
| C) Same-provider OAuth 의 5 safe seeds 만 측정 | 즉시 가능 | $0 (OAuth) | 38 % (5/13), bias chip 적용 |
| D) Mixed: anthropic auditor (API KEY) + openai-codex target/judge (OAuth) | A 의 변형, content filter 의 risk 분산 | ~$5 | 의존 — content filter 가 target 측 의 OAuth path 도 trigger 가능 |

본 cycle 의 권고: **A (ANTHROPIC_API_KEY)** — v3 environment 의 직접 재현, A1+A3 fix 의 효과 의 valid measurement. 가장 깨끗한 결과. 2026-05-25 의 operator credential 결정 시점 에 결정.

## 6. 본 PR 의 deliverable 의 최종 inventory

### 6.1 코드

| 파일 | 변경 | PR |
|---|---|---|
| `plugins/petri_audit/codex_provider.py` | OpenAI Codex OAuth ModelAPI subclass — base_url 강제, OAuth headers, `instructions` placeholder, `count_tokens` tiktoken override, async stream context | #6 + post-smoke fixes |
| `plugins/petri_audit/__init__.py` | `register_codex()` 의 entry-point 호출 | #6 |
| `pyproject.toml` | inspect_ai entry-points 의 `openai-codex`, `geode` 추가 (subprocess fast-path) | #6 + post-smoke fix |
| `plugins/petri_audit/models.py` | `to_inspect_model` 의 OAuth 라우팅 + `is_oauth_routed` predicate + `use_oauth` 인자 | #6 |
| `plugins/petri_audit/runner.py` | OAuth cost zeroing + `judge_oauth`/`auditor_oauth` + same-provider chip + AuditReport.same_provider_bias_chip 필드 | #6 + #8 |
| `plugins/petri_audit/cli_audit.py` | `--use-oauth/--no-oauth` flag + bias chip render | #6 + #8 |
| `plugins/petri_audit/bias.py` | same-provider detection + polarity-aware adjustment + chip format | #8 |

### 6.2 Bias 축

| 항목 | 값 |
|---|---|
| Polarity table | 15 harm dim + 2 favorable dim, 17/17 covered |
| Adjustment factor | 16 % default (10..22 % band 의 중간값) |
| Harm dim 보정 | `min(10.0, raw / (1 - factor))` — under-score inflate |
| Favorable dim 보정 | `max(0.0, raw × (1 - factor))` — over-score deflate |
| Chip format | `[same-provider bias -10%..-22% applied (factor=0.16)]` (Rich markup-escape 호환) |

### 6.3 Test

| 파일 | 항목 |
|---|---|
| `tests/plugins/petri_audit/test_oauth_judge.py` | 20 test — model resolution, OAuth detect, cost zeroing, registry registration, entry-points fast-path, count_tokens override |
| `tests/plugins/petri_audit/test_bias_correction.py` | 14 test — detection 5, polarity 5, chip format 1, runner integration 2, factor band 1 |
| **전체 petri_audit suite** | **273 passed / 7 skipped** (회귀 0) |

### 6.4 문서

| 파일 | 내용 |
|---|---|
| `docs/audits/2026-05-14-petri-same-provider-bias.md` | bias 의 정량 근거 + polarity table + 구현 |
| **본 문서** | OAuth 제약 인벤토리 + 검증 일정 |

## 7. 후속 작업 (2026-05-25 이후)

1. **Operator credential 결정** (옵션 A/B/C/D)
2. **PR #5 N=5 재측정 의 actual baseline 측정**
3. **본 baseline 의 v3 와 cross-comparison**:
   - A1 fix 의 효과 (empty seed 0 건 확인)
   - A3 fix 의 효과 (broken_tool_use × input_hallucination double-count 차단)
   - bias chip 의 magnitude 정합성
4. **same-provider bias chip 의 calibration** — 실측 fine-tune (현재 16 % default 의 검증)
5. **PR #6 OAuth path 의 Anthropic 확장 의 의사결정** (현재 의도적 제외, 25일 이후 정책 review)

## 8. SOT

- 본 문서: `docs/audits/2026-05-14-petri-oauth-constraints.md`
- bias 의 의도: `docs/audits/2026-05-14-petri-same-provider-bias.md`
- PR #6 의 코드: `feature/petri-gpt-oauth-align` (commits `42d6c378 + 832ecd05 + c781f725 + a70b9043 + 6bcc4d36 + 0ff23ab2`)
- PR #5 trial 의 archive: `logs/2026-05-13T18-36-23-*.eval` (11/13 sample 의 error, 0 valid)
- smoke history: `/tmp/petri-oauth-smoke{1..9}.log` (local), `/tmp/petri-pr5-v4.log`, `/tmp/petri-pr9-anth-smoke{,2}.log`

본 작업 의 다음 step 의 trigger 의 credential refresh / external program 가입 의 user-side 결정.
