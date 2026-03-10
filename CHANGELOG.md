# Changelog

All notable changes to the GEODE project will be documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Scope Rules

**What to record**:
- New features (Added) — user-facing capabilities, new modules, new tools
- Breaking changes (Changed) — API changes, renamed modules, behavior shifts
- Bug fixes (Fixed) — corrected behavior, edge case handling
- Removals (Removed) — deleted modules, deprecated features
- Infrastructure (Infrastructure) — CI, build, dependency changes
- Architecture (Architecture) — structural decisions that affect future development

**What NOT to record**:
- Internal refactors that don't change behavior (unless architecturally significant)
- Code quality passes (R1→R8 rounds) — summarize as one entry
- Merge commits, branch operations
- Documentation-only changes (blogs, README updates)
- Commit-level granularity — aggregate by feature area

**Granularity**: Feature-level, not commit-level. One entry per logical change.

---

## [Unreleased]

---

## [0.7.0] — 2026-03-10

### Added
- `AgenticLoop` — `while(tool_use)` multi-round execution loop (max 10 rounds)
- `ConversationContext` — sliding-window multi-turn history (max 20 turns)
- `ToolExecutor` — tool dispatch with HITL safety gate (SAFE/STANDARD/DANGEROUS classification)
- `BashTool` — shell command execution with 9 blocked dangerous patterns + user approval
- `SubAgentManager` — parallel task delegation via `IsolatedRunner` (MAX_CONCURRENT=5)
- `delegate_task` tool — LLM-callable parallel sub-task execution
- Multi-intent support: sequential tool chaining by LLM decision
- Multi-turn context: pronoun resolution, follow-up queries
- `.pre-commit-config.yaml` — ruff lint/format, mypy, bandit, standard hooks (local hooks via `uv run`)

### Changed
- **Package rename**: `src/geode/` → `core/` (315 files removed, all imports updated)
- NL Router system prompt updated for multi-tool sequential calling
- Prompt templates migrated from Python strings (`prompts.py`) to `.md` template files
- Prompt structured data (axes, rubrics) separated into `core/llm/prompts/axes.py`
- `core/llm/prompts/` package with `load_prompt()` API and backward-compatible exports
- Tool definitions centralized to `core/tools/definitions.json` (19 tools)
- Tool parameter schemas externalized to `core/tools/tool_schemas.json` (11 schemas)
- NL Router, AgenticLoop, BashTool, SubAgent load tools from JSON
- Cross-LLM verification prompts extracted to `cross_llm.md` template
- Report templates extracted to `core/extensibility/templates/` (HTML + 2 Markdown)
- Analyst/Synthesizer tool-augmented suffixes extracted to `tool_augmented.md`
- Domain data externalized: `evaluator_axes.yaml` (20 axes + rubric anchors), `cause_actions.yaml` (6 cause/action mappings)
- Constants centralized to `pydantic-settings`: `router_model`, `agreement_threshold`, `primary_analysts`, `secondary_analysts`
- `VALID_AXES_MAP` derived from canonical YAML (SSOT, eliminates duplication in `state.py`)
- `EVALUATOR_TYPES` derived from `EVALUATOR_AXES.keys()` (no hardcoded list)
- Test count: 1823 → 1879 (85 test files updated for `core` imports)

### Architecture
- Prompt management: `.md` templates + Python loader (content/code separation)
- 8 prompt templates: `analyst.md`, `evaluator.md`, `synthesizer.md`, `biasbuster.md`, `commentary.md`, `router.md`, `cross_llm.md`, `tool_augmented.md`
- Tool definitions: single JSON source (`definitions.json`) with per-module filtering
- Report templates: external files with `string.Template` rendering
- Domain config layer: `core/config/` directory for YAML-based domain data

### Infrastructure
- CI: `--cov=geode` → `--cov=core` coverage target
- Bandit: `# nosec B404/B602` for intentional subprocess in `bash_tool.py`
- Fixture EOF: 201 JSON files fixed (missing trailing newline)
- Pre-commit: `pre-commit` added as dev dependency

---

## [0.6.0] — 2026-03-10

Initial release of GEODE — Undervalued IP Discovery Agent.
56 commits across 5 development phases.

### Added

#### Core Pipeline (LangGraph StateGraph)
- 7-node pipeline: `router → signals → analyst×4 → evaluator×3 → scoring → verification → synthesizer`
- LangGraph `Send()` API for parallel analyst/evaluator fan-out
- `GeodeState` (TypedDict) with Pydantic validation models
- `GeodeRuntime` — production wiring with dependency injection
- Streaming mode (`_execute_pipeline_streaming`) — progressive panel rendering

#### Analysis Engine
- 4 Analysts: `game_mechanics`, `player_experience`, `growth_potential`, `discovery`
- Clean Context anchoring prevention (no cross-analyst contamination)
- 3 Evaluators: `quality_judge`, `hidden_value`, `community_momentum`
- 14-Axis Rubric Scoring (PSM Engine)
- 6-weighted composite score × confidence multiplier → Tier S/A/B/C classification

#### Verification Layer
- Guardrails G1–G4 (score bounds, consistency, genre-fit, data quality)
- BiasBuster — 6-bias detection (anchoring, genre, recency, popularity, cultural, survivorship)
- Cross-LLM validation (agreement threshold ≥ 0.67)
- Rights Risk assessment (GAP-5)
- Cause Classification Decision Tree

#### CLI (Typer + Rich)
- Interactive REPL with dual routing: `/command` (deterministic) + free-text (NL Router)
- 16+ slash commands: `/analyze`, `/compare`, `/search`, `/batch`, `/report`, `/model`, `/status`, etc.
- NL Router — Claude Opus 4.6 Tool Use (12 tools, autonomous routing)
- 3-stage graceful degradation: LLM Tool Use → offline pattern matching → help fallback
- IP search engine with keyword/genre matching
- Report generation (HTML, JSON, Markdown × Summary/Detailed/Executive templates)
- Batch analysis with parallel execution and ranking table

#### Agentic Loop (v0.6.0-latest)
- `AgenticLoop` — `while(tool_use)` multi-round execution (max 10 rounds)
- `ConversationContext` — sliding-window multi-turn history (max 20 turns)
- `ToolExecutor` — 17 tool handlers with HITL safety gate
- `BashTool` — shell execution with 9 blocked dangerous patterns + user approval
- `SubAgentManager` — parallel task delegation via `IsolatedRunner` (MAX_CONCURRENT=5)
- Multi-intent support: sequential tool chaining by LLM decision
- Multi-turn context: pronoun resolution, follow-up queries

#### Memory System (3-Tier)
- Organization Memory (fixtures, immutable)
- Project Memory (`.claude/MEMORY.md`, persistent insights + rules)
- Session Memory (in-memory TTL, conversation context)
- Auto-learning loop: `PIPELINE_END` → insight write-back to `MEMORY.md`
- Rule CRUD: create/update/delete/list analysis rules

#### Infrastructure (Hexagonal Architecture)
- `LLMClientPort` / `ClaudeAdapter` / `OpenAIAdapter` — multi-provider LLM
- `SignalEnrichmentPort` — market signal adapters
- Prompt caching (Anthropic cache_control)
- Ensemble mode: single / cross-LLM
- MCP Server (FastMCP: 6 tools, 2 resources)
- Auth profile management

#### Orchestration
- `HookSystem` — 23 lifecycle events (pipeline, node, analysis, verification, memory, prompt)
- `IsolatedRunner` — concurrent execution with timeout + semaphore (MAX_CONCURRENT=5)
- `TaskGraph` — DAG-based task dependency tracking
- `StuckDetector` — pipeline deadlock detection via hooks
- `LaneQueue` — concurrency control lanes
- `RunLog` — structured execution logging
- `PlanMode` — DRAFT → APPROVED → EXECUTING workflow

#### Tools & Policies
- `ToolRegistry` — 24 registered tools with lazy loading
- `PolicyChain` — composable tool access policies
- `NodeScopePolicy` — per-node tool allowlists
- Tool-augmented analyst paths with node-level retry

#### Automation (L4.5)
- Drift detection and monitoring
- Model registry with promotion lifecycle
- Confidence gating (feedback loop)
- Snapshot capture for reproducibility
- Trigger system (event-driven + cron-based)

### Fixed
- Scoring confidence calculation — empty/single/zero-mean edge cases (`7591445`)
- Evaluator fallback defaults `1.0 → 3.0` neutral + CLI type safety (`76e4e30`)
- Session ID wiring into pipeline initial state — GAP-001 (`e8fbcfe`)
- Billing error detection with user-friendly message (`d878078`)
- Memory 6 issues from 3-agent quality audit (`4430fd4`)
- API key availability → dry-run mode decision logic (`eeec586`, `8ea0555`)
- CI: bandit false positives, ruff format, mypy errors across 3 fix cycles

### Architecture
- Clean Architecture (Hexagonal) — ports/adapters separation
- 6-Layer hierarchy: Foundation → Memory → Agentic Core → Orchestration → Automation → Extensibility
- `src/` layout migration (`bf2bc24`)
- OpenClaw-inspired patterns: Gateway, Session Key, Binding Router, Lane Queue

### Infrastructure
- CI: 5-job pipeline (lint, typecheck, test matrix 3.12/3.13, security, gate)
- Strict `mypy` type checking (zero errors)
- `ruff` linting with S-series security rules
- `bandit` security scanning
- 1,879 tests across 115 modules
- 8 Claude skills + 4 analyst sub-skills
- LangSmith tracing (conditional, via `_maybe_traceable`)

---

## Version History

| Version | Date | Highlights |
|---------|------|------------|
| 0.7.0 | 2026-03-10 | Agentic loop, HITL bash, prompt/data externalization, package rename, pre-commit |
| 0.6.0 | 2026-03-10 | Initial release — full pipeline, 3-tier memory, 1823 tests |

<!-- Links -->
[Unreleased]: https://github.com/mangowhoiscloud/geode/compare/v0.7.0...HEAD
[0.7.0]: https://github.com/mangowhoiscloud/geode/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/mangowhoiscloud/geode/releases/tag/v0.6.0
