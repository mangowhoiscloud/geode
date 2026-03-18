# .geode Context Hub — 목적 중심 컨텍스트 계층 설계 v2

> Date: 2026-03-18 | Status: **Phase A+B 구현 완료, Vault 설계 확정**
> 선행: `research-geode-enhancement.md`, `ADR-011`, 프론티어 4종 리서치

## 0. 실제 사용 시나리오

GEODE는 범용 자율 실행 에이전트로, 실제 사용자 워크플로우:

| 시나리오 | 입력 | 산출물 | 저장 위치 (AS-IS) | 문제 |
|----------|------|--------|:-:|------|
| **리서치** | "AI 에이전트 시장 조사해줘" | 마크다운 보고서 | `/tmp/` | 재부팅 시 소멸 |
| **프로필 수집** | "내 YouTube, 블로그 시그널 분석해" | 시그널 분석 리포트 | `/tmp/` | 다음 세션에서 참조 불가 |
| **공고 탐색** | "프론트엔드 시니어 채용 찾아줘" | 공고 목록 + 매칭 분석 | 화면 출력만 | 영속 안 됨 |
| **지원서 작성** | "이 회사에 맞는 커버레터 써줘" | 커버레터 + 이력서 변형 | `/tmp/` | 버전 관리 안 됨 |

**근본 문제**: 에이전트가 생성한 산출물의 **영속 저장소**가 없다. `/tmp/`는 임시, `.geode/reports/`는 분석 리포트 전용.

## 1. 설계 원칙

**"각 계층은 하나의 질문에 답한다. 산출물은 목적별로 분류한다."**

## 2. 6-Layer Context Hierarchy (v2)

```
Layer  질문                           수명         쓰기 주체       물리 경로
──────────────────────────────────────────────────────────────────────────────
 C0    "나는 누구인가?"                 영구         사용자          ~/.geode/identity/
 C1    "이 프로젝트는 무엇인가?"         프로젝트      사용자          .geode/project/ + .claude/
 C2    "지금까지 무엇을 했는가?"         누적(불변)    에이전트        .geode/journal/
 V0    "무엇을 만들었는가?"             영속         에이전트        .geode/vault/
 C3    "지금 무엇을 하고 있는가?"        세션         에이전트        .geode/session/
 C4    "다음에 무엇을 해야 하는가?"      단기         에이전트+사용자  .geode/plan/
```

### C0: Identity — "나는 누구인가?"

사용자의 정체성, 경력, 선호. 프로젝트와 무관하게 모든 세션에서 참조.

| 파일 | 역할 |
|------|------|
| `~/.geode/identity/profile.md` | 이름, 역할, 전문 분야, 경력 요약 |
| `~/.geode/identity/career.toml` | 구조화된 경력 데이터 (스킬, 경험, 학력, 목표) |
| `~/.geode/identity/preferences.toml` | 선호 모델, 출력 형식, 언어, 예산 |
| `~/.geode/identity/policies.toml` | 사용자 수준 도구 정책 |

**career.toml 스키마**:
```toml
[basics]
name = ""
title = ""          # "ML Engineer", "프리랜서 개발자"
location = ""
languages = ["ko", "en"]

[summary]
bio = ""            # 2-3줄 자기소개 (커버레터/지원서 소스)
highlights = []     # 핵심 성과 3-5개

[skills]
primary = []        # ["Python", "LangGraph", "Agentic AI"]
secondary = []      # ["React", "TypeScript"]
tools = []          # ["Claude Code", "Docker", "Kubernetes"]

[experience]
# 최신 순서
[[experience.entries]]
company = ""
role = ""
period = ""         # "2024.03 - present"
description = ""
achievements = []

[education]
[[education.entries]]
school = ""
degree = ""
period = ""

[career_goals]
target_roles = []       # ["Senior ML Engineer", "AI Platform Lead"]
target_industries = []  # ["AI/ML", "게임", "핀테크"]
target_companies = []   # ["Anthropic", "넥슨"]
salary_range = ""       # "8000-12000만원"
preferred_locations = [] # ["서울", "Remote"]
```

**왜 career.toml이 C0인가?** 지원서 작성, 프로필 분석, 공고 매칭 등 모든 시나리오에서 참조되는 **원천 데이터**. 프로젝트가 바뀌어도 경력은 동일.

---

### C1: Project — "이 프로젝트는 무엇인가?"

프로젝트 규칙, 설정, 도메인 지식. 변경 없음 (기존과 동일).

---

### C2: Journal — "지금까지 무엇을 했는가?"

모든 실행의 불변 기록. **구현 완료** (Phase A).

| 파일 | 역할 |
|------|------|
| `.geode/journal/runs.jsonl` | 실행 이력 |
| `.geode/journal/costs.jsonl` | 비용 기록 |
| `.geode/journal/learned.md` | 학습 패턴 |
| `.geode/journal/errors.jsonl` | 에러 기록 |

---

### V0: Vault — "무엇을 만들었는가?" (NEW)

**목적**: 에이전트가 생성한 모든 산출물의 **목적별 영속 저장소**. `/tmp/`에 빠지던 파일들의 정식 거처.

```
.geode/vault/
├── profile/                    프로필 관련 산출물
│   ├── signal-report-2026-03-19.md     시그널 분석 보고서
│   ├── resume-v3.md                     이력서 (버전 관리)
│   └── portfolio-summary.md             포트폴리오 요약
├── research/                   리서치 산출물
│   ├── ai-agent-market-2026-03.md      시장 조사 보고서
│   ├── company-anthropic.md             회사 리서치
│   └── tech-langgraph-vs-crewai.md     기술 비교
├── applications/               지원서 산출물
│   ├── anthropic-senior-ml/
│   │   ├── cover-letter.md              커버레터
│   │   ├── resume-tailored.md           맞춤 이력서
│   │   └── meta.json                    지원 상태, 날짜, 결과
│   └── nexon-ai-platform/
│       ├── cover-letter.md
│       └── meta.json
└── general/                    분류 안 된 산출물
    └── {자동생성파일}.md
```

**핵심 속성**:
- **목적별 하위 디렉토리**: profile/, research/, applications/, general/
- **에이전트가 자동 분류**: 생성 시 카테고리 판단하여 적절한 하위 디렉토리에 저장
- **버전 관리**: 같은 파일 재생성 시 `-v2`, `-v3` suffix 또는 날짜 suffix
- **meta.json**: applications/ 하위에는 지원 상태 추적 메타데이터
- **다음 세션에서 참조 가능**: "지난번 작성한 Anthropic 커버레터 수정해줘"

**Vault 카테고리 라우팅 규칙**:

| 키워드/컨텍스트 | 카테고리 | 예시 |
|:--|:--|:--|
| 프로필, 시그널, 이력서, resume, CV | `profile/` | 시그널 분석, 이력서 |
| 리서치, 조사, 분석, 비교, report | `research/` | 시장 조사, 기술 비교 |
| 지원, 커버레터, cover letter, 자소서 | `applications/{company}/` | 회사별 지원 패키지 |
| 그 외 | `general/` | 기타 산출물 |

**meta.json (applications용)**:
```json
{
  "company": "Anthropic",
  "position": "Senior ML Engineer",
  "url": "https://...",
  "status": "draft",
  "applied_at": null,
  "deadline": "2026-04-01",
  "files": ["cover-letter.md", "resume-tailored.md"],
  "notes": ""
}
```

---

### C3: Session — "지금 무엇을 하고 있는가?"

**구현 완료** (Phase B). 변경 없음.

---

### C4: Plan — "다음에 무엇을 해야 하는가?"

미완료 작업 + 지원 트래킹. 기존 설계에 **지원 파이프라인** 추가.

| 파일 | 역할 |
|------|------|
| `.geode/plan/goals.json` | 분해된 목표 DAG |
| `.geode/plan/pending.json` | 미완료 작업 |
| `.geode/plan/tracker.json` | 지원 트래커 (회사별 상태 + 마감일) |

**tracker.json 스키마**:
```json
{
  "applications": [
    {
      "company": "Anthropic",
      "position": "Senior ML Engineer",
      "status": "applied",
      "applied_at": "2026-03-15",
      "deadline": "2026-04-01",
      "vault_path": "applications/anthropic-senior-ml/",
      "next_action": "follow-up in 2 weeks",
      "notes": ""
    }
  ]
}
```

---

## 3. 계층 간 데이터 흐름 (v2)

```
사용자: "내 프로필 시그널 분석해줘"
       │
       ├─ 읽기: C0(career.toml, profile.md) + C2(Journal 최근 리서치) + V0(기존 프로필 산출물)
       │        → 시스템 프롬프트 조립
       │
       ├─ 실행: 웹 검색 (YouTube, 블로그, GitHub) → 분석
       │
       ├─ 저장: V0(vault/profile/signal-report-YYYY-MM-DD.md)  ← /tmp/ 대신!
       │
       └─ 침전: C2(journal/runs.jsonl) ← 실행 기록
                C2(journal/learned.md) ← "이 사용자는 에이전틱 AI 분야 전문"

사용자: "Anthropic Senior ML Engineer에 지원서 써줘"
       │
       ├─ 읽기: C0(career.toml) + V0(vault/profile/signal-report.md) + V0(vault/research/company-anthropic.md)
       │
       ├─ 생성: 커버레터 + 맞춤 이력서
       │
       ├─ 저장: V0(vault/applications/anthropic-senior-ml/cover-letter.md)
       │        V0(vault/applications/anthropic-senior-ml/resume-tailored.md)
       │        V0(vault/applications/anthropic-senior-ml/meta.json)
       │
       └─ 갱신: C4(plan/tracker.json) ← 지원 상태 "draft"
```

## 4. 물리적 디렉토리 (v2)

```
~/.geode/                           C0: Identity (글로벌)
├── identity/
│   ├── profile.md                  이름, 역할, 자기소개
│   ├── career.toml                 구조화된 경력 데이터
│   ├── preferences.toml            선호 설정
│   └── policies.toml               도구 정책
├── config.toml                     글로벌 기본 설정
└── usage/                          글로벌 비용 추적

.geode/                             프로젝트 컨텍스트 (gitignored)
├── project/                        C1: 프로젝트 설정
│   └── config.toml
├── journal/                        C2: 불변 실행 기록
│   ├── runs.jsonl
│   ├── costs.jsonl
│   ├── learned.md
│   └── errors.jsonl
├── vault/                          V0: 산출물 영속 저장소
│   ├── profile/                    프로필 (시그널, 이력서, 포트폴리오)
│   ├── research/                   리서치 (시장, 회사, 기술)
│   ├── applications/               지원서 (회사별 패키지)
│   │   └── {company-slug}/
│   │       ├── cover-letter.md
│   │       ├── resume-tailored.md
│   │       └── meta.json
│   └── general/                    미분류 산출물
├── session/                        C3: 세션 체크포인트
│   └── {session-id}/
├── plan/                           C4: 미완료 작업 + 지원 트래커
│   ├── goals.json
│   ├── pending.json
│   └── tracker.json
└── cache/                          TTL 캐시

.claude/                            Claude Code 호환 (변경 없음)
```

## 5. 구현 계획

### 이미 완료 (Phase A+B)

- [x] `ProjectJournal` (C2) — runs.jsonl, costs.jsonl, learned.md, errors.jsonl
- [x] `journal_hooks.py` — PIPELINE_END/ERROR 자동 침전
- [x] `SessionCheckpoint` (C3) — save/load/cleanup
- [x] `ContextAssembler` C2 통합 — Journal 주입
- [x] `geode init` 디렉토리 생성 — journal/, session/, plan/, project/

### Phase D: Vault (산출물 저장소)

| # | 작업 | 파일 | 설명 |
|---|------|------|------|
| D1 | `Vault` 모듈 | `core/memory/vault.py` (신규) | `.geode/vault/` 카테고리 라우팅 + 저장 + 조회 |
| D2 | `geode init` vault 추가 | `core/cli/__init__.py` | vault/profile, research, applications, general 디렉토리 |
| D3 | 도구 연동 | AgenticLoop 산출물 저장 시 vault 경로 사용 | `/tmp/` → vault 라우팅 |

### Phase E: Career Identity (C0 확장)

| # | 작업 | 파일 | 설명 |
|---|------|------|------|
| E1 | `career.toml` 로딩 | `core/memory/user_profile.py` 확장 | career 필드 로드 + 시스템 프롬프트 주입 |
| E2 | 프로필 도구 연동 | `core/tools/profile_tools.py` 확장 | career 데이터 CRUD |

### Phase F: Application Tracker (C4 확장)

| # | 작업 | 파일 | 설명 |
|---|------|------|------|
| F1 | `tracker.json` 관리 | `core/memory/vault.py` 확장 | 지원 상태 CRUD |
| F2 | `/apply` 커맨드 | `core/cli/commands.py` | 지원 현황 조회/갱신 |

### 우선순위

```
Phase D (Vault) ──→ Phase E (Career) ──→ Phase F (Tracker)
  "산출물 저장"        "정체성 구조화"       "지원 파이프라인"
```
