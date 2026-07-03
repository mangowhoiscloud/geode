---
name: geode-context
visibility: public
triggers: geode, harness, agent, runtime, release, packaging, docs, plugin, architecture
description: GEODE runtime architecture and repo-shape context. Use for architecture, packaging, release, docs, CI, AgenticLoop, async runtime, and plugin boundary questions.
---

# GEODE Context

Version-agnostic runtime context. For current version and metrics always read
`CLAUDE.md` or `site/src/data/geode/sot.ts` — never trust numbers remembered
from this skill.

## Current Shape

- GEODE is a general-purpose autonomous-agent harness whose runtime is `AgenticLoop(while tool_use)`.
- The agent loop, sub-agents, plans, and batches are all instances of the same tool-use loop.
- Core runtime is domain-agnostic. Main packages:
  - `core/` — agent loop, tools, MCP, memory, hooks, wiring, CLI, server, gateway.
  - `plugins/` — first-party auxiliary plugins (`petri_audit`, `seed_generation`, `benchmark_harness`).
  - `site/` — public Next.js docs/site.

## Runtime Boundaries

- Canonical execution path is async-first: `AgenticLoop.arun()`, tool `aexecute()`, async provider clients.
- `core/agent/loop/agent_loop.py` is the implementation. `DEFAULT_MAX_ROUNDS = 0` means unlimited rounds; time budget and model-emitted termination signals (`model_action_required`, `user_clarification_needed`) control completion.
- Sub-agents: `core/agent/sub_agent.py` (`SubAgentManager`) — max depth 1 (no recursion), session-wide cap 15, global Lane concurrency 50 (`core/wiring/container.py`).
- Headless modes (DAEMON / SCHEDULER) deny `run_bash` / `delegate_task` / `computer` outright (`HEADLESS_DENIED_TOOLS`, `core/agent/safety.py`).

## Prompt And Context Injection

- `core/llm/prompt_assembler.py` owns prompt assembly and emits `PROMPT_ASSEMBLED`.
- `core/agent/system_prompt.py` inserts `__GEODE_PROMPT_CACHE_BOUNDARY__` between STATIC and DYNAMIC blocks; dynamic context is wrapped in `<dynamic_context>`.
- Skill metadata is injected as `<available_skills>` (metadata only); full skill bodies load on demand via the `use_skill` tool.
- Do not inject old Game IP pipeline facts, fixed DAG claims, analyst/evaluator topology, or confidence-threshold loop claims into the system prompt.

## Release Pipeline

- Functional commits update `CHANGELOG.md`.
- Quality gates: `ruff check` / `ruff format --check` (core, tests, plugins, scripts), `mypy core/ plugins/`, `lint-imports`, `pytest -m "not live"`, `geode version` smoke.
- Publishing is manual/approval-gated, not automatic on every main push.

## Guardrails

- Do not reintroduce `plugins.game_ip` imports into `core/`; Game IP is not the default domain.
- Do not describe GEODE as a fixed Plan-and-Execute DAG, fixed StateGraph, or confidence-threshold pipeline.
- Do not cite LangSmith as current observability; GEODE uses its own hooks, audit diagnostics, run logs, and site/docs gates.
- Do not hard-code deprecated model names. Use the provider registries and token/cost tables.
