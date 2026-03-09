# GEODE — Undervalued IP Discovery Agent

## Project Overview

저평가 IP를 데이터 기반으로 발굴하는 LangGraph Agent CLI 데모.

- **Version**: 6.0.0
- **Python**: >= 3.12
- **Package Manager**: uv
- **Entry Point**: `geode.cli:app` (Typer)

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
L5: EXTENSIBILITY — Custom Agents, Plugins, Reports
L4.5: AUTOMATION — Trigger Manager, Snapshot
L4: ORCHESTRATION — Planner, Plan Mode, Task System, Hooks
L3: AGENTIC CORE — Agent Loop, Analysts×4, Evaluators×3
L2: MEMORY — Organization > Project > Session
L1: FOUNDATION — MonoLake, LLM Clients, APIs, Skills
```

### Pipeline (LangGraph StateGraph)

```
START → router → cortex → signals → analyst×4 (Send API)
     → evaluators → scoring → verification → synthesizer → END
```

### Key Design Decisions

- **Send API Clean Context**: Analysts receive state WITHOUT `analyses` to prevent anchoring
- **Decision Tree**: Cause classification is code-based, NOT LLM
- **D-axis Exclusion**: D excluded from recovery_potential (PSM covers same dimension)
- **graph.stream()**: Step-by-step progress tracking (not invoke)

## SOT (Source of Truth)

| Document | Path | Content |
|----------|------|---------|
| Architecture v6 | `../ppt-workspace/task2/docs/architecture-v6.md` | Full spec, scoring formulas, rubric |
| LangGraph Flow | `../ppt-workspace/task2/docs/langgraph-flow.md` | StateGraph topology |
| FINAL-SLIDES | `../ppt-workspace/task2/slides/FINAL-SLIDES.md` | 3-slide story, expected outputs |
| Layer Plan | `docs/layer-implementation-plan.md` | 6-layer implementation roadmap |

## Project Structure

```
geode/
├── cli.py              # Typer CLI + interactive REPL
├── config.py            # Pydantic Settings (.env)
├── state.py             # GeodeState TypedDict + Pydantic models + Ports
├── graph.py             # StateGraph build + compile
├── nodes/
│   ├── router.py        # 6-mode routing
│   ├── cortex.py        # MonoLake fixture loader
│   ├── signals.py       # External signals fixture
│   ├── analysts.py      # 4 Analysts (Send API, Clean Context)
│   ├── evaluators.py    # 3 Evaluators (14-axis rubric)
│   ├── scoring.py       # PSM Engine + Final Score + Tier
│   └── synthesizer.py   # Decision Tree + Narrative
├── llm/
│   ├── client.py        # Anthropic Claude wrapper
│   └── prompts.py       # All prompt templates
├── verification/
│   ├── guardrails.py    # G1-G4 checks
│   ├── biasbuster.py    # Bias detection
│   └── cross_llm.py     # Cross-LLM (placeholder)
├── fixtures/            # JSON test data (3 IPs)
│   ├── cowboy_bebop.json
│   ├── berserk.json
│   └── ghost_in_shell.json
└── ui/
    ├── console.py       # Rich console
    ├── panels.py        # Rich panels
    └── streaming.py     # LLM streaming
```

## Development

```bash
# Test
uv run python -m pytest tests/ -q

# Lint
uv run ruff check geode/ tests/

# Type check
uv run mypy geode/
```

### Expected Test Results

98 tests pass. 3 IP fixtures produce tier spread:
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

## Conventions

- **Structured Output**: All LLM calls return JSON validated by Pydantic
- **Fixture vs Real**: External data = fixture, LLM calls = real Claude Opus
- **Verbose gating**: Debug prints only with `--verbose` flag
- **Node contract**: Each node returns `dict` with only its output keys
- **Reducer fields**: `analyses` and `errors` use `Annotated[list, operator.add]`

## Custom Skills

Project-specific skills in `.claude/skills/`:

| Skill | Triggers | Content |
|-------|----------|---------|
| `geode-pipeline` | pipeline, graph, topology, send api | StateGraph patterns, node contracts |
| `geode-scoring` | score, psm, tier, rubric, formula | Scoring formulas, 14-axis rubric |
| `geode-analysis` | analyst, evaluator, clean context | Analyst/Evaluator patterns, prompts |
| `geode-verification` | guardrail, bias, cause, decision tree | G1-G4, BiasBuster, Decision Tree |

## Linked Skills (from parent project)

| Skill | Use |
|-------|-----|
| `langgraph-pipeline` | LangGraph general patterns |
| `clean-architecture` | Port/Adapter, dependency rules |
| `prompt-engineering` | Prompt design best practices |
| `nexon-navigator` | Navigator methodology |
| `mermaid-diagrams` | Architecture diagram styling |
