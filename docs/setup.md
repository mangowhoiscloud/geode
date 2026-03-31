# GEODE Setup Guide

> [README](../README.md) | [Context Lifecycle](architecture/context-lifecycle.md) | [Hook System](architecture/hook-system.md) | [Workflow](workflow.md) | **Setup** | [한국어](setup.ko.md)

## Installation

```bash
git clone https://github.com/mangowhoiscloud/geode.git
cd geode && uv sync
```

## Quick Start

```bash
# Thin CLI (auto-starts serve daemon if needed)
uv run geode

# One-shot prompt
uv run geode "summarize the latest AI research trends"

# Domain Plugin: Game IP (dry-run, no LLM)
uv run geode analyze "Cowboy Bebop" --dry-run

# Headless daemon (Slack/Discord/Telegram + scheduler)
uv run geode serve
```

API key 없이 시작하면 자동으로 dry-run 모드로 전환됩니다.

---

## Architecture: Thin-Only

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

## Environment Setup

### 1. API Keys

```bash
# Global keys (모든 프로젝트에 적용)
mkdir -p ~/.geode
cat > ~/.geode/.env << 'EOF'
# LLM Providers (최소 1개 필수)
ANTHROPIC_API_KEY=sk-ant-...       # https://console.anthropic.com/settings/keys
OPENAI_API_KEY=sk-proj-...         # https://platform.openai.com/api-keys
ZAI_API_KEY=...                    # https://open.bigmodel.cn/usercenter/apikeys (optional)

# Messaging (Slack Gateway)
SLACK_BOT_TOKEN=xoxb-...           # https://api.slack.com/apps → OAuth & Permissions
SLACK_TEAM_ID=T...                 # Slack workspace settings

# Gateway toggle
GEODE_GATEWAY_ENABLED=true
EOF
chmod 600 ~/.geode/.env
```

**Key 우선순위**: Environment variable > Project `.env` > `~/.geode/.env`

### 2. Project Setup

```bash
# .geode/ 구조 초기화
uv run geode init

# 또는 수동으로
cp .env.example .env       # project-local keys (non-empty만 override)
```

### 3. Global CLI Install

```bash
uv tool install -e . --force
geode version   # 어디서든 실행 가능
```

---

## `geode serve` — Unified Daemon

모든 실행 경로의 backbone. thin CLI, Slack, scheduler 모두 serve를 통합니다.

### Commands

```bash
geode serve                # foreground (Ctrl+C to stop)
geode serve -p 5.0         # poll interval 5초 (default: 3.0)

# Background (production)
nohup geode serve > /tmp/geode-serve.log 2>&1 &
```

### Options

| Option | Default | Description |
|--------|---------|-------------|
| `--poll`, `-p` | `3.0` | Gateway poll interval (seconds) |

### Startup Sequence

1. ContextVars (domain, memory, profile, env)
2. Readiness check (API keys)
3. GeodeRuntime (MCP 13 servers, 10-30s)
4. SchedulerService (load jobs, start 60s tick)
5. Gateway pollers (Slack, Discord, Telegram)
6. CLIPoller (Unix socket `~/.geode/cli.sock`)

### Auto-Start

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
channel_id = "C0XXXXXXXXX"   # Slack channel → click name → bottom "Channel ID"
auto_respond = true
require_mention = true        # true: @mention only
max_rounds = 5
```

### 3. Verify

```bash
geode serve &
grep "binding" /tmp/geode-serve.log
# → Channel binding added: slack/C0XXXXXXXXX (auto_respond=True)

grep "Slack poller seeded" /tmp/geode-serve.log
# → Slack poller seeded ts=... for C0XXXXXXXXX
```

### Reactions

@mention message → :eyes: (received) → AgenticLoop → :white_check_mark: (done) → thread reply

---

## Scheduler

### CLI Usage

```bash
# Create (action required)
/schedule create "every 5 minutes" "check system drift"
/schedule create "daily at 9:00" "summarize today's news"

# Manage
/schedule list
/schedule delete <job_id>
/schedule enable <job_id>
/schedule disable <job_id>
/schedule run <job_id>
```

### Natural Language (via AgenticLoop)

```
> 매일 아침 9시에 뉴스 요약해줘
  ▸ schedule_job(expression="daily at 9:00", action="summarize today's news")
  ✓ schedule_job → Created: nl_abc12345
```

### Persistence

- Jobs: `~/.geode/scheduler/jobs.json` (atomic write, fcntl lock)
- Run logs: `~/.geode/scheduler/logs/{job_id}.jsonl` (auto-prune 2MB/2000 lines)
- Guardrail: `action=""` jobs rejected (no zombie no-ops)

---

## Interactive Slash Commands

| Command | Alias | Description |
|---------|-------|-------------|
| `/help` | | Show all commands |
| `/status` | | System status (model, API keys, MCP, mode) |
| `/model [N\|name]` | | Show / switch LLM model |
| `/key [provider] [value]` | | Show / set API key |
| `/cost` | | LLM cost dashboard (session + monthly) |
| `/verbose` | | Toggle verbose output |
| `/mcp` | | MCP server status |
| `/skills` | | Runtime skills list |
| `/context` | `/ctx` | Context tiers display |
| `/schedule` | `/sched` | Scheduler management |
| `/trigger` | | Event trigger management |
| `/auth` | | Auth profile management |
| `/tasks` | `/t` | Task list |
| `/clear` | | Clear conversation |
| `/compact` | | Compact context |
| `/analyze <IP>` | `/a` | IP analysis (Domain Plugin) |
| `/run <IP>` | `/r` | Analysis with LLM |
| `/search <query>` | `/s` | IP search |
| `/list` | | Available IPs |
| `/report <IP> [fmt]` | `/rpt` | Generate report (md/html/json) |
| `/batch <IPs>` | `/b` | Batch analysis |
| `/compare <A> <B>` | | Compare two IPs |
| `/quit` | `/q` | Exit |

---

## CLI Commands (Typer)

```bash
geode                                  # Interactive thin CLI
geode "prompt"                         # One-shot prompt via IPC
geode --continue                       # Resume last session
geode --resume <session_id>            # Resume specific session

geode analyze "Berserk" --dry-run      # Domain Plugin analysis
geode search "cyberpunk"               # IP search
geode report "Berserk" -f html         # Report generation
geode batch --top 5                    # Batch analysis
geode list                             # Available IPs
geode version                          # Version info
geode init                             # Initialize .geode/ structure
geode history                          # Execution history + cost
geode serve [-p 3.0]                   # Headless daemon
```

---

## Configuration Reference

`.env` variables (full list: `core/config.py`):

| Variable | Default | Description |
|----------|---------|-------------|
| **LLM** | | |
| `ANTHROPIC_API_KEY` | | Claude API key |
| `OPENAI_API_KEY` | | GPT API key (Cross-LLM) |
| `ZAI_API_KEY` | | ZhipuAI GLM key |
| `GEODE_MODEL` | `claude-opus-4-6` | Default LLM model |
| `GEODE_ENSEMBLE_MODE` | `single` | Ensemble mode (`single` / `cross`) |
| **Gateway** | | |
| `GEODE_GATEWAY_ENABLED` | `false` | Enable Slack/Discord gateway |
| `SLACK_BOT_TOKEN` | | Slack bot token |
| `SLACK_TEAM_ID` | | Slack workspace ID |
| **Pipeline** | | |
| `GEODE_CONFIDENCE_THRESHOLD` | `0.7` | Confidence gate |
| `GEODE_MAX_ITERATIONS` | `5` | Max re-analysis iterations |
| **Observability** | | |
| `LANGCHAIN_TRACING_V2` | `false` | LangSmith tracing |
| `LANGCHAIN_API_KEY` | | LangSmith API key |

---

## Testing

```bash
uv run pytest tests/ -m "not live" -q     # 3,422+ tests
uv run ruff check core/ tests/            # Lint
uv run mypy core/                         # Type check (190 modules)
uv run geode analyze "Cowboy Bebop" --dry-run  # E2E invariant: A (68.4)
```
