<p align="center">
  <img src="assets/geode-mascot.png" alt="GEODE — Autonomous Execution Harness" width="360" />
</p>

<p align="center">
  <img src="https://img.shields.io/badge/while(tool__use)-agentic%20loop-1e293b?style=flat-square" alt="while(tool_use)">
  <img src="https://img.shields.io/badge/57%20agentic%20tools-MCP%20native-1e293b?style=flat-square" alt="57 Agentic Tools">
  <img src="https://img.shields.io/badge/LangGraph-StateGraph-1e293b?style=flat-square" alt="LangGraph">
  <a href="https://github.com/mangowhoiscloud/geode/actions"><img src="https://img.shields.io/github/actions/workflow/status/mangowhoiscloud/geode/ci.yml?style=flat-square&label=ci&logo=github&logoColor=white" alt="CI"></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Anthropic-Opus_4.7-cc785c?style=flat-square&logo=anthropic&logoColor=white" alt="Anthropic Opus 4.7">
  <img src="https://img.shields.io/badge/OpenAI-GPT--5.5-412991?style=flat-square&logo=openai&logoColor=white" alt="OpenAI GPT-5.5">
  <img src="https://img.shields.io/badge/ZhipuAI-GLM--5.1-1a73e8?style=flat-square" alt="ZhipuAI GLM-5.1">
  <img src="https://img.shields.io/badge/+10_fallback-models-555?style=flat-square" alt="+10 fallback models">
</p>

<p align="center">
  <a href="https://mangowhoiscloud.github.io/geode/docs">Docs</a>
  ·
  <a href="README.ko.md">한국어</a>
</p>

# GEODE v0.99.51 — Long-running Autonomous Execution Harness

A general-purpose autonomous agent for exploratory research and signal prediction. You ask in plain language. GEODE plans, calls tools, and reports — for one prompt or a long-running session.

> **Have a ChatGPT Plus, Pro, Business, Edu, or Enterprise plan?** Route GEODE through that subscription. No API key. [Subscription setup ↓](#path-a--chatgpt-subscription-the-recommended-path-for-openai-users)
>
> **Claude Pro / Max?** Anthropic's terms (effective 2026-01-09) forbid third-party harness from using the Claude Code OAuth token, so GEODE doesn't read it. Use an Anthropic API key instead (Path B). Your Console account is the same; new accounts get $5 free credit.

---

## What you can ask it

Copy-paste these to see what it does:

```
"Summarize the latest RAG papers on arXiv from this month"
"Find LinkedIn job postings that match my profile and rank them"
"Schedule a 9 AM standup reminder every weekday"
"Watch hacker news for posts about LangGraph and DM me on Slack"
"Compare gpt-5.5 vs claude-opus-4.7 for code review"
```

GEODE chooses the right tools (web search, file ops, MCP servers, sub-agents), runs them, and shows you the answer with sources and cost.

---

## Setup in 5 minutes

### Prerequisites — what you need first

<details>
<summary><strong>Don't know what these are?</strong> Click here for a 1-line explainer of each.</summary>

- **Python 3.12+** — the language GEODE is written in. Most laptops don't have a recent enough version. Install from [python.org/downloads](https://www.python.org/downloads/) (download the macOS or Windows installer, click through).
- **Git** — how you copy GEODE's source code from GitHub. Mac: comes with Xcode Command Line Tools (`xcode-select --install`). Windows: [git-scm.com](https://git-scm.com/) installer.
- **uv** — a fast Python package manager (replaces pip). One-line install: copy the `curl` command below into Terminal/PowerShell.

If any of these fail, see [Troubleshooting](#troubleshooting) below.
</details>

| Tool | Install | Verify |
|------|---------|--------|
| Python 3.12+ | [python.org/downloads](https://www.python.org/downloads/) | `python3 --version` |
| Git | [git-scm.com](https://git-scm.com/) | `git --version` |
| uv | `curl -LsSf https://astral.sh/uv/install.sh \| sh` | `uv --version` |

### Step 1 — Install GEODE

GEODE's PyPI distribution is **`geode-agent`**. It installs the **`geode`** command.

```bash
uv tool install geode-agent
geode version
```

If the current release has not been published to PyPI yet, or you are developing GEODE itself, install from source instead:

```bash
git clone https://github.com/mangowhoiscloud/geode.git
cd geode
uv sync                              # installs dependencies (~30s)
uv tool install -e . --force         # makes `geode` available everywhere
```

### Step 2 — Run the setup wizard

```bash
geode setup
```

The wizard offers three paths: ChatGPT subscription (auto-detects `codex auth login` if you've already done it), API key (paste and go), or skip into dry-run mode for now. Pick whichever fits.

If you already ran `codex auth login` before installing GEODE, you can skip this step entirely — the next `geode` invocation will detect the token and start.

### Step 3 — Pick a path (manual reference)

The wizard above covers everything below; this section exists as a manual reference for what each path actually does.

---

#### Path A — ChatGPT subscription (the recommended path for OpenAI users)

Codex CLI signs you in once. GEODE picks up the token from `~/.codex/auth.json` and uses it for every call. Your subscription pays the bill; nothing extra to set up.

```bash
brew install codex                    # macOS  (or: npm install -g @openai/codex)
codex auth login                      # opens a browser; sign in with your ChatGPT account
geode                                 # done. GEODE finds the token automatically.
```

**Plans that work** (per the [official Codex CLI docs](https://developers.openai.com/codex/cli/)): Plus, Pro, Business, Edu, Enterprise.

**Quotas** (OpenAI-published, per 5-hour window): roughly 15–80 messages on Plus, up to 1,600 on Pro 20x. Edu and Enterprise have no fixed cap; usage scales with your workspace credits. Your admin needs to flip "Allow members to use Codex Local" before sign-in works on those tiers.

**Tier notes**:
- **gpt-5.5 is subscription-only.** API-key users (Path B) top out at gpt-5.4. If you want 5.5, you need ChatGPT.
- **ChatGPT Team is not currently supported** by Codex CLI. Team users should use Path B.
- **Free / Go** appear on OpenAI's pricing page but aren't listed in the CLI README. Treat them as best-effort; if it works, great, but no promises.

When the token nears expiry, GEODE refreshes it on its own (120 seconds before, plus a 401 retry). You shouldn't see this happen.

**Why Claude Pro isn't a Path A option.** Anthropic's terms changed on 2026-01-09: third-party tools may no longer reuse the Claude Code OAuth token. GEODE doesn't read `~/.claude/.credentials.json` to keep your account safe. The only Anthropic path GEODE accepts is an API key (Path B). ([Reference](https://www.theregister.com/2026/02/20/anthropic_clarifies_ban_third_party_claude_access))

---

#### Path B — API key (pay-as-you-go)

For Anthropic users (any tier, including Claude Pro / Max — OAuth isn't available), ChatGPT Team users, and anyone without a paid OpenAI subscription. You buy API credits directly. New Anthropic accounts get $5 in free credits, enough for hundreds of prompts.

**Get an Anthropic API key** (4 clicks):

1. Sign up at [console.anthropic.com](https://console.anthropic.com)
2. Top-right menu → **Settings** → **API Keys**
3. Click **Create Key** → name it "geode" → **Copy** the `sk-ant-...` string
4. Save it where GEODE will find it:

```bash
mkdir -p ~/.geode
echo 'ANTHROPIC_API_KEY=sk-ant-paste-your-key-here' > ~/.geode/.env
chmod 600 ~/.geode/.env
```

Want OpenAI or ZhipuAI GLM instead? Add `OPENAI_API_KEY=sk-proj-...` or `ZAI_API_KEY=...` to the same file. GEODE picks whichever is available.

**What it costs in practice.** A single prompt runs around 3,000 tokens, about $0.01. A research session with ten tool calls usually lands between $0.05 and $0.30. Your $5 free credit lasts roughly 500 prompts. Set `cost_limit_usd=5` in `.env` if you want a hard cap.

---

### Step 4 — Run

```bash
geode                                                # interactive chat
geode "what's new in AI today?"                      # one-shot prompt
```

You should see something like:

```
● AgenticLoop
  ✓ web_search → ok (1.5s)
  ✓ web_fetch → ok (1.1s)

  Today's top AI stories:
  • Anthropic released Claude Opus 4.7 with 1M-token context...
  • OpenAI's GPT-5.5 system card published; pricing matches 4.6...
  • LangGraph 0.6 ships native streaming for tool calls...

  ✢ Worked for 8s · claude-opus-4-7 · ↓2.1k ↑412 · $0.018
```

If you see this, you're done. If you see an error, run `geode doctor` for a diagnosis or jump to [Troubleshooting](#troubleshooting).

### Other useful commands

```bash
geode about           # version, model, registered auth, paths, daemon status
geode doctor          # 7-check bootstrap diagnosis with fix hints
uv tool upgrade geode-agent  # update a PyPI-installed CLI
geode update          # update a source checkout and refresh its editable CLI
geode uninstall       # remove runtime data and the installed CLI
geode setup --reset   # wipe ~/.geode/.env and re-run the wizard
```

---

### Updating

For a PyPI install, update the CLI package with uv:

```bash
uv tool upgrade geode-agent
geode version
```

For a source checkout install, let GEODE run the same update sequence it uses in smoke tests:

```bash
geode update
```

This runs `git pull --ff-only`, `uv sync`, `uv tool install -e . --force`, then `geode version`.
If `geode serve` was running, GEODE restarts it so the daemon loads the new code. Preview the
steps without changing files with:

```bash
geode update --dry-run
```

---

### Uninstalling

`geode uninstall` removes GEODE runtime data, stops the daemon, and removes the `geode-agent` uv tool install. Preview first if you want to see exactly what would be removed:

```bash
geode uninstall --dry-run
geode uninstall
```

If you only want to remove the PyPI-installed CLI and keep runtime data under `~/.geode/`, use uv directly:

```bash
uv tool uninstall geode-agent
```

Useful partial removal modes:

```bash
geode uninstall --keep-config   # keep .env and config.toml
geode uninstall --keep-data     # keep vault, identity, and user profile data
geode uninstall --force         # skip confirmations for automation
```

Verify removal:

```bash
which geode               # should print nothing
uv tool list | grep geode # should not list geode-agent
pgrep -f "geode serve"    # should print nothing
```

---

### Optional — Hook into Slack / Discord / Telegram

Once GEODE works in your terminal, you can let it answer on the messaging channels you already use:

```bash
geode serve                          # starts the always-on Gateway daemon
```

Configure channel bindings in `.geode/config.toml` (Slack bot token, Discord webhook, etc.). See [docs/setup.md → Gateway](docs/setup.md#gateway) for the full setup. After that, mentioning the bot in a channel routes the message into the same agent loop you use locally.

### Optional — Self-improving loop config (`~/.geode/config.toml`)

Tune the autoresearch / seed-generation / petri audit drivers — model picks, dim set, banner thresholds, PAYG fallback policy — by copying the `[self_improving_loop.*]` sections from [`docs/examples/self_improving_loop.config.toml.example`](docs/examples/self_improving_loop.config.toml.example) into `~/.geode/config.toml`. Absent sections fall back to documented defaults. To migrate per-role entries from the legacy `~/.geode/petri.toml`:

```bash
geode config migrate-petri-toml          # dry-run preview
geode config migrate-petri-toml --yes    # append [self_improving_loop.petri.*] to config.toml
```

---

## Troubleshooting

Run `geode doctor` first. It checks Python version, `geode` PATH, `~/.geode/.env`, Codex CLI OAuth, ProfileStore, the serve socket, and `~/.local/bin` PATH — and prints a concrete fix command for each failure. The expanders below cover the same ground in narrative form.

<details>
<summary><strong>"command not found: python3"</strong> — Python isn't installed or isn't on your PATH.</summary>

Mac: `xcode-select --install` then `brew install python@3.12`. Windows: download the installer from [python.org](https://www.python.org/downloads/) and check "Add Python to PATH" during setup. Verify with `python3 --version` — must be 3.12 or higher.
</details>

<details>
<summary><strong>"command not found: uv"</strong> — uv isn't on your PATH yet.</summary>

The install script writes uv to `~/.local/bin`. Either restart your terminal, or run `source ~/.bashrc` (bash) / `source ~/.zshrc` (zsh). Verify with `uv --version`.
</details>

<details>
<summary><strong>"command not found: geode"</strong> — the global install hasn't run.</summary>

For a PyPI install, run `uv tool install geode-agent`. For a source checkout, run `uv tool install -e . --force` from the `geode/` directory. Both paths put the `geode` command in `~/.local/bin/`. If that directory isn't on your PATH, add `export PATH="$HOME/.local/bin:$PATH"` to your shell config.
</details>

<details>
<summary><strong>"401 Unauthorized" or "Invalid API key"</strong> — wrong key, expired key, or wrong file location.</summary>

Check `cat ~/.geode/.env` and confirm the key starts with `sk-ant-` (Anthropic), `sk-proj-` (OpenAI), or `id.secret` (ZhipuAI GLM). Make sure there are no extra spaces or quote characters. If you used the ChatGPT subscription path (Path A), re-run `codex auth login` to refresh the OAuth token.
</details>

<details>
<summary><strong>"Address already in use" when running `geode serve`</strong> — daemon is already running.</summary>

`ps aux | grep "geode serve"` to find the PID, then `kill <PID>`. Or use `geode serve --port <other>` to pick a different port.
</details>

<details>
<summary><strong>The model doesn't seem to use my tools / runs in circles.</strong></summary>

Check `geode model` — some models are better at tool use than others. Default is `claude-opus-4-7` (best). If you're on `gpt-5.5`, set `effort: "high"` in `.geode/config.toml`. Run `tail -f ~/.geode/logs/serve.log` to see what the model is actually doing.
</details>

<details>
<summary><strong>I want to see what GEODE is doing under the hood.</strong></summary>

`tail -f ~/.geode/logs/serve.log` (or whichever log file you redirected when starting `geode serve` manually). Every LLM call, tool invocation, and decision is logged with timing. The `core.audit.diagnostics` fa4 channel writes per-month files under `~/.geode/diagnostics/<YYYY-MM>.log` for cross-process traces.
</details>

<details>
<summary><strong>How do I update?</strong></summary>

```bash
uv tool upgrade geode-agent   # PyPI install
geode update                  # source checkout
```
</details>

---

## What's inside

| Feature | What it does |
|---------|-------------|
| **`while(tool_use)` loop** | The single primitive every behavior is built on. Sub-agents, plans, batches — all instances of the same loop |
| **57 agentic tools + MCP catalog** | Web search, file ops, scheduling, memory, calendar, Slack/Discord, Korean job-board search, plus the Anthropic-published MCP registry (200 servers, cached at `~/.geode/mcp/registry-cache.json`). Auto-installed on first use |
| **3-provider failover** | Anthropic + OpenAI + ZhipuAI. Subscription OAuth (Codex) auto-detected; pay-as-you-go API keys also work; failover is in-provider only (no surprise cross-vendor charges, v0.53.0 governance) |
| **5-tier memory** | SOUL (0) → User Profile (0.5) → Organization (1) → Project (2) → Session (3). Persistent, survives daemon restarts |
| **Plan-mode + audit trail** | `create_plan` + `approve_plan` + `list_plans` for multi-step work. Disk-persistent (`.geode/plans.json`), survives restarts |
| **Long-running daemon** | `geode serve` runs as background daemon. Slack / Discord / Telegram pollers + scheduler tick + IPC for the thin CLI |
| **Sub-agents** | Full inheritance of parent capability, depth/cost guards, isolation by Lane |
| **Core verification** | Guardrails G1-G4 (structural) + Cross-LLM (inter-model, Krippendorff α ≥ 0.67) + Rights Risk (legal). External packages can add specialized bias / calibration layers |

---

## How GEODE compares

Grounded against the actual state of each frontier harness as of May 2026: **Claude Code v2.1.72** (build 2026-03-09), **Codex CLI v0.130.0** (released 2026-05-08), **OpenClaw v2026.5.12-beta.1**, **GEODE v0.99.51**. Marker legend: ✅✅ leader on the axis · ✅ supported · ⚠️ partial / qualified · ❌ absent · n/a not applicable.

<details>
<summary><strong>A. Runtime posture</strong> — how the agent stays alive</summary>

| | Claude Code | Codex CLI | OpenClaw | **GEODE** |
|---|---|---|---|---|
| Always-on daemon | ❌ per-invocation | ⚠️ opt-in `codex remote-control` (v0.130+) | ✅✅ launchd / systemd control plane | ✅ `geode serve` daemon |
| Native scheduler (cron) | ❌ (claude.ai web-only) | ❌ (Codex Cloud Automations only — [issue #8317](https://github.com/openai/codex/issues/8317)) | ✅ `cron add/edit/list` CLI | ✅ cron + event triggers |
| Thin CLI ↔ daemon IPC | ❌ | ⚠️ remote-control server mode | ✅ Gateway / Agent split | ✅ IPC server (v0.48+) |
| Sub-agent isolation | ✅ Agent tool + `run_in_background` | ✅ `multi_agent` feature, default `max_threads=6` | ✅✅ Lane Queue + Session bindings | ✅ Lane + depth / cost guard |
| Session resume / fork | ✅ JSONL transcripts | ✅ `/resume` + `/fork` slash commands | ✅ Session bindings with TTL | ✅ session resume (v0.21+) |

</details>

<details>
<summary><strong>B. Channels & UX surfaces</strong> — how it reaches users</summary>

| | Claude Code | Codex CLI | OpenClaw | **GEODE** |
|---|---|---|---|---|
| Slack | ❌ (MCP plugin possible) | ⚠️ Codex Cloud only, not CLI | ✅ Socket Mode, first-class | ✅ Socket Mode, first-class |
| Discord / Telegram / other chat | ❌ | ❌ | ✅✅ 23+ channels (Discord, Telegram, WhatsApp, Signal, iMessage, Teams, Matrix, Feishu, LINE, ...) | ✅ Discord + Telegram pollers |
| IDE plugin | ❌ (Chrome MCP extension only) | ✅✅ VS Code · JetBrains · Cursor · Windsurf | ❌ | ❌ |
| Web UI | ✅ claude.ai/code | ✅ Codex Cloud | ⚠️ WebChat plugin | ❌ (docs site only) |
| MCP server catalog | ✅ first-class | ✅ first-class | ✅ first-class | ✅ Anthropic-published registry (200 servers, cached at `~/.geode/mcp/registry-cache.json`) |

</details>

<details>
<summary><strong>C. LLM provider & cost governance</strong></summary>

| | Claude Code | Codex CLI | OpenClaw | **GEODE** |
|---|---|---|---|---|
| Multi-provider failover | ✅ Anthropic + AWS Bedrock + Google Vertex (env routing) | ✅✅ OpenAI + Azure + Bedrock + Ollama + any OpenAI-compatible (`model_providers` config) | ✅ `auth.order` cooldown-based auto-failover | ✅ Anthropic + OpenAI + ZhipuAI, in-provider only |
| Subscription OAuth tier | ✅ Pro / Max | ✅✅ Plus · Pro · Business · Edu · Enterprise | ⚠️ OpenAI + Gemini onboarding | ⚠️ ChatGPT only (Plus / Pro / Business / Edu / Enterprise) — Anthropic ToS (2026-01-09) blocks third-party Claude OAuth |
| Token / cost budget guard | ⚠️ cache token tracking only | ⚠️ retry caps (`request_max_retries`) | ⚠️ partial | ✅ **200K token guard** (v0.40), explicit budget governance |
| Context overflow handling | ✅ autocompaction | ⚠️ skills progressive disclosure (~2% budget) + fork | ✅ compaction + transcript streaming (252 MB → 27 MB peak) | ✅✅ **5-layer context overflow** (v0.39+) |
| Cross-vendor failover policy | ❌ | ⚠️ manual `model_providers` switch | ✅ automatic | ❌ by design (v0.53 governance — no surprise cross-vendor charges) |

</details>

<details>
<summary><strong>D. Persistence, memory & verification</strong></summary>

| | Claude Code | Codex CLI | OpenClaw | **GEODE** |
|---|---|---|---|---|
| Memory tiers | ⚠️ 3 (user / project / local settings merge) | ✅ hierarchical AGENTS.md (global `~/.codex/` + repo + nested dirs) | ⚠️ session-scoped | ✅✅ **5-tier** (SOUL · User · Org · Project · Session) |
| Disk-persistent plans | ✅ TodoWrite persistence | ⚠️ via resumable threads | ✅ task registry | ✅ `.geode/plans.json` |
| Permission / sandbox layers | ✅ 3-mode (default / auto / bypass) + Confirmation UI | ✅ `sandbox_mode` 3-level (read-only / workspace-write / danger-full-access) | ✅✅ Policy Chain (40+ audit surfaces) | ✅ Policy Chain + tool gates |
| Multi-layer guardrails | ⚠️ permission + hooks | ⚠️ hooks + sandbox | ✅ `audit.runtime` engine | ✅✅ **core verification** (G1-G4 + Cross-LLM Krippendorff α ≥ 0.67 + Rights Risk, plugin extension points for bias/calibration) |
| Hook event count | ⚠️ 5 (PreToolUse / PostToolUse / SessionStart / Notification / ConfigChange) | ⚠️ 6 (SessionStart / UserPromptSubmit / PreToolUse / PostToolUse / PermissionRequest / Stop) | ✅ 5 event types · many bundled handlers | ✅✅ **69 events** (`docs/architecture/hook-system.md`) |

</details>

<details>
<summary><strong>E. Extensibility & observability</strong></summary>

| | Claude Code | Codex CLI | OpenClaw | **GEODE** |
|---|---|---|---|---|
| Plugin / extension surfaces | ✅ manifest + marketplace (user / project / local scopes) | ✅ `/plugins` slash command + plugin sharing (v0.130+) | ✅✅ 4 extension points (Channel · Tool · Skill · Hook) via `@openclaw/plugin-sdk` | ✅ runtime SkillRegistry + MCP/tool surfaces |
| Skill system | ✅ Deferred tools + SKILL.md manifest | ✅ SKILL.md + progressive disclosure (`.agents/skills/`) | ✅ skill filter + archive upload | ✅ runtime `SkillRegistry` (14 skills across bundled/global/project scopes) |
| **Swappable pipeline DAG** | ❌ | ❌ | ⚠️ flows (channel-setup / doctor / provider — not a DAG abstraction) | ⚠️ external package responsibility; GEODE core no longer ships a pipeline port |
| Trace / replay / Run Log | ✅ `tengu_*` telemetry + `/insights` HTML | ⚠️ `/status` + `/debug-config` only | ✅ ACP session lineage + Task Registry | ✅ Native RunLog + Petri eval integration (v0.90+) |
| Cross-LLM verification | ❌ | ❌ | ❌ | ✅✅ Krippendorff α ≥ 0.67 inter-rater agreement gate |

</details>

---

Use **Claude Code** or **Codex** for short coding sessions inside an IDE or via cloud sync. Use **OpenClaw** to run a multi-channel chat agent fleet across 23+ messaging surfaces. Use **GEODE** when an agent must work over hours or days with multi-tier memory, multi-layer verification, scheduling, and daemon-backed tool execution.

> Sources — Claude Code v2.1.72 (build 2026-03-09, reverse-engineered reference). Codex CLI v0.130.0 release notes + [developers.openai.com/codex/config-reference](https://developers.openai.com/codex/config-reference) + [github.com/openai/codex](https://github.com/openai/codex). OpenClaw v2026.5.12-beta.1 (1.8M LoC TypeScript). GEODE — `CHANGELOG.md` (`v0.39` context overflow, `v0.40` 200K guard, `v0.85` 4-layer stack, `v0.90` Petri observability).

---

<details>
<summary><strong>Architecture overview</strong> (for contributors)</summary>

GEODE has two control layers:

- **Scaffold (production)** — Claude Code + `CLAUDE.md` + development Skills + CI Hooks. The external harness that produces GEODE's code and guarantees quality.
- **GEODE Runtime (agent)** — `while(tool_use)` loop + 57 agentic tools + native ToolRegistry + runtime Skills + 69 runtime Hooks + 5-Layer Verification. The internal system of the autonomously executing agent.

4-Layer Stack (Model → Runtime → Harness → Agent) + Sub-Agent System + 5-Tier Memory.

```mermaid
graph LR
    AG["Agent<br/>AgenticLoop, SubAgent<br/>CLIPoller, Gateway"] --> HA["Harness<br/>SessionLane, PolicyChain<br/>TaskGraph, HookSystem"]
    HA --> RT["Runtime<br/>Agentic tools(53), MCP catalog<br/>Memory, Skills"]
    RT --> MD["Model<br/>Claude, OpenAI, GLM"]

    style AG fill:#1e293b,stroke:#3b82f6,color:#e2e8f0
    style HA fill:#1e293b,stroke:#f59e0b,color:#e2e8f0
    style RT fill:#1e293b,stroke:#10b981,color:#e2e8f0
    style MD fill:#1e293b,stroke:#8b5cf6,color:#e2e8f0
```

| Layer | Core | Entry points |
|-------|------|--------------|
| **Agent** | AgenticLoop, SubAgentManager, CLIPoller, Gateway | `core/cli/`, `core/gateway/` |
| **Harness** | SessionLane, LaneQueue(global:8), PolicyChain, TaskGraph, HookSystem(69) | `core/orchestration/`, `core/hooks/` |
| **Runtime** | Agentic tools(53), native ToolRegistry(16), MCP Catalog (200 via Anthropic registry plus project-configured servers), runtime Skills, Memory(5-Tier), PlanStore | `core/tools/`, `core/memory/`, `core/orchestration/plan_store.py` |
| **Model** | ClaudeAdapter, OpenAIAdapter, CodexAdapter, GLMAdapter | `core/llm/` |

`.geode/` — agent context lifecycle (5-tier hierarchy assembled into every LLM call):

```
Tier 0    SOUL            GEODE.md — agent identity + constraints
Tier 0.5  User Profile    ~/.geode/user_profile/ — role, expertise, language
Tier 1    Organization    Cross-project data (signals, history)
Tier 2    Project         .geode/memory/PROJECT.md — analysis history (LRU-50)
Tier 3    Session         In-memory — conversation, tool results, plans
```

```
.geode/
├── config.toml         # Gateway, MCP servers, model
├── memory/             # T2: Project Memory (LRU rotate)
├── rules/              # Auto-generated project rules
├── vault/              # Permanent artifacts (reports, research)
├── skills/             # project runtime skills (5-tier discovery)
├── plans.json          # Disk-persistent PlanStore (v0.53.3)
└── result_cache/       # Pipeline LRU (SHA-256, 24h TTL)
```

[Full architecture →](docs/architecture/) | [Hook System →](docs/architecture/hook-system.md) | [Wiring Audit →](docs/architecture/wiring-audit-matrix.md)

</details>

<details>
<summary><strong>Development workflow (Scaffold)</strong></summary>

CANNOT (guardrails) before CAN (freedom). 7-step workflow + quality gates. CI ratchet — 5 jobs (pytest, mypy, ruff, import-order, test-count) must pass before any merge. Test count is monotonically increasing only.

| Gate | Command | Target |
|------|---------|--------|
| Lint | `uv run ruff check core/ tests/` | 0 errors |
| Type | `uv run mypy core/` | 0 errors |
| Test | `uv run pytest tests/ -q` | 4700+ pass |

See [CONTRIBUTING.md](CONTRIBUTING.md) and [docs/workflow.md](docs/workflow.md).

</details>

<details>
<summary><strong>Why — motivation</strong></summary>

In 2026, AI coding agents have made remarkable progress. They read, write, fix, and test code autonomously. But how much of real work is actually coding? Research, document analysis, scheduling, notifications, data pipelines, multi-axis evaluation for decision-making — the space requiring autonomous execution *beyond* coding is far broader.

Yet the core of all autonomous behavior is surprisingly simple: an LLM calls tools, observes results, decides the next action — a `while(tool_use)` loop. Claude Code, Codex, OpenClaw — all frontier harnesses stand on this primitive. GEODE generalizes it into a daemon-backed, memoryful runtime for long-running tool work.

</details>

---

## License

Apache License 2.0 — [LICENSE](./LICENSE)
