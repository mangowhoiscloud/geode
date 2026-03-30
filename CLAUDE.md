# GEODE — General-Purpose Autonomous Execution Agent

## Project Overview

A general-purpose autonomous execution agent built on LangGraph. Autonomously performs research, analysis, automation, and scheduling.

- **Version**: 0.37.2
- **Python**: >= 3.12
- **Package Manager**: uv
- **Entry Point**: `geode.cli:app` (Typer)
- **Modules**: 190
- **Tests**: 3429+
- **CHANGELOG**: `CHANGELOG.md` (Keep a Changelog + SemVer)

## Quick Start

```bash
# Install
uv sync

# Thin CLI (auto-starts serve daemon if needed)
uv run geode

# Natural language CLI
uv run geode "summarize the latest AI research trends"
uv run geode "compare React vs Vue for a new project"
uv run geode "schedule daily standup reminder at 9am"

# Game IP Domain Plugin (dry-run, no LLM)
uv run geode analyze "Cowboy Bebop" --dry-run

# Game IP Domain Plugin (full run, requires API keys)
uv run geode analyze "Cowboy Bebop" --verbose
```

## Architecture

4-Layer Stack (Model → Runtime → Harness → Agent) + orthogonal Domain.

```
AGENT:    AgenticLoop (while tool_use), SubAgentManager, CLIPoller, Gateway
HARNESS:  SessionLane, LaneQueue(global:8), PolicyChain, TaskGraph, HookSystem(40 events)
RUNTIME:  ToolRegistry(52), MCP Catalog(44), Skills, Memory(4-Tier), Reports
MODEL:    ClaudeAdapter, OpenAIAdapter, GLMAdapter (3-provider fallback)
─────────────────────────────────────────────────────────────────
⊥ DOMAIN: DomainPort Protocol, GameIPDomain (cross-cutting, binds to Runtime + Harness via Port)
```

### Sub-Agent System

Sub-agents inherit parent tools/MCP/skills/memory and execute in parallel within independent contexts.
`SubAgentManager` → `TaskGraph`(DAG) → `IsolatedRunner`(gated by Lane("global", max=8)).
Controls: max_depth=1 (explicit depth guard + denied_tools), max_total=15, timeout=120s, auto_approve=True(STANDARD only), max_rounds=0 (unlimited), max_tokens=32768, time_budget_s=0 (same as parent, time-based control).
All execution paths: `SessionLane.acquire(key)` → `Lane("global").acquire(key)` → execute.

**Memory Isolation Rules:**
- Sub-agents inherit parent memory snapshots as read-only
- Sub-agent writes go to a task_id-scoped buffer (direct modification of shared memory is prohibited)
- Parent merges only the summary after task completion — two agents never write to shared memory simultaneously

### Domain Plugin System

Domain-specific analysis pipelines can be swapped as plugins via the `DomainPort` Protocol.

```
DomainPort (Protocol)
  ├── Identity: name, version, description
  ├── Analyst Config: get_analyst_types(), get_analyst_specific()
  ├── Evaluator Config: get_evaluator_types(), get_evaluator_axes(), get_valid_axes_map()
  ├── Scoring: get_scoring_weights(), get_tier_thresholds(), get_confidence_multiplier_params()
  ├── Classification: get_cause_values(), get_cause_to_action()
  └── Fixtures: list_fixtures(), get_fixture_path()
```

- **ContextVar Injection**: `set_domain()` / `get_domain()` — `contextvars`-based DI
- **Domain Loader**: `load_domain_adapter(name)` — dynamic import + registry
- **Default Domain**: `game_ip` → `core.domains.game_ip.adapter:GameIPDomain`
- **Extension Method**: Implement `DomainPort` Protocol after `register_domain(name, adapter_path)`

### Game IP Pipeline (Domain Plugin)

```
START → router → signals → analyst×4 (Send API)
     → evaluator×3 → scoring → verification
     → [confidence ≥ 0.7?] → synthesizer → END
                            → gather (loopback to signals, max 5 iter)
```

### Key Design Decisions

- **Sub-Agent Inheritance**: Children inherit all parent tools/MCP/skills/memory (P2-B)
- **Token Guard**: Mandatory preservation of `summary` field in SubAgentResult to prevent context explosion
- **Domain Plugin**: Pipelines can be swapped via DomainPort implementations (Game IP is a plugin)
- **Send API Clean Context**: Analysts receive state WITHOUT `analyses` to prevent anchoring
- **Decision Tree**: Cause classification is code-based, NOT LLM
- **graph.stream()**: Step-by-step progress tracking (not invoke)
- **Typed Evaluator Output**: Per-evaluator Pydantic models enforce required axes in structured output
- **Confidence Multiplier**: `final = base × (0.7 + 0.3 × confidence/100)`

### Gateway Runtime (Thin-Only Architecture)

```
geode (thin CLI) ──── Unix socket IPC ────→ geode serve (unified daemon)
                                              │
                                        GeodeRuntime (ONE)
                                         ├── SessionLane (per-key serial, max_sessions=256)
                                         ├── Lane("global", max=8)
                                         ├── CLIPoller   → SessionMode.IPC (hitl=0, DANGEROUS blocked)
                                         ├── Gateway     → SessionMode.DAEMON (hitl=0)
                                         └── Scheduler   → SessionMode.SCHEDULER (hitl=0, 300s cap)

All paths: acquire_all(session_key, ["session", "global"]) → create_session(mode) → execute
```

- **Thin-Only**: `geode` always connects to serve via IPC. Auto-starts serve if not running.
- **SessionMode.IPC**: hitl=0 (WRITE allowed, DANGEROUS policy-blocked). For thin CLI clients.
- **SessionLane**: Same session key → serial. Different keys → parallel. Idle cleanup at 300s.

## SOT (Source of Truth)

| Document | Path | Content |
|----------|------|---------|
| Architecture | `CLAUDE.md` § Architecture | 4-layer stack (Model→Runtime→Harness→Agent) |
| Hook System | `docs/architecture/hook-system.md` | HookSystem 40 events |
| CLAUDE.md | `CLAUDE.md` | Architecture overview + conventions (this file) |

## Project Structure

Code is organized in 4-layer stack under `core/`. Check module count with `find core/ -name "*.py" | wc -l`.
Key entry points: `core/cli/agentic_loop.py`(AgenticLoop), `core/graph.py`(StateGraph), `core/runtime.py`(bootstrap).

## Development

```bash
# Test
uv run python -m pytest tests/ -q

# Lint
uv run ruff check core/ tests/

# Type check
uv run mypy core/
```

### Expected Test Results

3429+ tests pass. 3 IP fixtures produce tier spread:
- Berserk: **S** (81.2) — conversion_failure
- Cowboy Bebop: **A** (68.4) — undermarketed
- Ghost in the Shell: **B** (51.7) — discovery_failure

## Domain Plugin: Game IP — Scoring & Classification

### Scoring Formula (§13.8.1)

```
Final = (0.25×PSM + 0.20×Quality + 0.18×Recovery + 0.12×Growth + 0.20×Momentum + 0.05×Dev)
        × (0.7 + 0.3 × Confidence/100)

Tier: S≥80, A≥60, B≥40, C<40
```

### Cause Classification (§13.9.2)

Decision Tree on D-E-F axes:
- D≥3, E≥3 → conversion_failure
- D≥3, E<3 → undermarketed
- D≤2, E≥3 → monetization_misfit
- D≤2, E≤2, F≥3 → niche_gem
- D≤2, E≤2, F≤2 → discovery_failure

### Quality Evaluation (5-Layer)

1. **Guardrails** G1-G4: Schema, Range, Grounding, 2σ Consistency
2. **BiasBuster**: 6 bias types (CV < 0.05 → anchoring flag)
3. **Cross-LLM**: Agreement ≥ 0.67, Krippendorff's α
4. **Confidence Gate**: ≥ 0.7 → proceed, else loopback (max 5 iter)
5. **Rights Risk**: CLEAR/NEGOTIABLE/RESTRICTED/EXPIRED/UNKNOWN

## LLM Models (verified 2026-03-24)

| Provider | Model | Input $/M | Output $/M | Context | Purpose |
|----------|-------|-----------|------------|---------|---------|
| **Anthropic** | `claude-opus-4-6` | $5.00 | $25.00 | 1M | Primary (Pipeline + Agentic) |
| Anthropic | `claude-sonnet-4-6` | $3.00 | $15.00 | 1M | Fallback |
| Anthropic | `claude-haiku-4-5-20251001` | $1.00 | $5.00 | 200K | Budget |
| **OpenAI** | `gpt-5.4` | $2.50 | $15.00 | 1M | Cross-LLM Secondary (default) |
| OpenAI | `gpt-5.2` | $1.75 | $14.00 | 128K | Fallback 1 |
| OpenAI | `gpt-4.1` | $2.00 | $8.00 | 1M | Fallback 2 |
| OpenAI | `gpt-4.1-mini` | $0.40 | $1.60 | 1M | Budget |
| **ZhipuAI** | `glm-5` | $0.72 | $2.30 | 200K | GLM Primary |
| ZhipuAI | `glm-5-turbo` | $0.96 | $3.20 | 200K | GLM Agent |
| ZhipuAI | `glm-4.7-flash` | Free | Free | 200K | GLM Budget |

- **Fallback chain** (Anthropic): `claude-opus-4-6` → `claude-sonnet-4-6`
- **Fallback chain** (OpenAI): `gpt-5.4` → `gpt-5.2` → `gpt-4.1`
- **Fallback chain** (GLM): `glm-5` → `glm-5-turbo` → `glm-4.7-flash`
- **Cache pricing** (Anthropic): creation = input × 1.25, read = input × 0.1
- **Deprecated** (removed): gpt-4o, gpt-4o-mini, o3-mini, claude-haiku-3-5

## Tool Routing (AgenticLoop Direct)

All free-text input goes directly to AgenticLoop. Claude sees all 47 tool definitions and autonomously selects via tool_use.

- `/command` -> commands.py slash command dispatch
- Free text -> AgenticLoop.run() (while tool_use loop)

Tool definitions are centrally managed in `core/tools/definitions.json` (47 tools).

**Tool Permission Levels** (spanning PolicyChain 6 layers):
- **STANDARD**: Read/analysis tools — eligible for Sub-Agent auto_approve
- **WRITE**: State-changing tools (memory_save, profile_update, manage_rule) — approval required
- **DANGEROUS**: System access tools (run_bash, delegate_task) — always requires HITL approval

### Claude Code-style UI (agentic_ui.py)

```
▸ analyze_ip(ip_name="Berserk")        # tool call
✓ analyze_ip → S · 81.2               # tool result
✗ analyze_ip — Not found              # error
✢ claude-opus-4-6 · ↓1.2k ↑350 · 2.1s  # token usage
● Plan: Berserk                        # plan steps
  1. Signal collection
  2. Multi-analyst evaluation
```

## Conventions

- **Structured Output**: Anthropic `messages.parse()` with typed Pydantic models
- **Legacy JSON fallback**: `call_llm_json()` with robust JSON extraction
- **Fixture vs Real**: External data = fixture, LLM calls = real Claude
- **Verbose gating**: Debug prints only with `--verbose` flag
- **Node contract**: Each node returns `dict` with only its output keys
- **Reducer fields**: `analyses` and `errors` use `Annotated[list, operator.add]`
- **Hook-driven**: `core.hooks` — 40 lifecycle events (incl. `SUBAGENT_*`, `TOOL_RECOVERY_*`, `CONTEXT_*`, `SESSION_*`, `TURN_COMPLETE`, `LLM_CALL_*`, `TOOL_APPROVAL_*`, `MODEL_SWITCHED`) for extensibility. Cross-cutting; accessible from all layers via `from core.hooks import HookSystem, HookEvent`.
- **Domain Plugin**: `DomainPort` Protocol — per-domain pipeline swappable (`set_domain()` / `get_domain()`). Non-domain infrastructure uses direct imports (minimizing ContextVar DI).
- **LLM-consumed content in English**: All files injected into LLM context (system prompts, tool definitions, skill metadata, memory, rules) must be written in English. Korean trigger keywords may be retained for bilingual input matching. This improves LLM routing accuracy and tool selection reliability.

## Implementation Workflow

> **Design Principle**: CANNOT (guardrails) comes before CAN (freedom). Constraints guarantee quality. (Karpathy P1, OpenClaw Policy Chain, Codex Sandbox)

### CANNOT — Absolute Prohibition Rules

These cannot be violated at any stage. Violations must be immediately halted and corrected.

| Area | Rule | Rationale |
|------|------|-----------|
| **Git** | No code work without a worktree | Isolated execution (OpenClaw Session) |
| | No direct push to main/develop — PR → CI → merge | Ratchet (P4) |
| | No deleting other sessions' worktrees (`.owner` mismatch) | Ownership protection |
| | No `git checkout` switching within a worktree | Isolation maintenance |
| | No modifying `docs/progress.md` from feature/develop | Single source of truth on main |
| | No branch creation when remote is out of sync | Conflict prevention |
| **Planning** | No starting implementation without Socratic Gate (except bugs/docs) | Prevent over-engineering |
| **Quality** | No committing with lint/type/test failures | Ratchet (P4) |
| | No placeholders (XXXX) in metrics — measured values only | Truth guarantee |
| | No excessive `# type: ignore` — fix type errors instead | Correctness |
| | No unauthorized live test (`-m live`) execution | Cost control (P3) |
| **Docs** | No omitting CHANGELOG from code commits | Traceability |
| | No leaving `[Unreleased]` on main | Release discipline |
| | No version mismatch across 4 locations | Single source of truth |
| **PR** | No PR body without HEREDOC | Format consistency |
| | No PR without a "Why" rationale | Decision record |
| | No merging PRs that haven't passed CI guardrails | Ratchet (P4) |

### Refactoring Deception Prevention

| Item | Rule |
|------|------|
| **Partial implementation disguise** | No marking plan items complete when only partially implemented |
| **Stub disguise** | No claiming extraction is complete with empty modules (`pass` only) |
| **Original residue** | No marking "extraction complete" while code remains in the original (re-export only is allowed) |
| **Zero-context verification** | Independent agent cross-checks plan document + diff → confirms all items implemented → FAIL on any omission |

### CAN — Permitted Freedoms

Anything not in CANNOT is freely permitted. Specifically:

| Freedom | Description |
|---------|-------------|
| Simple bug/doc fixes | Skip Plan, implement directly in worktree |
| Discovering improvements not in plan | Handle in next iteration after completing current work |
| Selective test execution | Run only tests relevant to changes first, full suite at the end |
| Commit message language | Korean/English freely (maintain consistency only) |
| Tool selection | Freely choose faster tool if results are equivalent |

### Failure Modes

| Scenario | Detection | Action |
|----------|-----------|--------|
| Network down | `git fetch` failure | Halt work, report to user |
| Missing `.owner` file | worktree stat failure | Refuse execution — isolation violation |
| CI 30+ minute timeout | `gh pr checks` unresponsive | Cancel job, diagnose tests, then escalate |
| Corrupted memory file | Parsing errors like `tier=?`, `score=0.00` | Delete affected record and re-run |
| Confidence below threshold (5 retries) | loopback max 5 reached, confidence < 0.7 | Escalate to user — no autonomous override |
| All LLM providers down | 3-provider fallback chain exhausted | Degraded Response (is_degraded=True + defaults) — no pipeline interruption |
| MCP server spawn failure | subprocess timeout | Continue without that MCP (Graceful Degradation) |

### Gateway Thread Propagation

The `geode serve` Gateway poller runs in a daemon thread. Daemon threads do not inherit the parent's `set_domain()` context.
Solution: Call `boot.propagate_to_thread()` at each Gateway handler entry to re-inject the domain context.
Without this call: `get_domain()` → None → AgenticLoop crash.

### Workflow Steps

```
0. Board + Worktree → 1. GAP Audit → 2. Plan + Socratic Gate → 3. Implement+Test → 4. E2E Verify → 5. Docs-Sync → 6. PR → 7. Rebuild → 8. Board
```

#### 0. Board + Worktree Alloc

```bash
# 1) Record Backlog → In Progress on Progress Board (from main)
# Add/move work items in docs/progress.md

# 2) Allocate Worktree
git fetch origin
# Verify main/develop sync (pull if out of sync)
git worktree add .claude/worktrees/<task-name> -b feature/<branch-name> develop
echo "session=$(date -Iseconds) task_id=<task-name>" > .claude/worktrees/<task-name>/.owner
```

Record on Progress Board then allocate Worktree. On completion: `git push` → `git worktree remove`

#### 1. GAP Audit

> Before implementing, verify "is this actually needed?" through code inspection. Never rebuild what already exists.

**Process**:
1. List TO-BE items from plan documents (`docs/plans/`)
2. For each item, use `grep`/`Explore` to **verify whether it already exists in code**
3. Classify into 3 categories:

| Classification | Criteria | Action |
|----------------|----------|--------|
| **Fully Implemented** | Exists in code + tests pass | Remove from plan, move to `_done/` |
| **Partially Implemented** | Code exists but integration/tests incomplete | Implement remaining parts only |
| **Not Implemented** | Does not exist in code | Implementation target |

**Output**: GAP classification table (implemented/partial/not-implemented per plan item)

#### 2. Plan + Socratic Gate

> Simple bug/doc fixes may skip this. All other implementation requires the Socratic Gate.

**Socratic 5 Questions — for each plan item:**

| # | Question | On Failure |
|---|----------|------------|
| Q1 | **Does it already exist in code?** (`grep`/`Explore` verification) | → Remove |
| Q2 | **What breaks if we don't do this?** (actual failure scenario) | No answer → Remove |
| Q3 | **How do we measure the effect?** (tests, metrics, dry-run) | Cannot measure → Defer |
| Q4 | **What is the simplest implementation?** (P10 Simplicity Selection) | Adopt minimum changes only |
| Q5 | **Is this the same pattern across 3+ frontier systems?** (Claude Code, Codex CLI, OpenClaw, autoresearch) | Only 1 → Re-verify necessity |

**Process**:
1. Extract only "Not Implemented" items from GAP Audit results
2. Apply Socratic 5 Questions → only passing items become implementation targets
3. Frontier research (`frontier-harness-research` skill)
4. Write plan document (`docs/plans/`) → user approval
5. Register task via `TaskCreate`

#### 3. Implement → Unit Verify (iterate)

Code changes → repeat 3 quality gates. Fix on failure.

```bash
uv run ruff check core/ tests/      # Lint: 0 errors
uv run mypy core/                    # Type: 0 errors
uv run pytest tests/ -m "not live"   # Test: 3429+ pass
```

#### 4. E2E Verify

See `geode-e2e` skill.

```bash
uv run geode analyze "Cowboy Bebop" --dry-run  # Verify A (68.4) unchanged
```

5-persona verification team review: see `verification-team` + `anti-deception-checklist` skills (for large-scale changes).

**5-Persona Verification Team:**
1. **Kent Beck** — Design quality, test coverage, dead code, simplicity (XP/TDD)
2. **Andrej Karpathy** — Constraints, ratchets, context budget, time budgets (autoresearch)
3. **Peter Steinberger** — Session isolation, Lane Queue, lifecycle, plugin architecture (OpenClaw)
4. **Boris Cherny** — Tool safety (HITL), sub-agent isolation, permission model (Claude Code)
5. **Anti-Deception Checklist** — Fake success detection: test deletion, lint bypass, coverage regression, stub disguise, secret exposure

#### 5. Docs-Sync

See `geode-changelog` skill.

**Pre-write**: Sync CHANGELOG `[Unreleased]` + ABOUT across 4 locations + update measured values.
**Post-verify**: Re-verify measured values, fix on mismatch.

| Sync Target | Verification |
|-------------|--------------|
| Version across 4 locations | CHANGELOG, CLAUDE.md, README.md, pyproject.toml |
| Metrics | Tests, Modules, Commands — measured values |

**Versioning**: New feature = MINOR, Bug fix = PATCH, Docs only = none.

#### 6. PR & Merge

See `geode-gitflow` skill. feature → develop → main. HEREDOC PR. CI 5/5 required.

| Change | Cascading Updates |
|--------|-------------------|
| New tool | `definitions.json` + handlers + E2E |
| Pipeline node | `graph.py` + E2E |
| LLM adapter | `client.py` + E2E |

#### 7. Rebuild & Restart

After merging to main, rebuild CLI and serve to update the runtime to the latest code.

```bash
# 1) Stop geode serve
kill $(ps aux | grep "geode serve" | grep -v grep | awk '{print $2}')

# 2) Reinstall CLI as editable + sync dependencies
uv tool install -e . --force
uv sync

# 3) Verify version + restart serve
geode version          # Confirm version match
geode serve &          # Restart in background
```

#### 8. Progress Board

Update `docs/progress.md` only from main. Backlog → In Progress → Done.

### Quality Gates

| Gate | Command | Criteria |
|------|---------|----------|
| Lint | `uv run ruff check core/ tests/` | 0 errors |
| Type | `uv run mypy core/` | 0 errors |
| Test | `uv run pytest tests/ -m "not live"` | 3429+ pass |
| E2E | `uv run geode analyze "Cowboy Bebop" --dry-run` | A (68.4) |

## Custom Skills (Scaffold)

Skills used by Scaffold during GEODE development (`.claude/skills/`). Separate from GEODE runtime's `core/skills/` SkillRegistry.

| Skill | Triggers | Content |
|-------|----------|---------|
| `geode-pipeline` | pipeline, graph, topology, send api | StateGraph patterns, node contracts |
| `geode-scoring` | score, psm, tier, rubric, formula | Scoring formulas, 14-axis rubric |
| `geode-analysis` | analyst, evaluator, clean context | Analyst/Evaluator patterns, prompts |
| `geode-verification` | guardrail, bias, cause, decision tree | G1-G4, BiasBuster, Decision Tree |
| `geode-e2e` | e2e, live test, verification, langsmith, tracing | Live E2E patterns, LangSmith verification, quality checks |
| `geode-gitflow` | branch, git, pr, merge, commit | Gitflow strategy, PR templates, CI fix loops |
| `geode-changelog` | changelog, release, version, release | CHANGELOG management, SemVer versioning |
| `karpathy-patterns` | autoresearch, agenthub, ratchet, context budget | 10 autonomous agent design principles (P1-P10) |
| `openclaw-patterns` | gateway, session, binding, lane, plugin | Agent system design patterns (OpenClaw) |
| `frontier-harness-research` | research, gap, frontier, harness, case study | Frontier harness 4-system comparative research process |
| `verification-team` | verification, review, verify, inspect | 5-persona verification (Beck/Karpathy/Steinberger/Cherny + Anti-Deception) |
| `tech-blog-writer` | blog, posting, tech blog | Technical blog writing guide |
| `explore-reason-act` | explore, reason, root cause, read before write | 3-phase explore-reason-act before code modification (REODE backport) |
| `anti-deception-checklist` | deception, fake success, regression | Fake success prevention verification checklist (REODE backport) |
| `code-review-quality` | quality, SOLID, dead code, resource leak | Python code quality 6-lens review (REODE backport) |
| `dependency-review` | dependency, import, layer, circular, lazy | 6-Layer dependency health review (REODE backport) |
| `kent-beck-review` | kent beck, simple design, simplify, god object, SRP | Simple Design 4-rule code review (REODE backport) |
| `codebase-audit` | audit, dead code, refactor, god object, duplication | Code audit + refactoring workflow (v0.24.0 proven) |
| `geode-serve` | serve, gateway, slack, binding, poller, config.toml | Slack Gateway operations + debugging guide |

## Linked Skills (from parent project)

| Skill | Use |
|-------|-----|
| `langgraph-pipeline` | LangGraph general patterns |
| `prompt-engineering` | Prompt design best practices |
| `ip-evaluation` | IP evaluation methodology |
| `mermaid-diagrams` | Architecture diagram styling |
