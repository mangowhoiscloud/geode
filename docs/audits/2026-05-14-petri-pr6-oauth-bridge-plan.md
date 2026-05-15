# Petri × Codex OAuth Bridge — PR #6 Plan (2026-05-14)

> v3 audit 가 judge 한 번에 $7.50 가까이 태운 원인은 `openai/gpt-5.5` 가 inspect_ai 의 native openai provider 를 거쳐 `api.openai.com` per-token 으로 청구된 것. GEODE 는 이미 `core/llm/providers/codex.py` 에 ChatGPT Plus quota 를 쓰는 OAuth path 를 보유하고 있다. 이 PR 은 그 path 를 inspect_ai/petri 의 judge 호출까지 끌어다 붙여 judge 비용을 ~$0 로 만든다.

## 1. 현재 상태

- `core/llm/providers/codex.py:104-128` — `_get_codex_client()` 는 OAuth 토큰 + `ChatGPT-Account-ID` + `originator` 헤더가 박힌 `openai.OpenAI` 클라이언트를 반환. `CODEX_BASE_URL = https://chatgpt.com/backend-api/codex`.
- `core/llm/providers/codex.py:170-394` — `CodexAgenticAdapter` 는 GEODE agentic loop 만 다룸. inspect_ai 의 `ModelAPI` 가 요구하는 `generate(input, tools, tool_choice, config) -> ModelOutput` 형 시그니처는 없음.
- `plugins/petri_audit/models.py:97-107` — `to_inspect_model("gpt-5.5")` → `openai/gpt-5.5` 로 그대로 매핑. inspect_ai 의 native `openai` provider (`OpenAIAPI`) 가 받아 처리.
- `plugins/petri_audit/cli_audit.py:54-58` — `--judge` 기본값 `claude-haiku-4-5-20251001`. user 가 `gpt-5.5` 등을 명시하면 v3 의 per-token 청구 경로로 빠짐.
- `plugins/petri_audit/runner.py:355-385` — cost estimator 는 judge model 의 `MODEL_PRICING` entry × `judge_in_per_sample × judge_out_per_sample` 로 계산. OAuth 경로의 0 비용 인식이 없음.
- `plugins/petri_audit/targets/geode_target.py:321-461` — 이미 `@modelapi(name="geode")` 데코레이터로 `GeodeModelAPI` 를 등록하는 패턴 보유. **같은 방식으로 `openai-codex` provider 를 등록할 수 있음**.

## 2. Codex backend 의 inspect_ai 호환성

`docs/research/codex-oauth-request-spec.md` 의 3-codebase grounded 조사 기준:

| 영역 | Codex backend 요구 | inspect_ai 의 OpenAIAPI (`generate_responses`) 현재 행동 | gap |
|------|-------------------|--------------------------------------------------------|-----|
| 엔드포인트 | `chatgpt.com/backend-api/codex/responses` | `api.openai.com/v1/responses` | base_url 교체 필요 |
| 인증 | `Bearer <oauth_access_token>` | `OPENAI_API_KEY` env | api_key 교체 필요 |
| 헤더 | `ChatGPT-Account-ID`, `originator: codex_cli_rs` | 없음 | `default_headers` 주입 필요 |
| `store` | **REQUIRED `false`** | `responses_store=None` 일 때 `store=False` ✓ | 일치 |
| `stream` | **REQUIRED `true`** | `client.responses.create(...)` (non-streaming) | **streaming 으로 전환 필요** |
| `instructions` | REQUIRED (empty OK) | 안 보냄 (system → `role:developer` input item) | `instructions` 으로 옮길 필요 |
| `max_output_tokens` | **FORBIDDEN** (400 unsupported) | `config.max_tokens` 가 있으면 `max_output_tokens` 송신 | **스트립 필요** |
| `tools` | OK (Responses tool schema) | 동일 schema | 일치 |
| `tool_choice` | `auto` 고정 (Codex Rust + Hermes) | inspect_ai 가 dim-set 의 structured tool 위해 `required` 보낼 수도 | 정책 결정 필요. 일단 그대로 보내고 backend 가 거부 시 fallback |
| `parallel_tool_calls` | `true` | inspect_ai 의 `config.parallel_tool_calls` follow | 일치 |
| `reasoning` | gpt-5.x 는 `{effort, summary}` | inspect_ai 의 `config.reasoning_effort` follow | 일치 |
| `include` | reasoning 시 `["reasoning.encrypted_content"]` | 동일 | 일치 |
| `service_tier`, `prompt_cache_key` | 일부 허용 | 동일 | 무난 |
| 응답 파싱 | streaming SSE, `response.output_item.done` event 누적, `response.completed` 가 `output` 누락하는 backend 특수성 | `client.responses.create(...).model_dump()` 로 단발 응답 처리 | **streaming 파싱 별도 구현 필요** |

핵심 gap 4개: ① streaming 강제, ② `max_output_tokens` 스트립, ③ `instructions` 분리, ④ Codex Plus 의 `response.completed.output == []` 우회 (codex.py:331-344 의 패턴 그대로 차용).

## 3. 후보 접근 4종 비교

### A. inspect_ai custom provider registration

`@modelapi(name="openai-codex")` 로 inspect_ai 의 registry 에 신규 provider 를 등록. `OpenAIAPI` 를 상속해서 (a) `_create_client()` 에서 OAuth 토큰 + 헤더 + base_url 주입, (b) `generate()` 를 override 하여 streaming + `instructions` 분리 + `max_output_tokens` 스트립 처리.

- 장점:
  - GEODE 의 기존 `GeodeModelAPI` 등록 패턴과 동일 — 인프라 재활용.
  - inspect_ai 의 `--model-role judge=openai-codex/gpt-5.5` 형태로 자연스럽게 연결됨.
  - 기존 per-token `openai/gpt-5.5` 경로 비파괴 (별도 provider).
  - `OpenAIAPI` 의 input 직렬화 (`openai_responses_inputs`), tool 변환 (`openai_responses_tools`), 응답 파싱 helper 재활용 가능.
- 단점:
  - inspect_ai 의 `generate_responses` 가 `client.responses.create(**)` 를 부르므로, generate 메서드를 통째로 override 해야 함. 약 200 LOC.
- effort: **M**

### B. `--model-base-url` redirect + 로컬 proxy

사용자가 `--model-base-url https://chatgpt.com/backend-api/codex` + `--api-key <oauth_token>` 을 전달, 로컬 process 없이 inspect_ai 가 직접 codex backend 호출.

- 장점: 코드 0 LOC.
- 단점:
  - `max_output_tokens` 가 강제 송신되어 400 회피 불가.
  - streaming 전환 불가.
  - `ChatGPT-Account-ID` 헤더 주입 경로 없음 (`extra_headers` 는 per-request, 토큰별 account 매핑은 어려움).
  - **실현 불가**.
- effort: skip

### C. `cli_audit.py` 가 judge phase 만 codex.py 로 분리

inspect_ai 의 `audit_judge` 단계를 가로채서 GEODE 가 직접 codex.py 의 client 로 호출 → 결과를 inspect_ai 결과 객체로 어댑팅.

- 장점: inspect_ai 내부 손대지 않음.
- 단점:
  - inspect-petri 의 judge 는 `inspect_petri/_judge/judge.py:111-117` 에서 `get_model(role="judge")` 로 결정되며, `generate_answer` 가 그 model 의 `.generate()` 를 직접 호출. 따라서 audit subprocess 안에서 judge 만 분리하려면 결국 ModelAPI 를 register 해야 함 → A 와 수렴.
  - 외부 wrapper 만으로 분리하려면 inspect-petri 의 audit task 를 자체 fork 해야 함. **deal-breaker**.
- effort: L (사실상 불가능)

### D. inspect_ai openai provider import-time monkeypatch

`plugins/petri_audit/__init__.py` 가 import 시점에 inspect_ai 의 `OpenAIAPI._create_client` 와 `generate_responses` 를 patch.

- 장점: 사용자가 어떤 provider 명도 안 바꿔도 됨 (`openai/gpt-5.5` 가 자동으로 OAuth 로 라우팅).
- 단점:
  - **breaking change**: per-token 경로 자체가 사라짐. 사용자가 OAuth 없이도 PAYG 로 가야 할 케이스 (예: 다른 OpenAI org 토큰) 막힘.
  - monkeypatch 는 inspect_ai version drift 에 깨지기 쉬움.
  - 회귀 가드 어려움 — 어떤 호출이 OAuth 로 갔는지 외부에서 확인 안 됨.
- effort: M
- **거부**: CLAUDE.md 의 "No breaking changes to per-token path" 원칙 위반.

## 4. 결정

**접근 A 채택**. effort × correctness 비율 최고. 아래 4-step 구현.

## 5. 구현 단계

### Step 1 — 신규 provider 모듈

`plugins/petri_audit/codex_provider.py`:

- `OpenAICodexAPI(OpenAIAPI)` — `OpenAIAPI` 상속.
- `__init__` 에서 OAuth 토큰 resolve (`core.llm.providers.codex._resolve_codex_token`). 토큰 없으면 `EnvironmentVariableError` (inspect_ai 의 표준 패턴) 로 fast-fail.
- `_create_client()` override — `AsyncOpenAI(api_key=token, base_url=CODEX_BASE_URL, default_headers={ChatGPT-Account-ID, originator})`.
- `generate()` override — `generate_responses` 를 호출하지 않고 자체 streaming 구현:
  1. `openai_responses_inputs(input, self, synthesize_phase=False)` 로 input list 변환.
  2. system/developer message 를 별도로 추출해 `instructions=` 로 분리.
  3. `openai_responses_tools(tools, ...)`, `openai_responses_tool_choice(...)` 재활용.
  4. `completion_params_responses(...)` 호출 후 결과에서 `max_output_tokens` 키 **제거**.
  5. `client.responses.stream(**kwargs)` 로 streaming 호출, `response.output_item.done` 누적, `get_final_response()` 의 `output` 빈 경우 누적 결과로 덮어쓰기 (codex.py:331-344 패턴).
  6. `openai_responses_chat_choices(...)` 로 inspect_ai `ChatCompletionChoice` 변환.
  7. `model_usage_from_response(...)` 로 usage 변환.

### Step 2 — register hook

`plugins/petri_audit/__init__.py` 에 `@modelapi(name="openai-codex")` 등록. 기존 `register()` 와 동일한 try/except guard 로 `[audit]` extra 부재 시 silent skip.

### Step 3 — model id 매핑

`plugins/petri_audit/models.py`:

- `is_codex_oauth_available()` — `core.llm.providers.codex._resolve_codex_token()` 결과 boolean.
- `to_inspect_model(geode_id)` — gpt-5.x 가족이고 OAuth 토큰이 있으면 `openai-codex/<model>`, 없으면 기존 `openai/<model>`. raw passthrough (`/` 포함) 는 그대로.
- 신규 `--use-oauth/--no-oauth` 플래그를 `cli_audit.py` 에 추가, default `auto` (token 존재 시 자동 enable).
- `--no-oauth` 시 기존 매핑 강제. 사용자가 명시적으로 `--judge openai/gpt-5.5` pin 한 경우는 raw passthrough 로 그대로 (자동 재작성 안 함).

### Step 4 — cost estimator OAuth 인식

`plugins/petri_audit/runner.py`:

- `estimate_cost_usd` 의 judge 부분이 `inspect_judge` 가 `openai-codex/` 로 시작하면 judge 비용 = $0 처리.
- auditor 가 OAuth 경로일 때도 동일. (현재 PR 의 1차 범위는 judge 만이지만 estimator 는 양쪽 지원).

### Step 5 — 테스트

`tests/plugins/petri_audit/test_oauth_judge.py`:

- `test_to_inspect_model_uses_oauth_when_token_present` — `_resolve_codex_token` 을 mock 으로 truthy 만들고 `to_inspect_model("gpt-5.5")` → `openai-codex/gpt-5.5`.
- `test_to_inspect_model_falls_back_to_per_token_without_token` — mock 으로 `""` 반환, 결과 `openai/gpt-5.5`.
- `test_to_inspect_model_respects_raw_passthrough` — 사용자가 `openai/gpt-5.5` 직접 pin 하면 그대로 (자동 재작성 안 함).
- `test_estimate_cost_zero_for_oauth_judge` — `judge="gpt-5.5"` + token present → judge 비용 0.
- `test_estimate_cost_per_token_without_oauth` — token absent → 기존 추정치.
- `test_oauth_provider_registers_when_extra_present` — `[audit]` extra 설치 환경에서 import 시 `openai-codex` modelapi 가 inspect_ai registry 에 등록되는지 확인 (있을 때만 skip 안 함).

### Step 6 — `--judge` default 갱신

Token 있을 때만 `gpt-5.4-mini` 등 cheap codex model 을 권장. 기본은 그대로 `claude-haiku-4-5-20251001` 유지 (OAuth 없는 사용자 환경에서 회귀 없어야 함). 향후 PR 에서 cost-aware default 로 전환.

## 6. 비파괴성 보장 체크리스트

- [x] Anthropic judge (`claude-haiku-4-5-20251001`) 경로 무손상 — `to_inspect_model` 의 `claude-*` 분기 변동 없음.
- [x] Per-token `openai/gpt-5.5` 경로 무손상 — raw passthrough + `--no-oauth` 두 갈래.
- [x] OAuth token 없을 때 자동 fallback — `to_inspect_model` 의 token 검사 분기.
- [x] inspect_ai 본체 unmodified — 신규 provider 만 추가.
- [x] codex.py 본체 unmodified — `_resolve_codex_token` / `_extract_account_id` 만 read-only 사용.

## 7. 산출물 매핑

| Deliverable | File | 신규/수정 |
|-------------|------|----------|
| planning doc | `docs/audits/2026-05-14-petri-pr6-oauth-bridge-plan.md` | 신규 |
| bridge module | `plugins/petri_audit/codex_provider.py` | 신규 |
| register hook | `plugins/petri_audit/__init__.py` | 수정 |
| id mapping | `plugins/petri_audit/models.py` | 수정 |
| cost estimator | `plugins/petri_audit/runner.py` | 수정 |
| CLI flag | `plugins/petri_audit/cli_audit.py` | 수정 |
| tests | `tests/plugins/petri_audit/test_oauth_judge.py` | 신규 |

## 8. 검증

- 전체 261 tests + 신규 6+ tests 모두 PASS.
- 신규 provider 는 `[audit]` extra 환경에서만 import — `uv sync` (no extra) 환경에서 regression 없음.
- `geode audit --dry-run --judge gpt-5.5` 명령이 OAuth 토큰 있을 때 `openai-codex/gpt-5.5` 로, 없을 때 `openai/gpt-5.5` 로 표기되는지 수동 확인.

## 9. Out of scope

- Token refresh 흐름 — `core/auth/codex_cli_oauth` 가 이미 처리. 본 PR 은 read-only 사용.
- Auditor / target 의 OAuth 화 — 현재 audit 구조상 auditor 는 Anthropic 이 기본, target 은 `geode/<base>` 로 GEODE 내부 router 가 결정. judge phase 가 비용의 대부분이라 1차 PR 은 judge 만.
- Codex backend 가 `tool_choice="required"` 거부할 때의 graceful degradation — 처음에는 그대로 송신하고 backend 응답 확인 후 후속 PR.
