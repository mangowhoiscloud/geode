# autoresearch — Petri-signal fork (GEODE)

A GEODE Petri-domain fork of Karpathy's
[autoresearch](https://github.com/karpathy/autoresearch) (MIT, 2026-03,
26K+ stars — a single-file ML training loop). The original
3-file pattern (`prepare` / `train` / `program.md`), fixed-budget
loop, and "git as optimiser" philosophy are kept verbatim; the domain
is swapped from ML (GPT pre-train + `val_bpb`) to alignment auditing
(Petri seed pool + AlphaEval fitness).

## Why fork instead of port

The 3-file constraint Karpathy keeps so small is **the** design.
The outer-loop agent (Claude Code / Codex) advances research by
mutating a single file and grepping a few metrics. If GEODE's
outer loop can pass through the same constraint, the cost frontier of
self-improvement simplifies sharply. This fork places an equivalent
single-mutation file (`train.py`) and a read-only harness
(`prepare.py`) inside the GEODE tree to reuse exactly that loop
pattern.

## How it works

Same three-file structure as the original:

- **`prepare.py`** — Petri seed pool + AlphaEval 20-dim rubric
  existence/format sanity check and audit-harness self-test. The
  agent **does not modify** this file.
- **`train.py`** — GEODE wrapper system-prompt sections (mutation
  target) + `geode audit` subprocess invocation + AlphaEval fitness
  extraction. **The single file the agent modifies.** Section
  wording, additions, deletions, and reordering are all fair game.
- **`program.md`** — instructions to the agent. Humans modify this.

The original's fixed 5-min wall-clock budget becomes the audit budget
(default ~5 min, capped by ChatGPT Plus quota / Anthropic API spend).
The original's `val_bpb` metric becomes AlphaEval fitness — a 17-dim
weighted aggregate (5 critical + 12 auxiliary) plus a derived
stability axis (1.0 total weight, **higher = better**), with 3 info
dims tracked alongside but not weighted. `results.tsv` keeps the same role but
its columns are now per-tier aggregates and `fitness`; the raw 20-dim
signal lives in the companion `results.jsonl`.

Mutations to `WRAPPER_PROMPT_SECTIONS` propagate into the audit
subprocess through the `GEODE_WRAPPER_OVERRIDE` env var (which points
at `autoresearch/state/wrapper-override.json`). The GEODE runtime's
`PromptAssembler` Phase 0 reads it and replaces the wrapper base.
`--dry-run` skips the subprocess entirely so plumbing can be verified
without spending budget.

## Quick start

Requirements: `uv`, the GEODE `[audit]` extra (`inspect_ai`,
`inspect_petri`), and either `~/.codex/auth.json` (ChatGPT Plus
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

Boot the outer-loop agent with `program.md` in context. The
Karpathy-style prompt translates directly:

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
                     results.jsonl, baseline.json, audit_logs/, …)
```

## Cross-loop handoff (P0b)

`AUTORESEARCH_SEED_SELECT` env var swaps in a directory of seed `.md`
files at audit time. The companion seed-pipeline writes its winning
candidates to `<run_dir>/survivors/` (a directory of symlinks) and
stamps `state.pool_path_out` to that path; a parent driver can pipe
that into `AUTORESEARCH_SEED_SELECT` so the next audit consumes the
evolved pool instead of the static tree. Unset / whitespace falls
back to the hierarchical `plugins/petri_audit/seeds/` default.

## Design choices (preserved from the original)

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

- Karpathy autoresearch: https://github.com/karpathy/autoresearch (228791f)
- Local reference clone: `~/workspace/autoresearch`
- GEODE outer-loop spec (older 6-module stub, replaced by this fork):
  `docs/architecture/autoresearch.md`
- Petri evidence (gen-0 fitness signal):
  `docs/audits/2026-05-15-petri-insights.md` +
  `docs/audits/2026-05-15-autoresearch-gen0-plan.md`
- Wiring sprint plan:
  `docs/plans/2026-05-19-outer-loop-wiring-sprint.md`

## License

MIT (matches the upstream). The fork inherits the GEODE repo's
license.
