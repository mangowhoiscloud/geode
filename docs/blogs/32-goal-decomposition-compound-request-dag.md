# Goal Decomposition — 복합 요청을 $0.01에 DAG로 분해하기

> Date: 2026-03-16 | Author: geode-team | Tags: [goal-decomposition, dag, haiku, heuristic, cost-optimization, agentic-loop, task-graph]

## 목차

1. [도입 — "분석하고 비교하고 리포트 만들어줘"](#1-도입--분석하고-비교하고-리포트-만들어줘)
2. [2단계 휴리스틱 — LLM을 호출하지 않는 70%](#2-2단계-휴리스틱--llm을-호출하지-않는-70)
3. [LLM 분해 — Haiku로 $0.01에 DAG 생성](#3-llm-분해--haiku로-001에-dag-생성)
4. [시스템 프롬프트 주입 — 서브에이전트 없이 실행](#4-시스템-프롬프트-주입--서브에이전트-없이-실행)
5. [TaskGraph 변환 — 의존성과 실패 전파](#5-taskgraph-변환--의존성과-실패-전파)
6. [트레이드오프 — 주입 vs 위임 vs 계획](#6-트레이드오프--주입-vs-위임-vs-계획)
7. [마무리](#7-마무리)

---

## 1. 도입 — "분석하고 비교하고 리포트 만들어줘"

GEODE의 AgenticLoop은 `while(tool_use)` 루프로 작동합니다. LLM이 도구를 호출하고, 결과를 받고, 다음 도구를 호출합니다. 단일 의도 요청("Berserk 분석해줘")에는 이 구조가 잘 작동합니다.

문제는 **복합 요청**입니다.

```
"Berserk 분석하고 Cowboy Bebop이랑 비교해줘, 그리고 리포트도 만들어줘"
```

이 요청에는 3개의 독립적인 의도가 있습니다: 분석, 비교, 리포트 생성. LLM이 이 3개를 순서대로 실행하려면 **어떤 순서로, 어떤 도구를**, 그리고 **이전 결과에 의존하는 것은 무엇인지** 스스로 판단해야 합니다.

Claude Opus는 대부분 올바르게 처리하지만, 때로 비효율적인 순서를 선택하거나(리포트를 먼저 시도), 중간 단계를 건너뛰거나(비교 없이 리포트), 15 라운드 제한에 도달합니다.

Goal Decomposition은 이 문제를 **사전 분해(pre-decomposition)**로 해결합니다. 복합 요청을 받으면 경량 모델(Haiku)로 하위 목표 DAG(Directed Acyclic Graph)를 생성하고, 이 계획을 AgenticLoop의 시스템 프롬프트에 주입합니다.

---

## 2. 2단계 휴리스틱 — LLM을 호출하지 않는 70%

모든 요청에 LLM 분해를 적용하면 불필요한 비용이 발생합니다. "목록 보여줘"나 "/help"에 Haiku를 호출할 이유가 없습니다.

### Stage 1: 명백한 단순 요청

```python
# core/orchestration/goal_decomposer.py
def _is_clearly_simple(self, text: str) -> bool:
    if text.startswith("/"):
        return True   # 슬래시 커맨드
    if len(text) < 15:
        return True   # 짧은 입력
    return False
```

> 15자 미만의 입력은 복합 요청이 될 수 없습니다. "Berserk 분석해" (8자), "목록" (2자), "help" (4자)는 모두 단일 의도입니다. 이 경계값은 한국어 기준으로 "X 분석하고 Y 비교해" 같은 최소 복합문이 20자 이상이라는 관찰에서 결정했습니다.

### Stage 2: 복합 지표 탐지

```python
# core/orchestration/goal_decomposer.py
_COMPOUND_PATTERNS: list[str] = [
    "그리고", "다음에", "후에", "하고",     # 한국어 접속사
    "and", "then", "after that",           # 영어
    "종합", "전반적", "포괄적", "다각도",   # 복합 분석 키워드
    "comprehensive", "end-to-end",
]

def _has_compound_indicators(self, text: str) -> bool:
    lower = text.lower()
    return any(p in lower for p in self._COMPOUND_PATTERNS)
```

> Stage 1을 통과한 요청 중에서도 "Berserk 분석해줘"처럼 단일 의도인 경우가 대부분입니다. 복합 지표가 없으면 LLM 호출을 건너뜁니다. 이 2단계 필터로 전체 요청의 **약 70-80%가 LLM 호출 없이 통과**합니다.

### 흐름

```
"Berserk 분석해"
  → Stage 1: 14자? No (15자 미만 아님... 실제로는 통과 가능)
  → Stage 2: "그리고", "and" 등 복합 지표? No
  → 결과: passthrough (LLM 미호출)

"Berserk 분석하고 리포트 만들어줘"
  → Stage 1: 18자 → No
  → Stage 2: "하고" 발견! → Yes
  → 결과: LLM 분해 호출
```

---

## 3. LLM 분해 — Haiku로 $0.01에 DAG 생성

복합 지표가 감지되면 Haiku 모델로 요청을 구조화합니다.

### 출력 스키마

```python
# core/orchestration/goal_decomposer.py
class SubGoal(BaseModel):
    id: str                          # "step_1", "step_2"
    description: str                 # "Berserk IP 분석"
    tool_name: str                   # "analyze_ip"
    tool_args: dict[str, Any]        # {"ip_name": "Berserk"}
    depends_on: list[str] = []       # ["step_1"] — 이전 단계 의존

class DecompositionResult(BaseModel):
    is_compound: bool                # 복합 요청 여부
    goals: list[SubGoal]             # 하위 목표 리스트
    reasoning: str                   # LLM의 분해 근거
```

> `depends_on` 필드가 DAG의 핵심입니다. step_2가 `["step_1"]`에 의존하면, step_1이 완료되어야 step_2가 실행됩니다. 의존관계가 없는 step들은 병렬 실행 가능합니다.

### 비용 구조

```python
# 분해 호출
result = call_llm_parsed(
    system=decomposer_system,   # ~800 tokens
    user=user_request,          # ~50 tokens
    output_model=DecompositionResult,
    model=ANTHROPIC_BUDGET,     # claude-haiku-4-5-20251001
    max_tokens=2048,
    temperature=0.0,            # 결정적
)
```

| 항목 | 토큰 수 | 단가 (Haiku) | 비용 |
|------|--------|-------------|------|
| System prompt + tools | ~1300 | $1.00/M input | $0.0013 |
| User request | ~50 | $1.00/M input | $0.00005 |
| Output (JSON) | ~200 | $5.00/M output | $0.0010 |
| **합계** | ~1550 | | **~$0.0024** |

> Opus($5/$25)로 동일 작업을 하면 ~$0.012입니다. Haiku는 **5배 저렴**합니다. 분해는 정형화된 작업(복합문 → 도구 호출 리스트)이라 Haiku의 능력으로 충분합니다. 창의적 추론이 아닌 **구조적 매핑**이기 때문입니다.

### 프롬프트 캐싱 효과

시스템 프롬프트와 도구 정의는 세션 내에서 동일합니다. Anthropic의 ephemeral 캐시(5분)가 적용되면 2번째 분해부터 입력 비용이 90% 절감됩니다.

| 호출 | 캐시 | 입력 비용 |
|------|------|----------|
| 1회차 | Creation (1.25x) | $0.0016 |
| 2회차+ | Read (0.1x) | $0.00013 |

---

## 4. 시스템 프롬프트 주입 — 서브에이전트 없이 실행

분해된 목표를 어떻게 실행할까요? 세 가지 선택지가 있었습니다.

| 방식 | 장점 | 단점 |
|------|------|------|
| **서브에이전트 위임** | 병렬 실행, 격리된 컨텍스트 | 오버헤드 큼, 결과 취합 복잡 |
| **PlanMode 실행** | 기존 인프라 재사용 | 사용자 승인 필요 (AUTO 모드 아니면) |
| **시스템 프롬프트 주입** | 가장 단순, 기존 멀티툴 실행 재사용 | 세밀한 step별 제어 불가 |

**시스템 프롬프트 주입**을 선택했습니다.

```python
# core/cli/agentic_loop.py — _try_decompose()
decomposition_hint = self._try_decompose(user_input)

system_prompt = self._build_system_prompt()
if decomposition_hint:
    system_prompt += "\n\n" + decomposition_hint
```

주입되는 텍스트:

```
## Goal Decomposition Plan

The user's request has been decomposed into 3 sub-goals.
Execute them in dependency order. For each step, call the specified tool.

- **step_1**: Analyze Berserk → `analyze_ip(ip_name="Berserk")`
- **step_2**: Compare with Cowboy Bebop → `compare_ips(ip_a="Berserk", ip_b="Cowboy Bebop")`
  (depends on: step_1)
- **step_3**: Generate report → `generate_report(ip_name="Berserk")`
  (depends on: step_1)

Reasoning: Analysis first, then comparison and report can proceed independently.
```

> 이 접근의 핵심 통찰: **Opus는 이미 멀티툴 실행을 할 수 있습니다.** 분해기가 하는 일은 Opus에게 "이 순서로 해"라는 **힌트**를 주는 것뿐입니다. Opus가 힌트를 무시할 수도 있지만, 실제로는 구조화된 계획이 주어지면 거의 항상 따릅니다. 이는 별도의 실행 엔진을 만들지 않으면서 분해의 이점을 얻는 방법입니다.

### 서브에이전트 위임과의 차이

```
서브에이전트 위임 (delegate_task):
  Parent → SubAgentManager → Thread Pool → 3개 독립 AgenticLoop
  → 각각 LLM 호출 × N → 결과 취합 → Token Guard → Parent에 반환
  비용: Opus 호출 3회 × $0.30 = ~$0.90

시스템 프롬프트 주입 (GoalDecomposer):
  Haiku 분해 ($0.0024) → 힌트 주입 → 기존 AgenticLoop이 순서대로 실행
  비용: Haiku 1회 ($0.0024) + Opus 1회 ($0.30) = ~$0.30
```

> 서브에이전트는 **독립적이고 병렬 가능한** 태스크에 적합합니다 ("3개 IP를 동시에 분석해"). 시스템 프롬프트 주입은 **순차 의존성이 있는** 복합 요청에 적합합니다 ("분석하고 그 결과로 비교해"). 두 패턴은 경쟁이 아니라 보완입니다.

---

## 5. TaskGraph 변환 — 의존성과 실패 전파

분해 결과는 `TaskGraph`로 변환되어 의존성 추적과 실패 전파를 지원합니다.

```python
# core/orchestration/goal_decomposer.py
def build_task_graph_from_goals(result: DecompositionResult) -> TaskGraph:
    graph = TaskGraph()
    for goal in result.goals:
        task = Task(
            task_id=goal.id,
            name=goal.description,
            dependencies=goal.depends_on,
        )
        task.metadata = {"tool_name": goal.tool_name, "tool_args": goal.tool_args}
        graph.add_task(task)
    graph.validate()  # 순환 감지
    return graph
```

### 의존성 DAG 예시

```
"다크 판타지 IP 검색해서 가장 높은 거 분석하고 리포트 만들어줘"

step_1: search_ips(query="dark fantasy")         depends_on: []
step_2: analyze_ip(ip_name="")                   depends_on: [step_1]
step_3: generate_report(ip_name="")              depends_on: [step_2]

DAG: step_1 → step_2 → step_3 (선형 의존)
```

```
"Berserk 분석하고, 리포트도 만들고, Cowboy Bebop도 검색해줘"

step_1: analyze_ip(ip_name="Berserk")            depends_on: []
step_2: generate_report(ip_name="Berserk")       depends_on: [step_1]
step_3: search_ips(query="Cowboy Bebop")          depends_on: []

DAG: step_1 → step_2
     step_3 (독립)          ← step_1과 step_3은 병렬 가능
```

### 실패 전파

```python
# TaskGraph.propagate_failure()
# step_1이 실패하면:
#   step_2 (depends_on: [step_1]) → 자동 SKIPPED
#   step_3 (depends_on: [])       → 정상 실행
```

> `tool_args`가 비어있는 경우(`ip_name=""`)는 **의존성 기반 추론**을 의미합니다. step_2의 `ip_name`은 step_1의 결과에서 채워져야 합니다. 이 추론은 GoalDecomposer가 아닌 AgenticLoop의 LLM이 수행합니다. 분해기는 "무엇을 어떤 순서로"만 결정하고, "구체적으로 어떤 값을"은 실행 시점에 LLM이 판단합니다.

---

## 6. 트레이드오프 — 주입 vs 위임 vs 계획

### 세 가지 패턴의 위치

```
                 제어 수준 높음
                      │
    PlanMode ─────────┼───── delegate_task
    (승인 필요,        │    (병렬, 격리,
     단계별 검토)      │     독립 AgenticLoop)
                      │
  ────────────────────┼──────────────── 비용 높음
                      │
    GoalDecomposer ───┼
    (힌트 주입,        │
     ~$0.01, 자동)     │
                      │
                 제어 수준 낮음
```

| 패턴 | 적합한 요청 | 비용 | 사용자 개입 |
|------|-----------|------|-----------|
| **GoalDecomposer** | 순차 의존 복합 ("분석하고 비교해") | ~$0.01 + 1× Opus | 없음 |
| **delegate_task** | 독립 병렬 ("3개 IP 동시 분석") | N× Opus | 없음 |
| **PlanMode** | 고위험 다단계 ("전략 수립 → 실행") | 1× Haiku + N× Opus | 승인 필요 (MANUAL) |

### Graceful Degradation

GoalDecomposer가 실패하면 어떻게 될까요?

```python
# core/cli/agentic_loop.py
decomposition_hint = self._try_decompose(user_input)
# decomposition_hint가 None이면 → 힌트 없이 AgenticLoop 정상 실행
# LLM이 스스로 멀티툴 실행을 결정
```

> 분해기 실패는 **품질 저하(degradation)**이지 **오류(error)**가 아닙니다. Opus는 분해 힌트 없이도 복합 요청을 처리할 수 있습니다. 다만 순서가 비효율적이거나 max_rounds에 도달할 확률이 높아질 뿐입니다. 이 설계 덕분에 분해기를 추가해도 **기존 동작의 안정성이 영향받지 않습니다**.

---

## 7. 마무리

### 핵심 정리

| 항목 | 값 |
|------|-----|
| 모델 | Haiku (claude-haiku-4-5-20251001) |
| 호출 비용 | ~$0.0024/회 (~$0.01 보수 추정) |
| 휴리스틱 통과율 | ~70-80% (LLM 미호출) |
| 출력 | `DecompositionResult` (Pydantic Structured Output) |
| 실행 방식 | 시스템 프롬프트 주입 (서브에이전트 아님) |
| 의존성 추적 | TaskGraph DAG (순환 감지, 실패 전파) |
| 실패 시 | graceful degradation — AgenticLoop이 스스로 처리 |
| Temperature | 0.0 (결정적) |

### 설계 원칙

1. **비용 최적화가 아키텍처를 결정한다**: Haiku로 분해하고 Opus로 실행하는 2-tier 모델 분리는 비용 의식에서 비롯된 아키텍처 결정입니다. 분해는 정형화된 작업이므로 비싼 모델이 불필요합니다.

2. **실행보다 힌트가 낫다**: 분해기가 직접 도구를 호출하지 않고 AgenticLoop에 계획을 주입합니다. 실행은 기존 인프라(ToolExecutor, HITL, Error Recovery)를 재사용합니다. 새로운 실행 경로를 만들지 않아 안전 게이트가 보존됩니다.

3. **실패해도 괜찮다**: GoalDecomposer는 선택적 개선입니다. 없어도 AgenticLoop은 작동합니다. 이 "additive, not essential" 설계 덕분에 점진적 도입이 가능합니다.

### 체크리스트

- [x] 2단계 휴리스틱 필터 (slash + 길이 / 복합 지표)
- [x] Haiku 기반 SubGoal DAG 생성 (~$0.01)
- [x] Pydantic Structured Output으로 타입 안전 분해
- [x] 시스템 프롬프트 주입으로 AgenticLoop 가이드
- [x] TaskGraph 변환 + 의존성 기반 실행 순서
- [x] 실패 전파 (propagate_failure)
- [x] Graceful degradation (분해 실패 시 정상 실행)
- [x] 프롬프트 캐싱으로 반복 호출 비용 절감
