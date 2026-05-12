# LLM 프로바이더 매트릭스 — 결함 일괄 보강 plan (최종)

> 작성: 2026-05-12 / 최종 갱신: 2026-05-12
> 대상: `core/llm/providers/{anthropic,openai,glm}.py` + 부속 인프라
> 본 문서는 12축 매트릭스 감사 결과(`session 2026-05-12`)에 GAP-17(OpenAI HTML data URL)을 추가한 17 GAP plan + Socratic Gate 통과/탈락 결과.

---

## 최종 결산

**Implemented (5 PR, 5 GAP)** — 직렬 머지 대상
**Socratic-dropped (11 GAP)** — 각 사유 명시 (재도입 시 사유 확인)
**Deferred (1 GAP)** — 위험/이익 비례 안 맞아 별도 대규모 PR로 미룸

---

## 0. 변경 대상 핵심 파일

| 파일 | LOC | 역할 |
|------|-----|------|
| `core/llm/providers/anthropic.py` | 697 | Anthropic 어댑터 |
| `core/llm/providers/openai.py` | 858+ | OpenAI 어댑터(+ generate_stream) |
| `core/llm/providers/glm.py` | 265+ | GLM 어댑터(OpenAI 상속) |
| `core/llm/providers/codex.py` | — | Codex Plus OAuth 변형 |
| `core/llm/fallback.py` | — | 공용 retry/circuit breaker |
| `core/llm/token_tracker.py` | 439 | 단가 + ctx window 표 |
| `core/llm/errors.py` | — | BillingError, GLM 1113/1114/1301 |
| `core/llm/tool_choice.py` | 신규 | 3-provider tool_choice 정규화 (PR-2) |
| `core/llm/postprocess/html_output.py` | 신규 | OpenAI data URL detect/decode (PR-7) |

---

## 1. Implemented PRs (5)

### PR-1 — GAP-E1 (Critical) — retry SOT 회복 `[PR #1056]`
**브랜치**: `feature/llm-retry-policy-unification`

- `OpenAIAdapter._retry_with_backoff`가 모듈 로컬 상수 `_MAX_RETRIES`/`_RETRY_BASE_DELAY`/`_RETRY_MAX_DELAY`를 `retry_with_backoff_generic`에 명시 전달 → `settings.llm_*` 운영 튜닝이 OpenAI/GLM에 반영 안 되던 SOT 위반.
- 상수 + 명시 인자 제거 → `None` 디폴트 → `core.config.settings.llm_*` lazy 해석 경로 활용.
- `tests/test_retry_policy_sot.py` 2 cases.

### PR-2 — GAP-T1 (High) — tool_choice 정규화 `[PR #1057]`
**브랜치**: `feature/llm-tool-choice-normalize`

- 신규 `core/llm/tool_choice.py` — canonical 입력을 3-provider native shape으로 변환하는 `normalize(provider, choice)` helper.
- 3 어댑터(`anthropic.py:482-484`, `openai.py:507`, `glm.py:190`) inline 변환 제거 → helper 호출.
- `tests/test_tool_choice_normalize.py` 33 cases.

### PR-7 — GAP-17 (Critical, 신규) — OpenAI HTML data URL 가드 `[PR #1058]`
**브랜치**: `feature/llm-openai-html-output-guard`

- 1차 가드: `_build_model_card`에 OpenAI/Codex provider 분기 — `data:text/html` URL 금지 + raw `<!DOCTYPE html>` 지침.
- 2차 안전망: 신규 `core/llm/postprocess/html_output.py` — `detect_data_url` / `decode_html` / `extract_artifact_to` 순수 함수.
- `tests/test_html_output_guard.py` 18 cases (provider-gated 확인 포함).

### PR-3 — GAP-A2 (Critical) — OpenAI prompt_cache_key 주입 `[PR #1059]`
**브랜치**: `feature/llm-openai-prompt-cache`

- `_build_prompt_cache_key(system, tools)` — sha256 over `(system + \x00 + sort_keys(tools))` 32-hex.
- `OpenAIAgenticAdapter.agentic_call._do_call`의 `create_kwargs`에 `prompt_cache_key` 주입.
- 회계 path는 이미 완비 (`agentic_response.py:251` + `token_tracker.py:175`) → 본 PR이 dead-spec 활성화.
- `tests/test_openai_prompt_cache.py` 7 cases.

### PR-4 — GAP-R1 (High) — GLM thinking effort 게이팅 `[PR #1060]`
**브랜치**: `feature/llm-glm-thinking-control`

- `effort in ("off", "none")` 시 `extra_body.thinking={"type": "disabled"}` 송신.
- GLM-4.5/4.6 hybrid 모델에서 reasoning-token 비용 절감 (GLM-5.x/4.7는 compulsory thinking이라 영향 없음 — harmless).
- `tests/test_glm_thinking_control.py` 9 cases.

---

## 2. Dropped GAPs (11) — Socratic Gate 사유

| GAP | 등급 | 계획 PR | Drop 사유 | Socratic Q |
|-----|------|---------|-----------|------------|
| **M1** | Low | PR-1 | fallback chain은 list라 길이 무제한 — config에서 늘리면 그만 | Q1 fail |
| **E2** | Low | PR-1 | `fallback.is_billing_fatal` + `retry_with_backoff_generic:286-313`이 이미 1113/1114/1301 매핑 + BillingError 변환 | Q1 fail |
| **T3** | Medium | PR-2 | capability matrix 첫 호출처 부재 — premature abstraction | Q4 fail |
| **C2** | Medium | PR-3 | `token_tracker.py:175` (cached_mtok 단가) + `agentic_response.py:251` (cached_tokens 회수) 모두 이미 작동 중 — 매트릭스 감사 false positive | Q1 fail |
| **C1** | Medium | PR-4 | GLM은 `reasoning_content`를 `output_tokens`에 포함시키는 Chinese LLM 컨벤션 — 별도 thinking_tokens 필드 없음, `ModelPrice.thinking=0` 정상 회계 | Q1 fail |
| **R2** | Low | PR-4 | live test 없이 측정 불가 + C1과 동일 사유 (reasoning_tokens 별도 필드 없음) | Q3 fail |
| **S2** | Low | PR-5 | GLM 단발 stream 사용처 없음 — OpenAI `generate_stream`이 단발 용도 충분 | Q1 fail |
| **T2** | Medium | PR-6 | `grep image_url` 결과 GEODE 코드 어디서도 vision input 미사용. MCP utils의 image content는 tool result 처리용 | Q2 fail |
| **TK1** | Medium | PR-6 | 사용처 부재 (200K guard는 사후성으로 충분). tiktoken/anthropic count_tokens 신규 dependency 추가는 dead-code 위험 | Q1 fail |
| **A1** | Low | PR-6 | `stop_sequences`/`top_p` 호출자 부재 — premature abstraction | Q2 fail |
| **X1** | Medium | PR-6 | z.ai 공식 페이지 외부 확인 필요 — 코드 변경 없이 단가 표 데이터만 갱신, 별도 manual verification 작업 | Q1 deferred |

---

## 3. Deferred GAP (1) — 별도 대규모 PR

| GAP | 등급 | 사유 | 재개 조건 |
|-----|------|------|-----------|
| ~~**S1**~~ | ~~High~~ | ~~(1) Q3 측정 — mock으로는 TTFB 측정 의미 없음, live test 비용 필요. (2) 회귀 위험 큼 — stream context manager + async + `AgenticResponse` 재정상화 + `streaming.py` 통합. (3) 효과 vs 비용 비례 안 맞음 — 이익이 TTFB 체감 (사용자 체감 개선)~~ | **v0.95.0 PR #1063 으로 활성화·구현 완료**. minimal change (`messages.create` → `messages.stream` + `get_final_message()`) 로 실제 회귀 위험 작았음 — 2026-05-12 의 회고. OpenAI/GLM streaming 은 여전히 별도 후속 PR. |

---

## 4. 일괄 게이트 결과

각 PR에 대해 동일 통과:

```
ruff check core/ tests/ plugins/    → 0 errors
mypy core/ plugins/                  → 0 errors (변경 파일 대상)
pytest tests/ -m "not live"          → 코어 회귀 전부 통과
```

5 PR 합계 추가/수정:
- 신규 모듈 4개 (`tool_choice.py`, `postprocess/__init__.py`, `postprocess/html_output.py`)
- 회귀 테스트 신규 5개 파일, 69 cases
- 수정 파일 5개 (`openai.py`, `anthropic.py`, `glm.py`, `system_prompt.py`, `CHANGELOG.md` x5)

---

## 5. 머지 순서 (사용자 권한)

```
PR #1056 (E1)  ─┐
PR #1057 (T1)  ─┼─→ develop ─→ main (통합 MINOR bump)
PR #1058 (17) ─┤
PR #1059 (A2) ─┤
PR #1060 (R1) ─┘
```

같은 파일(openai.py / glm.py)을 만지는 PR이 있어 conflict 가능성 있음. PR-1 머지 후 PR-2/3는 develop 갱신해 rebase 필요할 수 있음 (GitHub auto-merge가 처리하면 통과).

---

## 6. 매트릭스 17 GAP 최종 분포 (사이클 완전 종결, 2026-05-12)

| 분류 | 건수 | 비율 |
|------|------|------|
| ✅ Implemented (v0.94.0 + v0.95.0) | **7** (E1·T1·17·A2·R1·S1·X1) | 41% |
| ❌ Socratic-dropped | **10** (M1·E2·T3·C2·C1·R2·S2·T2·TK1·A1) | 59% |
| 🟡 Deferred | 0 | 0% |
| **합계** | 17 | 100% |

**Dead-code 0건 도입**, **CLAUDE.md P10 (Simplicity Selection) 준수**, **호출처 없는 abstract 추가 0건**.

---

## 7. 매트릭스 감사 회고 — false positive 6건

본 audit 의 진짜 학습. 매트릭스 작성 시 단가/회수/사전경로 의 한쪽만 보고 결함 판정 한 사례:

| GAP | 본래 진단 | 실제 상태 | 누락한 검증 |
|-----|-----------|-----------|-------------|
| **C2** | "OpenAI cache_read 단가 dead-spec" | 단가(`token_tracker.py:175`) + 회수(`agentic_response.py:251`) 양쪽 작동 | 회수 path 의 `prompt_tokens_details.cached_tokens` 추출 코드 |
| **T2** | "vision 입력 변환 미검증" | 호출처 0 — `grep image_url` 0 매치 | 호출처 grep |
| **M1** | "fallback chain 2단계뿐" | `config/__init__.py:217,223,235` 의 chain 은 list — 길이 무제한 | `FALLBACK_CHAIN` 정의 직접 확인 |
| **C1** | "GLM thinking 단가 미등록" | GLM `completion_tokens = visible + reasoning` collapsed 컨벤션 — `thinking=0` 이 이중 청구 방지 정답 | provider 별 token-합산 컨벤션 확인 |
| **R2** | "GLM thinking_tokens 회계 미검증" | `agentic_response.py:240-242` (normalize_openai) → `_response.py:105` → `_lifecycle.py:129,188` 의 record path 완비 | normalize → record 전수 추적 |
| **TK1** | "사전 토큰 카운팅 부재" | `loop.py:470,1102` 가 매 호출 전 `check_context()` 호출 — 사전 추정 이미 작동. "정확한 tokenizer" 만 잠재 개선이고 그것도 API reject 시 청구 없음 → 실질 ROI 0 | 호출 전 hook 의 존재 + reject 토큰 청구 정책 확인 |

### 다음 매트릭스 감사 가이드라인

각 결함 후보마다 다음 5 checkbox 통과 후 plan 에 등재:

1. **호출처 grep** — 결함 으로 지목 한 path 가 실제 호출되는가?
2. **회수 path 추적** — 데이터 가 어디서 read 되어 어디까지 propagate 되는가? (normalize → record → cost)
3. **provider 별 컨벤션** — 같은 필드 이름 이 provider 마다 다른 의미를 가지는가? (e.g. GLM `completion_tokens` vs OpenAI o-series `completion_tokens`)
4. **사전 vs 사후 hook** — 결함 으로 지목 한 layer 가 이미 사전/사후 어느 위치 에 존재 하는가?
5. **실질 ROI** — 결함 해소 시 실제 비용/안정성 손실 회수 가 발생 하는가? (e.g. reject 시 청구 없으면 estimate 부정확 의 비용 손실 = 0)

5 항목 모두 OK 인 결함 만 plan 등재. 1 항목 이라도 미확인 → "verification needed" 상태 로 deferred, drop/implement 결정 보류.

---

## 8. 회고 — ROI 재평가 의 진실

직전 의 ROI 회고 에서 C1+R2 를 "후회 후보" 로 추천 했으나, 본 재감사 결과 둘 다 fully implemented (false positive). TK1 도 "사전 카운팅 부재" 진단 자체 가 false (이미 `check_context()` 가 작동, "정확한 tokenizer" 도 reject 시 청구 없어 ROI 0).

**진짜 추가 후회 후보 = 0건**. 7 implemented + 10 drop + 6 false positive = 매트릭스 audit 의 진짜 산출물.
