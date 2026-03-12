---
name: karpathy-patterns
description: 자율 에이전트 시스템을 설계하거나, 에이전트의 자유도/안전성/컨텍스트 관리/협업 인프라를 결정할 때 참조. Karpathy autoresearch(자율 ML 실험 루프) + AgentHub(에이전트 네이티브 Git DAG) 에서 증류한 10대 설계 원칙. "autoresearch", "agenthub", "래칫", "ratchet", "context budget", "dumb platform", "program.md", "overnight", "자율 실험", "branchless", "단일 파일 제약", "고정 시간 예산" 키워드로 트리거.
---

# Karpathy Patterns — 자율 에이전트 설계 원칙

> **출처**: `karpathy/autoresearch` (Python, 파일 3개) + `karpathy/agenthub` (Go, 단일 바이너리)
> **철학**: 인프라가 아닌 제약으로 품질을 담보한다.
> **상세**: [Blog 22](docs/blogs/22-karpathy-autoresearch-autonomous-ml-loop.md) · [Blog 23](docs/blogs/23-karpathy-agenthub-agent-native-infrastructure.md)

## 10대 패턴 개요

| # | 패턴 | 한줄 원칙 | 자유도 | 출처 |
|---|------|----------|:-----:|------|
| P1 | 제약 기반 설계 | "무엇을 할 수 없는가"를 먼저 정의 | 가드레일 | autoresearch |
| P2 | 단일 파일 제약 | 수정 표면적 = 1 파일(또는 최소 단위) | 가드레일 | autoresearch |
| P3 | 고정 시간 예산 | 스텝이 아닌 벽시계로 공정 비교 | 가이드라인 | autoresearch |
| P4 | 래칫 메커니즘 | 개선만 유지, 악화 시 자동 복구 | 가드레일 | autoresearch |
| P5 | Git as State Machine | 커밋=실험, reset=폐기, tip=최선 해 | 가이드라인 | autoresearch |
| P6 | Context Budget 관리 | 리다이렉트 + 선택 추출로 컨텍스트 보호 | 가드레일 | autoresearch |
| P7 | program.md 인터페이스 | 에이전트 행동 변경 = 지시서 수정 | 영감 | autoresearch |
| P8 | Dumb Platform | 플랫폼은 저장만, 조율은 프롬프트에 | 영감 | AgentHub |
| P9 | Branchless DAG | 이름 없는 커밋 DAG로 에이전트 협업 | 영감 | AgentHub |
| P10 | Simplicity Selection | 코드 삭제 개선 > 코드 추가 개선 | 가이드라인 | autoresearch |

> **자유도 범례**: 가드레일 = 반드시 따라야 안전 · 가이드라인 = 선호하되 상황 판단 · 영감 = 개념 참고용

---

## P1. 제약 기반 설계

에이전트의 자유도를 필요 최소로 제한한다. autoresearch 제약: 파일 3개, train.py만 수정, 5분 wall-clock, 패키지 설치 금지, val_bpb 단일 메트릭.

**판단**: 에이전트를 설계할 때 "할 수 있는 것" 전에 "할 수 없는 것"을 먼저 정의했는가?

**GEODE 대응**: 노드 계약(output keys 제한, `core/nodes/*.py`), Clean Context(analyses 차단, `analysts.py:417`), Confidence Gate ≥ 0.7 + max 5 iter(`graph.py:66-68`).

---

## P2. 단일 파일 제약

```
autoresearch: train.py (~630줄) = 유일한 수정 대상
→ 전체 코드가 컨텍스트 윈도우에 적재, holistic 이해, diff=실험 기록
```

**판단**:

| 시나리오 | 적용? |
|---------|:-----:|
| 자율 실험 / 설정 최적화 | O |
| 대규모 리팩토링 / 멀티모듈 변경 | X |

**GEODE 대응**: 각 Analyst/Evaluator가 독립 프롬프트 + 독립 출력 모델. 한 노드가 다른 노드의 프롬프트를 수정하지 않음.

---

## P3. 고정 시간 예산

```python
TRAINING_BUDGET_SECONDS = 300  # 효율적 아키텍처 = 더 많은 스텝 (자동 보상)
```

"N회 반복" 대신 "T분 안에 최선을 다하라" → 에이전트가 자체적으로 효율성을 최적화한다.

**GEODE 대응**: 현재 iter 기반(max 5). wall-clock 도입 시 노드 타임아웃 + 부분 결과 반환 패턴 필요.

---

## P4. 래칫 메커니즘

```
LOOP:
  modify → evaluate → if better: keep, else: revert
```

**강점**: 야간 무인 실행 안전. **약점**: local optima 갇힘.

**완화**: Diversity Forcing(5회 연속 같은 유형 → 강제 전환), Simulated Annealing, Multi-branch(AgentHub DAG), Meta-optimization(program.md 자체 수정).

> 상세: Blog 22 §3.3 래칫 메커니즘

**GEODE 대응**: 5-Phase RLHF 피드백 루프(`automation/feedback_loop.py`). 래칫보다 넓은 탐색(전문가 패널) + 수렴 보장 약함.

---

## P5. Git as State Machine

```
커밋 = 실험 기록     브랜치 tip = 최선 해     git reset = 실패 폐기
```

인프라 비용 0. **약점**: `git reset`으로 실패 기록 소실 → 같은 실패 반복 위험.

> 상세: Blog 22 §6 (MLflow/W&B 비교 포함)

**GEODE 대응**: 3-Tier Memory(`memory/organization.py`, `project.py`, `session.py`)가 실패 소실 문제를 계층적 TTL로 해결.

---

## P6. Context Budget 관리

```bash
uv run train.py > run.log 2>&1   # L1: 차단 (컨텍스트 소비 0)
grep "^val_bpb:" run.log          # L2: 추출 (2줄만)
                                  # L3: 요약 → 판정 1비트 (개선/악화)
```

> 상세: Blog 22 §7

**GEODE 대응**: Clean Context — Send API에서 기존 analyses 제외(`analysts.py:418-434`). Session TTL(`session.py:43-51`). PromptAssembler — 노드별 필요 정보만 조립(`prompt_assembler.py:48-110`).

---

## P7. program.md 인터페이스

program.md = 에이전트 지시서. Setup(초기화) + Experimentation(루프 프로토콜) + Constraints(금지) + Preferences(방향) + Style(품질 기준) 구성.

**핵심**: program.md의 품질이 에이전트의 연구 품질을 결정한다. 행동 변경 시 코드가 아닌 지시서를 수정.

**GEODE 대응**: CLAUDE.md(프로젝트 지시서) + 스킬 시스템(도메인별 전문 지시서) + HookSystem 26 이벤트(`hooks.py:19-62`).

---

## P8. Dumb Platform

```
Smart Platform (GEODE/OpenClaw): 플랫폼 = 라우팅 + 동시성 + 이벤트 + 조율
Dumb Platform (AgentHub):        플랫폼 = 저장 + 전달만, 조율은 프롬프트에
```

**판단**:

| 시나리오 | 추천 |
|---------|------|
| 결정론적 순서 / SLA | Smart |
| 빈번한 조율 변경 / 오픈 엔디드 탐색 | Dumb |
| **하이브리드** | 파이프라인은 Smart, 에이전트 간 토론은 Dumb |

> 상세: Blog 23 §4, §9 (OpenClaw 비교)

**GEODE 대응**: 현재 Smart Platform. L6 Custom Agent 지원 시 Dumb 요소 부분 도입 가능.

---

## P9. Branchless DAG

브랜치/PR/머지 없이, 커밋이 사방으로 뻗어나가는 DAG. 핵심 연산: `leaves`(프론티어), `lineage`(조상 경로), `children`(직계 자손).

> 상세: Blog 23 §3

**GEODE 대응**: TaskSystem의 `get_ready_tasks()`(`task_system.py:116-120`)가 `leaves` 연산과 동일 패턴 — 의존성 충족된 pending 태스크 = 프론티어 노드.

---

## P10. Simplicity Selection

```
program.md: "20줄 추가로 0.001 개선? 불채택. 코드 삭제로 0.001 개선? 반드시 채택."
```

| 변경 | 개선 | 판정 |
|------|------|------|
| 코드 삭제 | 미세 | **채택** |
| 깔끔한 추가 | 의미있음 | 채택 |
| 해키한 추가 | 미세 | **불채택** |

LLM은 기본적으로 코드를 추가하는 방향으로 편향. 지시서에 "단순한 해법 선호"를 명시적으로 포함해야 한다.

**GEODE 대응**: 시스템 프롬프트의 "Avoid over-engineering. Only make changes that are directly requested" 원칙과 동일 철학.

---

## 패턴 간 관계

```
P1 제약 기반 설계 ─── 상위 원칙
  ├── P2 단일 파일     (코드 수준)
  ├── P3 고정 시간     (자원 수준)
  └── P10 단순성 선택  (품질 기준)

P4 래칫 ─── 안전한 자율 실행
  └── P5 Git State Machine (구현 메커니즘)

P6 Context Budget ─── 장시간 실행 지속
  └── P7 program.md    (인간-에이전트 인터페이스)

P8 Dumb Platform ─── 다중 에이전트 확장
  └── P9 Branchless DAG (구현 패턴)
```

## 스케일별 적용 가이드

| 규모 | 적용 패턴 | 비적용 |
|------|----------|--------|
| 단일 에이전트, 단일 태스크 | P1, P2, P4, P5 | P8, P9 |
| 단일 에이전트, 야간 자율 | P1-P7, P10 | P8, P9 |
| 다중 에이전트, 탐색적 | P1, P4, P6, P8, P9 | P2 |
| 다중 에이전트, 프로덕션 | P1, P3, P4, P6 + Smart | P8 |

## 안티패턴

| 안티패턴 | 위반 | 증상 |
|---------|------|------|
| "모든 파일 수정 가능" | P2 | 파편적 변경, 의존성 파괴 |
| "무제한 실행" | P3 | 비용 폭주, 무의미한 탐색 |
| "모든 결과를 컨텍스트에" | P6 | 컨텍스트 고갈, 조기 종료 |
| "플랫폼이 전부 제어" | P8 | 유연성 상실, 배포 병목 |
| "개선이면 무조건 채택" | P10 | 복잡성 누적 |
| "실패 기록 미보존" | P5 | 같은 실패 반복 |
