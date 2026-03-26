# GEODE Setup Guide

> [README](../README.md) | [Architecture](architecture.md) | [Workflow](workflow.md) | **Setup**

## Installation

```bash
uv sync
```

## Quick Start

```bash
# Interactive REPL (primary interface)
uv run geode

# Natural language CLI
uv run geode "summarize the latest AI research trends"

# Game IP Domain Plugin (dry-run, no LLM)
uv run geode analyze "Cowboy Bebop" --dry-run
```

API 키 없이 시작하면 자동으로 dry-run 모드로 전환됩니다.

---

## Environment Setup

```bash
# 1. 환경 변수 설정
cp .env.example .env

# 2. .env 편집 — 최소 Anthropic API 키 입력
ANTHROPIC_API_KEY=sk-ant-...

# 3. REPL 시작
uv run geode
```

---

## Global Installation

어디서든 `geode` 명령 실행:

```bash
cd /path/to/geode
uv tool install . --force
```

설치 후 `geode`를 아무 디렉토리에서 실행할 수 있습니다.
프로젝트별 `.env`가 없으면 `~/.geode/.env`에서 글로벌 키를 읽습니다.

---

## Global API Keys (`~/.geode/.env`)

```bash
mkdir -p ~/.geode
cat > ~/.geode/.env << 'EOF'
# LLM Providers
ANTHROPIC_API_KEY=sk-ant-...       # https://console.anthropic.com/settings/keys
OPENAI_API_KEY=sk-proj-...         # https://platform.openai.com/api-keys
ZAI_API_KEY=...                    # https://open.bigmodel.cn/usercenter/apikeys (optional)

# Search & Data
BRAVE_API_KEY=...                  # https://brave.com/search/api/
GOOGLE_API_KEY=...                 # https://console.cloud.google.com/apis/credentials
YOUTUBE_API_KEY=...                # Google API Key (YouTube Data API v3 enabled)

# Messaging (Slack Gateway)
SLACK_BOT_TOKEN=xoxb-...           # https://api.slack.com/apps → OAuth & Permissions
SLACK_TEAM_ID=T...                 # Slack workspace settings

# Observability (optional)
LANGSMITH_API_KEY=lsv2_pt_...      # https://smith.langchain.com/settings
EOF
chmod 600 ~/.geode/.env
```

**Priority**: Environment variable > Project `.env` > `~/.geode/.env` > Code defaults

---

## Slack Gateway

GEODE를 Slack 채널과 연결하면 메시지로 대화할 수 있습니다.

### 1. Slack Bot 생성

- [api.slack.com/apps](https://api.slack.com/apps) → Create New App
- Bot Token Scopes: `chat:write`, `channels:history`, `channels:read`
- Bot Token (`xoxb-...`)과 Team ID를 `~/.geode/.env`에 설정

### 2. Gateway 활성화

```bash
# ~/.geode/.env에 추가
GEODE_GATEWAY_ENABLED=true
```

### 3. 채널 바인딩 (`.geode/config.toml`)

`.geode/config.toml`이 없으면 Slack 폴러가 모니터링할 채널이 없어 **메시지를 수신하지 않습니다**.
이 파일은 채널 ID(개인정보)를 포함하므로 git에 커밋하지 않습니다.

```bash
# 템플릿에서 복사
cp .geode/config.toml.example .geode/config.toml

# 채널 ID 편집
vi .geode/config.toml
```

```toml
[gateway.bindings]

[[gateway.bindings.rules]]
channel = "slack"
channel_id = "C0XXXXXXXXX"  # Slack 채널 → 채널명 클릭 → 맨 아래 Channel ID
auto_respond = true
require_mention = true       # true: @멘션 시에만 응답
max_rounds = 5

# 채널을 추가하려면 [[gateway.bindings.rules]] 블록을 반복
```

**채널 ID 확인법**: Slack 채널 → 채널명 클릭 → 스크롤 맨 아래 `Channel ID: C0XXXXXXXXX`

> **주의**: `git pull`로 코드를 업데이트해도 `.geode/config.toml`은 `.gitignore` 대상이므로 유지됩니다.
> 단, 클린 클론 시에는 `config.toml.example`에서 다시 복사해야 합니다.

### 4. 실행

```bash
# Headless (Gateway only, background)
nohup geode serve > /tmp/geode-gateway.log 2>&1 &

# Foreground (REPL + Gateway)
geode
```

### 5. 동작 확인

```bash
# 프로세스 확인
ps aux | grep "geode serve"

# 로그에서 바인딩 로드 확인
grep "binding" /tmp/geode-gateway.log
# → Channel binding added: slack/C0XXXXXXXXX (auto_respond=True)
# → Loaded 4 gateway bindings from config

# 로그에서 Slack 폴링 확인
grep "Slack poller seeded" /tmp/geode-gateway.log
# → Slack poller seeded ts=... for C0XXXXXXXXX (5 skipped)
```

바인딩이 0개이거나 "seeded" 로그가 없으면 `.geode/config.toml`이 없거나 채널 ID가 잘못된 것입니다.

`geode serve`는 REPL 없이 Gateway만 실행합니다. MCP 서버 14종이 순차 연결되므로 시작까지 2-3분 소요됩니다.

### 리액션

`require_mention = true`인 채널에서 @멘션 메시지를 보내면:
1. :eyes: 리액션 (수신 확인)
2. AgenticLoop 처리
3. :white_check_mark: 리액션 (완료)
4. 스레드에 응답 전송

---

## HITL Level

자율성을 단계별로 조절합니다:

```bash
# 0 = 완전 자율 (모든 승인 생략)
GEODE_HITL_LEVEL=0

# 1 = WRITE만 묻기 (bash/MCP는 자동 승인)
GEODE_HITL_LEVEL=1

# 2 = 전부 묻기 (기본값)
GEODE_HITL_LEVEL=2
```

---

## Configuration

`.env` 파일로 설정합니다 (전체 목록: `core/config.py`):

| Variable | Default | Description |
|----------|---------|-------------|
| **LLM** | | |
| `ANTHROPIC_API_KEY` | | Claude API key |
| `OPENAI_API_KEY` | | GPT API key (Cross-LLM) |
| `GEODE_MODEL` | `claude-opus-4-6` | Default LLM model |
| `GEODE_ENSEMBLE_MODE` | `single` | Ensemble mode (`single` / `cross`) |
| **Pipeline** | | |
| `GEODE_CONFIDENCE_THRESHOLD` | `0.7` | Confidence gate |
| `GEODE_MAX_ITERATIONS` | `5` | Max re-analysis iterations |
| `GEODE_PLAN_AUTO_EXECUTE` | `false` | Plan auto-execute mode |
| `GEODE_INTERRUPT_NODES` | | Interrupt nodes |
| `GEODE_CHECKPOINT_DB` | `geode_checkpoints.db` | Checkpoint DB path |
| **MCP** | | |
| `GEODE_STEAM_MCP_URL` | | Steam MCP server URL |
| `GEODE_BRAVE_API_KEY` | | Brave Search API key |
| **Observability** | | |
| `LANGCHAIN_TRACING_V2` | `false` | LangSmith tracing |
| `LANGCHAIN_API_KEY` | | LangSmith API key |

---

## Testing

```bash
uv run pytest                                        # Full (3202+ passed)
uv run pytest tests/test_e2e_live_llm.py -v -m live  # Live E2E
uv run ruff check core/ tests/                       # Lint
uv run mypy core/                                    # Type check (175 files)
uv run bandit -r core/ -c pyproject.toml             # Security
```

---

## Usage

### Interactive Mode

```bash
uv run geode
```

**Slash commands:**

| Command | Alias | Description |
|---------|-------|-------------|
| `/analyze <IP>` | `/a` | IP analysis (Domain Plugin) |
| `/search <query>` | `/s` | Search |
| `/report <IP> [fmt]` | `/rpt` | Report generation (md/html/json) |
| `/list` | | IP list (Domain Plugin) |
| `/batch [--top N]` | `/b` | Batch analysis |
| `/compare <A> <B>` | | Comparison analysis |
| `/schedule <cron>` | `/sched` | Schedule tasks |
| `/mcp status\|tools\|reload\|add` | | MCP management |
| `/skills` | | Skills list/detail |
| `/status` | | System status |
| `/model` | | LLM model selection |
| `/verbose` | | Verbose output toggle |
| `/quit` | `/q` | Quit |

### CLI Mode

```bash
# General research queries
uv run geode "summarize the latest AI agent framework trends"
uv run geode "summarize this URL: https://example.com/article"
uv run geode "schedule weekly Monday AI news briefing"

# Domain Plugin: Game IP analysis
uv run geode analyze "Berserk"                    # CLI analysis
uv run geode search "cyberpunk"                   # Genre search
uv run geode report "Berserk" -f html -o out.html # HTML report
uv run geode batch --top 5                        # Batch analysis
```
