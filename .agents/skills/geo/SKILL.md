---
name: geo
description: Design, implement, or evaluate GEODE's GEO capability with source-grounded stage diagnosis, frozen measurement contracts, and no-model preflight before live engine runs.
---

# GEODE GEO scaffold

Use this scaffold for repository work on `/geo`, generative discovery, AI-search
visibility, citations, or the GEO benchmark.

1. Read `.geode/skills/geo/SKILL.md` for the runtime behavior contract.
2. Read `docs/eval/geo-visibility.md` before defining a metric or run. Freeze a
   prospective run spec before any score-bearing commercial-engine call.
3. Read `docs/plans/2026-08-22-slash-control-enforcement.md` for typed state,
   then `docs/plans/2026-08-20-slash-goal-geo.md` before changing slash routing,
   planning authority, or Goal coupling.
4. Diagnose the exact stage and preserve its denominator:
   `F` fetch/index eligibility, `R` retrieval inclusion/rank, `C` citation
   selection, `P` visible placement/rank, `A` answer absorption, `Q`
   support/credibility/answer quality, and `O` first-party outcome. Preserve
   `not_measured`; never collapse the vector into one GEO score.
5. Run deterministic site preflight and relevant unit/E2E checks before asking
   for live-test approval. Never infer organic lift from a fixed-context test.
   Model tool calls cannot mint approval or preregistration receipts; exercise
   the operator-owned `/geo approve-live <receipt>` and `/geo preregister
   <receipt>` boundaries in state-machine tests. Require phase-bound evidence
   before each transition. Permit diagnostic completion from `live_observe`;
   require `experiment` only for a preregistered treatment claim.
6. Confirm `.geode/skills/geo/SKILL.md` is the runtime source selected by
   `SkillLoader`; use `get_geo`/`update_geo` as the state authority. Record
   primary sources, facts, inferences, unobserved stages, repetitions,
   locale, account state, and timestamps in the result.

## Long-running execution

For broad or explicitly long-running work, represent progress as a verifiable
evidence frontier: questions, dependencies, source locators, contradictions,
failed attempts, uncertainty, and unvisited leads. Do not store or expose hidden
chain-of-thought.

1. Keep deterministic preflight, prerequisites, synthesis, verification, and
   every write in the parent AgenticLoop.
2. Send at most three independent read-only branches through the existing
   `delegate_task` batch. Use durable `spawn_agent` only when a branch must be
   steered across waits. Keep prerequisite branches serial and children depth
   one. Built-in role workers inherit the parent's active model and credential
   source unless an explicit binding is part of the run contract.
3. Join all branches before synthesis. Bound each result to claims, evidence
   locators, contradictions, confidence, and unresolved gaps; do not copy raw
   logs into the parent context.
4. At each wave boundary, checkpoint evidence, uncertainty, failures, and
   unvisited leads. Treat the checkpoint as revisable, not as authority.
5. Permit one focused follow-up wave for a material gap or contradiction. Stop
   when required coverage, new primary evidence, and contradiction resolution
   cease improving.
6. Gate URL reachability, file facts, counts, hashes, citation locators, and
   benchmark invariants with deterministic checks. Same-model critique is not
   a truth oracle.

Reuse `SkillRegistry → AgenticLoop` plus the existing collaboration tools. Do
not add a GEO-only executor, natural-language subcommand parser, coordinator,
generic Tree-of-Thought/MCTS engine, or TaskGraph coupling without benchmarked
need.

For execution-strategy changes, compare the frozen A/B/C profiles in
`docs/eval/geo-visibility.md` with repeated runs; a single smoke cannot establish
that longer or parallel execution is better.

## Trajectory and publication

Keep the native result, verifier receipt, attempt lineage, normalized behavior,
and publication decision as separate authorities. Do not manufacture an
Inspect `.eval` archive from a GEODE slash transcript: bind `.eval` only when
Inspect produced it. For ordinary `/geo` runs, export the parent and every child
from canonical `sessions.db` as `geode.trajectory@1` with digested content.

Treat terminal transcripts, messages, evidence JSONL, worker results,
SQLite/WAL, profiles, usage, diagnostics, provider bodies, and hidden reasoning
as `withheld-private` by default. After an exact-byte privacy review, stage only
scope-complete normalized trajectories with
`geode session stage-trajectory-release`; use the explicit
`--allow-replay-incomplete` gate for reviewed content-digested releases. Copy
only the allowlisted release and reviewed aggregate sidecars into a fresh
`geode-eval-artifacts` PR, then bind the remote merge commit and manifest digest
back into the GEODE eval ledger after independent read-back. Never recursively
mirror a runtime home or artifact root.
