# seeds_gen1 — first co-scientist generated batch

This directory will hold the first `gen1` batch of Petri seeds produced
by the seed-pipeline orchestrator (`plugins/seed_pipeline/`). It is the
output of the S12 generation run (sprint plan
`docs/plans/2026-05-18-seed-pipeline-sprint-plan.md`).

## Current status

**EMPTY — awaiting first run.** S12 ships the scaffolding (this
directory + the run-book at
`docs/audits/seed-generation-runs/2026-05-18/`) but the actual
generation is deferred behind one prerequisite + one external
constraint:

1. **PipelineRegistry agent factories** — `plugins/seed_pipeline/cli.py`
   `_dispatch_pipeline()` currently builds an empty
   `PipelineRegistry`, so `Pipeline.run()` raises a `RuntimeError("no
   registered agent")` on the first phase. The 7 concrete agents
   (Generator, Critic, Proximity, Pilot, Ranker, Evolver,
   MetaReviewer — all S2-S8) need to be instantiated with their
   resolved `RoleBinding` from the picker and registered before
   `geode audit-seeds generate` can produce real seeds.

2. **Credit availability** — the user has flagged Anthropic credits
   as currently constrained (Session 60-62 baseline retry notes).
   When credits become available the operator can execute the
   run-book below; until then the gate flow + cost preview + slash
   command are all exercisable end-to-end with the empty registry to
   verify the operator experience.

## Once the prereqs land

See `docs/audits/seed-generation-runs/2026-05-18/run-book.md` for the
step-by-step procedure. Expected output: 15 candidate `.md` files
named `<gen_tag>-<uuid>.md`, frontmatter declaring `target_dim`,
selected via the Ranker top-K (`survivors_k=5`) AND optionally the
Evolution agent's section-rewrite variants. After human ratification,
the surviving seeds are promoted into `seeds_safe<N>/` and the
`autoresearch/state/baseline.json` is refreshed from the audit's
dim_means/dim_stderr.
