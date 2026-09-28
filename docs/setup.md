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

# Then type a prompt in the REPL
# summarize the latest AI research trends

# Daemon (CLI IPC; also Slack/Discord/Telegram when gateway is enabled)
uv run geode serve
```

A usable API key, subscription OAuth login, or GEODE login profile enables LLM
calls. Without credentials, onboarding offers setup or an explicit dry-run
choice; the absence of an API key alone does not imply dry-run.

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

`geode setup` and `/login` store API keys in `~/.geode/auth.toml`. `~/.geode/.env`
is optional: it holds variables you set by hand, such as the Slack tokens below.

Edit `~/.geode/.env`, preserving existing entries and adding only the credentials
you need. If creating the file, restrict it to owner read/write (`0600`) before
adding secrets. The following is example file content, not a replacement
command. Subscription-only use does not require a provider API key.

```dotenv
# API-key providers (only those you use)
ANTHROPIC_API_KEY=sk-ant-...       # https://console.anthropic.com/settings/keys
OPENAI_API_KEY=sk-proj-...         # https://platform.openai.com/api-keys
OPENROUTER_API_KEY=sk-or-v1-...    # https://openrouter.ai/keys (optional)
ZAI_API_KEY=...                    # https://open.bigmodel.cn/usercenter/apikeys (optional)

# Messaging (Slack Gateway)
SLACK_BOT_TOKEN=xoxb-...           # https://api.slack.com/apps → OAuth & Permissions
SLACK_APP_TOKEN=xapp-...           # Basic Information → App-Level Tokens (connections:write)
SLACK_TEAM_ID=T...                 # optional; enables clickable doctor links
```

Check that the file remains owner-only after editing:

```bash
chmod 600 ~/.geode/.env
```

For the order in which exported variables, `~/.geode/.env`, a project `.env` and
`config.toml` apply, see
[Configuration basics](https://mangowhoiscloud.github.io/geode/docs/config/basics/).

### 2. Project Setup

```bash
# .geode/ 구조 초기화
uv run geode init
```

For manual secret configuration, use `.env.example` as a reference and merge
only needed entries into an existing project `.env`; do not replace it.
The project `.env` and the `.geode/config.toml` settings that widen what the
agent may do apply only after you run `geode config trust` in the folder; see
[project trust](https://mangowhoiscloud.github.io/geode/docs/config/basics/#project-trust).

### 3. Global CLI Install

```bash
uv tool install geode-agent
geode version   # available from any directory
```

`geode-agent` is the PyPI distribution name; it installs the `geode` command.
If the current release is not on PyPI yet, or you are developing GEODE itself,
install the source checkout instead:

```bash
uv sync
uv tool install -e . --force
geode version
```

Update and uninstall paths depend on how the CLI was installed:

```bash
geode update                  # uv: latest patch; source: pull + rebuild
geode update --latest         # uv only: allow minor/major upgrades
geode update --dry-run        # detect and preview without changing anything
geode uninstall               # runtime data + installed CLI
uv tool uninstall geode-agent # CLI only
```

`geode update` reads installation metadata instead of guessing from the current
directory. A standard registry-backed uv tool is constrained to the newest
patch in its current major/minor series; an editable install updates the actual
GEODE source checkout. Custom uv receipts stop rather than discarding their
installation settings and report the receipt path. Missing metadata never falls
back to the current Git checkout. Registry resolution is isolated from the
current project's uv configuration. A running daemon is stopped only after the
update preflight and before the live install is replaced. A failed update stays
stopped; a successful restart must report the same CLI and IPC version. No network update runs
implicitly at CLI startup.

---

## `geode serve` — Unified Daemon

모든 실행 경로의 backbone. thin CLI, Slack, scheduler 모두 serve를 통합니다.

### Commands

```bash
geode serve                # foreground (Ctrl+C to stop)
geode serve -p 5.0         # Discord/Telegram + Slack fallback poll interval (default: 3.0)

# Background (production) — stdout/stderr go to ~/.geode/logs/serve.log
# via the internal logger; redirect only if you need a separate stream.
nohup geode serve >/dev/null 2>&1 &
```

### Options

| Option | Default | Description |
|--------|---------|-------------|
| `--poll`, `-p` | `3.0` | Discord/Telegram and Slack compatibility-fallback poll interval (seconds) |

### Startup Sequence

1. Daemon environment load
2. Readiness check (API keys, subscription OAuth, or login profiles)
3. GeodeRuntime (connects configured MCP servers)
4. SchedulerService (load jobs, start 60s tick)
5. Gateway receivers (Slack Socket Mode, Discord/Telegram pollers)
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
- **OAuth & Permissions** → Bot Token Scopes:
  `app_mentions:read`, `chat:write`, `channels:history`, `channels:read`
  (`reactions:write` is optional but enables progress reactions)
- **Socket Mode** → Enable Socket Mode
- **Basic Information** → App-Level Tokens → create an `xapp-...` token with
  `connections:write`
- **Event Subscriptions** → subscribe to bot events `app_mention` and
  `message.channels`, then install/reinstall the app
- Put both `SLACK_BOT_TOKEN=xoxb-...` and `SLACK_APP_TOKEN=xapp-...` in
  `~/.geode/.env`, and run `/invite @geode` in every bound channel

### 2. Channel Binding (`config.toml`)

Turn the gateway on with `[gateway] enabled = true` in `~/.geode/config.toml`,
then add a `[[gateway.bindings.rules]]` entry for each Slack channel, in the same
file or in a project `.geode/config.toml`. The rule format is in
[Configure a binding](https://mangowhoiscloud.github.io/geode/docs/guides/binding/).
Update an existing `[gateway]` table rather than declaring it twice. In Slack, the
channel ID is at the bottom of the dialog that opens when you click the channel
name. A project `[gateway]` table applies only in a
[trusted folder](https://mangowhoiscloud.github.io/geode/docs/config/basics/#project-trust).

### 3. Verify

```bash
geode serve &
grep -E "Slack inbound mode|Slack Socket Mode connected" ~/.geode/logs/serve.log
# → Slack inbound mode: Socket Mode (push)
# → Slack Socket Mode connected

grep "binding" ~/.geode/logs/serve.log
# → Channel binding added: slack/C0XXXXXXXXX (auto_respond=True)

geode doctor slack
# Every binding_access row must say bot_member=True and include its channel link.
```

### Optional: computer use from a bound channel

Remote desktop control is denied in gateway sessions by default. First make
`geode doctor` report `computer-use desktop` as healthy, then opt in only for a
private, membership-restricted binding:

```toml
[computer_use]
enabled = true
env = "host"
driver = "helper"

[gateway]
allow_computer_use = true
```

This grants every sender admitted by a binding the ability to request desktop
actions. The execution exception permits only `computer` and `computer_use`;
`run_bash`, `delegate_task`, personal-workspace tools, scheduler sessions, and
MCP `run_agent` remain denied. When the option is off, the executor rejects
either desktop tool before approval or dispatch even if a provider-visible
schema is present.

Without `SLACK_APP_TOKEN`, GEODE logs `polling fallback` and keeps the old
history polling path for migration compatibility. `geode doctor slack` reports
that state as `DEGRADED`; it is not the production target.

### Reactions

@mention message → :eyes: (received) → AgenticLoop → :white_check_mark: (done) → thread reply

With `require_mention = true`, only a new top-level conversation (or an
unengaged thread) needs the mention. After GEODE joins a thread, later human
replies continue the same session without repeating `@geode`; they receive the
same reaction lifecycle and thread response. The root timestamp is also the
session/checkpoint identity from the first turn, so an ACTIVE or PAUSED thread
can resume after a daemon restart.

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

- Jobs: project `.geode/scheduled_tasks.json` (atomic write, `scheduled_tasks.lock` lock file)
- Run logs: project `.geode/scheduler_logs/{job_id}.jsonl` (auto-prune 2MB/2000 lines)
- Legacy `~/.geode/scheduler/jobs.json` is read only when the project has no job file
- Guardrail: `action=""` jobs rejected (no zombie no-ops)

---

## Interactive Slash Commands

| Command | Alias | Description |
|---------|-------|-------------|
| `/help` | | Show all commands |
| `/status` | | System status (model, API keys, MCP, mode) |
| `/model [N\|name]` | | Show / switch LLM model (project-scoped: writes `./.geode/config.toml`) |
| `/model global [N\|name]` | | Switch the user-global default model (`~/.geode/config.toml`) |
| `/key [provider] [value]` | | Show / set API key |
| `/cost` | | LLM cost dashboard (session + monthly) |
| `/verbose` | | Toggle verbose output |
| `/mcp` | | MCP server status |
| `/skills` | | Runtime skills list |
| `/context` | `/ctx` | Context tiers display |
| `/schedule` | `/sched` | Scheduler management |
| `/trigger` | | Event trigger management |
| `/tasks` | `/t` | Task list |
| `/clear` | | Clear conversation |
| `/compact` | | Compact context |
| `/quit` | `/q` | Exit |

For the model resolution order and a `/model` switch that does not stick, see
[Configuration basics](https://mangowhoiscloud.github.io/geode/docs/config/basics/);
the default model is listed in
[Configure providers](https://mangowhoiscloud.github.io/geode/docs/run/providers/).

---

## CLI Commands (Typer)

```bash
geode                                  # Interactive thin CLI
geode --continue                       # Resume last session
geode --resume <session_id>            # Resume specific session

geode version                          # Version info
geode init                             # Initialize .geode/ structure
geode history                          # Execution history + cost
geode serve [-p 3.0]                   # Headless daemon
```

---

## Configuration Reference

[Configuration basics](https://mangowhoiscloud.github.io/geode/docs/config/basics/)
covers which file holds what and
[when project files apply](https://mangowhoiscloud.github.io/geode/docs/config/basics/#project-trust);
the full on-disk layout is in
[storage-hierarchy.md](architecture/storage-hierarchy.md).

Environment settings (declarations: [`core/config/_settings.py`](../core/config/_settings.py)):

| Variable | Default | Description |
|----------|---------|-------------|
| **LLM** | | |
| `ANTHROPIC_API_KEY` | | Claude API key |
| `OPENAI_API_KEY` | | GPT API key (OpenAI adapter) |
| `OPENROUTER_API_KEY` | | OpenRouter credit-backed API key; select exact refs as `openrouter/<publisher>/<model>` |
| `ZAI_API_KEY` | | ZhipuAI GLM key |
| `GEODE_MODEL` | [routing default](https://mangowhoiscloud.github.io/geode/docs/run/providers/) | Manual session override only; persist model choices in `config.toml` |
| `GEODE_ENSEMBLE_MODE` | `single` | Manual session override only; prefer `config.toml` for durable behavior |
| **Gateway** | | |
| `GEODE_GATEWAY_ENABLED` | `false` | Manual session override; prefer `[gateway] enabled = true` in `config.toml` |
| `SLACK_BOT_TOKEN` | | Slack bot token |
| `SLACK_APP_TOKEN` | | Slack Socket Mode app token (`xapp-`, `connections:write`) |
| `SLACK_TEAM_ID` | | Optional workspace ID for clickable diagnostic links |
| **Pipeline** | | |
| **Observability** | | |
| _(no env vars — built-in event sink)_ | | Lifecycle events flow into project-local `sessions.db:hook_events`; active autoresearch runs also mirror sanitized rows to `transcript.jsonl` |

---

## Self-improving loop

The self-improving loop runs a Petri audit over GEODE's own scaffold, measures the result, and gates each candidate change behind that measurement. It does not promise improvement: it measures and either promotes or rejects.

Before running a campaign, three prerequisites are BLOCKING:

1. **Audit extra**: `uv sync --extra audit`. This pulls in `inspect_ai` + `petri` (putting the `inspect` CLI on PATH), which the audit subprocess and the seed-generation pilot both require. Without it the audit aborts loudly: `evals/petri/runner.py` checks `shutil.which("inspect")` and returns an aborted report with `` `inspect` CLI not found on PATH — install the [audit] extra: `uv sync --extra audit`. ``, and the loop returns failure for that cycle.
2. **Model accounts**:
   - An **auditor + judge model** (Anthropic): the auditor drives the Petri scenario and the judge scores each rollout. Configured via the `[self_improving_loop.autoresearch.auditor]` / `[self_improving_loop.autoresearch.judge]` sections (`model` + `source`).
   - A **target model**: defaults to the manifest `claude-haiku-4-5`; override to `geode/gpt-5.5` via ChatGPT / Codex OAuth with `[self_improving_loop.autoresearch.target]` (`model = "geode/gpt-5.5"`, `source = "openai-codex"`) in config.
3. **Config**: use `docs/examples/self_improving_loop.config.toml.example` as a reference and merge the needed `[self_improving_loop.*]` sections into `~/.geode/config.toml`. Preserve existing settings and credential choices; do not replace the file. Absent sections fall back to documented defaults.

```bash
uv sync --extra audit
```

To run a campaign, start with the quick-start runbook: [docs/self-improving/campaign-quick-start.md](self-improving/campaign-quick-start.md). For the full procedure (difficulty seeding, baseline re-measurement, the 3-arm comparison, the bench axis), see [docs/self-improving/campaign-procedure.md](self-improving/campaign-procedure.md).

---

## Testing

Select checks by the affected behavior using the canonical
[verification gates](../.agents/skills/geode-workflow/references/verification-gates.md).
For broad local preflight checks:

```bash
scripts/preflight.sh
```

Report the checks and skips actually observed. Targeted checks or `--fast` are
not a full preflight pass; remote CI on the current PR head remains the merge gate.
