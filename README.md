# GEODE v6.0 — Undervalued IP Discovery Agent

LangGraph 기반 저평가 IP 발굴 에이전트 CLI.
미디어 IP(애니메이션, 만화 등)의 게임화 잠재력을 6-Layer 아키텍처로 분석하고, 14-Axis 루브릭으로 평가합니다.

## Features

- **6-Layer Pipeline** — Router → Cortex → Signals → Analysts → Evaluators → Scoring → Verification → Synthesis
- **14-Axis Rubric** — PSM(Prospect Scoring Model) 기반 정량 평가
- **Cross-LLM** — Claude Opus 4.6 + GPT-5.4 듀얼 평가, Failover 지원
- **자연어 입력** — 한국어/영어 자유 입력으로 IP 검색 및 분석
- **Report Generation** — HTML/JSON/Markdown 다중 포맷 리포트 출력
- **Graceful Degradation** — API 키 없이도 dry-run 분석, 검색 가능
- **Project Memory** — `.claude/MEMORY.md` + `rules/`로 분석 맥락 유지
- **Checkpoint** — SqliteSaver 기반 파이프라인 상태 영속화
- **Feedback Loop** — Confidence < 0.7이면 자동 재분석 (최대 3회)
- **Auth Profile Rotation** — 다중 API 키 관리 및 자동 전환
- **1615 Tests** — 79 modules, pytest + ruff + mypy strict 전체 통과

## Installation

```bash
uv sync
```

## Quick Start

```bash
# 인터랙티브 모드 (권장)
uv run geode

# Dry-run 분석 (API 키 불필요)
uv run geode analyze "Berserk"

# 리포트 생성
uv run geode report "Berserk" --format html --output berserk.html

# IP 검색
uv run geode search "다크 판타지"

# IP 목록
uv run geode list
```

## Setup

```bash
# 1. 환경 변수 설정
cp .env.example .env

# 2. .env 편집 — API 키 입력
ANTHROPIC_API_KEY=sk-ant-...

# 3. Full 분석 실행
uv run geode analyze "Cowboy Bebop"
```

API 키 없이 시작하면 자동으로 dry-run 모드로 안내됩니다:

```
  ✓ Dry-Run Analysis
  ✓ IP Search
  ✗ LLM Analysis (ANTHROPIC_API_KEY not set)

  API key not configured — dry-run mode only
```

## Usage

### Interactive Mode

```bash
uv run geode
```

**슬래시 커맨드:**

| Command | Alias | Description |
|---------|-------|-------------|
| `/analyze <IP>` | `/a` | Dry-run 분석 |
| `/run <IP>` | `/r` | Full LLM 분석 |
| `/search <query>` | `/s` | IP 검색 |
| `/report <IP> [fmt]` | `/rpt` | 리포트 생성 (md/html/json) |
| `/list` | | IP 목록 |
| `/generate [count]` | `/gen` | 합성 데모 데이터 생성 |
| `/model` | | LLM 모델 선택 |
| `/key [value]` | | API 키 설정 |
| `/auth` | | 인증 프로필 관리 |
| `/verbose` | | 상세 출력 토글 |
| `/help` | | 도움말 |
| `/quit` | `/q` | 종료 |

**자연어 입력:**

```
> Berserk 분석해           → dry-run 분석
> 소울라이크 찾아줘         → 장르 검색
> Berserk vs Cowboy Bebop  → 비교 분석
> Berserk 리포트 생성해     → 리포트 생성
> 뭐가 있어?               → IP 목록
```

### CLI Mode

```bash
geode analyze "Berserk"                          # dry-run
geode analyze "Berserk" --verbose                 # 상세 출력
geode analyze "Cowboy Bebop" --skip-verification  # 검증 생략
geode report "Berserk"                            # Markdown summary
geode report "Berserk" -f html -o berserk.html    # HTML 파일 저장
geode report "Berserk" -f json -t detailed        # JSON detailed
geode search "사이버펑크"                          # 검색
geode list                                        # 목록
geode version                                     # 버전
```

## Available IPs

| IP | Tier | Score | Genre |
|----|------|-------|-------|
| Berserk | S | 82.2 | Dark Fantasy |
| Cowboy Bebop | A | 69.4 | SF Noir |
| Ghost in the Shell | B | 54.0 | Cyberpunk |

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  L0  CLI / NL Router          (cli/, nl_router.py, search.py)  │
├─────────────────────────────────────────────────────────────────┤
│  L1  Infrastructure           (ports/, adapters/, llm/, auth/) │
├─────────────────────────────────────────────────────────────────┤
│  L2  Memory                   (session, checkpoint, project)   │
├─────────────────────────────────────────────────────────────────┤
│  L3  LangGraph Pipeline       (graph.py, state.py, nodes/)     │
├─────────────────────────────────────────────────────────────────┤
│  L4  Orchestration            (hooks, run_log, lanes, policies)│
├─────────────────────────────────────────────────────────────────┤
│  L5  Extensibility            (reports, tools, data, templates)│
└─────────────────────────────────────────────────────────────────┘
```

### Pipeline Flow

```
START → Router → Cortex(Gather) → Signals
      → Analyst ×4 (Send API, parallel)
      → Evaluator ×3 (Cross-LLM)
      → Scoring (PSM 14-Axis)
      → Verification (Guardrails + BiasBuster)
      ↺ Feedback Loop (confidence < 0.7 → retry, max 3)
      → Synthesizer → END
```

## Project Structure

```
geode/
├── cli/                    # CLI + NL Router + Search + Startup
│   ├── __init__.py         # Typer app, REPL, pipeline execution
│   ├── commands.py         # Slash command dispatch
│   ├── nl_router.py        # Natural language intent classification
│   ├── search.py           # IP search engine (synonym expansion)
│   └── startup.py          # Readiness check, Graceful Degradation
├── auth/                   # Auth profile management + rotation
├── automation/             # Feedback loop, confidence gating
├── config.py               # Settings (pydantic-settings)
├── data/                   # Synthetic data generation
├── extensibility/          # Report generation (HTML/JSON/MD)
├── fixtures/               # Fixture data (Berserk, Cowboy Bebop, GitS)
├── graph.py                # LangGraph StateGraph definition
├── infrastructure/
│   ├── ports/              # LLMClientPort (ABC)
│   └── adapters/llm/       # ClaudeAdapter
├── llm/                    # LLM client (Anthropic, OpenAI)
├── memory/
│   ├── project.py          # ProjectMemory (.claude/MEMORY.md + rules/)
│   ├── session.py          # InMemorySessionStore (TTL)
│   └── session_key.py      # Session key builder
├── nodes/                  # Pipeline nodes (cortex, analyst, evaluator, ...)
├── orchestration/
│   ├── hooks.py            # HookSystem (11 events)
│   ├── run_log.py          # JSONL run logging
│   ├── lane_queue.py       # Concurrency control
│   ├── coalescing.py       # Request deduplication
│   ├── hot_reload.py       # Config hot reload
│   └── stuck_detection.py  # Long-running task detection
├── runtime.py              # GeodeRuntime (production wiring)
├── state.py                # GeodeState (TypedDict + Pydantic models)
├── tools/                  # Tool Protocol + Registry + Policy
├── ui/                     # Rich console + panels
└── verification/           # Guardrails + BiasBuster + Rights Risk
```

## Testing

```bash
# 전체 테스트
uv run pytest

# 상세 출력
uv run pytest -v

# 특정 모듈
uv run pytest tests/test_graph.py
uv run pytest tests/test_nl_router.py

# 품질 검사
uv run ruff check .
uv run ruff format --check .
uv run mypy geode/
```

## Configuration

`.env` 파일로 설정합니다:

| Variable | Default | Description |
|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | | Claude API 키 |
| `OPENAI_API_KEY` | | GPT API 키 (Cross-LLM) |
| `GEODE_MODEL` | `claude-opus-4-6` | 기본 LLM 모델 |
| `GEODE_VERBOSE` | `false` | 상세 출력 |
| `GEODE_CHECKPOINT_DB` | `geode_checkpoints.db` | Checkpoint DB 경로 |

## License

Internal use only.
