# 2026-05-18 — seed-generation gen1 run-book

> First scheduled execution of the seed-generation orchestrator end-to-end.
> Treated here as a run-book (operator-followable procedure) rather than
> a finished artifact, because two prerequisites remain open. See the
> "Prerequisites" section below.

## Status

**Run-book authored, execution deferred.** S12 (sprint plan
`docs/plans/2026-05-18-seed-generation-sprint-plan.md`) ships this
document + the empty `plugins/petri_audit/seeds_gen1/` directory; the
actual run waits on the two prerequisites.

## Prerequisites

| Item | Tracked as | Status |
|------|-----------|--------|
| PipelineRegistry agent-factory wiring | S11-wire (implicit) | Pending |
| Anthropic credit availability | external | Constrained per Session 60-62 |

> Note: the prior **BudgetGuard worker-side propagation** entry was
> removed in PR 1 (2026-05-18). The hard-cap budget layer is gone;
> spend control is now the pre-run cost preview + human gate.

## Procedure (when prerequisites are green)

### 1. Picker dry-run

```bash
uv run python -c "
from plugins.seed_generation.picker import pick_bindings
from plugins.seed_generation.cost_preview import estimate_cost, format_cost_summary
pr = pick_bindings(auto_probe=True)
print(format_cost_summary(estimate_cost(pr, candidate_count=15)))
"
```

Confirms: (a) every role resolves to a concrete `(family, source)`
binding, (b) the cost estimate sits within the `$2.00 soft / $10.00
hard` per-phase budget. If subscription paths are in use, the ToS
notice prints once.

### 2. Pre-flight gate

```bash
uv run python -c "
from plugins.seed_generation.picker import pick_bindings
from plugins.seed_generation.pre_flight import run_pre_flight
report = run_pre_flight(pick_bindings(), soft_usd=2.0, hard_usd=10.0)
for issue in report.issues:
    print(issue.severity, issue.code, issue.message, '|', issue.fix)
print('has_errors:', report.has_errors)
"
```

`has_errors: False` is required before proceeding.

### 3. Generation run (`geode audit-seeds`)

```bash
geode audit-seeds generate \
  --target-dim broken_tool_use \
  --gen-tag gen1 \
  --candidates 15 \
  --soft-usd 2.00 \
  --hard-usd 10.00
```

The CLI surfaces the cost preview + pre-flight report and prompts for
`yes` to proceed. Drop `--yes` from this first run so the human gate
is exercised; the operator should READ the preview before confirming.

After the prompt, the orchestrator walks all 7 phases (Generator →
Proximity → Critic → Pilot → Ranker → Evolver → MetaReviewer) and
writes the run state to `~/.geode/seed-generation/gen1-broken_tool_use/`.

### 4. Inspect the run artifacts

| Artifact | Location |
|----------|----------|
| state.json (S8 offload) | `~/.geode/seed-generation/gen1-<dim>/state.json` |
| elo_log.tsv (S6) | `~/.geode/seed-generation/gen1-<dim>/elo_log.tsv` |
| candidates_*/ | `~/.geode/seed-generation/gen1-<dim>/candidates/`, `candidates_evolved/` |
| meta_review | state.json `meta_review` key |

### 5. Promote surviving candidates

```bash
# Inspect state.json → meta_review.session_summary
jq .meta_review ~/.geode/seed-generation/gen1-broken_tool_use/state.json

# Promote the top-K survivors into plugins/petri_audit/seeds_gen1/
for survivor in $(jq -r .survivors[] state.json); do
  cp ~/.geode/seed-generation/gen1-broken_tool_use/candidates/${survivor}.md \
     plugins/petri_audit/seeds_gen1/
done
```

### 6. Refresh autoresearch baseline (post-S9)

```bash
# Trigger one audit on the new seeds_gen1 pool to seed baseline.json
geode audit --seed-select plugins/petri_audit/seeds_gen1 --dim-set subset --live

# The audit emits a summary JSON with dim_means + dim_stderr;
# write the post-S9 schema (no axes wrapping) to:
cat > autoresearch/state/baseline.json <<EOF
{
  "dim_means":  { ... },
  "dim_stderr": { ... }
}
EOF
```

### 7. Commit + tag

```bash
git add plugins/petri_audit/seeds_gen1/
git commit -m "data: seed-generation gen1 — N survivors for <target_dim>"
git tag autoresearch/2026-05-XX-seeds-gen1
```

`autoresearch/state/baseline.json` is gitignored — treat the tag as
the reproducible marker for "this audit run defined the baseline."

## Definition of done

- `plugins/petri_audit/seeds_gen1/` contains 5+ promoted survivors.
- `autoresearch/state/baseline.json` exists with the new schema
  (`{"dim_means": ..., "dim_stderr": ...}`).
- `~/.geode/seed-generation/gen1-<dim>/state.json` archived alongside
  this run-book at `docs/audits/seed-generation-runs/2026-05-18/`.
- An updated `session_summary` paragraph (from the MetaReviewer
  output) is pasted into a follow-up session handoff note.

## Cost expectation

Per S6.5 cost preview with default (15 candidates × 3-judge × ~59
matches):

- claude-cli / openai-codex (subscription) ≈ $1.50 quota-equivalent
- api_key (PAYG) ≈ $1.00–$1.50

Total: under $3 per generation. The $10 hard cap per phase is the
safety net.
