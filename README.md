<p align="center">
  <img src="assets/geode-mascot.png" alt="GEODE — Autonomous Execution Harness" width="360" />
</p>

<p align="center">
  <img src="https://img.shields.io/badge/while(tool__use)-agentic%20loop-1e293b?style=flat-square" alt="while(tool_use)">
  <img src="https://img.shields.io/badge/56%20tools-MCP%20native-1e293b?style=flat-square" alt="56 Tools">
  <img src="https://img.shields.io/badge/LangGraph-StateGraph-1e293b?style=flat-square" alt="LangGraph">
  <a href="https://github.com/mangowhoiscloud/geode/actions"><img src="https://img.shields.io/github/actions/workflow/status/mangowhoiscloud/geode/ci.yml?style=flat-square&label=ci&logo=github&logoColor=white" alt="CI"></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Anthropic-Opus_4.7-cc785c?style=flat-square&logo=anthropic&logoColor=white" alt="Anthropic Opus 4.7">
  <img src="https://img.shields.io/badge/OpenAI-GPT--5.5-412991?style=flat-square&logo=openai&logoColor=white" alt="OpenAI GPT-5.5">
  <img src="https://img.shields.io/badge/ZhipuAI-GLM--5.1-1a73e8?style=flat-square" alt="ZhipuAI GLM-5.1">
  <img src="https://img.shields.io/badge/+10_fallback-models-555?style=flat-square" alt="+10 fallback models">
</p>

[한국어](README.ko.md)

# GEODE v0.53.3 — Long-running Autonomous Execution Harness

A general-purpose autonomous agent for **exploratory research and signal prediction**. You ask in plain language; GEODE plans, calls tools, and reports — across one prompt or a long-running session.

> **Already pay for ChatGPT Plus or Claude Pro?** You don't need an API key. [Skip to subscription setup ↓](#path-a--use-your-existing-subscription-recommended)

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

### Step 1 — Get the code

```bash
git clone https://github.com/mangowhoiscloud/geode.git
cd geode
uv sync                              # installs dependencies (~30s)
uv tool install -e . --force         # makes `geode` available everywhere
```

### Step 2 — Pick how you'll talk to the model

Pick **one** of the two paths below. Both work; one is cheaper if you already pay for a chat subscription.

---

#### Path A — Use your existing subscription (recommended)

If you already pay for **ChatGPT Plus** ($20/mo) or **Claude Pro** ($20/mo), you can route GEODE's calls through that subscription with **no extra charge** and no API key.

**ChatGPT Plus / Pro / Business** → use the Codex backend:

```bash
brew install codex                    # macOS — or: npm install -g @openai/codex
codex auth login                      # opens browser → sign in with your ChatGPT account
geode                                 # GEODE auto-detects the OAuth token
```

**Claude Pro / Max** → use Claude CLI:

```bash
brew install claude                   # macOS — or: npm install -g @anthropic-ai/claude-code
claude /login                         # opens browser → sign in with your Anthropic account
geode                                 # GEODE auto-detects the OAuth token
```

> **Why this works**: Codex and Claude CLI both ship with OAuth flows that exchange your subscription login for a short-lived token. GEODE reads the same token file (`~/.codex/auth.json`, `~/.claude/.credentials.json`) — no copy-paste, no leaks. If your subscription resets, GEODE refreshes the token automatically (120s before expiry, 401 auto-retry).

---

#### Path B — Use an API key (pay-as-you-go)

If you don't have a subscription, you can buy API credits directly. New Anthropic accounts come with **$5 free credits**, enough for hundreds of conversations.

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

> **Cost reality check.** A typical single-prompt session uses ~3,000 tokens at ~$0.01. A long research session with 10 tool calls is usually $0.05–$0.30. The free $5 credit covers ~500 prompts. Set `cost_limit_usd=5` in your `.env` to cap spend.

---

### Step 3 — Run

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

If you see this, you're done. If you see an error, jump to [Troubleshooting](#troubleshooting).

---

### Optional — Hook into Slack / Discord / Telegram

Once GEODE works in your terminal, you can let it answer on the messaging channels you already use:

```bash
geode serve                          # starts the always-on Gateway daemon
```

Configure channel bindings in `.geode/config.toml` (Slack bot token, Discord webhook, etc.). See [docs/setup.md → Gateway](docs/setup.md#gateway) for the full setup. After that, mentioning the bot in a channel routes the message into the same agent loop you use locally.

---

## Troubleshooting

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

Run `uv tool install -e . --force` from the `geode/` directory. This puts the `geode` command in `~/.local/bin/`. If that directory isn't on your PATH, add `export PATH="$HOME/.local/bin:$PATH"` to your shell config.
</details>

<details>
<summary><strong>"401 Unauthorized" or "Invalid API key"</strong> — wrong key, expired key, or wrong file location.</summary>

Check `cat ~/.geode/.env` and confirm the key starts with `sk-ant-` (Anthropic), `sk-proj-` (OpenAI), or `id.secret` (ZhipuAI GLM). Make sure there are no extra spaces or quote characters. If you used the subscription path, re-run `codex auth login` or `claude /login` to refresh the OAuth token.
</details>

<details>
<summary><strong>"Address already in use" when running `geode serve`</strong> — daemon is already running.</summary>

`ps aux | grep "geode serve"` to find the PID, then `kill <PID>`. Or use `geode serve --port <other>` to pick a different port.
</details>

<details>
<summary><strong>The model doesn't seem to use my tools / runs in circles.</strong></summary>

Check `geode model` — some models are better at tool use than others. Default is `claude-opus-4-7` (best). If you're on `gpt-5.5`, set `effort: "high"` in `.geode/config.toml`. Run `tail -f /tmp/geode-serve.log` to see what the model is actually doing.
</details>

<details>
<summary><strong>I want to see what GEODE is doing under the hood.</strong></summary>

`tail -f ~/.local/share/geode/logs/serve.log` (or `/tmp/geode-serve.log` if you started it manually). Every LLM call, tool invocation, and decision is logged with timing.
</details>

<details>
<summary><strong>How do I update?</strong></summary>

```bash
cd geode
git pull origin main
uv sync
uv tool install -e . --force
```
</details>

---

## What's inside

| Feature | What it does |
|---------|-------------|
| **`while(tool_use)` loop** | The single primitive every behavior is built on. Sub-agents, plans, batches — all instances of the same loop |
| **56 tools + 44 MCP servers** | Web search, file ops, scheduling, memory, calendar, Slack/Discord, native MCP catalog. Auto-installed on first use |
| **3-provider failover** | Anthropic + OpenAI + ZhipuAI. Subscription OAuth (Codex, Claude CLI) auto-detected; pay-as-you-go API keys also work; failover is in-provider only (no surprise cross-vendor charges, v0.53.0 governance) |
| **4-tier memory** | SOUL (identity) → User Profile → Organization → Project → Session. Persistent, survives daemon restarts |
| **Plan-mode + audit trail** | `create_plan` + `approve_plan` + `list_plans` for multi-step work. Disk-persistent (`.geode/plans.json`), survives restarts |
| **Long-running daemon** | `geode serve` runs as background daemon. Slack / Discord / Telegram pollers + scheduler tick + IPC for the thin CLI |
| **Sub-agents** | Full inheritance of parent capability, depth/cost guards, isolation by Lane |
| **5-layer verification** | Guardrails G1-G4 + BiasBuster + Cross-LLM (Krippendorff α ≥ 0.67) + Confidence Gate + Rights Risk |
| **Domain-specific DAG (swappable)** | Pipelines (research, multi-axis evaluation, synthesis) plug in via the `DomainPort` Protocol. Ships with one reference DAG out-of-the-box; replace it for any exploratory-research / signal-prediction problem |

---

## How GEODE compares

| | Claude Code | Codex CLI | OpenClaw | **GEODE** |
|---|---|---|---|---|
| Always-on daemon | ❌ session only | ❌ session only | ✅ Gateway | ✅ `geode serve` |
| Slack/Discord channels | ❌ | ❌ | ✅ many | ✅ Slack first-class |
| Multi-provider failover | ⚠️ Anthropic only | ⚠️ OpenAI only | ✅ many | ✅ 3 + governance |
| Subscription OAuth (no API key) | ✅ Pro/Max | ✅ Plus | ✅ both | ✅ both |
| Disk-persistent plans + memory | ⚠️ partial | ⚠️ partial | ✅ | ✅ 4-tier |
| Swappable domain DAG | ❌ | ❌ | ❌ | ✅ `DomainPort` |
| Scheduler (long-running) | ❌ | ❌ | ⚠️ partial | ✅ cron + triggers |

Use **Claude Code** or **Codex** for short coding sessions. Use **GEODE** when you need it to keep running, watch signals, and report back over hours or days.

---

<details>
<summary><strong>Architecture overview</strong> (for contributors)</summary>

GEODE has two control layers:

- **Scaffold (production)** — Claude Code + `CLAUDE.md` + development Skills + CI Hooks. The external harness that produces GEODE's code and guarantees quality.
- **GEODE Runtime (agent)** — `while(tool_use)` loop + 56 tools + 15 runtime Skills + 58 runtime Hooks + 5-Layer Verification. The internal system of the autonomously executing agent.

4-Layer Stack (Model → Runtime → Harness → Agent) + Sub-Agent System + 4-Tier Memory.

```mermaid
graph LR
    AG["Agent<br/>AgenticLoop, SubAgent<br/>CLIPoller, Gateway"] --> HA["Harness<br/>SessionLane, PolicyChain<br/>TaskGraph, HookSystem"]
    HA --> RT["Runtime<br/>Tools(56), MCP(44)<br/>Memory, Skills"]
    RT --> MD["Model<br/>Claude, OpenAI, GLM"]

    AG -.-> DP["⊥ Domain<br/>DomainPort Protocol<br/>(swappable DAG)"]
    HA -.-> DP
    RT -.-> DP

    style AG fill:#1e293b,stroke:#3b82f6,color:#e2e8f0
    style HA fill:#1e293b,stroke:#f59e0b,color:#e2e8f0
    style RT fill:#1e293b,stroke:#10b981,color:#e2e8f0
    style MD fill:#1e293b,stroke:#8b5cf6,color:#e2e8f0
    style DP fill:#1e293b,stroke:#06b6d4,color:#e2e8f0,stroke-dasharray: 5 5
```

| Layer | Core | Entry points |
|-------|------|--------------|
| **Agent** | AgenticLoop, SubAgentManager, CLIPoller, Gateway | `core/cli/`, `core/gateway/` |
| **Harness** | SessionLane, LaneQueue(global:8), PolicyChain, TaskGraph, HookSystem(58) | `core/orchestration/`, `core/hooks/` |
| **Runtime** | ToolRegistry(56), MCP Catalog(44), Skills, Memory(4-Tier), PlanStore | `core/tools/`, `core/memory/`, `core/orchestration/plan_store.py` |
| **Model** | ClaudeAdapter, OpenAIAdapter, CodexAdapter, GLMAdapter | `core/llm/` |
| **⊥ Domain** | `DomainPort` Protocol — domain-specific DAG plugged in via Port (cross-cutting). One reference DAG ships in the repo; replace for any exploratory-research / signal-prediction domain | `core/domains/` |

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
├── rules/              # Auto-generated domain rules
├── vault/              # Permanent artifacts (reports, research)
├── skills/             # 15 runtime skills (3-tier visibility)
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
| Test | `uv run pytest tests/ -q` | 4200+ pass |

See [CONTRIBUTING.md](CONTRIBUTING.md) and [docs/workflow.md](docs/workflow.md).

</details>

<details>
<summary><strong>Why — motivation</strong></summary>

In 2026, AI coding agents have made remarkable progress. They read, write, fix, and test code autonomously. But how much of real work is actually coding? Research, document analysis, scheduling, notifications, data pipelines, multi-axis evaluation for decision-making — the space requiring autonomous execution *beyond* coding is far broader.

Yet the core of all autonomous behavior is surprisingly simple: an LLM calls tools, observes results, decides the next action — a `while(tool_use)` loop. Claude Code, Codex, OpenClaw — all frontier harnesses stand on this primitive. GEODE generalizes it: domain-agnostic harness, swappable `DomainPort` DAGs for whatever exploratory or signal-prediction problem you're solving.

</details>

---

## License

Apache License 2.0 — [LICENSE](./LICENSE)
