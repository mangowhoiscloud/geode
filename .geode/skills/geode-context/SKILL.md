---
name: geode-context
visibility: public
description: GEODE v0.99.247 runtime and release context. Use for architecture, packaging, release, docs, CI, AgenticLoop, async runtime, and external plugin boundary questions. Triggers include "geode", "harness", "agent", "runtime", "release", "packaging", "docs", and "plugin".
---

# GEODE v0.99.247 Context

## Current Shape

- GEODE is a general-purpose autonomous-agent harness whose runtime is `AgenticLoop(while tool_use)`.
- The agent loop, sub-agents, plans, and batches are all modeled as instances of the same tool-use loop.
- Core runtime is domain-agnostic. Domain analysis packages are distributed separately through plugins or external packages.
- Current SOT metrics: v0.99.247, 455 modules, 8,854 standard tests, 1 live test.
- Main packages:
  - `core/` — agent loop, tools, MCP, memory, hooks, wiring, CLI, server, gateway.
  - `plugins/` — first-party auxiliary plugins such as `petri_audit`.
  - `site/` — public Next.js docs/site.

## Runtime Boundaries

- Canonical execution path is async-first:
  - agent loop: `AgenticLoop.arun()`
  - tools: `aexecute()`
  - providers: async SDK clients and async tool-use paths
- Public sync facades were removed or reduced to process-edge compatibility only.
- `core/agent/loop/agent_loop.py` is the implementation. `DEFAULT_MAX_ROUNDS = 0` means unlimited rounds by default; time and termination signals control completion.
- Auto-escalation was removed in v0.90.0. The model emits explicit termination signals such as `model_action_required` or `user_clarification_needed`.
- Sub-agent concurrency is managed by `core/agent/subagent.py` with `MAX_CONCURRENT = 5` and `SessionLane` slot allocation.

## Prompt And Context Injection

- `core/llm/prompt_assembler.py` owns six-step prompt assembly and emits `PROMPT_ASSEMBLED`.
- `core/agent/system_prompt.py` inserts `__GEODE_PROMPT_CACHE_BOUNDARY__` between STATIC and DYNAMIC blocks.
- Since v0.93, dynamic context is wrapped in `<dynamic_context>`.
- Sandwich reminders use XML tags such as `<system-reminder>`.
- Skill metadata injected into the agent prompt must stay metadata-only and XML-delimited; full skill bodies are loaded on demand.
- Do not inject old Game IP pipeline facts, fixed DAG claims, analyst/evaluator topology, or confidence-threshold loop claims into the general GEODE system prompt.

## Release Pipeline

- Functional commits update `CHANGELOG.md`.
- Release validation includes:
  - `uv run ruff check core/ tests/ plugins/ scripts/`
  - `uv run ruff format --check core/ tests/ plugins/ scripts/`
  - `uv run mypy core/ plugins/ scripts/`
  - `uv run python -m pytest tests/ -q`
  - `uv build`
  - install smoke and site build through GitHub Actions when PRs are opened
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
- Do not describe GEODE as a fixed Plan-and-Execute DAG, fixed StateGraph, or confidence-threshold pipeline.
- Do not cite LangSmith as current observability; GEODE uses its own hooks, audit diagnostics, run logs, and site/docs gates.
- Do not hard-code deprecated model names. Use the provider registries and token/cost tables.
- For current metrics and version, prefer `site/src/data/geode/sot.ts`, `CLAUDE.md`, and `AGENTS.md` over skill memory.
