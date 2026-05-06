# Plan: Agentic Loop Evolution (Plan → Gather → Action → Verify)

> Companion research: [`docs/research/agentic-loop-optimization.md`](../research/agentic-loop-optimization.md)
> Scope: `core/cli/agentic_loop.py` + `core/agent/*` runtime — **NOT** the `core/graph.py` StateGraph pipeline.
> Status: planning (not yet implementation)

## Problem

Furiosa Agent System JD asks for "tool use, planning, reasoning systems" — i.e. dynamic agentic loops where the LLM decides next-action each step. GEODE today has two distinct loop systems:

| Loop kind | Code | Behavior | Furiosa relevance |
|-----------|------|----------|-------------------|
| Pipeline loop | `core/graph.py` (7-node StateGraph + confidence ≥ 0.7 feedback) | Fixed topology. game_ip domain analysis. | Tangential |
| **Agentic loop** | `core/cli/agentic_loop.py` + `core/agent/{convergence,error_recovery,context_manager}.py` | Dynamic next-step. Domain-agnostic. | **Direct match** |

Prior interview feedback flagged "methodology clarity" weakness (autoresearch-class patterns). The agentic loop is where that gap shows. This plan focuses **only** on the agentic loop side.

## Socratic Gate

| # | Question | Answer |
|---|----------|--------|
| Q1 | Does it already exist in code? | `AgenticLoop` exists with `ConvergenceDetector` (3-strikes + escalation), `ErrorRecovery` (4-step), `ContextManager` (200K guard). Plan/Verify/Replan as **explicit phases** do not yet exist. |
| Q2 | What breaks if we don't do this? | Loop remains "ReAct-with-error-handling" — no plan externalization, no in-loop verify, no failure memory. Furiosa-tier interview answer remains weak. |
| Q3 | How do we measure the effect? | (a) tokens/task on a fixed scenario suite; (b) success rate on a 10-task agentic benchmark fixture; (c) iterations-to-resolution distribution. |
| Q4 | What is the simplest implementation? | Phase by phase. Each phase ships one capability with measurable delta vs. prior baseline. |
| Q5 | Is this pattern in 3+ frontier systems? | Yes — Claude Code (TodoWrite + subagent verify), Codex (plan-then-execute + approval), Devin (planner + Devin Review), AIDE (Solution Tree Search). 4/4. |

## Design

### Approach

Evolve `AgenticLoop` from "single-thread ReAct + error recovery" to **explicit Plan / Gather / Action / Verify phases** with measurable optimizations at each phase. Keep the existing `core/graph.py` pipeline as-is — it serves the game_ip domain plugin and is out of scope.

The full body of this plan is split into **9 capability cards** grouped under three layers:

```
Layer 1 — Phase Externalization     (A1, A3, A4)
Layer 2 — Search & Memory           (A2, A5, A8)
Layer 3 — Cross-cutting Infra       (A6, A7, A9)
```

### Layer 1 — Phase Externalization

#### A1. Dynamic Replan
- **What**: Introduce an explicit `Plan` object (`{steps[], current, completed[], abandoned[]}`). Replan every N steps, not only at start.
- **Why**: ReWOO ([2305.18323](https://arxiv.org/abs/2305.18323)) showed plan/observation decouple → 5x token efficiency. Self-Discover ([2402.03620](https://arxiv.org/abs/2402.03620)) showed task-level plan composition → 10–40x fewer inferences than ToT/Self-Consistency.
- **GEODE today**: AgenticLoop builds an implicit plan from system prompt; no explicit `Plan` object.
- **Files**: `core/agent/plan.py` (new), `core/cli/agentic_loop.py` (integrate), `core/agent/state.py` (plan field).
- **Estimated size**: ~150 LOC + tests.
- **Measurable**: tokens/task on agentic fixture suite.

#### A3. In-loop Verify (Reflexion-style)
- **What**: Distinct verify step after each action — LLM judge compares observed result against `plan.expected`. Pass/fail/retry signal.
- **Why**: Anthropic guidance: *"verify is the single highest-leverage thing"*. Reflexion ([2303.11366](https://arxiv.org/abs/2303.11366)) reached HumanEval 91% pass@1 via verbal RL.
- **GEODE today**: Verify is implicit — `error: True/False` from tool result. No expectation comparison.
- **Files**: `core/agent/verify.py` (new), `core/agent/loop.py` (wire after action).
- **Estimated size**: ~120 LOC + tests.
- **Measurable**: success rate on 10-task fixture.

#### A4. Failure Memory (verbal RL)
- **What**: Self-Reflexion summary of each failure stored in episodic memory; injected into next plan prompt.
- **Why**: Reflexion verbal RL paradigm. Existing `recent_errors` is just a 6-element string sliding window — no semantic learning.
- **GEODE today**: `ConvergenceDetector.recent_errors` tracks identity matches only.
- **Files**: `core/agent/memory.py` (new) or extension of `core/memory/session.py`.
- **Estimated size**: ~100 LOC + tests.
- **Measurable**: iterations-to-resolution distribution (should shift left).

### Layer 2 — Search & Memory

#### A2. Tool Selection as Search
- **What**: Replace next-tool prediction with A*-style policy over a tool-call decision tree, biased by historical success and current plan step.
- **Why**: ToolChain* ([2310.13227](https://arxiv.org/abs/2310.13227)) achieved **7.35x speedup** vs DFS on real tool benchmarks.
- **GEODE today**: Tool selection is the LLM's free choice each step — no policy.
- **Files**: `core/agent/tool_search.py` (new), integrate in loop.
- **Estimated size**: ~200 LOC + tests.
- **Measurable**: total tool calls / task; wall-clock latency.

#### A5. Skill Library Growth (Voyager)
- **What**: Detect successful multi-tool sequences automatically and register them as composite skills in `SkillRegistry`.
- **Why**: Voyager ([2305.16291](https://arxiv.org/abs/2305.16291)) achieved 3.3x items / 15.3x faster milestones via skill accretion.
- **GEODE today**: `SkillRegistry` is static — skills defined at design time.
- **Files**: `core/skills/auto_skill.py` (new), hook into `LOOP_COMPLETE` event.
- **Estimated size**: ~250 LOC + tests + curation policy.
- **Measurable**: skill count growth + reuse rate on subsequent tasks.

#### A8. Best-First Tree Search (LATS / AIDE Solution Tree)
- **What**: Replace single-thread loop with a tree where each step branches K candidate actions; value function selects best path. Spike first, decision after measurement.
- **Why**: LATS ([2310.04406](https://arxiv.org/abs/2310.04406)), Koh 2024 ([2407.01476](https://arxiv.org/abs/2407.01476)) → +28–39.7% on web tasks. AIDE 3x medals on MLE-bench.
- **GEODE today**: Pure single-thread sequential loop.
- **Files**: spike branch, then `core/agent/tree_search.py` (new) if greenlit.
- **Estimated size**: 200 LOC spike → 500–800 LOC if adopted.
- **Measurable**: success rate × token cost — Pareto frontier vs. greedy baseline.

### Layer 3 — Cross-cutting Infra

#### A6. Plan/Action Model Separation
- **What**: Plan = Opus 4.7 (deep). Action execution prediction = Sonnet 4.6 / Haiku 4.5 (fast).
- **Why**: Cursor Composer 2 + Apply ~13x speedup; Aider architect/editor split; AlphaEvolve fast/slow ensemble.
- **GEODE today**: All steps share one model pool.
- **Files**: `core/llm/router.py`, `core/config.py`, `AgenticLoop` model dispatch.
- **Estimated size**: ~80 LOC + cost/quality regression tests.
- **Measurable**: $ per task; quality regression on fixture suite.

#### A7. Wall-clock + Token Budget Forcing
- **What**: AgenticLoop accepts `max_wall_seconds` and `max_thinking_tokens` in addition to `max_iterations`. s1-style "Wait" injection or hard truncate at limit.
- **Why**: autoresearch P3 (`fixed time budget of 5 minutes`); s1 ([2501.19393](https://arxiv.org/abs/2501.19393)) budget forcing → AIME24 50→57%.
- **GEODE today**: `max_iterations` + 200K hard guard. No wall-clock.
- **Files**: `core/agent/budget.py` (new), `AgenticLoop` integrate.
- **Estimated size**: ~80 LOC + tests.
- **Measurable**: P95 latency under budget caps.

#### A9. External Verifier Integration (deferred)
- **What**: Define `VerifierResult { source, verdict, evidence }` interface; consume linter/CI/security-scanner output in the verify step.
- **Why**: Devin Autofix closed-loop pattern.
- **GEODE today**: LangSmith trace exists (observation only); no automated consumer.
- **Files**: `core/verification/external.py` (new) + arch doc.
- **Estimated size**: ~150 LOC core + adapters.
- **Measurable**: out-of-scope for v0.66 — track for v0.70+.

### Affected Files

| File | Change |
|------|--------|
| `core/agent/plan.py` | NEW — `Plan` dataclass + replan logic (A1) |
| `core/agent/verify.py` | NEW — in-loop verify step (A3) |
| `core/agent/memory.py` | NEW — failure memory + Reflexion summary (A4) |
| `core/agent/tool_search.py` | NEW — A*-style policy (A2) |
| `core/skills/auto_skill.py` | NEW — skill auto-induction (A5) |
| `core/agent/tree_search.py` | NEW (after spike) — best-first search (A8) |
| `core/agent/budget.py` | NEW — wall-clock + token forcing (A7) |
| `core/verification/external.py` | NEW (deferred) — external verifier (A9) |
| `core/cli/agentic_loop.py` | INTEGRATE — wire phases through `AgenticLoop` |
| `core/llm/router.py` | EXTEND — model role dispatch (A6) |
| `core/config.py` | EXTEND — new budget / role parameters |
| `tests/agent/test_*.py` | NEW per capability |
| `docs/architecture/agentic-loop.md` | NEW — phase contract + invariants |
| `CHANGELOG.md` | per-phase entries |

### Out of Scope (explicitly)

These are valuable but belong to the **pipeline loop** (`core/graph.py`), not the agentic loop:

- Final-node re-selection across iteration_history (game_ip pipeline only)
- `_gather_node` Σ(T) summarization
- 14-axis ablation refinement
- `enrichment_needed` dynamic threshold
- Domain entity PageRank gather

These may be tracked in a separate `pipeline-loop-tightening.md` plan if motivated by game_ip needs.

### Alternatives Considered

| Alternative | Why rejected |
|-------------|--------------|
| Patch `core/graph.py` and call it agentic | Conflates pipeline with agentic loop. Furiosa-tier interview answer demands the distinction. |
| Rebuild the loop from scratch | Existing `ConvergenceDetector` + `ErrorRecovery` + `ContextManager` are solid. Phase-additive plan preserves them. |
| Adopt LangGraph React agent wholesale | Loses GEODE-specific Hooks, Skills, Memory. Phase plan keeps these intact. |
| Implement A8 first (sexy) | Greedy baseline must be measured before adding tree search complexity (Karpathy P10). |

## Implementation Phases

| Phase | Items | Target version | Why this batch |
|-------|-------|----------------|----------------|
| **Phase 0** (this PR) | Plan doc + research consolidation | v0.66.x docs | Establish methodology vocabulary |
| **Phase 1** | A1 Dynamic Replan + A3 In-loop Verify | v0.67.0 | Phase externalization minimal viable |
| **Phase 2** | A4 Failure Memory + A7 Budget Forcing | v0.68.0 | Reflexion + autoresearch P3 parity |
| **Phase 3** | A6 Plan/Action Model Split + A2 Tool Search | v0.69.0 | Cost & efficiency Pareto improvement |
| **Phase 4** | A5 Skill Auto-Induction | v0.70.0 | Voyager-style accretion |
| **Phase 5** (spike-gated) | A8 Best-First Tree Search | v0.71.0+ | Only after greedy baseline measured |
| **Deferred** | A9 External Verifier | v1.0+ | Requires CI/linter consumer adapters |

## Implementation Checklist (per phase)

- [ ] GAP audit — `grep`/`Explore` confirms target code does not already exist
- [ ] Implementation
- [ ] Unit + integration tests
- [ ] Live E2E (`-m live`) for at least one scenario
- [ ] Measurable delta documented (tokens, success rate, latency)
- [ ] Lint + Type check
- [ ] CHANGELOG entry citing the source paper(s)
- [ ] `docs/architecture/agentic-loop.md` updated

## Verification (per phase)

```bash
uv run ruff check core/ tests/ plugins/
uv run mypy core/ plugins/
uv run pytest tests/ -m "not live"
uv run pytest tests/agent/ -v
# Live (authorized only)
uv run pytest tests/agent/test_loop_e2e.py -m live
```

## Frontier Research Summary

| System | Related pattern | Adoption | Rationale |
|--------|-----------------|----------|-----------|
| Claude Code | TodoWrite + subagent verify + Plan Mode | Adopt (A1, A3) | "Verify is single highest-leverage thing" cited verbatim |
| Codex CLI | Plan-then-execute + approval gate | Adapt (A1, A7) | Approval-gate pattern → wall-clock budget pattern |
| Devin | Long-term planner + Devin Review + Autofix | Adapt (A3, A9) | Closed-loop external verifier; adopt later (A9 deferred) |
| Aider | architect/editor split + repo-map | Adopt (A6) | Concrete model-split case study with shipped quality |
| AIDE | Solution Tree Search + Σ(T) | Adopt (A8) | Greedy + tree spike comparison; AIDE achieved 3x medals |
| MLE-STAR | Outer ablation + Inner refinement | Defer (pipeline) | Pipeline loop scope, not agentic |
| AlphaEvolve | Fast/slow LLM ensemble + evaluator pool | Adopt (A6) | Backup citation for model-split |
| autoresearch | P3 wall-clock + P4 ratchet + P6 context budget | Adopt (A7) | Verbatim citation: `fixed time budget of 5 minutes` |
| FunSearch | LLM creator + auto evaluator | Adopt (A3) | Verifier-as-ratchet philosophy |
| LATS / Koh / ToolChain* | Tree / A* search over actions | Spike-gated (A2, A8) | Only after greedy measured (P10) |

## Interview Talking Points (post-Phase 1+)

1. **autoresearch parity** — wall-clock budget (A7) + ratchet (existing `ConvergenceDetector`) + context budget (existing 200K guard) implemented; SETI@home limit acknowledged via Send API parallelism in pipeline.
2. **Verify priority** — Anthropic's *"single highest-leverage thing"* operationalized as A3 dedicated phase, citing Reflexion HumanEval 91%.
3. **Search-theoretic answer to attempt reduction** — A2 cites ToolChain* 7.35x; A8 cites LATS / Koh +28–39.7%.
4. **Cost-conscious deployment** — A6 model split cites Cursor 13x speed and AlphaEvolve ensemble.
5. **Methodology vocabulary** — explicit Plan / Gather / Action / Verify phases with named source papers in CHANGELOG.

## References

- Companion research: [`docs/research/agentic-loop-optimization.md`](../research/agentic-loop-optimization.md)
- Frontier precedent: Claude Code, Codex, Devin, Aider, AIDE, autoresearch
- Skills consulted: `frontier-harness-research`, `karpathy-patterns`
- Furiosa JD: <https://furiosa.ai/careers/software-agentsystem>

## Status

- 2026-05-06 — plan drafted, Phase 0 PR pending
