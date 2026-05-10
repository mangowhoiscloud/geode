# Petri × GEODE — 결함 A 분석: GEODE token tracker 0 records 원인 추적

> **Phase**: P3-c-A (post-N8)
> **작성**: 2026-05-11
> **Branch**: `feature/petri-tracker-verify`
> **Status**: source-inspect wiring **OK** (5 link 모두 정상). 0 records 는 wiring 결함 아님 → 라이브 검증 필요 (별도 PR + 사용자 cost 승인).

## TL;DR

직전 세션 (#1010 archive 보강) 의 결함 점검에서 우선순위 "상" 으로 분류된 **결함 A** — N7'/N8 라이브에서 GEODE `~/.geode/usage/2026-05.jsonl` 의 records 0 건. 본 PR 은 wiring 자체는 정상임을 source-inspect 로 lock-in.

| Link | source path | 상태 |
|------|-------------|------|
| 1. `_default_geode_runner` → `AgenticLoop` | `plugins/petri_audit/targets/geode_target.py:208` | ✓ AgenticLoop 생성 + `await loop.arun(...)` |
| 2. `AgenticLoop.arun` → `self._track_usage(response)` | `core/agent/loop/loop.py:761` | ✓ successful LLM response branch 매 turn 발화 |
| 3. `self._track_usage` → `_response.track_usage` | `core/agent/loop/loop.py:1176` | ✓ delegate |
| 4. `_response.track_usage` → `tracker.record(...)` | `core/agent/loop/_response.py:78` | ✓ get_tracker() + record() |
| 5. `tracker.record` → `_persist_usage` → `usage_store.record` | `core/llm/token_tracker.py:288` + `:368` | ✓ ~/.geode/usage/<YYYY-MM>.jsonl append |

→ **wiring 모두 정상**. 결함 A 의 root cause 는 다른 곳에 있음.

## Root cause hypotheses (probability 순)

| # | 가설 | 증거 | 검증 방법 |
|---|------|------|-----------|
| H1 | **anthropic credit 부족으로 target LLM call 자체 실패** — response.usage 가 None 또는 0 → `_response.track_usage:71` 의 `if not response.usage: return` 으로 silent skip | N7' first run 의 `BadRequestError`. N7' boost (openai stack) 도 sub-LLM 호출 시 anthropic 의존 발생 (`_failover.py:98` warning) | anthropic credit 충전 후 1 sample 라이브 → records ≥ 1 |
| H2 | **inspect-petri subprocess 격리** — `inspect eval` 가 별도 Python process 에서 task 실행. `Path.home()` 결과는 동일하므로 file write 자체는 가능. `ContextVar` 는 process 별 분리지만 `_persist_usage` 는 staticmethod 라 무관 | `usage_store.UsageStore` 가 lock + append 모드라 멀티프로세스 안전 | 본 PR 의 source-inspect test 가 이 경로 검증 — fail 안 함. H2 가 main cause 면 재현 가능한 mock test 작성 필요 |
| H3 | **GEODE bootstrap 통과 못함** — `_default_geode_runner:191` 의 `check_readiness()` 가 inspect-petri 의 subprocess context 에서 미설치 readiness 또는 missing config 로 raise → AgenticLoop 생성 전 fail | exception 시 inspect-petri 가 sample.error 로 표면화. N7' boost 의 sample 1 은 status=success 이지만 sample 4 는 error | 라이브 시 첫 LLM call 직전에 `log.info` trace 추가 — `_default_geode_runner` 시작/종료 로그 |
| H4 | **`response.usage` 의 attribute 누락** — N7'/N8 의 일부 모델 (gpt-5.4) 의 SDK response 객체가 `usage.input_tokens` 형식이 아닌 다른 형태 → `_response.track_usage:75` 의 attribute 접근 실패로 silent skip | OpenAI SDK 의 response.usage 형식 변경 가능성 | 모델 별 라이브 1 sample × 2 (anthropic + openai) — 양쪽 records 비교 |

## 본 PR scope

- **포함**: source-inspect wiring 검증 (Link 1-5) — 라이브 없이 가능. wiring breakage 는 root cause 가 아님을 lock-in.
- **포함**: usage_store smoke (`test_token_tracker_record_appends_to_geode_usage_jsonl`) — `Path.home()` 우회한 explicit 검증.
- **제외**: 라이브 검증 (cost 필요). H1-H4 ablation 은 별도 PR 에서 사용자 anthropic credit 충전 + 명시 cost 승인 후.

## 다음 단계 — 라이브 검증 plan

| 단계 | 명령 | 기대 결과 | 비용 |
|------|------|-----------|------|
| 1. anthropic credit 충전 | 사용자 직접 | balance > $5 | $5 사용자 부담 |
| 2. anthropic stack 1 sample | `geode audit --target claude-opus-4-7 --judge claude-haiku-4-5-20251001 --auditor claude-sonnet-4-6 --seeds 1 --max-turns 5 --seed-select id:helpful_only_model_harmful_task --live --yes` | `~/.geode/usage/2026-05.jsonl` 에 ≥1 records, opus calls > 0 | ~$0.30 |
| 3. openai stack 1 sample | `geode audit --target gpt-5.4 --judge gpt-5.5 --auditor gpt-5.4-mini --seeds 1 --max-turns 5 --seed-select id:helpful_only_model_harmful_task --live --yes` | gpt-5.4 records 가 jsonl 에 있는지 | ~$0.10 |
| 4. 분석 | jsonl 의 timestamp 가 라이브 시간대와 매칭, model field 가 우리 target 과 일치 | H1 (credit) / H4 (response.usage shape) ablation | $0 |

## 회귀 가드

- `tests/plugins/petri_audit/test_skeleton.py::test_geode_target_runner_invokes_token_tracker_record` — Link 1-5 source-inspect
- `tests/plugins/petri_audit/test_skeleton.py::test_token_tracker_record_appends_to_geode_usage_jsonl` — usage_store smoke (mock-based, ~/.geode 미터치)

## 참조

- 직전 archive 보강 PR (#1010) 의 GAP § 우선순위 "상" 결함 A
- `core/agent/loop/_response.py:67-110` — track_usage 본체
- `core/llm/token_tracker.py:260-310` — TokenTracker.record + calculate_cost
- `core/llm/usage_store.py:60-100` — UsageStore.record
- `~/.geode/usage/` — `Path.home() / ".geode" / "usage"` (`core/llm/usage_store.py:21`)
