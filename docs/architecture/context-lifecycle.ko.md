# `.geode/` -- 에이전트 Context 라이프사이클

> [English](context-lifecycle.md) | **한국어**

`.geode/` 디렉토리는 에이전트의 프로젝트-로컬 영속 저장소입니다. 세션 간에 유지되며, 모든 LLM 호출을 형성하는 context 계층 구조를 제공합니다.

## 디렉토리 구조

```
.geode/
├── config.toml              # Gateway bindings, MCP servers, model 설정
├── MEMORY.md                # 사람이 읽을 수 있는 memory 인덱스 (deprecated, 마이그레이션 중)
├── LEARNING.md              # 에이전트 학습 로그
│
├── memory/                  # Tier 2: Project Memory
│   └── PROJECT.md           # 구조화된 IP 분석 이력 (최대 50, LRU 로테이션)
│
├── rules/                   # 자동 생성된 도메인 규칙
│   ├── dark-fantasy.md      # 패턴: *berserk*, *dark*soul*, *elden*
│   ├── anime-ip.md          # 패턴: *cowboy*, *ghost*, *evangelion*
│   └── indie-steam.md       # 패턴: *satisfactory*, *factorio*
│
├── vault/                   # 영구 산출물 (자동 삭제 없음)
│   ├── reports/             # 생성된 분석 리포트 (md/html/json)
│   ├── research/            # 심층 리서치 결과물
│   ├── profile/             # 사용자 경력 프로필, 이력서
│   └── applications/        # 입사 지원 추적
│
├── skills/                  # Runtime Skills (20개 도메인 특화 프롬프트 주입)
│   ├── arxiv-digest/        # AI 논문 자동 검색 및 요약
│   ├── daily-briefing/      # 아침 뉴스/트렌드 요약
│   ├── deep-researcher/     # 체계적 웹 리서치 + 리포트
│   ├── job-hunter/          # 채용공고 검색 + 매칭 분석
│   └── ...
│
├── result_cache/            # 파이프라인 결과 LRU 캐시 (SHA-256 key, 24h TTL)
└── user_profile/            # Tier 0.5: 사용자 아이덴티티 + 선호 설정
```

## Context 계층 구조

`ContextAssembler`는 5개 티어를 하나의 context dict로 병합하여 모든 LLM 호출에 주입합니다. 동일 키에 대해 낮은 티어가 높은 티어를 오버라이드합니다.

```
Tier 0   SOUL           GEODE.md — 에이전트 아이덴티티, 미션, 제약 조건
Tier 0.5 User Profile   ~/.geode/user_profile/ — 역할, 전문 분야, 언어, 포맷 선호
Tier 1   Organization   MonoLake — 크로스 프로젝트 IP 데이터 (DAU, 매출, 시그널)
Tier 2   Project        .geode/memory/PROJECT.md — 프로젝트 로컬 분석 이력
Tier 3   Session        인메모리 — 현재 대화, 도구 결과, 계획
```

### 조립 플로우

```
ContextAssembler.assemble(session_id, ip_name)
│
├── T0  GEODE.md 로드 (아이덴티티)
├── T0.5 user_profile 로드 (선호 설정)
├── T1  org_memory.get_ip_context(ip_name) 로드
├── T2  project_memory.get_context_for_ip(ip_name) 로드
├── T3  session_store.get(session_id) 로드
│
├── project_env 주입 (감지된 harness: Python/Node/등)
├── run_history 주입 (최근 실행 요약, Karpathy P6 L3)
├── journal_context 주입 (학습된 패턴)
└── vault_context 주입 (관련 산출물)
```

### 예산 할당 (280자 압축)

Context가 예산을 초과하면, `ContextAssembler.compress()`가 비례 할당합니다:

| 티어 | 예산 | 전략 |
|------|------|------|
| SOUL | 10% | 미션 라인 추출 (첫 비헤더 라인) |
| User Profile | (SOUL과 공유) | 한 줄 요약 |
| Organization | 25% | 핵심 지표만 |
| Project | 25% | 최신 분석 항목 |
| Session | 40% | 최근 메시지 + 도구 결과 |

## 영속성 라이프사이클

| 저장소 | 범위 | TTL | 로테이션 | 쓰기 트리거 |
|--------|------|-----|----------|-------------|
| `memory/PROJECT.md` | Project | 영구 | 최대 50개, LRU 제거 | 파이프라인 완료 |
| `rules/` | Project | 영구 | 수동 | 에이전트가 반복 패턴에서 자동 생성 |
| `vault/` | Project | 영구 | 삭제 없음 | 리포트 생성, 리서치 완료 |
| `result_cache/` | Project | 24h | SHA-256 중복 제거, TTL 제거 | 파이프라인 완료 |
| `skills/` | Project | 영구 | 수동 리로드 | 사용자 또는 에이전트 생성 |
| `config.toml` | Project | 영구 | Hot-reload (chokidar 300ms debounce) | 사용자 편집 |

## 런타임 Context 소스 (`.geode/` 외부)

| 소스 | 위치 | 주입 형태 |
|------|------|-----------|
| GEODE.md | 프로젝트 루트 | T0 SOUL 아이덴티티 |
| `~/.geode/user_profile/` | Global | T0.5 사용자 선호 설정 |
| `~/.geode/.env` | Global | API keys (기본값) |
| `.env` | 프로젝트 루트 | API keys (오버라이드, 비어있지 않은 값만) |
| `~/.geode/scheduler/jobs.json` | Global | Scheduler 상태 (atomic JSON) |
| `~/.geode/cli.sock` | Global | IPC socket (serve daemon) |

## 4-Layer Stack에서의 Context

```
Agent Layer    AgenticLoop system prompt를 통해 context 읽기
                 │
Harness Layer  ContextAssembler가 5개 티어 병합
                 │
Runtime Layer  Memory 모듈이 티어별 원시 데이터 제공
                 │
Model Layer    최종 조립된 context를 system prompt prefix로 수신
```

에이전트는 `.geode/` 파일을 직접 읽지 않습니다. 모든 접근은 `ContextAssembler`를 통하며, 티어 우선순위, 예산 할당, 최신성 검사를 강제합니다.
