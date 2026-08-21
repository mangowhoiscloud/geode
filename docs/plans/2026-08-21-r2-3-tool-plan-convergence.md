# R2.3 Tool-Plan Runtime Convergence

Status: implementation authorized by roadmap claim [#3050](https://github.com/mangowhoiscloud/geode/pull/3050)

Base: `origin/develop@0556c55ba0000745de07cc659277b3402d1153c5`

GAPs: `CAP-003`, `CAP-005`

## Outcome

Bind the existing immutable `ToolPlan` to one immutable handler mapping and
make that same catalog the schema and execution authority for product daemon,
worker, MCP one-shot, `AgenticLoop`, `ToolExecutor`, and provider/deferred
projections. CLI surfaces become compatibility forwarders instead of runtime
catalog owners.

This package adds no mutable registry, plugin system, or provider-neutral wire
format. Provider-hosted tools remain adapter-owned.

## Measured gap

- `geode_product.tool_handlers.compose_tool_plan()` creates a `ToolPlan`, but
  `SharedServices` stores it beside an independent mutable handler dictionary.
- `SharedServices.create_session()` passes only the handler dictionary to
  `ToolExecutor`; `AgenticLoop` reloads `definitions.json` independently.
- worker, MCP one-shot, Petri, and seed roots call the compatibility handler
  builder without retaining the plan.
- Anthropic and OpenAI adapters reshape loop-local tool dictionaries, while
  deferred membership is not part of the plan hash.
- plan generation/hash reaches no live bounded diagnostic.

## Frontier research summary

| System | Related pattern | Decision |
|---|---|---|
| Codex | one finalized ordered router owns model specs and execution registry | Adopt the same-snapshot invariant; do not copy Rust trait/context structure |
| Codex Cloud | stable task/attempt identity and preflight-before-side-effect | Adapt bounded plan identity only; do not infer unpublished registry internals |
| OpenClaw | attempt-local effective catalog feeds policy-filtered visibility and normal execution | Adopt one concrete catalog; reject its multi-stage mutable pipeline |
| autoresearch | frozen evaluator, bounded surface, simplicity criterion | Adopt fixed acceptance and deletion preference; registry design is not applicable |

Pinned sources:

- [Codex spec plan](https://github.com/openai/codex/blob/dad1db87bb5a/codex-rs/tools/src/spec_plan.rs), [router](https://github.com/openai/codex/blob/dad1db87bb5a/codex-rs/core/src/tools/router.rs), and [turn wiring](https://github.com/openai/codex/blob/dad1db87bb5a/codex-rs/core/src/session/turn.rs)
- [OpenClaw attempt catalog](https://github.com/openclaw/openclaw/blob/49b4841081c6/src/agents/embedded-agent-runner/run/attempt-tool-catalog.ts) and [client tools](https://github.com/openclaw/openclaw/blob/49b4841081c6/src/agents/embedded-agent-runner/run/attempt-client-tools.ts)
- [autoresearch program](https://github.com/karpathy/autoresearch/blob/228791fb499a/program.md)

## Boundary

1. Add one frozen `BoundToolPlan` value in the existing neutral plan module:
   `ToolPlan` plus an immutable ordinary-handler mapping. Validate ordinary and
   special routes before session side effects. Callables stay outside the
   content hash; stable binding metadata remains inside it.
2. Runtime/product composition builds that catalog once. CLI compatibility
   functions may return a dictionary copy, but no agent/server/product runtime
   may rebuild schema and execution authorities independently.
3. Pass the same catalog object through `SharedServices`, `AgenticLoop`, and
   `ToolExecutor`. Mode/allowlist filtering returns another immutable derived
   catalog; it never mutates the parent.
4. Build adapter-neutral `ToolSpec` order from the plan. Anthropic/OpenAI keep
   their own hosted-tool and wire-shape logic.
5. Add one hash-bound eager/deferred attribute to plan metadata. Threshold,
   provider support, settings kill switches, hosted search tools, and the
   OpenAI blocklist stay adapter-owned.
6. Worker and MCP roots receive the same bound-catalog builder. Dynamic MCP and
   benchmark-specific tool overlays remain explicit transient inputs; exact
   per-step refresh belongs to R3.1.
7. Emit only generation, full content hash, and bounded counts in existing
   diagnostics. Do not include schemas, callables, credentials, or payloads.

## Explicit non-goals

- R2.4 effect/resource-key, approval, retention, redaction, or data-policy
  derivation;
- R3.1 `StepSnapshot`, `TurnState`, exact in-flight refresh lifetime, budget,
  cancellation, or trace identity;
- ambient OAuth/API availability in a static plan;
- a new global registry, manifest, cache, or plugin discovery framework;
- changing user-visible tool names, arguments, order, approvals, or provider
  payloads except to fail a previously hidden parity error.

## Acceptance

- one catalog object is shared by services, loop, and executor; worker and MCP
  build the same content hash from the same contribution set;
- enabled schema names and order equal executable routes after filtering;
  duplicate, missing, or non-callable bindings fail before session effects;
- normalized Anthropic/OpenAI function schemas and deferred function order are
  derived from the same plan; hosted tools are explicit adapter-owned extras;
- changing schema, stable binding metadata, order, or defer membership changes
  the hash/generation and leaves the previous catalog unchanged;
- unavailable capability and denied policy remain distinguishable and neither
  is advertised or dispatched;
- diagnostics expose the exact plan hash/generation used without raw schemas,
  callables, secrets, or user payloads;
- behavioral poison tests prove legacy JSON snapshots, CLI builders, and old
  defer sets cannot become a hidden live authority;
- targeted tests, ruff, format, mypy, import-linter, architecture/debt gates,
  package/install checks, official docs, and the full non-live suite pass.

## GitFlow

One functional PR from `feature/r2-3-tool-plan-convergence` targets `develop`
and names both GAPs. After merge, a roadmap-only reconciliation moves both rows
to `IN_DEVELOP`, records one evidence row, removes the claim, and re-audits the
next package. Main promotion waits for the remaining planned packages to
converge on `develop`.
