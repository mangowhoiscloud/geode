# GEODE v6.0 — Undervalued IP Discovery Agent

LangGraph-based CLI demo for IP Detaction

## Quick Start

```bash
# Install
uv sync

# Dry run (no API key needed)
uv run geode analyze "Cowboy Bebop" --dry-run

# Full run (requires API key)
cp .env.example .env
# Edit .env with your ANTHROPIC_API_KEY
uv run geode analyze "Cowboy Bebop"

# Other commands
uv run geode list              # Available IPs
uv run geode analyze --help    # All options
```

## Options

```
geode analyze "Cowboy Bebop"                    # Full pipeline
geode analyze "Cowboy Bebop" --dry-run          # No LLM calls
geode analyze "Cowboy Bebop" --verbose          # Detailed output
geode analyze "Cowboy Bebop" --skip-verification # Skip guardrails
```

## Agent Core Loop

```
Router → Cortex → Signals → Analysts ×4 (Send API) → Evaluators ×3 → Scoring → Verification → Synthesizer
```

## Tests

```bash
uv run pytest tests/ -v
```
