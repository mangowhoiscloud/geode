# Storage Hierarchy — root vs project decision

Where does each piece of GEODE state live, and why? This document captures
the **decision rules** synthesized from three frontier harnesses (Claude
Code, Hermes Agent by NousResearch, OpenClaw) and applied to GEODE's
two-tier layout (`~/.geode/` + `{workspace}/.geode/`).

The decision drives both writers (where new data lands) and the
migration runner at `core/wiring/layout_migrator.py` (where legacy data
gets moved on the next boot).

## Three frontier patterns

| Harness | Policy | Reference |
|---------|--------|-----------|
| **Claude Code** | Dual — `~/.claude/` for user-private state (sessions, auto memory keyed by project hash) + `.claude/` for team-shareable items (`settings.json`, `CLAUDE.md`, `skills/`, `hooks/`). 5-source priority: policy > flag > local > project > user. | `claude-code/src/config/settings.ts:1-26`, `claude-code/src/session/manager.ts:11-48`, `claude-code/src/core/system-prompt.ts:36-97` |
| **Hermes Agent** | Single — `~/.hermes/` only. Project-local rejected. Profiles (`~/.hermes/profiles/<name>/`) replace per-project isolation. Justified by: cross-platform messaging (Telegram / Discord / Slack have no cwd notion), cron jobs that aren't bound to a project, project move/delete safety. | `hermes-agent/hermes_cli/profiles.py:1-9, 35-50`, `hermes-agent/hermes_constants.py:14-68, 165-188` |
| **OpenClaw** | Single — `~/.openclaw/agents/<agentId>/`. Gateway-centric. 4-level session keys (`agent:<id>:<scope>:<rest>`) handle isolation as routing concern, not directory nesting. | `openclaw/src/config/paths.ts:60-89`, `openclaw/src/infra/state-migrations.ts:517-661`, `openclaw/src/routing/session-key.ts` |

**Frontier consensus** — 2 of 3 reject project-local entirely. The one that
keeps it (Claude Code) uses project-local only for **explicitly
team-shareable items intended to be committed to git**.

## GEODE's hybrid

GEODE is closer to Claude Code than Hermes/OpenClaw because:

- It is a **per-workspace agent runtime** — the IP analysis plugin, the
  scheduler, the `CLAUDE.md` scaffold are all bound to a specific
  project tree.
- A workspace can be cloned, archived, or moved — project-local state
  that follows the workspace is sometimes the correct mental model
  (e.g., a project-specific cron schedule, project-specific rules).
- But many concerns (session transcripts, snapshots, result caches,
  embedding caches) are user-private and should not pollute the
  workspace.

The split is therefore deliberate, not accidental.

## Decision rules

| Question | Answer | Tier |
|----------|--------|------|
| Is it a credential / OAuth token? | yes | `~/.geode/auth.toml` |
| Is it cross-project user identity (career, preferences, learned memory)? | yes | `~/.geode/identity/`, `~/.geode/user_profile/` |
| Is it agent operating state (LLM usage, session transcript, diagnostics)? | yes | `~/.geode/` top-level (`usage/`, `diagnostics/`, `approval_history.jsonl`) |
| Is it project-bound but user-private (per-project session, snapshot, cache)? | yes | `~/.geode/projects/<encoded-cwd>/` (Claude Code parity) |
| Is it project-bound + meant to be committed / team-shareable? | yes | `{workspace}/.geode/` (rules, skills, custom config) |
| Is it project-bound + user-generated output? | yes | `{workspace}/.geode/reports/` |
| Is it a project-scoped scheduled job? | yes | `{workspace}/.geode/scheduled_tasks.json` (the schedule travels with the workspace) |

## Concrete GEODE layout (current — verified correct)

```
~/.geode/                                  user-private state
├── auth.toml                              # credentials + plans + routing
├── config.toml                            # global config overrides
├── cli.sock                               # thin-CLI ↔ serve IPC
├── .env                                   # secrets
├── .layout-version                        # migration marker (v0.95.x+)
│
├── identity/career.toml                   # cross-project user identity
├── user_profile/{learned,preferences,profile}.md
├── skills/                                # personal skills (user-tier)
│
├── usage/<YYYY-MM>.jsonl                  # LLM cost time-series
├── diagnostics/<YYYY-MM>.log              # fa4 cross-process append-only
├── approval_history.jsonl                 # HITL audit
├── logs/serve.log                         # serve daemon log
│
├── mcp/                                   # MCP state (registry cache + traces)
│   ├── registry-cache.json
│   └── <server>/trace-runs/run-<id>/
├── petri/logs/*.eval                      # Petri evaluation raw
│
├── projects/<encoded-cwd>/                # per-project user-private state
│   ├── journal/{runs,errors}.jsonl        # execution journal
│   ├── sessions/                          # session transcripts
│   ├── snapshots/snap-*.json              # langgraph checkpoints
│   └── result_cache/                      # tool result memoization
│
├── runs/geode-<hash>.jsonl                # per-run log (TODO: bucket by YYYY-MM)
├── workers/<task>.{result.json,stderr.log} # delegate worker output
├── scheduler/                             # legacy global scheduler (predates project-local)
├── vault/{general,research}/              # accumulated agent outputs (TTL TODO)
│
└── models/                                # reserved (empty)


{workspace}/.geode/                        project-bound, potentially team-shareable
├── config.toml                            # project-level config overrides
├── memory/PROJECT.md                      # project insights (`G4` tier in system prompt)
├── rules/*.md                             # project rules (loaded by tag)
├── skills/                                # project-specific skills
├── reports/                               # generated reports (user output)
├── scheduled_tasks.json + .lock           # project-scoped cron jobs
└── scheduler_logs/                        # scheduler run history
```

## Migration policy

Migrations live in `core/wiring/layout_migrator.py` and run at every
bootstrap via `core.paths.ensure_directories()` (idempotent — module-level
once-flag, dotfile marker `~/.geode/.layout-version`).

| Version | Step | Status |
|---------|------|--------|
| v0 → v1 | Path reconciliation — `serve.log`, `approve_history.json`, `mcp-registry-cache.json` to canonical locations | done |
| v1 → v2 | Vestigial constant cleanup — `PROJECT_EMBEDDING_CACHE` has no writer; remove if confirmed unused after one release window | this PR (marker bump only) |
| v2 → v3 | TBD — bucket `~/.geode/runs/geode-*.jsonl` by `<YYYY-MM>/` (currently flat at 600+ files) | backlog |
| v3 → v4 | TBD — vault TTL policy (`~/.geode/vault/{general,research}/` currently 1800+ flat files) | backlog |

Pattern for adding a new migration (mirrors Hermes
`SessionDB._init_schema` at `hermes-agent/hermes_state.py:550-678`):

1. Bump `GEODE_LAYOUT_VERSION`.
2. Append a step to `_run_pending_migrations` under
   `if current_version < N:`.
3. Each step must be **idempotent** (safe to re-run partially) and
   **lossless** (no file ever disappears mid-move).
4. Conflicts (both source and destination present) → leave source in
   place + warn; never overwrite user data.

## Reference

- `core/paths.py` — current path constants
- `core/wiring/layout_migrator.py` — migration runner (v0.95.x+)
- `core/memory/project.py` — project memory cascade (project → global)
- `core/cli/cmd_lifecycle.py` — `/clean` / `/uninstall` consumers (must
  honour the same tier rules)
