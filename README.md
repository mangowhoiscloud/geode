<p align="center">
  <img src="assets/geodi-dot.svg" alt="Geodi, GEODE's dot mascot" width="240" />
</p>

<p align="center">
  <a href="https://github.com/mangowhoiscloud/geode/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/mangowhoiscloud/geode/ci.yml?style=flat-square&label=ci" alt="CI"></a>
  <a href="https://github.com/mangowhoiscloud/geode/releases/latest"><img src="https://img.shields.io/github/v/release/mangowhoiscloud/geode?style=flat-square&label=release" alt="Latest release"></a>
</p>

<p align="center">
  <a href="https://mangowhoiscloud.github.io/geode/docs/">Docs</a> ·
  <a href="https://github.com/mangowhoiscloud/geode-eval-artifacts">Evaluation artifacts</a> ·
  <a href="README.ko.md">한국어</a>
</p>

# GEODE v1.0.30 — Autonomous Agent Runtime + Evaluation Substrate

GEODE is a Python agent runtime for research, file work, and scheduled tasks.
Its agentic loop calls tools, reads their results, and continues the task.
A daemon owns execution and sessions; the terminal client connects over IPC.
MCP servers and messaging integrations extend the available tools and channels.

The same distribution includes evaluation tools and experimental scaffold
search. These have separate responsibilities from the runtime; see
[package boundaries](#package-boundaries).

## Quick start

Use Python 3.12+ and [uv](https://docs.astral.sh/uv/getting-started/installation/)
on macOS or Linux. Git is needed only for source development.

```bash
uv tool install geode-agent
geode version
geode setup
geode
```

The package name is **`geode-agent`**; the terminal command is **`geode`**.
Setup offers ChatGPT sign-in, API-key entry, or an explicit dry-run choice.
The terminal client starts the daemon when needed.

Try a request in the session:

```text
Summarize the documents in this directory and cite the source files.
Compare these two design proposals and list the unresolved decisions.
```

Web access, messaging, and other integrations require their own configuration
and permissions. See the [setup guide](docs/setup.md).

### Authentication and model selection

Inside a GEODE session:

| Command | Purpose |
|---|---|
| `/login openai` | ChatGPT device-code sign-in for an eligible account |
| `/login anthropic` | Hidden API-key entry for Anthropic |
| `/login add` | Choose a provider/account type and add credentials interactively |
| `/login status` | Inspect configured authentication |
| `/model` | Select an available model and effort |

The OpenAI subscription route calls the Codex backend through an in-process
OAuth adapter. It can also read existing Codex credentials; it does not run
Codex CLI for inference. Account entitlement and limits still apply.
Anthropic uses API keys; the retired Claude CLI subscription route is unsupported.

API-key routes include Anthropic, OpenAI, OpenRouter, and Z.AI.
Use hidden terminal prompts instead of placing keys in commands or chat.
GEODE-managed provider keys and OAuth accounts are stored in
`~/.geode/auth.toml`, an owner-only plaintext file, not an OS keychain.
Externally supplied environment credentials remain supported.

See [provider configuration](https://mangowhoiscloud.github.io/geode/docs/run/providers/)
and [authentication](https://mangowhoiscloud.github.io/geode/docs/ops/oauth/)
for source selection, credential precedence, and account routing.

### Optional Jev judgments

v1.0.30 supports Jev judgments through TypeSafe or OpenRouter. Configure a
usable credential, then select the judgment route explicitly:

```text
/model judgment typesafe
/model judgment openrouter
/model judgment llm
```

Choose one route; `llm` returns to the LLM judgment path. This selection preserves
the generative model and effort. Adding a key alone does not enable Jev.
Reflection runs after tool-result rounds and before final delivery, subject to
runtime guards. See [judgment configuration](https://mangowhoiscloud.github.io/geode/docs/config/reference/)
and [verification and evaluation](https://mangowhoiscloud.github.io/geode/docs/verification/evaluation/)
for credentials, usage, and the scope of each judgment.

## Configuration and operations

| Location | Responsibility |
|---|---|
| `~/.geode/auth.toml` | GEODE-managed provider credentials and account metadata |
| `~/.geode/.env` | Optional environment credentials and integration secrets |
| `~/.geode/config.toml` | User-wide behavior defaults |
| `./.geode/config.toml`, `./.env` | Project overrides; capability keys apply only in a trusted folder |
| `~/.geode/trusted_projects.toml` | Folders you trusted with `geode config trust` |
| `~/.geode/` | Runtime state, sessions, diagnostics, and private artifacts |

Project behavior overrides user defaults. A repository's `.env`, MCP servers,
gateway config, and keys that widen capability (sandbox, computer use,
webhooks, storage paths) apply only after `geode config trust` in that folder. Credential resolution also depends
on the selected model, source, and account; it is not one flat settings ladder.
Google Workspace OAuth has its own
[account and keyring storage](https://mangowhoiscloud.github.io/geode/docs/run/google-workspace/).

```bash
geode about                    # Effective model, paths, and daemon status
geode doctor                   # Diagnose local setup and credential availability
geode config explain model     # Show the layers behind a behavior setting
geode update --dry-run          # Preview the update path
geode update                   # Registry install: newest compatible patch
geode update --latest          # Explicitly allow minor/major registry upgrades
```

Source-checkout updates and customized uv installs have separate handling; see
[installation and updates](docs/architecture/immutable-distribution-lifecycle.md).
To remove only the uv-installed CLI while keeping runtime data, use
`uv tool uninstall geode-agent`. `geode uninstall` also removes runtime data;
inspect `geode uninstall --dry-run` first.

Cost guards use observed usage and configured tariffs. They are not a provider
billing cap: an in-flight call can exceed a threshold, and missing usage is not
zero cost. See [usage accounting](docs/architecture/usage-accounting.md).

### If something fails

- **Command not found:** check `uv tool dir --bin` and your shell's PATH.
- **Authentication failure:** inspect `/login status`, then sign in or replace
  the key through `/login`. Do not paste credentials into diagnostics or issues.
- **Unexpected model or setting:** inspect `geode about`, `/model`, and
  `geode config explain model`; running sessions retain admitted settings.
- **Daemon connection failure:** run `geode doctor` and check the configured
  Unix socket and `~/.geode/logs/serve.log`. Identify the owning process before
  stopping it; another session may be using it.

## Integrations

**Messaging.** `geode serve` runs the daemon and configured Slack, Discord,
Telegram, and scheduler services. Channel credentials and bindings are opt-in.
Remote computer use is disabled in Gateway sessions unless explicitly enabled.
See [Gateway setup](docs/setup.md#slack-gateway).

**MCP client.** Attach external tool servers through GEODE's MCP configuration.
See the [MCP guide](https://mangowhoiscloud.github.io/geode/docs/runtime/tools/mcp/).

**MCP server.** Configure an MCP client's stdio command as `geode-mcp`.
The core server exposes `run_agent`, `query_memory`, and `get_health`.
For HTTP access, `geode-mcp --http` uses `GEODE_MCP_TOKEN` bearer authentication;
a non-loopback bind without a token is refused. This endpoint can execute agent
tools, so access grants execution authority. See the
[server implementation](core/mcp_server.py) for its current transport contract.

## Package boundaries

| Package | Responsibility | Commands |
|---|---|---|
| `core/` | Agent runtime, terminal client, daemon, tools, memory, MCP | `geode`, `geode-mcp` |
| `evals/` | Audits, benchmark adapters, evaluation evidence | `geode-eval` |
| `evolve/` | Experimental scaffold search and Crucible | `geode-evolve` |

Installed code and bundled assets stay separate from mutable state.
Scaffold mutation and promotion require a writable GEODE Git checkout.

SIL and Crucible are **experimental**. They evaluate changes to prompts, tools,
and other scaffolding without updating model weights. Safety-audit results and
benchmark results have different acceptance contracts. The public record does
not establish sustained self-improvement.
Start with the [self-improving hub](https://mangowhoiscloud.github.io/geode/self-improving/)
or the [campaign guide](docs/self-improving/campaign-quick-start.md).

## Evaluation evidence

Read results with their source revision, task set, model route, effort,
timeout, and attempt history. A runtime completion message, a model judgment,
and a benchmark verifier result are different observations.

| Track | Scope to check |
|---|---|
| [Tau2](https://mangowhoiscloud.github.io/geode/docs/benchmarks/tau2/) | Native-user and GEODE-user tracks; completion and quota contamination |
| [MCPMark](https://mangowhoiscloud.github.io/geode/docs/benchmarks/mcpmark/) | Covered services, paired observations, and full-Verified limitations |
| [Terminal-Bench 2.1](https://mangowhoiscloud.github.io/geode/docs/benchmarks/terminal-bench/) | Account-scoped one-task smoke versus full-suite results |
| [Jev judgments](https://mangowhoiscloud.github.io/geode/docs/verification/evaluation/) | Decision quality, completion timing, and end-to-end task outcomes |

Receipts and privacy-reviewed trajectories are published in the
[evaluation artifact repository](https://github.com/mangowhoiscloud/geode-eval-artifacts).
These tracks do not form a single product score or a frontier-harness ranking.

## Development

```bash
git clone https://github.com/mangowhoiscloud/geode.git
cd geode
uv sync --locked
uv run geode version
```

Read [AGENTS.md](AGENTS.md) for contributor rules and [CONTRIBUTING.md](CONTRIBUTING.md)
for development and PR guidance. The [workflow](docs/workflow.md) owns verification
and integration; [architecture docs](docs/architecture/) own subsystem contracts.

Development guidance in `.agents/skills/` is separate from runtime skills in
`.geode/skills/`. Runtime prompt guidance also does not replace executable
permission checks. See [prompt assembly](https://mangowhoiscloud.github.io/geode/docs/runtime/llm/prompt-system/).

[Changelog](CHANGELOG.md) · [Security policy](SECURITY.md) · [Apache 2.0 license](LICENSE)
