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
| Feature, fix, or release preparation | fetched `origin/develop` → topic branch → `develop` | merge |
| Main drift | current `main` → the existing topic branch, before its PR merges | local merge commit, then fresh PR CI |
| Promotion | `develop` → `main` | merge |

Never push directly to `main` or `develop`. Promotion can batch verified
features; it does not itself authorize a tag, package publication, installation,
or service restart. `[Unreleased]` may remain on main.

### Don't cases

- **Don't squash or rebase a PR.** Both discard the reviewed head's ancestry.
  Use a merge commit for feature integration, synchronization, and promotion.
- **Don't open a separate `main -> develop` or `sync/*` PR.** Include missing
  main commits in the existing feature branch before integration. CI and the
  merge guard reject those standalone sync heads.
- **Don't run an old checkout's merge guard after fetching.** Fetch refreshes
  remote refs, not local instructions or scripts. Inspect the guard in the
  owned, current worktree; a stale `main` checkout is not the policy authority.
- **Don't confuse `--merge` with a method guarantee.** Older guards used that
  flag only to authorize the write and still sent `merge_method=squash`.
- **Don't treat green CI or a merged PR as proof of preserved history.** Check
  the result's ordered parents against the admitted base and head. An uncertain
  write/readback requires inspection, not retry, cleanup, or a success claim.

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
carries no implementation; the next owned feature branch incorporates that
main history before integration.
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
Promotion PRs identify included PRs, the main-ancestry result, and head-specific CI;
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
or a failed/cancelled/timed-out/skipped/neutral required check is not green.
An inapplicable inner step may skip only when explicit change detection permits
it and the enclosing required check completes successfully.

```bash
gh pr checks <PR#> --watch --repo mangowhoiscloud/geode
gh pr view <PR#> --repo mangowhoiscloud/geode \
  --json headRefOid,baseRefName,mergeable,statusCheckRollup
uv run python scripts/merge_pr.py --pr <PR#>
```

Run these as inspected steps, not as an unconditional command chain followed
by merge. Preserve command failures. Use a bounded watcher when waiting;
report meaningful state changes rather than polling an unchanged failure.
On failure, inspect `gh run view <run-id> --log-failed`, fix the actual cause,
verify affected behavior, push the scoped fix, and wait for the new head's CI.
Do not delete tests or suppress a security finding merely to get green.

The read-only merge guard requires the live repository settings
`allow_merge_commit=true`, `allow_squash_merge=false`, and
`allow_rebase_merge=false`. These [GitHub repository settings](https://docs.github.com/en/rest/repos/repos#update-a-repository)
also reject obsolete squash requests from other checkouts or the UI. Only an
authorized operator changes them; the guard never repairs server policy itself.

The guard checks the current head and base, current PR-linked
required GitHub Actions evidence (app 15368), and server protection: strict
up-to-date checks, administrator enforcement and no force-push/deletion bypass. It rejects
missing or ambiguous evidence rather than interpreting an empty list as green.
Pages Render lint and Build are required alongside CI and both install-smoke
platforms; Deploy is intentionally not a PR check. A green CI Gate alone is
insufficient when Pages fails.

Once authorized, use the same guard's explicit merge mode. It rereads the
snapshot immediately before the head-pinned REST request and verifies the
merged PR afterward, including exactly two ordered commit parents: the verified
base SHA, then the PR head SHA. Its receipt retains the returned merge SHA even
when that readback is unavailable or mismatched; do not retry an uncertain write.

```bash
uv run python scripts/merge_pr.py --pr <PR#> --merge
```

The guard chooses merge for feature-to-develop PRs and develop-to-main promotion.
It requires the current main SHA to be an ancestor of the admitted PR head and
rechecks that SHA before the write. A refusal never permits an unguarded merge.
Record its merge SHA and receipt.
A changed head or base requires fresh verification. Never use
`--admin` to bypass gates or `gh pr merge --delete-branch` inside a linked
worktree: GitHub CLI may switch that checkout while deleting the local branch.
The guarded cleanup below owns branch/worktree deletion.

The server settings are a live prerequisite, not a promise made by this file.
If protection or merge-method policy is weakened or unavailable, stop; do not downgrade the
guard to proceed. An administrator can still change repository policy itself;
the guard rejects observed policy drift but does not claim tamper-proof hosting.

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

### Integrate main before feature merge

Fetch before integrating a feature. Check main ancestry in its owned worktree:

```bash
git merge-base --is-ancestor origin/main HEAD
```

Compare actual content too. If main is missing, merge `origin/main` there before
the feature PR is admitted; resolve conflicts without rewriting history, push
the synchronization commit, and wait for required CI on that new head. Also
incorporate current `origin/develop` when strict protection or concurrent
feature changes require it.

Do not create a separate `main -> develop` or `sync/*` PR. An ancestor-preserving
feature merge carries both the feature and prior main history into develop.
The roadmap resolver trusts only canonical main evidence already in that head;
the ledger validator still checks exact closure rows rather than trusting new
claims merely because main is an ancestor.

Before `develop -> main`, fetch and confirm main is an ancestor of develop.
If main moved after feature integration, return to the owned feature/update
branch, integrate the new tip, and pass fresh CI before promotion. Do not bypass
that proof or create a standalone synchronization transaction.

Serialize protected-branch integrations: GitHub pins the PR head, not the
non-target main tip. Rechecking ancestry does not make the last window atomic.

## Release Flow

Only when a release is requested, create its worktree from `origin/develop`,
prepare version stamps and promote the changelog under
[`geode-changelog`](../geode-changelog/SKILL.md), then merge into develop.
Leave a fresh `[Unreleased]` heading. Incorporate main in the release branch
before its feature merge, then
promote develop to main with a merge commit. Release preparation does not bypass
CI or add an automatic post-release backmerge; main-owned tracking may still
require incorporation into the next owned feature branch.

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
remote branch, worktree, and local topic branch and prunes. The owner
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
