# Slash-command convergence matrix — GEODE vs Claude Code / Codex CLI / Hermes

Measured 2026-07-29 against GEODE v1.0.7. Every frontier entry was read from
primary source, not recalled:

| Tool | Source | Version | Commands |
|---|---|---|---|
| Claude Code | `code.claude.com/docs/en/commands.md` (raw markdown, `All commands` table) | docs 2026-07-29 | 103 |
| Codex CLI | `codex-rs/tui/src/slash_command.rs` — `enum SlashCommand` | `rust-v0.146.0` | 55 |
| Hermes | `hermes_cli/commands.py` — `COMMAND_REGISTRY` | `nousresearch/hermes-agent` v0.19.0 | 90 |
| **GEODE** | `core/cli/commands/_state.py` — `COMMAND_MAP` | **v1.0.7** | **33** (24 actions + 9 aliases) |

Legend: **Y** present · **~** partial or differently-shaped · **—** absent ·
**N/A** not applicable to that product. "Converged" counts the three frontier
tools only, so GEODE's column reads as a gap list rather than being self-scoring.

---

## 1. Session lifecycle

| Capability | Claude Code | Codex | Hermes | Converged | GEODE |
|---|---|---|---|---|---|
| Quit / exit | `/exit` `/quit` | `/quit` `/exit` | `/quit` `/exit` | **3/3** | **Y** `/quit` `/exit` `/q` |
| New / clear conversation | `/clear` | `/new` `/clear` | `/new` `/clear` | **3/3** | **Y** `/clear` |
| Resume a past session | `/resume` | `/resume` | `/resume` `/sessions` | **3/3** | **Y** `/resume` |
| Fork / branch the conversation | `/fork` `/branch` | `/fork` | `/branch` `/fork` | **3/3** | **—** |
| Rename current session | `/rename` | `/rename` | `/title` | **3/3** | **—** |
| Stop background work | `/stop` | `/stop` | `/stop` | **3/3** | **—** |
| Rewind / checkpoint restore | `/rewind` | — | `/rollback` `/snapshot` | 2/3 | **—** |
| Retry / undo last turn | — | — | `/retry` `/undo` | 1/3 | **—** |
| Move working dir | `/cd` `/add-dir` | — | — | 1/3 | **—** |
| Hand off to another surface | `/desktop` `/mobile` `/teleport` | `/app` | `/handoff` | **3/3** | **—** |
| Archive / delete session | — | `/archive` `/delete` | `/quit --delete` | 2/3 | **—** |

## 2. Context and memory

| Capability | Claude Code | Codex | Hermes | Converged | GEODE |
|---|---|---|---|---|---|
| Compact / compress context | `/compact` | `/compact` | `/compress` `/compact` | **3/3** | **Y** `/compact` |
| Context usage visualization | `/context` | — | `/context` `/ctx` | 2/3 | **Y** `/context` `/ctx` |
| Project guide bootstrap | `/init` | `/init` | `/init` | **3/3** | **~** `geode init` CLI exists but scaffolds `.geode/` config, **not** a project guide — same name, different job |
| Persistent memory management | `/memory` | `/memories` | `/memory` | **3/3** | **~** `/recall` (read-only recall; no write/approval UI) |
| Side question (off-transcript) | `/btw` | `/side` `/btw` | `/background` `/btw` | **3/3** | **—** |
| Export / copy transcript | `/export` `/copy` | `/copy` `/raw` | `/copy` `/save` | **3/3** | **~** `geode session export` CLI, no slash |
| Session recap | `/recap` | — | `/history` | 2/3 | **—** |

## 3. Model and configuration

| Capability | Claude Code | Codex | Hermes | Converged | GEODE |
|---|---|---|---|---|---|
| Switch model | `/model` | `/model` | `/model` | **3/3** | **Y** `/model` |
| Reasoning effort / thinking level | `/effort` | `/model` (combined) | `/reasoning` | **3/3** | **—** (config-only) |
| Settings UI / direct set | `/config` | `/debug-config` | `/config` | **3/3** | **~** `geode config` CLI, no slash |
| Permission / approval policy | `/permissions` | `/permissions` | `/approvals` `/yolo` | **3/3** | **—** |
| Sandbox control | `/sandbox` | `/setup-default-sandbox` | (docker egress) | **3/3** | **—** |
| Verbosity / output detail | `/focus` | — | `/verbose` `/focus` | 2/3 | **Y** `/verbose` |
| Theme / appearance | `/theme` `/color` | `/theme` | `/skin` | **3/3** | **—** |
| Status line | `/statusline` | `/statusline` | `/statusbar` | **3/3** | **—** |
| Keybindings | `/keybindings` | `/keymap` | — | 2/3 | **—** |
| Personality / response style | (via config) | `/personality` | `/personality` | 2/3 | **—** |
| Fast / priority lane | `/fast` | — | `/fast` | 2/3 | **—** |
| Voice input | `/voice` | — | `/voice` `/wake` | 2/3 | **—** |

## 4. Auth and billing

| Capability | Claude Code | Codex | Hermes | Converged | GEODE |
|---|---|---|---|---|---|
| Login | `/login` | — (auto) | — | 1/3 | **Y** `/login` |
| Logout | `/logout` | `/logout` | — | 2/3 | **~** via `/login` |
| API key entry | (via `/login`) | — | — | 1/3 | **Y** `/key` |
| Plan / subscription management | `/upgrade` `/passes` | — | `/subscription` `/topup` | 2/3 | **—** |
| Credits / usage limits | `/usage-credits` | `/usage` (reset redeem) | `/usage reset` | **3/3** | **—** |

## 5. Tools, MCP, skills

| Capability | Claude Code | Codex | Hermes | Converged | GEODE |
|---|---|---|---|---|---|
| MCP server management | `/mcp` | `/mcp` | `/reload-mcp` | **3/3** | **Y** `/mcp` |
| Skills list / manage | `/skills` | `/skills` | `/skills` `/bundles` | **3/3** | **Y** `/skills` `/skill` |
| Reload skills/plugins live | `/reload-skills` `/reload-plugins` | — | `/reload-skills` `/reload` | 2/3 | **—** |
| Plugin management | `/plugin` | `/plugins` | `/plugins` | **3/3** | **—** |
| Hooks inspection | `/hooks` | `/hooks` | — | 2/3 | **—** |
| Per-tool enable/disable | (via `/permissions`) | — | `/tools` `/toolsets` | 2/3 | **—** |
| IDE integration | `/ide` | `/ide` | — | 2/3 | **—** |
| Learn a new skill from context | `/run-skill-generator` | — | `/learn` `/curator` | 2/3 | **—** |

## 6. Agents, subagents, scheduling

| Capability | Claude Code | Codex | Hermes | Converged | GEODE |
|---|---|---|---|---|---|
| List agents / background tasks | `/agents` `/tasks` | `/agent` `/subagents` `/ps` | `/agents` `/tasks` | **3/3** | **Y** `/tasks` `/task` `/t`, `/fleet` |
| Spawn background / detached run | `/background` `/subtask` | — | `/background` `/bg` | 2/3 | **—** (tool-level only) |
| Standing goal across turns | `/goal` | `/goal` | `/goal` `/subgoal` | **3/3** | **—** |
| Scheduled / cron routines | `/schedule` `/loop` | — | `/cron` `/blueprint` | 2/3 | **Y** `/schedule` `/sched`, `/trigger` |
| Queue / steer a running turn | — | — | `/queue` `/steer` | 1/3 | **—** |
| Multi-agent workflow control | `/workflows` `/batch` | — | `/moa` `/kanban` | 2/3 | **—** |

## 7. Observability and cost

| Capability | Claude Code | Codex | Hermes | Converged | GEODE |
|---|---|---|---|---|---|
| Session status | `/status` | `/status` | `/status` | **3/3** | **Y** `/status` |
| Cost / token usage | `/usage` `/cost` `/stats` | `/usage` | `/usage` | **3/3** | **Y** `/cost` |
| Session insights / patterns | `/insights` | — | `/insights` | 2/3 | **~** `/cognitive` (loop-state view, different intent) |
| Identity / profile | — | — | `/whoami` `/profile` | 1/3 | **—** |

## 8. Dev and meta

| Capability | Claude Code | Codex | Hermes | Converged | GEODE |
|---|---|---|---|---|---|
| Help | `/help` | (popup) | `/help` `/commands` | **3/3** | **Y** `/help` |
| Diff of working changes | `/diff` | `/diff` | `/diff` | **3/3** | **—** |
| Plan mode | `/plan` `/ultraplan` | `/plan` | — | 2/3 | **—** |
| Code review | `/code-review` `/review` `/ultrareview` | `/review` | — | 2/3 | **~** `/audit` `/petri` (alignment audit, not code review) |
| Security review | `/security-review` | — | — | 1/3 | **—** |
| Doctor / install checkup | `/doctor` | — | `/debug` | 2/3 | **~** `geode doctor` CLI, no slash |
| Version / update | `/release-notes` | — | `/version` `/update` | 2/3 | **—** |
| Bug report / feedback | `/bug` `/feedback` | `/feedback` | `/debug` | **3/3** | **—** |
| Self-improvement loop control | — | — | — | 0/3 | **Y** `/self-improving` `/sil`, `/apply`, `/audit-seeds` |

---

## Reading the matrix

**Of the 30 capabilities all three frontier tools agree on, GEODE fully covers
11, partially covers 4, and is missing 15.** The agreement is strongest exactly
where GEODE is thinnest: session shape (fork / rename / stop / handoff), the
project-guide bootstrap, memory *writes*, the off-transcript side question, and
the `/permissions` + `/sandbox` safety pair — all 3/3 upstream, none present
here as a slash command.

**Four GEODE surfaces exist but are not reachable as slash commands** —
`geode config`, `geode doctor`, `geode session export`, and the
Google/workspace login live only as top-level CLI verbs. That is a
discoverability gap, not a capability gap, and it is the cheapest class to
close.

**`init` is a name collision, not a match.** `geode init` scaffolds a
`.geode/` directory with a template `config.toml`; the frontier `/init`
generates a *project guide* (`CLAUDE.md` / `AGENTS.md`) by scanning the repo.
Adding the frontier behaviour therefore needs a decision — extend `geode init`,
or introduce a separate command — and shipping it under the existing name
without that decision would repeat the `/recall` and `/cognitive` mismatch
called out above.

**One GEODE capability has no frontier counterpart**: the self-improving loop
control surface (`/self-improving`, `/apply`, `/audit-seeds`, `/petri`). No
convergence pressure applies to it; it should be judged on its own terms.

**Naming already matches where it matters.** `/model`, `/status`, `/cost`,
`/mcp`, `/skills`, `/compact`, `/context`, `/resume`, `/clear`, `/tasks`,
`/help`, `/login` all land on the frontier spelling. The two divergences worth
noting are `/recall` (frontier says `/memory`) and `/cognitive` (frontier says
`/insights`) — both currently name a *different* thing than the frontier
command they resemble, so a rename would be a semantic decision, not cosmetic.

**Convergence evidence, not coincidence.** Codex CLI ships `/import`
documented as importing setup and recent chats *from Claude Code*; Hermes
mirrors Claude Code's `/compact` under its own `/compress` with `/compact` kept
as an alias. The three tools are converging on each other deliberately, which
is what makes this matrix a usable roadmap rather than a survey.

## Candidate gaps, ordered by (frontier agreement × implementation cost)

| Rank | Gap | Frontier | Why it is cheap here |
|---|---|---|---|
| 1 | `/init` (project-guide sense) | 3/3 | GEODE already parses `PROJECT.md` / `AGENTS.md`, so the generator is short — but it collides with the existing `geode init` scaffolder, so name it deliberately |
| 2 | `/doctor`, `/config`, `/export` as slash | 2-3/3 | Verbs already exist; only `COMMAND_MAP` rows + a thin adapter are missing |
| 3 | `/diff` | 3/3 | Read-only `git diff` render; no new state |
| 4 | `/stop`, `/rename` | 3/3 | Session registry already tracks both id and lifecycle |
| 5 | `/btw` (side question) | 3/3 | Needs an ephemeral fork of `ConversationContext` — real work, high daily value |
| 6 | `/copy` (last response) | 3/3 | No transcript plumbing needed — renderer already holds the last response |
| 7 | `/permissions` | 3/3 | `tool_policy` + HITL levels exist; the gap is a UI over them |
| 8 | `/goal` | 3/3 | Overlaps the existing Plan surface; decide whether to fold or add |

Items 2-4 and 6 are mechanical. Items 1, 5, 7 and 8 each carry a design
decision (naming collision, ephemeral fork, policy UI, Plan overlap).
