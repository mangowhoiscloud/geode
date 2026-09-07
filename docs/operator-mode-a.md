# Mode A: an external agent operates the scaffold-search loop

Mode A uses a separately authorized Claude Code or Codex session to propose
and inspect mutations. Mode B uses GEODE's configured mutator. Both consume
the same runtime evidence and policy owners; changing the operator does not
grant extra tool permissions, budget, or promotion authority.

Mode B's single-mutation entry point is `geode-evolve scaffold run`.
Hosts that register evolution slash commands expose the same dispatcher as
`/self-improving run`; neither entry point expands the approved run contract.

## Before a run

Read [the maintained experiment program](../evolve/scaffold_search/program.md)
and [campaign quick start](self-improving/campaign-quick-start.md). Keep the
run's task/pool, models and credential sources, verifier, budget, and stop
conditions explicit before any live audit. Subscription access by the external
agent does not establish free access for Petri's target or judge.

Use an owned, isolated worktree from fetched `origin/develop` following
[GitFlow allocation](../.agents/skills/geode-gitflow/SKILL.md#worktree-allocation).
Do not switch the root checkout or reuse another session's branch. Inspect
existing dirty files before any candidate edit or rollback.

A suitable starting request is:

```text
Read evolve/scaffold_search/program.md and the frozen run contract.
Verify the owned worktree, mutation scope, and measurement setup.
Run only the authorized experiment budget, preserving evidence and reporting
any ownership, credential, billing, or source-integrity blocker.
```

## Contracts, not duplicated recipes

- Mutation scope and experiment termination:
  [program.md](../evolve/scaffold_search/program.md).
- Policy, measurement, and state ownership:
  [loop overview](self-improving/loop-overview.md).
- Campaign execution and evidence:
  [campaign procedure](self-improving/campaign-procedure.md).
- Rollback: preserve the rejected attempt and apply the owner's explicit
  candidate-revert path. Do not discard unrelated edits or erase a ledger.
- Integration and cleanup: use the repository GitFlow only when requested;
  a completed experiment does not authorize pushing, merging, or deleting its
  worktree.

The [2026-05-21 design](plans/2026-05-21-self-improving-loop-ux.md) preserves
the original Mode A/Mode B comparison. Its retired `autoresearch/` paths,
branch-switch recipes, and historical cost estimates are not current commands.
