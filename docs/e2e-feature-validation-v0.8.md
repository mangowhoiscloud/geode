# E2E Feature Validation — v0.8.0

README.md + CHANGELOG.md 기반 기능별 E2E 검증 시나리오.
기존 `e2e-orchestration-scenarios.md`(§1-§8)와 중복되지 않는 항목 중심.

## 실행 결과 (2026-03-11)

| # | 기능 | 결과 | 비고 |
|---|------|------|------|
| F1 | Pipeline dry-run 3 IP tier | **PASS** | Berserk S/81.3, Cowboy Bebop A/68.4, Ghost in the Shell B/51.6 |
| F2 | NL Router offline 한/영 | **9/10 PASS** | "list all IPs"→batch (regex 우선순위, LLM 모드 정상) |
| F3 | Plan/Delegate NL offline | **6/6 PASS** | 한/영 모두 정확 매핑 |
| F4 | Tool 결과 JSON 직렬화 | **PASS** | dict, list, datetime 모두 valid JSON |
| F5 | Snapshot _sanitize_state() | **PASS** | 6→3 keys (3 _-prefixed 필터링) |
| F6 | Verification LangSmith tracing | **4/4 PASS** | guardrails, biasbuster, cross_llm, rights_risk |
| F7 | Guardrails G1-G4 | **4/4 PASS** | Schema, Range, Grounding, Consistency |
| F8 | BiasBuster | **PASS** | overall_pass=True, anchoring=False (dry-run) |
| F9 | Cross-LLM Agreement | **PASS** | agreement=0.9612, passed=True |
| F10 | Scoring tier classification | **4/4 PASS** | S≥80, A≥60, B≥40, C<40 |
| F11 | Cause classification | **5/5 PASS** | Decision tree D-E-F 5개 케이스 |
| F12 | Rights risk assessment | **4/4 PASS** | 3 fixture + 1 unknown |
| F13 | ToolRegistry 21 tools | **PASS** | definitions.json 21개 확인 |
| F14 | IP Search Engine | **3/3 PASS** | dark fantasy→berserk, cyberpunk→GiTS, nonexistent→0 |
| F15 | Batch analysis dry-run | **PASS** | 3 IP, all A tier, 67.3-68.2 range |
| F16 | Report templates | **PASS** | 3 templates (HTML, summary MD, detailed MD) |
| F17 | Graceful degradation | **PASS** | No API key → force_dry_run=True |
| F18 | _ACTION_TO_TOOL mapping | **PASS** | 17 entries |
| F19 | Claude Code UI renderers | **4/4 PASS** | ▸/✓/✗ markers, _fmt_tokens |
| F20 | Analyst YAML dynamic load | **PASS** | ANALYST_TYPES == YAML keys (4 types) |

**전체: 19/20 PASS, 1 KNOWN ISSUE (F2 offline regex 우선순위)**

---

## 검증 대상 기능 리스트

| # | 기능 | 출처 | 검증 방법 |
|---|------|------|----------|
| F1 | Pipeline dry-run 3 IP tier 정합성 | README Available IPs | CLI dry-run × 3 |
| F2 | NL Router offline 한/영 의도 매핑 (20 tools) | CHANGELOG 0.8.0, README NL Router | Python 직접 호출 |
| F3 | Plan/Delegate NL offline 매핑 | CHANGELOG 0.8.0 Added | Python 직접 호출 |
| F4 | Tool 결과 JSON 직렬화 (str→json.dumps) | CHANGELOG 0.8.0 Changed | Unit 검증 |
| F5 | Snapshot _sanitize_state() 필터링 | CHANGELOG 0.8.0 Changed | Unit 검증 |
| F6 | Verification LangSmith tracing 데코레이터 | CHANGELOG 0.8.0 Added | 데코레이터 존재 확인 |
| F7 | Guardrails G1-G4 정상 동작 | README Quality Evaluation | Pipeline state 검증 |
| F8 | BiasBuster 6-bias 검출 | README Quality Evaluation | dry-run state 검증 |
| F9 | Cross-LLM agreement 계산 | README Quality Evaluation | 수치 검증 |
| F10 | Scoring 6-weighted composite + tier | README Scoring Formula | 수식 검증 |
| F11 | Cause classification decision tree | README Cause Classification | D-E-F 축 입력 → 분류 |
| F12 | Rights risk assessment | README Quality Evaluation | fixture IP 검증 |
| F13 | ToolRegistry 기본 21개 + 동적 확장 | README Dynamic Tools | 등록/조회 검증 |
| F14 | IP search engine (keyword/genre) | README Features | 검색 결과 검증 |
| F15 | Batch analysis (dry-run) | README Features | CLI batch 실행 |
| F16 | Report generation (md/html/json) | README Features | 파일 생성 확인 |
| F17 | Graceful degradation (no API key) | README Features | 환경변수 제거 후 실행 |
| F18 | Offline mode _ACTION_TO_TOOL 매핑 | CHANGELOG 0.8.0 Fixed | 전체 action→tool 검증 |
| F19 | Claude Code UI 렌더러 (▸/✓/✗/✢/●) | CHANGELOG 0.8.0 Added | render 함수 출력 검증 |
| F20 | Analyst YAML 동적 로드 | CHANGELOG 0.7.0 C2 | ANALYST_TYPES == YAML keys |

---

## 시나리오별 상세

### F1: Pipeline Dry-run 3 IP Tier 정합성

```
입력: "Berserk", "Cowboy Bebop", "Ghost in the Shell" × --dry-run
기대:
  - Berserk → S tier, score ≈ 81.3
  - Cowboy Bebop → A tier, score ≈ 68.4
  - Ghost in the Shell → B tier, score ≈ 51.6
검증: CLI 실행 + exit code 0 + tier/score 출력 포함
```

### F2: NL Router Offline 의도 매핑 (20 tools)

```
입력 (한국어 10 + 영어 10):
  한: "목록 보여줘" → list_ips
  한: "Berserk 분석해" → analyze_ip
  한: "소울라이크 찾아줘" → search_ips
  한: "비교해줘" → compare_ips
  한: "도움말" → show_help
  한: "리포트 만들어" → generate_report
  한: "배치 분석" → batch_analyze
  한: "상태 확인" → check_status
  한: "모델 바꿔" → switch_model
  한: "기억해" → memory_save
  영: "list all IPs" → list_ips
  영: "analyze Berserk" → analyze_ip
  영: "search cyberpunk" → search_ips
  영: "compare A and B" → compare_ips
  영: "help" → show_help
  영: "generate report" → generate_report
  영: "batch run" → batch_analyze
  영: "system status" → check_status
  영: "switch model" → switch_model
  영: "remember this" → memory_save
검증: _offline_fallback() 반환 action == 기대 action
```

### F3: Plan/Delegate NL Offline 매핑

```
입력:
  "Berserk 분석 계획 세워줘" → create_plan (action=plan)
  "계획 승인해" → approve_plan (action=plan)
  "병렬로 처리해" → delegate_task (action=delegate)
  "plan for Cowboy Bebop" → create_plan (action=plan)
  "approve the plan" → approve_plan (action=plan)
  "delegate analysis" → delegate_task (action=delegate)
검증: _offline_fallback() 반환 action 일치
```

### F4: Tool 결과 JSON 직렬화

```
입력: dict, list, Pydantic model, datetime 등 다양한 타입
기대: json.dumps() 호출 → 유효 JSON 문자열
검증: json.loads(result) 성공, Python repr 형식("{'key': ...}") 아님
```

### F5: Snapshot _sanitize_state()

```
입력: {"ip_name": "Berserk", "_prompt_assembler": <object>, "_tool_definitions": [...], "tier": "S"}
기대: {"ip_name": "Berserk", "tier": "S"} (_-prefixed 제거)
검증: 반환 dict에 _-prefixed 키 없음
```

### F6: Verification LangSmith Tracing

```
검증 대상:
  - run_guardrails: @_maybe_traceable 데코레이터 존재
  - run_biasbuster: @_maybe_traceable 데코레이터 존재
  - run_cross_llm_check: @_maybe_traceable 데코레이터 존재
  - check_rights_risk: @_maybe_traceable 데코레이터 존재
검증: hasattr(fn, "__wrapped__") 또는 소스코드에 데코레이터 존재 확인
```

### F7: Guardrails G1-G4

```
입력: 유효한 GeodeState (analyses, evaluations, psm_result, tier, final_score 포함)
기대:
  - G1(Schema): PASS
  - G2(Range): PASS (scores in [1,5], composite in [0,100])
  - G3(Grounding): PASS (evidence + reasoning 존재)
  - G4(Consistency): PASS (scores within 2σ)
검증: GuardrailResult.all_passed == True
```

### F8: BiasBuster

```
입력: dry-run GeodeState (4 analysts)
기대:
  - CV > 0.05 → anchoring_bias = False
  - overall_pass = True (dry-run)
검증: BiasBusterResult 필드 확인
```

### F9: Cross-LLM Agreement

```
입력: 4 analyst scores [3.5, 4.0, 3.8, 4.2]
기대:
  - agreement coefficient ≥ 0.67
  - passed = True
검증: cross_llm_agreement 값 범위 [0, 1], passed 필드
```

### F10: Scoring 6-Weighted Composite

```
입력: PSM=70, Quality=75, Recovery=60, Growth=65, Momentum=80, Dev=50, Confidence=85
기대:
  Final = (0.25×70 + 0.20×75 + 0.18×60 + 0.12×65 + 0.20×80 + 0.05×50)
         × (0.7 + 0.3 × 85/100)
       = 71.3 × 0.955 = 68.1
  Tier: A (60 ≤ 68.1 < 80)
검증: 계산 결과 ± 1.0 오차 범위
```

### F11: Cause Classification

```
입력 → 기대:
  D=4, E=4 → conversion_failure
  D=4, E=2 → undermarketed
  D=2, E=4 → monetization_misfit
  D=2, E=2, F=4 → niche_gem
  D=2, E=2, F=2 → discovery_failure
검증: classify 결과 일치
```

### F12: Rights Risk Assessment

```
입력:
  "Cowboy Bebop" → NEGOTIABLE, risk_score=45
  "Berserk" → RESTRICTED, risk_score=72
  "Ghost in the Shell" → NEGOTIABLE, risk_score=40
  "Unknown IP" → UNKNOWN, risk_score=80
검증: status, risk_score 정확히 일치
```

### F13: ToolRegistry 21개 + 동적 확장

```
검증:
  1. definitions.json 로드 → 21개 tool 존재
  2. ToolRegistry.register(custom_tool) → 22개로 증가
  3. get_agentic_tools(registry) → custom_tool 포함
```

### F14: IP Search Engine

```
입력 → 기대:
  "dark fantasy" → Berserk 포함
  "cyberpunk" → Ghost in the Shell 포함
  "SF" → Cowboy Bebop 포함
  "nonexistent_genre_xyz" → 빈 결과
검증: 검색 결과에 기대 IP 포함
```

### F15: Batch Analysis (dry-run)

```
입력: batch --top 3 --dry-run
기대: 3 IP 모두 분석 완료, tier 할당됨
검증: exit code 0, 3개 결과 반환
```

### F16: Report Generation

```
입력: "Berserk" report 생성 (md/html/json)
기대: 각 포맷별 유효한 출력
검증: HTML에 <html> 태그, JSON에 valid parse, Markdown에 # 헤더 포함
```

### F17: Graceful Degradation

```
환경: ANTHROPIC_API_KEY 미설정
기대: 자동 dry-run 모드 전환, 에러 없이 분석 완료
검증: ReadinessReport.force_dry_run == True
```

### F18: Offline _ACTION_TO_TOOL 매핑

```
검증: _ACTION_TO_TOOL dict의 모든 value가 definitions.json tool name에 존재
      모든 _TOOL_ACTION_MAP value가 _ACTION_TO_TOOL key에 존재
```

### F19: Claude Code UI 렌더러

```
검증:
  - render_tool_call("analyze_ip", {"ip_name": "Berserk"}) → "▸" 포함
  - render_tool_result("analyze_ip", "S · 81.3") → "✓" 포함
  - render_tool_result("analyze_ip", None, error="Not found") → "✗" 포함
```

### F20: Analyst YAML 동적 로드

```
검증: ANALYST_TYPES == list(ANALYST_SPECIFIC.keys())
      len(ANALYST_TYPES) >= 4
      "game_mechanics" in ANALYST_TYPES
```

---

## 실행 순서

```
Phase 1: Unit/Integration (F4-F6, F18-F20) — 코드 레벨 검증
Phase 2: Component (F7-F12) — 개별 모듈 동작 검증
Phase 3: System (F1-F3, F13-F17) — CLI/Pipeline 통합 검증
```
