# seeds_gen1 — historical generation placeholder

This directory records the intended S12 `gen1` output location from
`docs/plans/2026-05-18-seed-generation-sprint-plan.md`. It is not the current
runtime output directory or an execution-status ledger.

## Current runtime path

- `evals/seed_generation/cli.py` builds the run under
  `core.paths.STATE_SEED_GENERATION_DIR / run_id` and prints the resolved
  directory, state file, and survivor output.
- `_registry_builder.populate_registry()` installs the picker-resolved agent
  bindings before `Pipeline.arun()`. The old empty-registry prerequisite has
  been resolved; this placeholder is not evidence that generation is blocked.
- Use `geode-eval audit-seeds generate --help` for the current operator interface.
  Live generation requires an approved run contract, resolved model/source
  bindings, and budget. No current account-quota claim is maintained here.

Read the emitted run artifacts to establish what actually executed. Historical
run plans and candidate counts do not authorize a new run or prove promotion.
Publication follows `docs/eval/external-artifact-repository.md`; do not recreate
retired output paths or rewrite frozen campaign evidence here.
