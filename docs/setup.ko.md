# GEODE 설치 가이드

> [README](../README.md) | [Context Lifecycle](architecture/context-lifecycle.md) | [Hook System](architecture/hook-system.md) | [Workflow](workflow.md) | [English](setup.md) | **한국어**

## 설치

```bash
git clone https://github.com/mangowhoiscloud/geode.git
cd geode && uv sync
```

## 빠른 시작

```bash
# Thin CLI (serve daemon이 없으면 자동 시작)
uv run geode

# 원샷 프롬프트
uv run geode "summarize the latest AI research trends"

# Domain Plugin: Game IP (dry-run, LLM 미사용)
uv run geode analyze "Cowboy Bebop" --dry-run

# Headless daemon (Slack/Discord/Telegram + scheduler)
uv run geode serve
```

API key 없이 시작하면 자동으로 dry-run 모드로 전환됩니다.

---

## 아키텍처: Thin-Only

```
geode (thin CLI) ── Unix socket IPC ──→ geode serve (unified daemon)
                                          │
                                      GeodeRuntime
                                       ├── CLIPoller    → SessionMode.IPC
                                       ├── Gateway      → SessionMode.DAEMON (Slack/Discord)
                                       └── Scheduler    → SessionMode.SCHEDULER (cron)
```

- `geode` = thin client. 모든 실행은 serve daemon으로 IPC relay.
- serve가 미실행이면 자동 시작 (auto-start, 30s timeout).
- 실시간 streaming: tool calls (▸), results (✓/✗), token usage (✢) thin client에 표시.

---

## 환경 설정

### 1. API Keys

```bash
# Global keys (모든 프로젝트에 적용)
mkdir -p ~/.geode
cat > ~/.geode/.env << 'EOF'
# LLM Providers (최소 1개 필수)
ANTHROPIC_API_KEY=sk-ant-...       # https://console.anthropic.com/settings/keys
OPENAI_API_KEY=sk-proj-...         # https://platform.openai.com/api-keys
ZAI_API_KEY=...                    # https://open.bigmodel.cn/usercenter/apikeys (선택)

# 메시징 (Slack Gateway)
SLACK_BOT_TOKEN=xoxb-...           # https://api.slack.com/apps → OAuth & Permissions
SLACK_TEAM_ID=T...                 # Slack workspace 설정

# Gateway 토글
GEODE_GATEWAY_ENABLED=true
EOF
chmod 600 ~/.geode/.env
```

**Key 우선순위**: Environment variable > Project `.env` > `~/.geode/.env`

### 2. 프로젝트 설정

```bash
# .geode/ 구조 초기화
uv run geode init

# 또는 수동으로
cp .env.example .env       # project-local keys (비어있지 않은 값만 override)
```

### 3. Global CLI 설치

```bash
uv tool install -e . --force
geode version   # 어디서든 실행 가능
```

---

## `geode serve` — 통합 Daemon

모든 실행 경로의 backbone. thin CLI, Slack, scheduler 모두 serve를 통합니다.

### 명령어

```bash
geode serve                # foreground (Ctrl+C로 종료)
geode serve -p 5.0         # poll interval 5초 (기본값: 3.0)

# Background (프로덕션)
nohup geode serve > /tmp/geode-serve.log 2>&1 &
```

### 옵션

| 옵션 | 기본값 | 설명 |
|------|--------|------|
| `--poll`, `-p` | `3.0` | Gateway poll 간격 (초) |

### 시작 순서

1. ContextVars (domain, memory, profile, env)
2. Readiness check (API keys)
3. GeodeRuntime (MCP 13 servers, 10-30s)
4. SchedulerService (jobs 로드, 60s tick 시작)
5. Gateway pollers (Slack, Discord, Telegram)
6. CLIPoller (Unix socket `~/.geode/cli.sock`)

### 자동 시작

thin CLI (`geode`)는 serve 미실행 시 자동 시작합니다:

```
geode → is_serve_running()? → No → start_serve_if_needed(30s) → connect IPC
```

- Pidfile lock (`~/.geode/cli.startup.lock`)로 TOCTOU 방지
- `start_new_session=True` + stdout DEVNULL로 background spawn

---

## Slack Gateway

### 1. Slack Bot 생성

- [api.slack.com/apps](https://api.slack.com/apps) → Create New App
- Bot Token Scopes: `chat:write`, `channels:history`, `channels:read`
- Bot Token (`xoxb-...`)과 Team ID를 `~/.geode/.env`에 설정

### 2. Channel Binding (`.geode/config.toml`)

```bash
cp .geode/config.toml.example .geode/config.toml
```

```toml
[gateway.bindings]

[[gateway.bindings.rules]]
channel = "slack"
channel_id = "C0XXXXXXXXX"   # Slack channel → 이름 클릭 → 하단 "Channel ID"
auto_respond = true
require_mention = true        # true: @mention만 반응
max_rounds = 5
```

### 3. 확인

```bash
geode serve &
grep "binding" /tmp/geode-serve.log
# → Channel binding added: slack/C0XXXXXXXXX (auto_respond=True)

grep "Slack poller seeded" /tmp/geode-serve.log
# → Slack poller seeded ts=... for C0XXXXXXXXX
```

### 리액션

@mention 메시지 → :eyes: (수신) → AgenticLoop → :white_check_mark: (완료) → thread 응답

---

## Scheduler

### CLI 사용법

```bash
# 생성 (action 필수)
/schedule create "every 5 minutes" "check system drift"
/schedule create "daily at 9:00" "summarize today's news"

# 관리
/schedule list
/schedule delete <job_id>
/schedule enable <job_id>
/schedule disable <job_id>
/schedule run <job_id>
```

### 자연어 입력 (AgenticLoop 경유)

```
> 매일 아침 9시에 뉴스 요약해줘
  ▸ schedule_job(expression="daily at 9:00", action="summarize today's news")
  ✓ schedule_job → Created: nl_abc12345
```

### 영속성

- Jobs: `~/.geode/scheduler/jobs.json` (atomic write, fcntl lock)
- 실행 로그: `~/.geode/scheduler/logs/{job_id}.jsonl` (자동 정리 2MB/2000 lines)
- Guardrail: `action=""` jobs 거부 (zombie no-op 방지)

---

## 인터랙티브 슬래시 명령어

| 명령어 | 별칭 | 설명 |
|--------|------|------|
| `/help` | | 전체 명령어 표시 |
| `/status` | | 시스템 상태 (model, API keys, MCP, mode) |
| `/model [N\|name]` | | LLM 모델 표시 / 전환 |
| `/key [provider] [value]` | | API key 표시 / 설정 |
| `/cost` | | LLM 비용 대시보드 (세션 + 월간) |
| `/verbose` | | 상세 출력 토글 |
| `/mcp` | | MCP 서버 상태 |
| `/skills` | | 런타임 skills 목록 |
| `/context` | `/ctx` | Context 티어 표시 |
| `/schedule` | `/sched` | Scheduler 관리 |
| `/trigger` | | 이벤트 트리거 관리 |
| `/auth` | | 인증 프로필 관리 |
| `/tasks` | `/t` | 작업 목록 |
| `/clear` | | 대화 초기화 |
| `/compact` | | Context 압축 |
| `/analyze <IP>` | `/a` | IP 분석 (Domain Plugin) |
| `/run <IP>` | `/r` | LLM을 사용한 분석 |
| `/search <query>` | `/s` | IP 검색 |
| `/list` | | 사용 가능한 IP 목록 |
| `/report <IP> [fmt]` | `/rpt` | 리포트 생성 (md/html/json) |
| `/batch <IPs>` | `/b` | 배치 분석 |
| `/compare <A> <B>` | | 두 IP 비교 |
| `/quit` | `/q` | 종료 |

---

## CLI 명령어 (Typer)

```bash
geode                                  # 인터랙티브 thin CLI
geode "prompt"                         # IPC 경유 원샷 프롬프트
geode --continue                       # 마지막 세션 이어서
geode --resume <session_id>            # 특정 세션 재개

geode analyze "Berserk" --dry-run      # Domain Plugin 분석
geode search "cyberpunk"               # IP 검색
geode report "Berserk" -f html         # 리포트 생성
geode batch --top 5                    # 배치 분석
geode list                             # 사용 가능한 IP 목록
geode version                          # 버전 정보
geode init                             # .geode/ 구조 초기화
geode history                          # 실행 이력 + 비용
geode serve [-p 3.0]                   # Headless daemon
```

---

## 설정 레퍼런스

`.env` 변수 (전체 목록: `core/config.py`):

| 변수 | 기본값 | 설명 |
|------|--------|------|
| **LLM** | | |
| `ANTHROPIC_API_KEY` | | Claude API key |
| `OPENAI_API_KEY` | | GPT API key (Cross-LLM) |
| `ZAI_API_KEY` | | ZhipuAI GLM key |
| `GEODE_MODEL` | `claude-opus-4-6` | 기본 LLM 모델 |
| `GEODE_ENSEMBLE_MODE` | `single` | 앙상블 모드 (`single` / `cross`) |
| **Gateway** | | |
| `GEODE_GATEWAY_ENABLED` | `false` | Slack/Discord gateway 활성화 |
| `SLACK_BOT_TOKEN` | | Slack bot token |
| `SLACK_TEAM_ID` | | Slack workspace ID |
| **Pipeline** | | |
| `GEODE_CONFIDENCE_THRESHOLD` | `0.7` | Confidence gate |
| `GEODE_MAX_ITERATIONS` | `5` | 최대 재분석 반복 횟수 |
| **Observability** | | |
| `LANGCHAIN_TRACING_V2` | `false` | LangSmith tracing |
| `LANGCHAIN_API_KEY` | | LangSmith API key |

---

## 테스트

```bash
uv run pytest tests/ -m "not live" -q     # 3,422+ tests
uv run ruff check core/ tests/            # Lint
uv run mypy core/                         # Type check (190 modules)
uv run geode analyze "Cowboy Bebop" --dry-run  # E2E 불변량: A (68.4)
```
