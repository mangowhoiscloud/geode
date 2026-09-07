# GEODE self-improving loop: ownership and execution

The outer loop searches over GEODE's scaffold, not model weights. Petri measures
candidate behavior; the search loop uses that evidence to accept or reject a
candidate. A better observed score is not a guarantee of general improvement.

The maintained agent instruction is
[program.md](../../evolve/scaffold_search/program.md). This page maps owners;
it does not duplicate the scoring formula, model defaults, or experiment budget.

## Role split — petri vs autoresearch

| Responsibility | Current owner |
|---|---|
| Judge rubric and fitness dimensions | `evals/petri/judge_dims/geode_judge_subset.yaml`, `evals/petri/dimensions.py` |
| Raw per-dimension evidence | `evals/petri/`, `core/audit/dim_extractor.py` |
| Audit invocation and role configuration | `evolve/scaffold_search/measure.py`, `evals/config.py` |
| Fitness computation | `evolve/scaffold_search/fitness.py` |
| Promotion decision and candidate recovery | `evolve/scaffold_search/gate.py` |
| Baseline and result persistence | `evolve/scaffold_search/ledger.py` |
| Mutation-policy state | `evolve/scaffold_search/loop/mutate/policies.py` |
| Runtime policy injection | `core/agent/policy_injection/`, `core/agent/system_prompt.py` |

Read the owner when changing a contract. In particular, use
`ledger.RESULTS_TSV_HEADER` for TSV fields instead of copying a second schema.
Judge dimensions and weighted fitness dimensions are different sets.

## How it works

The Karpathy-style `prepare` / `train` / `program.md` shape separates frozen
measurement from candidate edits. `prepare.py` validates the measurement setup;
`train.py` invokes the experiment; `program.md` limits the operator's actions.
The calculation and persistence helpers in the table above remain measurement
apparatus, not extra mutation targets.

Wrapper candidates reach the audit through the selected policy sources;
`core.agent.system_prompt` assembles those sections into the runtime prompt.
`--dry-run` tests the plumbing with synthetic evidence, not a publishable score.

## Quick start

Use [campaign quick start](campaign-quick-start.md) for setup and
[campaign procedure](campaign-procedure.md) for execution. Live target, auditor,
and judge calls require an explicit run contract, credentials, and budget.
An external coding-agent subscription does not establish entitlement for every
evaluation role.

For an authorized offline plumbing check in an installed checkout:

```bash
uv run python -m evolve.scaffold_search.train --dry-run
```

## Running the agent

Start in an owned worktree and load the full path
`evolve/scaffold_search/program.md`. Follow the frozen run scope and stop
conditions; do not inherit an indefinite campaign from a historical example.
[Mode A](../operator-mode-a.md) explains external-agent operation.

## Project structure

Code and the agent program live under `evolve/scaffold_search/`.
`core.paths.AUTORESEARCH_STATE_DIR` owns versioned policy and ledger paths;
`core.paths.RUNTIME_ROOT` owns machine-local runtime evidence and scratch.
Inspect [core/paths.py](../../core/paths.py) and the run's state-root overrides
before reading, writing, or cleaning either location. A worker override may
isolate both homes; a memorized home-directory path is not ownership proof.

## Cross-loop handoff (P0b)

`AUTORESEARCH_SEED_SELECT` selects the seed directory consumed by an audit.
The seed-generation output records its selected pool; preserve candidate,
survivor, and attempt lineage rather than deduplicating away selection evidence.
Freeze the selected pool before comparing candidate and baseline results.

## Design choices

- Mutate only the candidate surface selected in the run contract.
- Keep measurement, replication, budget, and promotion authority separate.
- Preserve rejected attempts; use scoped recovery instead of erasing history.
- Reuse the current measurement and persistence owners rather than duplicating
  their formulas in another guide.

## Source

The [earlier architecture spec](../architecture/autoresearch.md) is historical.
Dated Petri reports are routed through the
[artifact repository index](../eval/external-artifact-repository.md).
The three-file pattern is attributed to
[Karpathy autoresearch](https://github.com/karpathy/autoresearch).

## License

MIT (matches the Karpathy autoresearch attribution); this driver
otherwise inherits the GEODE repo's license terms.
