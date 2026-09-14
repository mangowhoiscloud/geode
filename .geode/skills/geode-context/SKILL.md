---
name: geode-context
visibility: public
triggers: geode, harness, agent, runtime, release, packaging, docs, plugin, architecture, model, pricing
description: GEODE runtime context for model selection and metadata, architecture, packaging, release, docs, CI, AgenticLoop, async runtime, and plugin boundaries.
---

# GEODE Context

Version-agnostic runtime context. Use `geode version` / `geode about` for the
installed version and runtime facts; never trust numbers remembered from this
skill.

## Current Shape

- GEODE is a general-purpose autonomous-agent harness whose runtime is `AgenticLoop(while tool_use)`.
- The agent loop, sub-agents, plans, and batches are all instances of the same tool-use loop.
- The runtime is domain-agnostic. Shipped packages:
  - `core/` — agent loop, tools, MCP, memory, hooks, wiring, CLI, server, gateway.
  - `evals/` — Petri audits, benchmarks, seed generation, and GEO measurement.
  - `evolve/` — scaffold search and Crucible experiment supervision.
- `site/` is the public Next.js docs/site, not a Python package.
- Dependency direction is `evolve -> evals -> core`; reverse imports are forbidden.

## Runtime Boundaries

- Canonical execution path is async-first: `AgenticLoop.arun()`, tool `aexecute()`, async provider clients.
- `core/agent/loop/agent_loop.py` is the implementation. `DEFAULT_MAX_ROUNDS = 0` means no round cap. Model completion and runtime guard exits are distinct `TerminationReason` values in `core/agent/loop/models.py`; a diagnostic or budget exit is not task success.
- Sub-agents: `core/agent/sub_agent.py` (`SubAgentManager`) — max depth 1 (no recursion), session-wide cap 15, global Lane concurrency 50 (`core/wiring/container.py`).
- Headless mode policy lives in `core/server/supervised/services.py`: `run_bash` and delegation remain denied; DAEMON desktop control requires explicit `gateway.allow_computer_use`, while SCHEDULER keeps the desktop denial. The active tool plan and profile can further restrict access.

## Prompt And Context Injection

- `core/agent/system_prompt.py` builds the base prompt; `core/agent/loop/_context.py` composes skill and session context. `core/llm/prompt_assembler.py` contains shared formatting helpers, not another assembler.
- `GEODE.md` (packaged as `core/GEODE.md`) is the SOUL source. The default loop extracts Identity, Voice & Conduct, Operating Principles and RUNTIME CANNOT into G1; persona-off and audit modes omit G1. The separate `ContextAssembler` exposes the full SOUL to explicit callers, not as the default loop prompt.
- `PROMPT_CACHE_BOUNDARY` is the opening `<dynamic_context>` tag. Stable instructions precede it; per-turn context stays inside the closed envelope. `core/agent/loop/agent_loop.py` emits `PROMPT_ASSEMBLED` after each per-round rebuild.
- Skill metadata is injected as `<available_skills>` (metadata only); full skill bodies load on demand via the `use_skill` tool.
- Do not inject old Game IP pipeline facts, fixed DAG claims, analyst/evaluator topology, or confidence-threshold loop claims into the system prompt.

## Model Information

Use the current `<model_card>` for questions about the configured model; do not
load a catalog merely to repeat fields already present. The normal and audit
builders place it in dynamic context when a model is supplied. Explicit agent
prompt overrides replace that base and need not contain a card; absence is not
permission to guess from this skill or prior replies.

| Question | Read or inspect |
|----------|-----------------|
| Which model is selected, and why? | `/model` for registered choices and role selections; `geode about` and `geode config explain model` for resolved settings. Project/global config and environment can override shipped defaults. |
| Which defaults or fallback chains ship? | `core/config/routing.toml` and its loader `core/config/routing_manifest.py`; operator overrides live in `~/.geode/routing.toml`. Chains ship empty and require explicit opt-in. Do not silently switch model, provider or billing route. |
| Where do limits and rate estimates come from? | `core/llm/model_pricing.toml` supplies catalog limits/rates; `core/llm/model_catalog.py` and provider adapters consume model metadata. Catalog context is not the runtime's remaining context budget; API rates are not subscription billing. Verify current vendor documentation when freshness matters. |
| Does this account have access? | Picker availability checks a local credential route, not remote entitlement. A model ID in the catalog, a default binding or a configured credential does not establish successful provider access. Live probes need explicit approval. |

See the [provider guide](https://mangowhoiscloud.github.io/geode/docs/run/providers/)
for operator configuration. In a source checkout, use the existing
[model-onboarding skill](../../../.agents/skills/model-onboarding/SKILL.md) for
implementation changes; that development scaffold is not bundled with the runtime.
Never copy a versioned model/spec table into this skill or the SOUL.

## Release Pipeline

- Functional commits update `CHANGELOG.md`.
- Quality gates: `ruff check` / `ruff format --check` (`core`, `evals`, `evolve`, `tests`, `scripts`), `mypy core/ evals/ evolve/`, `lint-imports`, `pytest -m "not live"`, `geode version` smoke.
- Publishing is manual/approval-gated, not automatic on every main push.

## Guardrails

- Do not restore the retired top-level `plugins`, `geode_product`, or
  `core.self_improving` packages. Evaluation and evolution stay explicit outer
  consumers of `core`.
- Do not describe GEODE as a fixed Plan-and-Execute DAG, fixed StateGraph, or confidence-threshold pipeline.
- Do not cite LangSmith as current observability; GEODE uses its own hooks, audit diagnostics, run logs, and site/docs gates.
- Do not hard-code deprecated model names. Use the provider registries and token/cost tables.
