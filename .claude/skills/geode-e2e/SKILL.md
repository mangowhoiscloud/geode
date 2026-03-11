# GEODE E2E Testing Skill

> Live E2E 검증 + LangSmith Observability + 품질 점검 패턴.
> Triggers: e2e, live test, 검증, langsmith, tracing, observability, 품질 점검

---

## Test Tiers

| Tier | 파일 | LLM 호출 | 실행 시간 | 용도 |
|------|------|---------|----------|------|
| **Mock** | `test_agentic_loop.py`, `test_e2e.py`, `test_e2e_orchestration_live.py` | No | ~3s | CI/CD, regression |
| **Live** | `test_e2e_live_llm.py` | Yes (Anthropic API) | ~5min | 실제 동작 검증 |

## Live Test 실행

```bash
# .env 로드 + live marker 테스트만 실행
set -a && source .env && set +a && uv run pytest tests/test_e2e_live_llm.py -v -m live

# 특정 시나리오만
uv run pytest tests/test_e2e_live_llm.py::TestAgenticLoopLive::test_1_2_single_tool -v

# 오프라인 모드만 (API 비용 없음)
uv run pytest tests/test_e2e_live_llm.py::TestOfflineModeLive -v
```

## 시나리오 매핑 (docs/e2e-orchestration-scenarios.md)

### §1 AgenticLoop (실제 Anthropic API)

| ID | 시나리오 | 검증 포인트 |
|----|---------|-----------|
| 1-1 | 텍스트 응답 ("안녕하세요") | tool_calls=[], rounds=1, text 비어있지 않음 |
| 1-2 | 단일 도구 ("IP 목록 보여줘") | list_ips tool 호출, result에 error 없음 |
| 1-3 | 순차 도구 ("분석하고 비교해줘") | analyze_ip → compare_ips 순서, rounds >= 2 |
| 1-4 | 병렬 도구 ("둘 다 검색해줘") | tool_calls >= 2 |
| 1-5 | Max rounds 가드레일 | rounds <= max_rounds, error="max_rounds" |
| 1-7 | 멀티턴 컨텍스트 | turn_count 증가, 이전 분석 참조 |

### §4 LangSmith Tracing

| ID | 검증 포인트 |
|----|-----------|
| 4-2 | LangSmith 'geode' 프로젝트에 AgenticLoop 트레이스 존재 |

### §5 Full Pipeline (실제 LLM)

| ID | 시나리오 | 검증 포인트 |
|----|---------|-----------|
| 5-1 | 단일 IP (Berserk) | tier in S/A/B/C, score > 0, analyses = 4, synthesis 존재 |
| 5-2 | 3 IP 스모크 | 3개 모두 유효한 tier + score |
| 5-3 | 피드백 루프 | synthesizer 방문, high confidence → gather 미방문 |

### §6 Plan/Sub-agent NL Integration

| ID | 시나리오 | 검증 포인트 |
|----|---------|-----------|
| 6-1 | Plan NL ("계획 세워줘") | create_plan tool 호출, plan_id 반환 |
| 6-2 | Plan Approve NL ("승인해") | approve_plan tool 호출 |
| 6-3 | Delegate NL ("병렬로 처리해") | delegate_task tool 호출 |
| 6-4 | Plan Offline | regex → plan action |
| 6-5 | Delegate Offline | regex → delegate action |

### §C5 Offline Mode

| ID | 검증 포인트 |
|----|-----------|
| offline-list | regex → list action, rounds=1 |
| offline-analyze | regex → analyze action |
| offline-help | 미인식 → help fallback |
| offline-plan | regex → plan action ("계획", "plan") |
| offline-delegate | regex → delegate action ("병렬", "parallel") |

## 핵심 패턴

### 1. _make_loop() — 완전한 테스트 환경 구성

```python
def _make_loop(*, force_dry_run=False):
    # 1. ReadinessReport 설정 (force_dry_run 제어)
    # 2. _build_tool_handlers() → 20개 핸들러 등록 (plan/delegate 포함)
    # 3. ToolExecutor(action_handlers=handlers)
    # 4. AgenticLoop(context, executor)
```

**주의**: `ToolExecutor()`를 핸들러 없이 생성하면 모든 tool 호출이 `Unknown tool` 에러 반환. 반드시 `_build_tool_handlers()`로 핸들러를 등록할 것.

### 2. ReadinessReport — dry-run 제어

```python
readiness = check_readiness()
readiness.force_dry_run = False  # 실제 LLM 호출 허용
readiness.has_api_key = True
_set_readiness(readiness)
```

`_build_tool_handlers()` 내부에서 `_get_readiness().force_dry_run`을 읽어 analyze_ip 등의 dry_run 기본값을 결정함.

### 3. LangSmith 트레이스 검증

```python
import time
from langsmith import Client

time.sleep(3)  # async flush 대기
client = Client()
runs = list(client.list_runs(project_name="geode", limit=5))
assert any("AgenticLoop" in (r.name or "") for r in runs)
```

### 4. 품질 점검 체크리스트

라이브 테스트 실행 후 반드시 확인:

- [ ] **Tool 실행 성공**: tool_calls의 result에 `error` 키 없음
- [ ] **핸들러 등록**: `_build_tool_handlers()` 사용, 빈 ToolExecutor 금지
- [ ] **ReadinessReport**: `force_dry_run=False` 확인 (라이브 테스트에서)
- [ ] **토큰 비용**: LangSmith metrics에서 cost_usd 확인
- [ ] **파이프라인 모드**: `dry-run (no LLM)` vs 실제 모델명 확인
- [ ] **LangSmith 트레이스**: pending 상태 run이 없는지 확인
- [ ] **Claude Code UI**: tool call 시 `▸`/`✓`/`✗` 마커 출력 확인
- [ ] **Plan/Delegate NL**: "계획 세워줘"→plan, "병렬로"→delegate 매핑 확인

## 환경 변수

```bash
# .env (필수)
ANTHROPIC_API_KEY=sk-ant-...
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=lsv2_pt_...
LANGCHAIN_PROJECT=geode
```

## 업데이트 규칙

기능 변경 시 이 순서로 E2E 테스트를 업데이트:

1. **시나리오 문서** 갱신: `docs/e2e-orchestration-scenarios.md`
2. **Mock 테스트** 갱신: `test_agentic_loop.py`, `test_e2e.py`, `test_e2e_orchestration_live.py`
3. **Live 테스트** 갱신: `test_e2e_live_llm.py`
4. **이 스킬** 갱신: 시나리오 매핑 테이블 + 검증 포인트

### 변경 유형별 가이드

| 변경 | Mock 테스트 | Live 테스트 | 시나리오 문서 |
|------|-----------|-----------|------------|
| 새 tool 추가 | ToolExecutor mock 추가 | 1-2류 시나리오 추가 | §1 추가 |
| 파이프라인 노드 추가 | 5-1류 visited_nodes 갱신 | 5-1류 assert 갱신 | §5 추가 |
| LLM 어댑터 변경 | 4-* tracing mock 갱신 | 4-2 LangSmith 검증 | §4 갱신 |
| Offline 패턴 추가 | nl_router regex 테스트 | offline-* 시나리오 추가 | §C5 갱신 |
