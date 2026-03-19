# .geode 고도화 -- 프론티어 리서치

> Date: 2026-03-17 | Status: **Research Complete**

## 1. 현재 상태 (AS-IS)

GEODE의 설정/상태 파일은 3개 위치에 분산되어 있다.

### 1.1. `~/.geode/` (글로벌, 사용자 수준)

| 경로 | 용도 | 구현 |
|------|------|------|
| `~/.geode/user_profile/profile.md` | 사용자 프로필 (Tier 0.5) | `FileBasedUserProfile` |
| `~/.geode/user_profile/preferences.json` | 구조화된 선호도 | `FileBasedUserProfile` |
| `~/.geode/user_profile/learned.md` | 자동 학습 패턴 | `FileBasedUserProfile` |
| `~/.geode/runs/*.jsonl` | 실행 이력 (IP별 JSONL) | `RunLog` |
| `~/.geode/scheduler/jobs.json` | 스케줄러 작업 정의 | `SchedulerService` |
| `~/.geode/scheduler/logs/*.jsonl` | 스케줄러 실행 이력 | `JobRunLog` |
| `~/.geode/skills/*.md` | 글로벌 스킬 (우선순위 3) | `SkillRegistry` |
| `~/.geode_history` | REPL 히스토리 | `prompt_toolkit` |

**특징**: 사용자 단위 영속 데이터. 프로젝트와 무관하게 유지.

### 1.2. `.geode/` (프로젝트 로컬)

| 경로 | 용도 | 구현 |
|------|------|------|
| `.geode/snapshots/` | 파이프라인 스냅샷 | `SnapshotManager` |
| `.geode/reports/` | 생성된 리포트 | CLI `_REPORT_DIR` |
| `.geode/result_cache/` | 분석 결과 캐시 (LRU 8) | `ResultCache` |
| `.geode/models/` | 모델 레지스트리 | `ModelRegistry` |
| `.geode/sessions/` | 파일 기반 세션 (옵션) | `InMemorySessionStore` |
| `.geode/user_profile/` | 프로젝트별 프로필 오버라이드 | `FileBasedUserProfile` |

**특징**: `.gitignore`에 포함. 프로젝트별 캐시/산출물.

### 1.3. `.claude/` (Claude Code 호환)

| 경로 | 용도 | 구현 |
|------|------|------|
| `.claude/MEMORY.md` | 프로젝트 메모리 (200줄) | `ProjectMemory` |
| `.claude/SOUL.md` | 조직 미션 (Tier 0) | `OrganizationMemory` |
| `.claude/rules/*.md` | 조건부 규칙 (YAML frontmatter) | `ProjectMemory` |
| `.claude/skills/` | 프로젝트 스킬 (우선순위 1) | `SkillRegistry` |
| `.claude/mcp_servers.json` | MCP 서버 설정 | `MCPServerManager` |
| `.claude/settings.json` | Claude Code 설정 | Claude Code |
| `.claude/worktrees/` | 격리 작업공간 | git worktree |

**특징**: Claude Code와 호환. 일부는 git 추적.

## 2. 프론티어 시스템 비교

### 2.1. Claude Code (.claude/)

Claude Code의 `.claude/` 시스템은 "설정 = 행동 변경" 철학의 성공 사례.

| 요소 | Claude Code | GEODE | 차이 |
|------|-------------|-------|------|
| **프로젝트 지시서** | `CLAUDE.md` (자동 로딩) | `.claude/MEMORY.md` (200줄 제한) | GEODE도 동일 패턴 |
| **조건부 규칙** | `rules/*.md` (glob matching) | `rules/*.md` (glob matching) | 동일 |
| **MCP 설정** | `mcp_servers.json` (자동 감지) | `mcp_servers.json` + `MCPRegistry` | GEODE가 더 풍부 (카탈로그 38종) |
| **사용자 메모리** | `~/.claude/` (자동 관리) | `~/.geode/user_profile/` | 유사 |
| **실행 이력** | 없음 (세션 종료 시 소멸) | `~/.geode/runs/` (JSONL 영속) | GEODE가 우위 |
| **비용 추적** | 내장 (세션 내) | `LLMUsageAccumulator` (세션 내) | 세션 간 누적 없음 |
| **설정 캐스케이드** | `~/.claude/` > `.claude/` | 부분적 (user_profile만) | 확장 필요 |

**Claude Code의 강점**: 단순성. 3개 파일(CLAUDE.md, rules/, settings.json)으로 모든 행동을 제어.

### 2.2. Karpathy autoresearch (P1-P10)

| 패턴 | autoresearch | GEODE 현재 | Gap |
|------|-------------|-----------|-----|
| **P4 Ratchet** | `if better: keep, else: revert` | RLHF 피드백 루프 | 단일 메트릭 래칫 없음 |
| **P5 Git State** | 커밋=실험, reset=폐기 | 3-Tier Memory | 실패 기록 명시적 보존 없음 |
| **P6 Context Budget** | 리다이렉트 + 선택 추출 + 1비트 판정 | Clean Context + TTL | 세션 간 컨텍스트 압축 없음 |
| **P7 program.md** | 설정=행동 변경, 코드 수정 불필요 | CLAUDE.md + Skills | 런타임 설정 변경 제한적 |

**핵심 인사이트**: autoresearch는 "실행 결과를 다음 실행에 반영"하는 폐쇄 루프. GEODE는 실행 이력(`RunLog`)을 기록하지만 이를 다음 실행 컨텍스트에 자동 주입하지 않는다.

### 2.3. OpenClaw

| 패턴 | OpenClaw | GEODE 현재 | Gap |
|------|---------|-----------|-----|
| **Session Key 계층** | `agent:{id}:{context}` | `ip:{name}:{phase}` | 구현 완료 |
| **4-tier Skill** | Bundled > Extra > Managed > Workspace | .claude > project > user > extra | 구현 완료 |
| **Atomic Store** | tmp + rename | `SchedulerService.save()` | 일부 구현 |
| **Config Hot Reload** | chokidar + debounce | `HotReloadManager` | 구현 완료 |
| **Run Log JSONL** | `{jobId}.jsonl` + pruning | `RunLog` + pruning | 구현 완료 |
| **Policy Chain** | Profile > Global > Agent > Group > Sandbox > Subagent | `PolicyChain` | 구현 완료 |
| **Active Hours** | 타임존별 quiet hours | `SchedulerService.is_within_active_hours()` | 구현 완료 |
| **Config Cascade** | 4-level override (profile > agent > group > global) | user_profile 2-level만 | 확장 필요 |
| **Health Dashboard** | 없음 (CLI 기반) | 없음 | 신규 필요 |

## 3. Gap Analysis

### 3.1. 프론티어에 있고 GEODE에 없는 것

| # | Gap | 설명 | 영향도 |
|---|-----|------|:------:|
| G1 | **설정 캐스케이드** | `~/.geode/config.toml` > `.geode/config.toml` > env > CLI 순서 오버라이드. 현재는 Pydantic Settings가 env/.env만 처리 | 높음 |
| G2 | **실행 이력 → 컨텍스트 주입** | RunLog에 기록은 하지만, 다음 실행 시 "지난번 Berserk 분석은 S tier였다"를 자동 주입하지 않음 | 높음 |
| G3 | **비용 추적 영속화** | `LLMUsageAccumulator`가 세션 내에서만 유지. 일별/주별/월별 비용 추적 없음 | 중간 |
| G4 | **API 키 Health Monitor** | MCPRegistry가 사용 가능 여부를 체크하지만, API 키의 잔액/한도/만료를 주기적으로 점검하지 않음 | 중간 |
| G5 | **Workflow Persistence** | 진행 중인 Agentic Loop/Plan Mode 상태가 프로세스 종료 시 소실. 재개 불가 | 중간 |
| G6 | **Agent Reflection** | 에이전트가 "어떤 분석을 잘했고 어떤 것을 못했는지"를 기록/학습하는 메커니즘 없음 | 중간 |
| G7 | **`.geode/` 초기화 마법사** | `geode init` 명령으로 프로젝트 .geode/ 구조 자동 생성 + 가이드 없음 | 낮음 |
| G8 | **글로벌 설정 파일** | `~/.geode/config.toml`에 기본 모델, 언어, 출력 형식 등 저장 없음 | 낮음 |
| G9 | **Usage Dashboard** | 세션별/일별 토큰 사용량, 비용, 호출 횟수 시각화 없음 | 낮음 |
| G10 | **Plugin Marketplace** | 커뮤니티 스킬/도구를 설치/공유하는 메커니즘 없음 (장기) | 낮음 |

### 3.2. 있지만 불완전한 것

| # | 항목 | 현재 | 개선 방향 |
|---|------|------|----------|
| I1 | **User Profile** | Tier 0.5 (profile.md + preferences.json + learned.md) | `learned.md`에 자동 학습 트리거 부재. 분석 완료 Hook에서 패턴 추출 필요 |
| I2 | **Result Cache** | LRU 8, `.geode/result_cache/` | 캐시 무효화 정책 없음. 시간/버전 기반 expiry 필요 |
| I3 | **Snapshot Manager** | 수동 capture만 | 파이프라인 완료 시 자동 스냅샷 + diff 비교 기능 없음 |
| I4 | **Run Log** | IP별 JSONL, auto-pruning | 집계 뷰 없음. "최근 10회 분석 요약"을 한눈에 볼 수 없음 |
| I5 | **Session Store** | TTL 기반, 파일 백업 옵션 | 세션 간 데이터 공유 없음 (각 세션이 독립) |

## 4. 기회 영역 (우선순위 순)

### Tier 1: 즉시 가치 (1-2일)

| # | 기회 | 예상 효과 | 난이도 |
|---|------|----------|:------:|
| O1 | **Config Cascade** (`~/.geode/config.toml` + `.geode/config.toml`) | 프로젝트별 모델/언어/출력 형식 설정. env 없이도 기본값 변경 가능 | 낮음 |
| O2 | **Run History Context Injection** | ContextAssembler에서 최근 RunLog 3건을 자동 주입. "이전 분석 결과"를 LLM이 참조 | 낮음 |
| O3 | **`geode init` 명령** | `.geode/` + `.claude/MEMORY.md` + `.claude/rules/` 구조 자동 생성 + 가이드 | 낮음 |

### Tier 2: 핵심 개선 (3-5일)

| # | 기회 | 예상 효과 | 난이도 |
|---|------|----------|:------:|
| O4 | **Cost Tracker 영속화** | 세션별 비용을 `~/.geode/usage/YYYY-MM.jsonl`에 기록. 월별 비용 조회 | 중간 |
| O5 | **Agent Reflection + Learned Patterns** | 분석 완료 시 `PIPELINE_COMPLETE` Hook에서 패턴 자동 추출 → `learned.md` | 중간 |
| O6 | **Result Cache Expiry** | 시간 기반(24h) + 버전 기반(prompt hash 변경 시) 캐시 무효화 | 중간 |
| O7 | **Run Log Aggregation** | `geode history` 명령 — 최근 N회 분석 요약 테이블 출력 | 중간 |

### Tier 3: 고급 기능 (1-2주)

| # | 기회 | 예상 효과 | 난이도 |
|---|------|----------|:------:|
| O8 | **Workflow Persistence** | Plan Mode/Agentic Loop 상태를 `.geode/workflows/`에 저장. 프로세스 재시작 후 재개 | 높음 |
| O9 | **API Health Monitor** | 주기적 API 키 상태 점검 + 잔액 경고 + 비용 한도 설정 | 높음 |
| O10 | **Usage Dashboard** | `geode usage` 명령 — Rich 테이블로 일별/모델별 비용 시각화 | 중간 |

## 5. 디렉토리 구조 TO-BE

```
~/.geode/                               # 글로벌 (사용자 수준)
├── config.toml                         # [NEW] 글로벌 설정 (기본 모델, 언어, 형식)
├── user_profile/
│   ├── profile.md                      # 사용자 프로필
│   ├── preferences.json                # 구조화된 선호도
│   └── learned.md                      # 자동 학습 패턴
├── usage/                              # [NEW] 비용 추적
│   ├── 2026-03.jsonl                   # 월별 사용량 JSONL
│   └── summary.json                    # 집계 캐시
├── runs/                               # 실행 이력 (IP별)
│   └── ip_berserk_analysis.jsonl
├── scheduler/
│   ├── jobs.json                       # 스케줄러 작업
│   └── logs/                           # 작업별 실행 로그
├── skills/                             # 글로벌 스킬
└── .geode_history                      # REPL 히스토리

.geode/                                 # 프로젝트 로컬
├── config.toml                         # [NEW] 프로젝트 설정 (글로벌 오버라이드)
├── snapshots/                          # 파이프라인 스냅샷
├── reports/                            # 생성된 리포트
├── result_cache/                       # 분석 결과 캐시
├── models/                             # 모델 레지스트리
├── sessions/                           # 파일 기반 세션
├── user_profile/                       # 프로젝트별 프로필 오버라이드
└── workflows/                          # [NEW] 진행 중 작업 상태

.claude/                                # Claude Code 호환
├── MEMORY.md                           # 프로젝트 메모리
├── SOUL.md                             # 조직 미션
├── rules/                              # 조건부 규칙
├── skills/                             # 프로젝트 스킬
├── mcp_servers.json                    # MCP 서버 설정
├── settings.json                       # Claude Code 설정
└── worktrees/                          # 격리 작업공간
```

## 6. 프론티어 패턴 적용 매핑

| Karpathy 패턴 | 적용 대상 | 구현 방법 |
|---------------|----------|----------|
| P4 Ratchet | O5 Agent Reflection | 분석 점수 래칫: 같은 IP의 이전 최고 점수를 기록, 하락 시 경고 |
| P6 Context Budget | O2 Run History Injection | 최근 3건만 1줄 요약으로 주입 (전체 결과가 아닌 "Berserk: S/81.3") |
| P7 program.md | O1 Config Cascade | `config.toml`이 program.md 역할. 설정 변경 = 행동 변경 |

| OpenClaw 패턴 | 적용 대상 | 구현 방법 |
|--------------|----------|----------|
| Config Cascade | O1 | 4-level: CLI > env > `.geode/config.toml` > `~/.geode/config.toml` |
| Atomic Store | O4, O8 | 모든 영속 파일에 tmp + rename 패턴 적용 |
| Run Log JSONL | O4 | `~/.geode/usage/YYYY-MM.jsonl` — 월별 비용 JSONL |
| Health Check | O9 | Heartbeat Runner 패턴으로 주기적 API 키 상태 점검 |

## 7. 참고 자료

- `core/memory/user_profile.py` — Tier 0.5 User Profile 구현
- `core/memory/session.py` — InMemorySessionStore (TTL + file persistence)
- `core/memory/project.py` — ProjectMemory (MEMORY.md + rules/)
- `core/memory/context.py` — ContextAssembler (3-tier merge)
- `core/config.py` — Pydantic Settings (.env)
- `core/orchestration/run_log.py` — RunLog (JSONL + auto-pruning)
- `core/automation/scheduler.py` — SchedulerService (3-type + active hours)
- `core/cli/result_cache.py` — ResultCache (LRU 8 + disk)
- `core/automation/snapshot.py` — SnapshotManager
- `core/llm/skill_registry.py` — SkillRegistry (4-priority)
- `core/infrastructure/adapters/mcp/registry.py` — MCPRegistry
- `.claude/skills/karpathy-patterns/SKILL.md` — P1-P10
- `.claude/skills/openclaw-patterns/SKILL.md` — Session Key, Config Cascade, Run Log
