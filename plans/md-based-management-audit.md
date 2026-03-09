# GEODE .md 기반 관리 체계 점검 결과

> 점검일: 2026-03-01
> 비교 대상: Claude Code auto-memory, OpenClaw soul.md/skills

---

## 1. 현황 요약

GEODE에는 **두 개의 분리된 .md 관리 체계**가 존재합니다.

```
체계 A: Claude Code 네이티브 (.claude/)
  └── 개발자가 Claude Code를 사용할 때 로드됨 (개발 시점)

체계 B: SkillRegistry 번들 (geode/skills/)
  └── 파이프라인 런타임에 PromptAssembler가 소비 (실행 시점)
```

이 두 체계는 **서로 연결되지 않습니다**.

---

## 2. 체계 A: Claude Code 네이티브 (.claude/)

### 2.1 존재하는 파일

```
.claude/
├── MEMORY.md                          ← 프로젝트 메모리 (18줄, 정적)
├── settings.json                      ← 권한 설정
├── rules/
│   └── anime-ip.md                    ← 컨텍스트 규칙 (1개만)
└── skills/                            ← Claude Code 스킬 (7개)
    ├── architecture-patterns/SKILL.md
    ├── geode-analysis/
    │   ├── SKILL.md
    │   └── references/prompts.md
    ├── geode-pipeline/
    │   ├── SKILL.md
    │   └── references/topology.md
    ├── geode-scoring/
    │   ├── SKILL.md
    │   └── references/formulas.md
    ├── geode-verification/
    │   ├── SKILL.md
    │   └── references/decision-tree.md
    ├── geode-gitflow/SKILL.md
    └── openclaw-patterns/SKILL.md
```

### 2.2 용도

| 파일 | 소비자 | 시점 | 상태 |
|---|---|---|---|
| `CLAUDE.md` | Claude Code (개발자 도구) | 세션 시작 시 | ✅ 활용 중 |
| `.claude/MEMORY.md` | Claude Code auto-memory | 세션 시작 시 200줄 로드 | ⚠️ 존재하나 정적 (자동 갱신 안됨) |
| `.claude/rules/*.md` | `ProjectMemory.load_rules()` | 파이프라인 cortex_node | ⚠️ 1개만 존재 |
| `.claude/skills/*/SKILL.md` | Claude Code 자체 | 개발 세션 | ✅ 활용 중 |

### 2.3 MEMORY.md 내용 (전문)

```markdown
# GEODE Project Memory

## 프로젝트 개요
- 목적: 게임화 IP 중 저평가된 IP 발굴 및 회복 전략 도출
- 파이프라인: Cortex → Signals → Analysts → Evaluators → Scoring → Synthesis

## 분석 규칙
- @rules/ 디렉토리의 .md 파일이 자동 로딩됩니다

## 자주 분석하는 IP
- Berserk: 다크 판타지, S-tier, conversion_failure
- Cowboy Bebop: SF 느와르, A-tier, undermarketed
- Ghost in the Shell: 사이버펑크, B-tier, discovery_failure

## 팀 특화 루브릭 오버라이드
- (없음 — 기본 14-axis 루브릭 사용)

## 최근 인사이트
(비어 있음)
```

**진단**: MEMORY.md가 존재하지만 `## 최근 인사이트` 섹션이 비어 있습니다. `ProjectMemory.add_insight()`가 구현되어 있으나 **파이프라인에서 자동 호출되는 곳이 없습니다**.

---

## 3. 체계 B: SkillRegistry 번들 (geode/skills/)

### 3.1 존재하는 파일

```
geode/skills/
├── analyst-discovery.md
├── analyst-game-mechanics.md
├── analyst-growth-potential.md
└── analyst-player-experience.md
```

### 3.2 Frontmatter 포맷

```yaml
---
name: analyst-game-mechanics
node: analyst
type: game_mechanics
priority: 50
version: "1.0"
role: system
enabled: true
---
```

### 3.3 소비 경로

```
geode/skills/*.md
  → SkillRegistry._discover_skills() (정규식 frontmatter 파싱)
  → SkillRegistry.get_skills(node="analyst", role_type="game_mechanics")
  → PromptAssembler Phase 2 (system prompt 주입)
```

### 3.4 진단

| 항목 | 상태 |
|---|---|
| 4개 analyst 스킬 존재 | ✅ |
| SkillRegistry가 4-path 탐색으로 로드 | ✅ |
| PromptAssembler Phase 2에서 주입 | ✅ |
| ANALYST_SPECIFIC 마이그레이션 (스킬 우선) | ✅ |
| evaluator/synthesizer/biasbuster 스킬 | ❌ 없음 |

---

## 4. 부재 항목 (Claude Code / OpenClaw 대비)

### 4.1 soul.md

| 시스템 | 파일 | 용도 | GEODE |
|---|---|---|---|
| OpenClaw | `soul.md` | 에이전트 정체성, 행동 원칙, 톤 | ❌ 없음 |
| Claude Code | 해당 없음 (system prompt 내장) | — | — |
| GEODE | — | — | **CLAUDE.md가 부분 대체** (프로젝트 규칙만, 에이전트 성격 없음) |

### 4.2 Auto-Memory (자동 학습 루프)

```
Claude Code:
  PostToolUse hook → 인사이트 추출 → MEMORY.md 자동 갱신 → 다음 세션 활용

GEODE:
  PIPELINE_END hook → (아무 것도 안 함) → MEMORY.md 변경 없음
```

| 기능 | Claude Code | GEODE | 간극 |
|---|---|---|---|
| 결과 → 인사이트 자동 추출 | ✅ PostToolUse | ❌ | **핵심 부재** |
| MEMORY.md 자동 갱신 | ✅ | ❌ (`add_insight()` 미호출) | **핵심 부재** |
| topic 파일 (debugging.md 등) | ✅ | ❌ | 부재 |
| 메모리 압축/정리 | ✅ PreCompact | ❌ | 부재 |
| /memory 사용자 제어 | ✅ | ❌ | 부재 |

### 4.3 Rules 확장

```
현재: rules/ 에 anime-ip.md 1개만 존재
필요: 장르별, IP 유형별, 분석 패턴별 규칙 확장
```

### 4.4 스킬 확장

```
현재: analyst 4종만 번들
필요: evaluator 3종, synthesizer, biasbuster 스킬도 .md로 외부화
```

---

## 5. 두 체계의 연결 상태

### 5.1 연결된 부분

```
.claude/rules/*.md
  → ProjectMemory.load_rules(context)
  → ContextAssembler.assemble() → state["memory_context"]
  → PromptAssembler Phase 3 → system prompt 주입
```

이 경로는 **동작합니다**. rules/*.md에 작성한 내용이 파이프라인 LLM 프롬프트에 도달합니다.

### 5.2 연결되지 않은 부분

```
.claude/skills/*/SKILL.md
  → Claude Code 전용 (개발 시점)
  → SkillRegistry가 이 파일을 읽지 않음
  → 파이프라인 런타임에 영향 없음

.claude/MEMORY.md
  → ProjectMemory.load_memory(200) 로드
  → ContextAssembler.assemble() → state["memory_context"]["_project_loaded"]
  → PromptAssembler Phase 3 → system prompt 주입
  → 그러나 자동 갱신 경로 없음 (단방향 읽기만)
```

### 5.3 관계 다이어그램

```
                    개발 시점                    실행 시점
                  (Claude Code)              (LangGraph Pipeline)
                       │                           │
  CLAUDE.md ──────────►│                           │
  .claude/MEMORY.md ──►│    ProjectMemory ────────►│
  .claude/rules/*.md ──►│    ContextAssembler ─────►│
  .claude/skills/* ────►│    (이 파일은 무시)        │
                       │                           │
                       │    geode/skills/*.md ─────►│  ← SkillRegistry
                       │    prompts.py templates ──►│  ← PromptAssembler
                       │                           │
                       │              ◄──── 결과 ───┤
                       │         (MEMORY.md 갱신 안됨) │
```

---

## 6. 결론

### 적용 현황 점수

| 카테고리 | Claude Code 수준 | GEODE 현재 | 점수 |
|---|---|---|---|
| **CLAUDE.md** (프로젝트 지침) | 표준 | 상세히 작성됨 | 9/10 |
| **Skills (.md 외부화)** | 표준 | 2-tier 분리 (7 + 4개) | 7/10 |
| **Rules (컨텍스트 규칙)** | 표준 | 프레임워크 있으나 1개만 | 3/10 |
| **Memory (자동 학습)** | auto-memory | 정적, 단방향 읽기 | 2/10 |
| **Soul (에이전트 정체성)** | N/A (내장) | 없음 | 0/10 |
| **Auto-write-back** | PostToolUse | 미구현 | 0/10 |

**종합**: 인프라(읽기 경로)는 70% 수준이나, 쓰기 경로(자동 학습)는 0%.

---

## 7. 권장 작업 (우선순위 순)

### P0: 자동 학습 루프 연결
- `PIPELINE_END` hook → 분석 결과 요약 → `ProjectMemory.add_insight()` 자동 호출
- `MEMORY.md` "## 최근 인사이트" 섹션 자동 갱신

### P1: 스킬 확장
- evaluator 3종 (quality_judge, market_viability, innovation_potential) .md 추가
- synthesizer, biasbuster .md 추가
- geode/skills/ 에 7종 추가 → 총 11종

### P2: Rules 확장
- 장르별: rpg.md, fps.md, moba.md, idle.md
- IP 유형별: manga-ip.md, novel-ip.md, film-ip.md
- 분석 패턴별: high-growth.md, revival-candidate.md

### P3: Topic 파일 도입
- .claude/memory/ 디렉토리 (MEMORY.md index + topic files)
- ip-patterns.md, scoring-insights.md, failure-modes.md

### P4: Soul.md 도입 (선택)
- 에이전트 정체성, 분석 톤, 판단 원칙 정의
- OpenClaw의 SOUL.md 패턴 차용
