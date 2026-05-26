# autoresearch — GEODE self-improving loop driver

`autoresearch/` is **GEODE's self-improving loop driver**. Petri's
`geode audit` subprocess scores each transcript on the 20-dim alignment
rubric and emits a per-dim `mean + stderr` baseline; this driver runs
the wrapper-prompt mutation loop on top of that baseline, picking
hypotheses that push the fitness scalar up without regressing the
5 critical dims.

The 3-file shape (`prepare` / `train` / `program.md`), fixed per-run
budget, and "git as optimiser" idiom are borrowed from Karpathy's
[autoresearch](https://github.com/karpathy/autoresearch) (MIT,
2026-03, 26K+ stars). The domain is GEODE's own alignment audit —
not GPT pre-training — so `val_bpb` is replaced by the AlphaEval
fitness scalar, `fineweb` tokenisation by the Petri seed pool +
20-dim rubric, and the Muon-optimised training loop by a single
audit invocation per file edit.

## Role split — petri vs autoresearch

| Layer | Owner | Outputs |
|------|-------|---------|
| dim universe (20 names + 3 info) | `plugins/petri_audit/judge_dims/geode_judge_subset.yaml` | rubric YAML |
| per-dim raw measurement (`mean` + `stderr`, 1-10 concerning scale) | `geode audit` subprocess (LLM judge) → `core/audit/dim_extractor` | `dim_means` / `dim_stderr` dicts |
| per-run baseline (latest "good" snapshot) | autoresearch (`state/baseline.json` after promote) | promoted snapshot |
| tier classification (critical / auxiliary / info) | autoresearch (`AXIS_TIERS` in `train.py`) | constant tuples |
| weight allocation (17 + stability sum to 1.0) | autoresearch (`DIM_WEIGHTS` + `STABILITY_WEIGHT`) | constant dict |
| cross-axis gate + auto-promote rule | autoresearch (`compute_fitness` / `decide_promote`) | scalar + verdict |
| wrapper-prompt mutation candidate | self-improving-loop agent (edits `WRAPPER_PROMPT_SECTIONS`) | git commit |

Petri owns *what* gets measured; autoresearch owns *how it accrues into
fitness* and *what counts as a promote*. No code overlap — the boundary
runs through `dim_extractor` → `compute_fitness`.

## How it works

Same three-file structure borrowed from Karpathy autoresearch:

- **`prepare.py`** — Petri seed pool + AlphaEval 20-dim rubric
  existence/format sanity check and audit-harness self-test. The
  agent **does not modify** this file.
- **`train.py`** — GEODE wrapper system-prompt sections (mutation
  target) + `geode audit` subprocess invocation + AlphaEval fitness
  extraction. **The single file the agent modifies.** Section
  wording, additions, deletions, and reordering are all fair game.
- **`program.md`** — instructions to the agent. Humans modify this.

The Karpathy 5-min wall-clock budget maps onto the audit budget
(default ~5 min, capped by ChatGPT subscription quota / Anthropic API spend).
The `val_bpb` metric maps onto AlphaEval fitness — a 17-dim weighted
aggregate (5 critical + 12 auxiliary) plus a derived stability axis
(1.0 total weight, **higher = better**), with 3 info dims tracked
alongside but not weighted. `results.tsv` keeps a per-row layout but
its columns are per-tier aggregates and `fitness`; the raw 20-dim
signal lives in the companion `results.jsonl`.

Mutations to `WRAPPER_PROMPT_SECTIONS` propagate into the audit
subprocess through the `GEODE_WRAPPER_OVERRIDE` env var (which points
at `autoresearch/state/wrapper-override.json`). The GEODE runtime's
`PromptAssembler` Phase 0 reads it and replaces the wrapper base.
`--dry-run` skips the subprocess entirely so plumbing can be verified
without spending budget.

## Quick start

Requirements: `uv`, the GEODE `[audit]` extra (`inspect_ai`,
`inspect_petri`), and either `~/.codex/auth.json` (ChatGPT subscription
OAuth) or `ANTHROPIC_API_KEY`.

```bash
# 1. Install GEODE dependencies + audit extras
uv sync --extra audit

# 2. One-time seed-pool + rubric sanity check
uv run python autoresearch/prepare.py

# 3. Real audit experiment (~5 min, consumes LLM quota / API budget)
uv run python autoresearch/train.py

# 3-alt. Plumbing-only smoke (no quota / spend)
uv run python autoresearch/train.py --dry-run
```

The final `---` block on stdout carries grep-friendly metrics.

## Running the agent

Boot the self-improving-loop agent with `program.md` in context. The
boot prompt is intentionally minimal:

```
Read program.md and start a new experiment. Begin with the baseline
for this PR.
```

`program.md` is a lightweight skill — the agent reads its mutation
candidates, fitness interpretation, and loop termination conditions
from there.

## Project structure

```
autoresearch/
├── prepare.py     — seed-pool + rubric sanity check (do not modify)
├── train.py       — wrapper prompt sections + audit invocation (agent modifies)
├── program.md     — agent instructions (humans modify)
├── README.md      — this file
└── state/         — runtime artefacts (gitignored: results.tsv,
                     results.jsonl, baseline.json, …)
```

## Cross-loop handoff (P0b)

`AUTORESEARCH_SEED_SELECT` env var swaps in a directory of seed `.md`
files at audit time. The companion seed-generation writes its winning
candidates to `<run_dir>/survivors/` (a directory of symlinks) and
stamps `state.pool_path_out` to that path; a parent driver can pipe
that into `AUTORESEARCH_SEED_SELECT` so the next audit consumes the
evolved pool instead of the static tree. Unset / whitespace falls
back to the hierarchical `plugins/petri_audit/seeds/` default.

## Design choices

- **Single file to modify.** The agent only edits `train.py`. The
  mutation scope's upper bound is explicit, so every diff is
  meaningful.
- **Fixed budget.** Each audit is ~5 min wall-clock. Every hypothesis
  costs the same — apples-to-apples comparison. Roughly 12
  experiments per hour, ~100 overnight.
- **Self-contained.** No new dependencies. The existing GEODE
  `[audit]` extra is sufficient.
- **Git as optimiser.** Branch tip = best wrapper; each commit is an
  experiment; `git reset` discards a hypothesis.

## Source

- Attribution — Karpathy autoresearch (3-file pattern + fixed-budget
  loop source): https://github.com/karpathy/autoresearch (228791f);
  local reference clone at `~/workspace/autoresearch`.
- Older 6-module self-improving-loop stub (superseded by this driver):
  `docs/architecture/autoresearch.md`
- Petri evidence (gen-0 fitness signal):
  `docs/audits/2026-05-15-petri-insights.md` +
  `docs/audits/2026-05-15-autoresearch-gen0-plan.md`
- Wiring sprint plan:
  `docs/plans/2026-05-19-self-improving-loop-wiring-sprint.md`

## License

MIT (matches the Karpathy autoresearch attribution); this driver
otherwise inherits the GEODE repo's license terms.
