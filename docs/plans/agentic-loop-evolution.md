# Plan: Agentic Loop Evolution (Plan → Gather → Action → Verify)

> [!NOTE]
> Historical capability plan: several premises and paths no longer describe
> the current runtime. Current agent-kernel GAPs, ordering, and completion
> evidence are owned by
> [`docs/architecture/extensibility-roadmap.md`](../architecture/extensibility-roadmap.md),
> especially LOOP-001 through LOOP-005.
>
> Companion research: [`docs/research/agentic-loop-optimization.md`](../research/agentic-loop-optimization.md)
> Scope: `core/agent/loop/agent_loop.py` + `core/agent/*` runtime.
> Status: planning (not yet implementation)

## Problem

Furiosa Agent System JD asks for "tool use, planning, reasoning systems" — i.e. dynamic agentic loops where the LLM decides next-action each step. GEODE today has two distinct loop systems:

| Loop kind | Code | Behavior | Furiosa relevance |
|-----------|------|----------|-------------------|
| Legacy pipeline loop | Removed Game-IP StateGraph pipeline | Historical domain-analysis topology. Not current runtime. | Archive only |
| **Agentic loop** | `core/agent/loop/agent_loop.py` + `core/agent/{convergence,error_recovery,context_manager}.py` | Dynamic next-step. Domain-agnostic. | **Direct match** |

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

Evolve `AgenticLoop` from "single-thread ReAct + error recovery" to **explicit Plan / Gather / Action / Verify phases** with measurable optimizations at each phase. Keep the removed Game-IP pipeline out of scope; current work targets the AgenticLoop runtime only.

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
- **GEODE today**: hook events, RunLog, usage JSONL, and audit diagnostics exist;
  verifier outputs still need a first-class automated consumer.
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

These are historical Game-IP pipeline ideas, not current AgenticLoop runtime work:

- Final-node re-selection across iteration_history (game_ip pipeline only)
- `_gather_node` Σ(T) summarization
- 14-axis ablation refinement
- `enrichment_needed` dynamic threshold
- Domain entity PageRank gather

They are archived outside the main project with the confidence-gate material.

### Alternatives Considered

| Alternative | Why rejected |
|-------------|--------------|
| Recreate the deleted pipeline and call it agentic | Conflates a domain DAG with the current agentic loop. Furiosa-tier interview answer demands the distinction. |
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

## Benchmark Methodology

> **References**: Meta-Harness ([2603.28052v1](https://arxiv.org/html/2603.28052v1)) for the methodology backbone; MLE-bench ([2410.07095](https://arxiv.org/abs/2410.07095)), RE-Bench ([2411.15114](https://arxiv.org/abs/2411.15114)), AIDE ([2502.13138](https://arxiv.org/abs/2502.13138)), Snell test-time compute ([2408.03314](https://arxiv.org/abs/2408.03314)) for adjacent precedent.
>
> Each phase ships its own measurement deliverable. Single-metric reporting is **explicitly disallowed** — every claim must show a Pareto trade-off.

### B1. Multi-objective Pareto reporting (no single-metric claims)

Meta-Harness's "**Pareto frontier of accuracy and context cost**" is the standard. For every phase capability we report at minimum:

| Axis | Unit | Phase relevance |
|------|------|-----------------|
| **Success rate** | % task completion | A1, A3, A8 |
| **Context cost** | total prompt + output tokens / task | A1, A4, A6, A7 |
| **Wall-clock latency** | P50 / P95 seconds / task | A2, A6, A7 |
| **Tool calls** | count / task | A2, A5 |
| **Iterations to resolution** | distribution (P50, P90) | A3, A4 |
| **$ cost** | USD / task at list price | A6, A7 |

Required artifact: a Pareto **scatter plot** (success rate × context cost) with prior baseline + new variant labelled. Reject any phase claim that improves one axis while silently regressing another.

### B2. Layered task suite (search / eval split + OOD)

Following Meta-Harness ("250 search set + 200 IMO-level held-out") and MLE-bench's Kaggle 75-task selection, GEODE benchmark fixture splits:

| Tier | Task count | Source | Use |
|------|-----------:|--------|-----|
| **Search (in-distribution)** | 10 | curated agentic tasks (file ops, web fetch, multi-step reasoning) | iteration / hyper-tuning during phase development |
| **Held-out (in-distribution)** | 10 | structurally similar but disjoint | final phase claim |
| **OOD** | 10 | adversarial / underspecified / long-horizon | regression detection |

Hard rule: **never tune on held-out or OOD**. Carry-over from prior phase must be re-evaluated on the same suite — no metric movement allowed without explanation.

### B3. Baseline comparison structure

Meta-Harness's two-track comparison (hand-crafted harnesses vs program-search) maps to:

| Baseline track | What it is | Why it's the baseline |
|----------------|------------|----------------------|
| **B0 — Pre-phase GEODE** | Current `AgenticLoop` at the prior version tag | Direct ratchet — must improve or hold |
| **B1 — ReAct-only ablation** | A1 / A3 disabled, plain ReAct loop | Isolates the capability's contribution |
| **B2 — Frontier reference** | Claude Code subagent verify pattern (A3) / TodoWrite plan (A1) replayed manually on the same fixture | Establishes ceiling |
| **B3 — autoresearch-style** | Wall-clock budget + greedy ratchet on the same fixture | autoresearch P3+P4 parity check |

Each phase report **must table all four baselines**. A phase that beats B0 but trails B2 by >20% is logged as "improvement, not parity."

### B4. Trajectory storage (causal-reasoning-ready)

Meta-Harness: *"the proposer has access to all prior candidates (source code, execution traces, scores)"*. Compression to summary lost diagnostic info (38.7 vs 50.0).

Implementation hook (Phase 1+ deliverable):
- **`core/agent/trace.py`** — every step writes `{step_id, plan_snapshot, action, observation, verify_verdict, tokens, latency_ms}` to `runs/<task_id>/trace.jsonl`
- Reflexion's failure memory (A4) reads from this trace, **not** from a summarized window
- Full trace is the canonical source for the Pareto plot above

### B5. Failure-mode taxonomy (mandatory)

Every benchmark run produces a per-task verdict in one of:

| Code | Meaning | Action signal |
|------|---------|---------------|
| `OK` | task succeeded under budget | none |
| `BUDGET_EXCEEDED` | hit `max_iter` / wall-clock / token cap | tighten plan or relax budget |
| `VERIFY_REJECTED` | A3 verdict failed, no recovery | examine plan.expected vs observation gap |
| `LOOP_DETECTED` | `ConvergenceDetector` 3-strikes break | plan diversity issue |
| `TOOL_FAILURE` | external tool error after retries | error_recovery escalation gap |
| `HALLUCINATION` | verifier caught fabricated tool result | verifier strengthening needed |
| `INCORRECT` | finished, output wrong | plan / verify both miss |

**Per-class counts must appear in every phase PR's Verification section.** Trends across phases reveal which capability addresses which failure class.

### B6. Reporting format (per phase PR)

Mandatory artifacts attached to each phase PR:

1. **`docs/runs/v0.X.Y-bench.md`** — benchmark report
2. **Pareto scatter** (success × context cost) — checked-in PNG / SVG
3. **Per-baseline table** — B0/B1/B2/B3 × 6 axes
4. **Per-task verdict matrix** — task × verdict code
5. **Failure-mode delta** — counts vs. prior phase
6. **Sample trajectories** — at least 1 OK, 1 failure, hand-annotated

A phase PR without artifacts 1, 3, 4 cannot merge to develop. Items 2, 5, 6 are required for PRs that touch >100 LOC.

### B7. Statistical hygiene

- **3-sample average** for stochastic metrics (Meta-Harness's `pass@1` convention).
- **Seed pinning**: every benchmark run records the seed; comparisons across phases use matched seeds.
- **No retroactive task removal**: a fixture task only leaves the suite via an explicit retirement PR with rationale.
- **Contamination check**: when a fixture changes, prior baseline numbers are re-run, not back-ported.

### B8. Phase-specific success criteria

| Phase | Capability | Concrete success bar |
|-------|------------|----------------------|
| Phase 1 | A1 + A3 | ≥ +10% success rate **OR** ≥ −20% iterations-to-resolution on held-out, with no >5% context-cost regression |
| Phase 2 | A4 + A7 | ≥ −15% iterations distribution P90 (Reflexion claim direction) **AND** wall-clock budget enforces stop within 5% of cap |
| Phase 3 | A6 + A2 | ≥ −30% $ cost at no >5% success regression (model split) **AND** ≥ −20% tool calls / task (search) |
| Phase 4 | A5 | skill reuse rate ≥ 30% on second-pass tasks (Voyager direction) |
| Phase 5 | A8 | Pareto-dominates greedy on at least 1 of {success, context cost} on held-out — else **rejected** |

Phases that don't hit their bar **stay open** rather than ship. No "soft success" merges.

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

1. **autoresearch parity** — wall-clock budget (A7) + ratchet (existing `ConvergenceDetector`) + context budget (existing 200K guard) implemented; parallelism belongs to `SubAgentManager`/lane orchestration, not a fixed pipeline.
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
- 2026-05-06 — Benchmark Methodology section added (Meta-Harness [2603.28052v1](https://arxiv.org/html/2603.28052v1) + MLE-bench / RE-Bench / AIDE / Snell precedent). Implementation deferred — handled in another session.
