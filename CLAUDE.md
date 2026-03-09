# GEODE — Undervalued IP Discovery Agent

## Project Overview

저평가 IP를 데이터 기반으로 발굴하는 LangGraph Agent CLI.

- **Version**: 0.6.0
- **Python**: >= 3.12
- **Package Manager**: uv
- **Entry Point**: `geode.cli:app` (Typer)
- **Modules**: 102
- **Tests**: 1541+

## Quick Start

```bash
# Install
uv sync

# Dry-run (no LLM, fixture only)
uv run geode analyze "Cowboy Bebop" --dry-run

# Full run (requires API keys in .env)
uv run geode analyze "Cowboy Bebop"

# Verbose
uv run geode analyze "Cowboy Bebop" --verbose

# Interactive REPL
uv run geode
```

## Architecture

6-Layer Architecture based on `architecture-v6.md` SOT.

```
L6: EXTENSIBILITY   — Custom Agents, Plugins, Reports
L5: AUTOMATION       — Triggers, Dispatch, Snapshot, CUSUM Drift, Predefined(10)
L4: ORCHESTRATION    — Planner, Plan Mode, Task System, Hooks(19), Bootstrap
L3: AGENTIC CORE     — StateGraph, Analysts×4, Evaluators×3, Feedback Loop(5-Phase)
L2: MEMORY           — Organization > Project > Session (3-Tier + Hybrid L1/L2)
L1: FOUNDATION       — MonoLake, LLM Clients, APIs, Skills, DI (Port/Adapter)
```

### Pipeline (LangGraph StateGraph)

```
START → router → signals → analyst×4 (Send API)
     → evaluator×3 → scoring → verification
     → [confidence ≥ 0.7?] → synthesizer → END
                            → gather (loopback to signals, max 5 iter)
```

### Key Design Decisions

- **Send API Clean Context**: Analysts receive state WITHOUT `analyses` to prevent anchoring
- **Decision Tree**: Cause classification is code-based, NOT LLM
- **D-axis Exclusion**: D excluded from recovery_potential (PSM covers same dimension)
- **graph.stream()**: Step-by-step progress tracking (not invoke)
- **Typed Evaluator Output**: Per-evaluator Pydantic models enforce required axes in structured output
- **Confidence Multiplier**: `final = base × (0.7 + 0.3 × confidence/100)`
- **Port/Adapter DI**: All infra accessed via Protocol ports + contextvars injection

## SOT (Source of Truth)

| Document | Path | Content |
|----------|------|---------|
| Architecture v6 | `docs/architecture-v6.md` | Full spec (335KB) |
| LangGraph Flow | `docs/langgraph-flow.md` | StateGraph topology |
| Layer Plan | `docs/layer-implementation-plan.md` | 6-layer roadmap |

## Project Structure

```
src/geode/
├── cli/                 # Typer CLI + NL router + search
├── config.py            # Pydantic Settings (.env)
├── state.py             # GeodeState TypedDict + Pydantic models
├── graph.py             # StateGraph build + compile
├── runtime.py           # GeodeRuntime — DI wiring + graph execution
├── nodes/
│   ├── router.py        # 6-mode routing + fixture loading + memory assembly
│   ├── signals.py       # External signals fixture
│   ├── analysts.py      # 4 Analysts (Send API, Clean Context)
│   ├── evaluators.py    # 3+1 Evaluators (14-axis rubric, typed output models)
│   ├── scoring.py       # PSM Engine + 6-weighted composite + Tier
│   └── synthesizer.py   # Decision Tree + Narrative
├── llm/
│   ├── client.py        # Anthropic Claude wrapper (retry, circuit breaker, failover)
│   ├── prompts.py       # All prompt templates (versioned SHA-256)
│   ├── prompt_assembler.py  # ADR-007 prompt assembly
│   ├── skill_registry.py   # Skill definition + registry
│   └── commentary.py       # LLM commentary generation
├── memory/
│   ├── organization.py  # Org tier — fixture-based, read-only
│   ├── project.py       # Project tier — .claude/MEMORY.md, rules, insights
│   ├── session.py       # Session tier — in-memory with TTL
│   ├── hybrid_session.py # L1(Redis) → L2(PostgreSQL) hybrid store
│   ├── session_key.py   # Hierarchical key builder (ip:name:phase)
│   └── context.py       # 3-tier context assembler
├── orchestration/
│   ├── hooks.py         # HookSystem (23 events)
│   ├── bootstrap.py     # Node bootstrap (pre-execution context injection)
│   ├── planner.py       # Planner (multi-step plan generation)
│   ├── plan_mode.py     # Plan mode state machine
│   ├── task_system.py   # Task tracking + dependency management
│   ├── task_bridge.py   # Task ↔ pipeline bridge
│   ├── coalescing.py    # Duplicate request coalescing
│   ├── lane_queue.py    # Priority lane queue
│   ├── hook_discovery.py # Auto-discovery of hook handlers
│   ├── hot_reload.py    # Hot reload support
│   ├── isolated_execution.py # Sandboxed execution
│   ├── run_log.py       # Run audit log
│   └── stuck_detection.py # Stuck pipeline detection
├── automation/
│   ├── triggers.py      # TriggerManager + unified dispatch
│   ├── predefined.py    # 10 predefined automation templates (§12.4)
│   ├── drift.py         # CUSUM drift detection
│   ├── snapshot.py      # Pipeline snapshot capture
│   ├── feedback_loop.py # 5-Phase RLHF cycle (incl. RLAIF)
│   ├── scheduler.py     # Cron-based scheduler
│   ├── nl_scheduler.py  # Natural language schedule parsing
│   ├── outcome_tracking.py # Outcome tracking + correlation
│   ├── correlation.py   # Statistical correlation analysis
│   ├── model_registry.py # Model version registry
│   ├── expert_panel.py  # Expert panel management
│   └── trigger_endpoint.py # HTTP trigger endpoint
├── verification/
│   ├── guardrails.py    # G1-G4 checks (schema, range, grounding, consistency)
│   ├── biasbuster.py    # 6 bias types (REAE framework)
│   ├── cross_llm.py     # Cross-LLM agreement + Krippendorff's α
│   └── rights_risk.py   # IP rights risk assessment
├── infrastructure/
│   ├── ports/           # Protocol interfaces (LLM, Memory, Auth, Hook, Tool, etc.)
│   └── adapters/llm/    # Claude + OpenAI adapters
├── tools/               # LLM-callable tools (memory, signal, analysis, output, data)
├── auth/                # API key rotation, cooldown, profiles
├── extensibility/       # Custom agents, plugins, report generators
├── fixtures/            # JSON test data (3 IPs) + data generator
└── ui/                  # Rich console, panels, streaming, status
```

## Development

```bash
# Test
uv run python -m pytest tests/ -q

# Lint
uv run ruff check src/geode/ tests/

# Type check
uv run mypy src/geode/
```

### Expected Test Results

1541+ tests pass. 3 IP fixtures produce tier spread:
- Berserk: **S** (82.2) — conversion_failure
- Cowboy Bebop: **A** (69.4) — undermarketed
- Ghost in the Shell: **B** (54.0) — discovery_failure

## Scoring Formula (§13.8.1)

```
Final = (0.25×PSM + 0.20×Quality + 0.18×Recovery + 0.12×Growth + 0.20×Momentum + 0.05×Dev)
        × (0.7 + 0.3 × Confidence/100)

Tier: S≥80, A≥60, B≥40, C<40
```

## Cause Classification (§13.9.2)

Decision Tree on D-E-F axes:
- D≥3, E≥3 → conversion_failure
- D≥3, E<3 → undermarketed
- D≤2, E≥3 → monetization_misfit
- D≤2, E≤2, F≥3 → niche_gem
- D≤2, E≤2, F≤2 → discovery_failure

## Quality Evaluation (5-Layer)

1. **Guardrails** G1-G4: Schema, Range, Grounding, 2σ Consistency
2. **BiasBuster**: 6 bias types (CV < 0.05 → anchoring flag)
3. **Cross-LLM**: Agreement ≥ 0.67, Krippendorff's α
4. **Confidence Gate**: ≥ 0.7 → proceed, else loopback (max 5 iter)
5. **Rights Risk**: CLEAR/NEGOTIABLE/RESTRICTED/EXPIRED/UNKNOWN

## Conventions

- **Structured Output**: Anthropic `messages.parse()` with typed Pydantic models
- **Legacy JSON fallback**: `call_llm_json()` with robust JSON extraction
- **Fixture vs Real**: External data = fixture, LLM calls = real Claude
- **Verbose gating**: Debug prints only with `--verbose` flag
- **Node contract**: Each node returns `dict` with only its output keys
- **Reducer fields**: `analyses` and `errors` use `Annotated[list, operator.add]`
- **Port/Adapter**: All infra via Protocol ports + contextvars DI
- **Hook-driven**: 19 lifecycle events for extensibility

## Custom Skills

Project-specific skills in `.claude/skills/`:

| Skill | Triggers | Content |
|-------|----------|---------|
| `geode-pipeline` | pipeline, graph, topology, send api | StateGraph patterns, node contracts |
| `geode-scoring` | score, psm, tier, rubric, formula | Scoring formulas, 14-axis rubric |
| `geode-analysis` | analyst, evaluator, clean context | Analyst/Evaluator patterns, prompts |
| `geode-verification` | guardrail, bias, cause, decision tree | G1-G4, BiasBuster, Decision Tree |
| `geode-gitflow` | branch, git, feature, release, hotfix | Gitflow strategy, commit convention |

## Linked Skills (from parent project)

| Skill | Use |
|-------|-----|
| `langgraph-pipeline` | LangGraph general patterns |
| `clean-architecture` | Port/Adapter, dependency rules |
| `prompt-engineering` | Prompt design best practices |
| `ip-evaluation` | IP evaluation methodology |
| `mermaid-diagrams` | Architecture diagram styling |
