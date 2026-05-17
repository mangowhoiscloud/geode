---
name: geode-context
visibility: public
description: GEODE v0.99.11 runtime and release context. Use for architecture, packaging, release, docs, CI, async runtime, and external plugin boundary questions. "geode", "harness", "agent", "runtime", "release", "packaging", "docs", "plugin" 키워드로 트리거.
---

# GEODE v0.99.11 Context

## Current Shape

- GEODE is a general-purpose autonomous execution harness on LangGraph.
- Core runtime is domain-agnostic. Domain analysis packages are distributed separately.
- Current SOT metrics: v0.99.11, 339 modules, 4,897 standard tests, 24 live tests, 154 releases.
- Main packages:
  - `core/` — agent loop, tools, MCP, memory, hooks, wiring, CLI, server, gateway.
  - `plugins/` — first-party auxiliary plugins only. Bundled Game IP analysis is no longer part of GEODE core.
  - `site/` — public Next.js docs/site.

## Runtime Boundaries

- Canonical execution path is async-first:
  - agent loop: `AgenticLoop.arun()`
  - tools: `aexecute()`
  - providers: async SDK clients and async tool-use paths
  - process-edge coroutine execution: `core.async_runtime`
- Public sync facades were removed or reduced to process-edge compatibility only.
- `core/agent/loop/agent_loop.py` is the implementation. Legacy loop module paths are compatibility shims only where still present.

## Prompt And Context Injection

- Prompt templates use XML-shaped sections.
- Static and dynamic context are separated by `<dynamic_context>`.
- Sandwich reminders use XML tags such as `<system-reminder>`.
- Skill metadata injected into the agent prompt must stay metadata-only and XML-delimited; full skill bodies are loaded on demand.
- Do not inject old Game IP pipeline facts into the general GEODE system prompt.

## Release Pipeline

- Functional commits update `CHANGELOG.md`.
- Release validation includes:
  - `uv run ruff check .`
  - `uv run ruff format --check core plugins tests autoresearch scripts`
  - `uv run mypy core plugins scripts`
  - `uv run pytest -q`
  - `uv run python scripts/check_official_docs.py`
  - `uv build`
  - `uv run twine check dist/*`
  - CLI smoke: `uv run geode version`, `uv run geode doctor bootstrap`
- Hugging Face release assets are generated into a versioned bundle with wheel, sdist, checksums, release notes, manifest, repo card, and `latest.json`.
- Publishing should be manual/approval-gated, not automatic on every main push.

## Documentation

- Human docs:
  - `docs/`
  - `site/src/app/docs/`
- LLM entry points:
  - `AGENTS.md`
  - `CLAUDE.md`
  - `GEODE.md`
  - `site/public/llms.txt`
  - `site/public/llms-full.txt`
- KR/EN release support is required for README and changelog release sections.

## Removed From Core

- Bundled `plugins/game_ip/`
- `geode analyze` / `geode batch` Game IP CLI surface
- Game IP fixtures and E2E gates
- Game IP analyst/evaluator prompt skills and domain rules
- Historical one-off `scripts/eco2_token_cost.py`

## Guardrails

- Do not reintroduce `plugins.game_ip` imports into `core/`.
- Do not make Game IP the default domain for GEODE core.
- Do not cite LangSmith as current observability; GEODE uses its own hooks, audit diagnostics, run logs, and site/docs gates.
- Do not hard-code deprecated model names. Use the provider registries and token/cost tables.
