# R3.1 Step and Turn State

Status: implementation authorized by roadmap claim [#3064](https://github.com/mangowhoiscloud/geode/pull/3064)

Base: `origin/develop@5b4096dc2e637d3c811cf0c3296f92fb878eeea6`

GAPs: `LOOP-001`, `LOOP-002`

## Outcome

Make one immutable sampling-step snapshot and one explicit mutable physical-turn
accumulator the state owners inside the existing `AgenticLoop`. Keep the current
while-tool-use control flow and every terminal reason unchanged.

## Measured gap

- turn identity, route, tool-plan generation, budgets, cancellation, retry
  counters, messages, and round index currently live in unrelated locals and
  mutable loop fields;
- model retries can reuse `round_idx` without a distinct sampling identity;
- tool execution reconstructs provider/source/model identity rather than
  receiving the exact sampling snapshot that produced the tool call;
- checkpoints persist round and guard counters, but no runtime value ties one
  model response, its optional tool batch, and their trace correlation together.

## Frontier research

| System | Related pattern | Decision |
|---|---|---|
| Codex | request-scoped `StepContext` pins model, environment, MCP catalog, and finalized tool router | Adopt immutable per-sampling identity and exact catalog; reject Rust ownership structure |
| Codex Cloud | public task/attempt APIs expose stable isolation, not an internal step-state type | Record N/A for unpublished internals; do not infer them |
| OpenClaw | one attempt-local effective tool catalog is prepared before execution | Adopt attempt-local snapshot timing; reject the multi-stage mutable catalog pipeline |
| autoresearch | fixed wall budget and simplicity criterion constrain the loop | Keep existing budgets in the snapshot; add no phase engine or scheduler |

Pinned sources:

- [Codex StepContext](https://github.com/openai/codex/blob/e3e5ad28470f6a225301518c30a66e749a880164/codex-rs/core/src/session/step_context.rs)
- [OpenClaw attempt tool catalog](https://github.com/openclaw/openclaw/blob/49b4841081c6/src/agents/embedded-agent-runner/run/attempt-tool-catalog.ts)
- [autoresearch program](https://github.com/karpathy/autoresearch/blob/228791fb499a/program.md)

## Smallest implementation

1. Add frozen `StepSnapshot` and mutable `TurnState` records beside the existing
   loop state models. `StepSnapshot` carries route, exact bound tool plan,
   budgets, cancellation, and hook correlation. `TurnState` owns messages,
   round/step/retry counters, plan hint, terminal reason, and the turn-wide
   cancellation event.
2. Open a fresh step for every `_call_llm` sampling request. Adapter retry
   attempts reuse that step; a context-recovery or model retry opens the next
   step without incrementing the completed tool round.
3. Bind that same snapshot to `ToolCallProcessor`; derive every `ToolContext`
   from it so a response and its tool batch cannot observe a newer route or
   tool-plan generation.
4. Keep checkpoint format and the closed `TerminationReason` alphabet intact.
   The terminal-result choke point records the reason in the active turn state.

## Non-goals

- R3.2 phase extraction or a new state-machine framework;
- R3.3 structural budget enforcement changes;
- R3.4 sub-agent protocol changes;
- checkpoint schema migration, dynamic MCP refresh redesign, or provider retry
  policy changes.

## Acceptance

- one model response and its optional tool batch share one immutable snapshot;
- retries have monotone step identities while the completed-round count remains
  backward compatible;
- route/tool-plan changes affect only a later sampling step;
- one turn-wide cancellation handle reaches tool contexts;
- all existing terminal reasons, checkpoint-before-retry behavior, context
  recovery, usage/cost accounting, approval/input-block behavior, and hook order
  remain green;
- targeted tests, ruff, format, mypy, import/debt gates, package/install checks,
  official docs, and the full non-live suite pass.

## GitFlow

One functional PR from `feature/r3-1-step-turn-state` targets `develop` and
names both GAPs. After merge, a roadmap-only reconciliation moves both rows to
`IN_DEVELOP`, records one evidence row, removes the claim, and re-audits the
next package.
