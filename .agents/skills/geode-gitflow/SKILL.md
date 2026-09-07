---
name: geode-gitflow
description: Prepare GEODE worktrees, Korean PRs, CI-gated merges, and guarded cleanup. Use for repository branch, commit, PR, merge, or release work; apply only the stages the user authorized.
---

# GEODE Git & PR Workflow

Apply only the stages authorized by the current request. Review or local edits
do not authorize commit, push, merge, cleanup, reinstall, or runtime restart.
The [workflow](../../../docs/workflow.md) owns development phases;
this skill owns the GitFlow procedure. Read `AGENTS.md` for repository guardrails.

## Merge Flow

| Transaction | Base and head | Merge method |
|---|---|---|
| Feature, fix, or release preparation | fetched `origin/develop` → topic branch → `develop` | squash |
| Canonical pre-sync | current `main` → `develop`, or the trusted conflict-resolution head below | merge |
| Promotion | `develop` → `main` | merge |

Never push directly to `main` or `develop`. Promotion can batch verified
features; it does not itself authorize a tag, package publication, installation,
or service restart. `[Unreleased]` may remain on main.

## Worktree Allocation

Inspect `git status --short --branch`, `git worktree list`, and any `.owner`
before editing. Continue in the correct existing worktree when available;
read-only inspection does not require allocating another checkout.

For a new implementation worktree:

```bash
git fetch origin
git worktree add .claude/worktrees/<task-name> \
  -b feature/<branch-name> origin/develop
```

Use the host's branch prefix when specified. Record the current session and
`task_id=<task-name>` in the gitignored `.owner` file using the available file
editor. Do not overwrite another session's ownership record, change branches
inside a worktree, or move a checkout held by another session. Fetching does
not update a checked-out local `develop`; allocate from the remote-tracking tip.

### Architecture Ledger

Ordinary tracking documents are maintained from `main`. Architecture-program
exceptions and status transitions belong to
[`extensibility-roadmap.md` §0.3](../../../docs/architecture/extensibility-roadmap.md).
Read that section only when the task participates in the program.

Implementation starts from `origin/develop` after its package-atomic claim is
merged there. It preserves `IN_PROGRESS`; no prospective `IN_DEVELOP` or `DONE`.
The roadmap-only readiness, claim, registration, reconciliation, and full-ledger
audit paths use the roadmap's own prerequisites, not an extra implementation
claim. Tracking-only `DONE` work starts from `origin/main`, targets `main`,
carries no implementation, and is followed by a CI-gated main-to-develop sync.
Do not turn an ordinary bug or documentation fix into a new architecture program.

## Pre-PR Quality Gate

Use [verification-gates.md](../geode-workflow/references/verification-gates.md)
to select local checks by changed behavior and risk. `scripts/preflight.sh` is
the existing broad local gate runner; `--fast` skips tests and site generation.
Report skipped checks explicitly. Neither a targeted pass nor `--fast` proves
the full suite passed, and local checks never replace required remote CI.

Reuse passing evidence while the relevant code, configuration, dependencies,
and environment are unchanged. Rerun or broaden for a new change, failed check,
or unresolved concern—not merely because another workflow stage was reached.
Never hide exit codes with `gate | tail`, `gate | grep -c`, or `check; merge`.

Functional commits include their `CHANGELOG.md` entry and necessary user-facing
documentation. Documentation-only corrections need no artificial code commit
or version bump. Regenerate affected derived artifacts through their existing
generators; do not hand-edit generated snapshots. Stage only in-scope paths.

## PR Body Template

Use the single [repository PR template](../../../.github/PULL_REQUEST_TEMPLATE.md).
Write the title and body in Korean, keep titles under 70 characters, and assign
`mangowhoiscloud`. Keep `Summary`, `Why`, `Changes`, and `Verification`; fill them
from the actual diff against the fetched target branch and executed checks.
Group related files when that is clearer than repeating one sentence per file.

Add a GAP Audit table for audit-driven work. Include design choices, compatibility,
migrations, external sources, or live-test limitations only when relevant.
Promotion PRs identify included PRs, the pre-sync result, and head-specific CI;
they link feature evidence instead of copying its whole report. Do not pre-check
unrun gates, fabricate counts, or attribute work to a tool/model that did not do it.

Prepare a Markdown body file with the editor and pass `--body-file <path>` to
`gh pr create`; a safely quoted heredoc is also valid. The transport is not a
quality rule—preserve the rendered body and inspect it after creation.

```bash
gh pr create --base develop --head <topic-branch> \
  --assignee mangowhoiscloud --title "<type>: <한국어 설명>" \
  --body-file <pr-body.md>
```

## Post-PR CI Ratchet

Before every merge, confirm the current PR head, base, mergeability, and actual
required check results. Zero attached checks, an unknown result, pending work,
or a failed/cancelled/timed-out required check is not green. An intended skip is
acceptable only when repository policy permits it and the required gate passes.

```bash
gh pr checks <PR#> --watch --repo mangowhoiscloud/geode
gh pr view <PR#> --repo mangowhoiscloud/geode \
  --json headRefOid,baseRefName,mergeable,statusCheckRollup
```

Run these as inspected steps, not as an unconditional command chain followed
by merge. Preserve command failures. Use a bounded watcher when waiting;
report meaningful state changes rather than polling an unchanged failure.
On failure, inspect `gh run view <run-id> --log-failed`, fix the actual cause,
verify affected behavior, push the scoped fix, and wait for the new head's CI.
Do not delete tests or suppress a security finding merely to get green.

Once authorized and verified, merge remotely with the method from
[Merge Flow](#merge-flow), pinning the exact head that passed. For a topic PR
into develop:

```bash
gh api --method PUT repos/mangowhoiscloud/geode/pulls/<PR#>/merge \
  -f merge_method=squash \
  -f sha=<verified-full-head-sha>
```

For canonical sync or develop-to-main promotion, use `-f merge_method=merge`.
Require the response to report `merged: true`, then read the merged PR and
record its merge SHA. A changed head requires fresh verification. Never use
`--admin` to bypass gates or `gh pr merge --delete-branch` inside a linked
worktree: GitHub CLI may switch that checkout while deleting the local branch.
The guarded cleanup below owns branch/worktree deletion.

### Concurrent-session drift & CI-trigger recovery

Serialize develop merges. After another merge, fetch and inspect the actual
content, ancestry, mergeability, and CI before deciding an update is needed.
Commit-count asymmetry alone does not require rebasing every waiting worktree.

For a conflicting feature PR, merge current `origin/develop` in its owned
worktree, preserve concurrent changes, stage only resolved in-scope paths, and
rerun affected checks plus required CI on the new head. Do not rewrite another
session's branch. Only an authorized release changes version stamps; verify the
version remains available and regenerate affected metadata after resolving it.
Ordinary fixes stay under `[Unreleased]`.

If a new PR has no checks, inspect Actions availability, applicable workflow
events/path filters, and the current head's check-runs API before treating it as
a missed event. An outage is not a code failure. After confirming a missed
`pull_request` event and authorized PR operation, close/reopen once to regenerate
the event, then verify new runs attached. If checks remain absent, report the
specific blocker instead of repeating mutations or treating absence as success.

### Deliberate main-to-develop pre-sync

Before every `develop -> main` promotion, fetch both protected branches and
compare content and ancestry. If main has commits not in develop and the sync is
conflict-free, open a CI-gated PR directly from the current `main` head to
`develop`. Do not put a fast-forwarded copy of main behind a trusted sync prefix.

If conflicts require a separate worktree, create
`sync/main-into-develop-<task>` from current `origin/develop` and explicitly merge
current `origin/main`. Its head must have exactly two parents, in this order:
current `origin/develop`, current `origin/main`. Immediately before merge,
fetch and rerun the trust resolver from that sync worktree:

```bash
git fetch origin
uv run python scripts/resolve_architecture_roadmap_trust.py \
  --event-mode pull_request --target-branch develop \
  --head-ref "sync/main-into-develop-<task>" \
  --head-repo mangowhoiscloud/geode --repository mangowhoiscloud/geode \
  --head-sha "$(git rev-parse HEAD)" --require-trust main
```

For a direct-main sync, use `--head-ref main` and the current canonical main SHA.
The resolver must pass for that exact head. If either tip invalidates the trust
proof, reconstruct from the new tips and rerun CI; an earlier green is stale.
After sync, promote current develop through a separate CI-gated merge PR.

## Release Flow

Only when a release is requested, create its worktree from `origin/develop`,
prepare version stamps and promote the changelog under
[`geode-changelog`](../geode-changelog/SKILL.md), then squash into develop.
Leave a fresh `[Unreleased]` heading. Perform the canonical pre-sync above and
promote develop to main with a merge commit. Release preparation does not bypass
CI or add an automatic post-release backmerge; main-owned tracking may still
require its own sync transaction.

Tags, GitHub Release, PyPI publication, and installed-version verification follow
[`geode-distribution`](../geode-distribution/SKILL.md) only when authorized.
Inspect the affected workflow's actual trigger before promising deployment;
do not infer publication from a merge SHA or static workflow description.

## Post-Merge Cleanup

After an owned feature PR merges and the checkout is no longer needed, run the
guarded command from outside the target worktree:

```bash
uv run python scripts/check_repo_hygiene.py free-merged-worktree \
  --pr <feature-pr> --worktree .claude/worktrees/<task-name>
```

It verifies the merged PR and final head, replays that head onto the merge's
base to compare the resulting tree, checks local ancestry and remote head,
requires a clean checkout, and validates `.owner.task_id`. It then removes the
remote branch, worktree, and squash-only local branch and prunes. The owner
record's task-name check is not proof that another active session has released
the checkout; confirm current session ownership first. Use `--dry-run` when
inspection is needed. A refusal requires investigation, never manual force.

After promotion, verify fetched branch content and the actual requested CI or
deployment result. Reuse unchanged docs/test evidence; investigate drift if the
merged result differs. Update tracking only when in scope, through its owning
workflow. Report PRs, merge SHAs, verification, skipped work, and cleanup results.

## Rebuild & Restart

A merge does not authorize changing global installations or running services.
When deployment or restart is explicitly in scope:

1. Resolve the intended installation, checkout, process identity, and owner.
   Inspect `core/cli/commands/lifecycle.py` before selecting the operation;
   a process-name match alone does not establish ownership.
2. Stop only the confirmed in-scope process. Do not use broad `pkill -f`, stop
   another session, or hide a failed stop with `|| true`.
3. Install the requested channel and extras under the distribution contract.
   Editable global installation and `[audit]` are not ordinary runtime defaults.
4. Verify version, process identity, and the requested smoke result. If ownership
   or restart authority is unclear, preserve the artifact and ask for direction.
