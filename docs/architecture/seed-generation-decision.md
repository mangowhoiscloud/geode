# ADR -- Seed Generation Architecture

> **English** | [한국어](seed-generation-decision.ko.md)

> **Status**: Accepted (2026-05-18)
> **Scope**: GEODE seed regeneration pipeline. Ports the 6-agent generate-debate-evolve loop of co-scientist (arXiv:2502.18864) onto GEODE's sub-agent infrastructure. Expands the quality + size of the Petri × autoresearch frozen seed pool (`plugins/petri_audit/seeds_safe10/`).

## Context

The Petri × autoresearch closed loop (PR #1187+#1189+#1190) is wired, but the fitness input signal is an N=10 seed × 19-dim rubric. The stderr at N=10 is 10–30% of the mean, and only 5 of the 15 substantive dims feed fitness. Both the quality (discriminative power + dim coverage + realism + stability) and the size of the seed pool need expansion.

The AI co-scientist paper's 6-agent topology (Generation / Reflection / Ranking / Evolution / Proximity / Meta-review) + Elo tournament maps 1:1 to this problem. open-coscientist (Jataware, LangGraph 1.0) has an equivalent implementation (MIT + Commons Clause).

## Decision

**Port (in-house implementation), not vendored**. Implement a **7-role topology** in-house on top of GEODE's `SubAgentManager` + `IsolatedRunner` + `AgentRegistry` + `HookSystem` + `TaskGraph` infrastructure (the paper's 6 agents + Pilot, which replaces the paper's scientist-in-the-loop slot with an automated Petri audit). No LangGraph / litellm / LangSmith dependencies are added.

**Location**: `plugins/seed_generation/` (sibling to `plugins/petri_audit/`, not nested). The sibling dependency is declared explicitly with `depends = ["petri-audit"]`.

**Full-fidelity**: all 7 roles are actually implemented (no Meta-review stub). Elo tournament + 3-judge panel + enforced provider diversity. CLAUDE.md's Socratic Q4 simplicity constraint is lifted for this sprint only (see the separate fidelity amendment doc).

### Operational defaults (settled, binding for this ADR)

| Item | Default | Rationale |
|---|---|---|
| Token budget guard | soft warning at $0.50 / sub-agent (cumulative), hard kill at $2.00 | Avoids runaway during unattended evolution. Configurable (`SEED_PIPELINE_BUDGET_SOFT_USD` / `_HARD_USD` env). |
| Pipeline run budget cap | soft $0.30 / gen, hard $1.00 / gen | Controls the worst case of tournament 60 matches × 3 judges × ~$0.02 = ~$3.6. Configurable. |
| Concurrency Lane | `seed-generation` Lane, `DEFAULT_SEED_PIPELINE_CONCURRENCY` (currently 50, raised from 16 by PR-LANE-CAP-50 2026-05-27); shares ceiling with `global` Lane (`DEFAULT_GLOBAL_CONCURRENCY` also 50) | Reduces wall-time for 50 parallel candidates + tournament matches; the per-adapter lanes at 50 share the same ceiling |
| Sub-agent recursion depth | `max_depth=1` (current SubAgentManager default) | Parent AgenticLoop as central supervisor. All 6 phases are expressible |
| Bootstrap (first generation) | `baseline=None` → cross-axis gate disabled, returns a simple weighted sum | The baseline measurement itself is the first gen's output. See ADR-002 §5 |

## Decision Drivers

- **No external dep**: GEODE core has no LangGraph. Adding LangGraph only for seed-generation makes separating it from the core awkward. The self-hosted SubAgentManager already supports 90% of the 6 phases.
- **Frozen ground-truth contract**: the seed pool cannot be mutated by the self-improving-loop agent. The pipeline is user-trigger only, a separate phase outside the autoresearch loop.
- **Co-evolution risk mitigation**: Generator + Pilot judge come from different families. Provider diversity for the 3-judge panel is enforced (minimum 2 families).
- **Compatible with the Karpathy single-file pattern**: the pipeline output is a new `plugins/petri_audit/seeds_gen<N>/` directory. autoresearch's `program.md` Setup §3 updates only the seed pool path.

## Topology

```
[user trigger] geode audit-seeds generate --target <dim> --budget 30m --gen <N>
       ↓
[Phase A] Generation × 15 (parallel sub-agent spawn)
       ↓
[Phase B] Proximity dedup (embedding + lexical + role 3-track)
       ↓
[Phase C] Reflection × survivors (per-candidate critique, dim-level)
       ↓
[Phase D] Pilot run (1 candidate × 2 model × 1 paraphrase, Petri inner-loop subset)
       ↓
[Phase E] Elo tournament (pairwise match, K=32, 3-judge panel with diversity)
       ↓
[Phase F] Evolution × top-K (Reflection-driven section rewrite) → re-pilot
       ↓
[Phase G] Meta-review (batch coverage + dim gap + next-gen prior)
       ↓
[Human gate] user explicitly approves top-N → saved to `plugins/petri_audit/seeds_gen<N>/`
```

The parent `AgenticLoop` is the central orchestrator. Within the `depth=1` limit it calls `delegate(tasks=[…])` per phase. depth=2 is unnecessary (same as the LangGraph supervisor pattern).

## Considered Options

1. **Port + GEODE-native** (✓ Accepted): in-house implementation, 0 deps, sibling plugin.
2. Vendor `open-coscientist`: ~150 LOC bridge, langgraph+litellm+langsmith 4 deps. Commons Clause license constraint. Rejected: burden of introducing LangGraph into GEODE core + license gray area.
3. Nested under `petri_audit`: `plugins/petri_audit/seed_generation/`. Rejected: bloats the manifest and blocks future separation.
4. MVP (Generation + Pilot only): Rejected: the effect requires co-scientist's generate-debate-evolve to operate as distinct stages. A partial port = stub disguise.

## Consequences

### Positive

- Zero dependency impact on GEODE core.
- Leverages the existing arsenal of HookSystem / TaskGraph / IsolatedRunner / AgentRegistry as-is; frontier-level observability + budget + sandbox capabilities apply immediately.
- A clear user-facing surface via the `geode audit-seeds` Typer sub-app.
- Separate PyPI distribution is possible later (paperclip-style).

### Negative

- ~2,000 LOC of new code + 600 LOC of UI/UX. 6-7 sprints of work.
- Parent context accumulates due to the depth=1 limit; each phase must save results to disk and keep only a summary in the conversation (using the `note_save` tool).
- 4 infrastructure reinforcements are needed up front (new Lane max=16, new `text_embed` tool, 3-judge plan_registry binding, token budget guard).

### Neutral

- Introduces a BaseSeedAgent abstraction for the 7-role topology (paper's 6-agent symmetry + GEODE Pilot). It may look like premature abstraction, but the paper's multi-way role symmetry justifies it. Stated in the fidelity amendment doc.

## Implementation pointers

- Directory layout: `plugins/seed_generation/{manifest.py, cli.py, orchestrator.py, agents/, fitness.py, tournament.py, cost_preview.py, picker.py, pre_flight.py}`
- AgentDefinition: `plugins/seed_generation/agents/{generator,critic,proximity,pilot,ranker,evolver,meta_reviewer,supervisor}.md`, 8 YAML files (CSP-9, 2026-05-22)
- Pool storage: `plugins/petri_audit/seeds_gen<N>/` (frozen, monotonic gen-suffix). `seeds_safe10` is preserved.
- Runtime artifacts: `~/.geode/seed-generation/<run_id>/` (gitignored).
- Audit trail: `https://github.com/mangowhoiscloud/geode-eval-artifacts/blob/main/sil/audit-reports/seed-generation-runs/<YYYY-MM-DD>/` (committed).

## References

- AI co-scientist paper -- arXiv:2502.18864 (Google Research, 2025-02-26)
- open-coscientist v0.2.0 -- https://github.com/jataware/open-coscientist (reference only, not vendored)
- AlphaEval 5-axis (parity dropped, see ADR-002) -- arXiv:2508.13174
- GEODE SubAgentManager -- `core/agent/sub_agent.py:1-114`
- Petri inner-loop -- `plugins/petri_audit/` (P1-A~G manifest pattern)
- Outer-loop SOT -- `core/self_improving/program.md`
- Petri × autoresearch closed-loop -- `[[project_autoresearch_self_improving_loop]]`
- Plan A revised cumulative meeting notes -- the preceding 4 reports (Plan A vs B, infrastructure assessment, UI/UX integration, folder layout)
