# Codex–GEODE Paired Coding

Use this reference when a user explicitly asks to compare Codex and GEODE
implementations, or when a GAP audit leaves a material design choice that one
producer plus a read-only reviewer cannot resolve. Ordinary work uses the
single-producer `geode-workflow`; paired production is not the default.

This is a cross-runtime workflow. `CodexOAuthAdapter` runs a Codex model
inside GEODE's AgenticLoop and is not an independent Codex candidate.
`CodexCliAdapter` launches native `codex exec`, but as written it does not
freeze a separate worktree, current directory, native trajectory, or candidate
receipt, so it is not automatically a valid paired arm either.

## Hard Boundaries

- Both candidates start from the same exact `base_sha`.
- Both receive the same canonical brief bytes and `brief_sha256`.
- Each candidate owns a separate Git worktree and branch.
- `allowed_paths`, `protected_paths`, and `acceptance_commands` are frozen
  before either candidate sees the task.
- Candidates do not see each other's patch, findings, or check output until
  both candidate commits and receipts are frozen.
- The operator derives actual changed paths and command exit statuses. Model
  self-reports are supporting evidence only.
- Selection is human-owned. The workflow must not auto-merge or auto-promote.
- Live provider tests still require explicit user approval.

`geode-mcp run_agent` may draft edits, but its headless execution denies
`run_bash` and delegation. It cannot be called a complete implementation arm
unless an operator independently runs the same frozen acceptance commands in
its isolated worktree.

The official Codex MCP server exposes the stateful `codex` and `codex-reply`
tools. Do not invent `exec`, `review`, or `apply` MCP aliases. The Codex arm
may use the Desktop app, CLI, or official MCP surface, but its actual runtime,
version/source revision, sandbox, and worktree must be recorded.

## Frozen Scope Record

Write this compact record into the plan or PR body before production:

```text
contract_id:
task_id:
base_ref:
base_sha:
brief_sha256:
allowed_paths:
protected_paths:
acceptance_commands:
live_test_approved:
non_goals:

geode_arm:
  runtime_and_version:
  worktree_and_branch:
codex_arm:
  runtime_and_version:
  worktree_and_branch:
```

The brief itself remains the human-readable authority. `brief_sha256` only
proves that both arms received the same bytes.

## Production Workflow

1. **GAP audit** — confirm the task is not already solved and that paired
   production is worth more than ordinary independent review.
2. **Freeze input** — record the scope fields above, including exact primary
   checks and security or compatibility invariants.
3. **Allocate** — fetch once, resolve one `base_sha`, then create two
   separately owned worktrees from that SHA. Never share a writable checkout.
4. **Produce independently** — each runtime reads the same brief and repository
   instructions, then implements only in its own worktree. Do not pass peer
   commentary or partial diffs between arms.
5. **Check locally** — an arm may run exploratory checks, but those do not
   replace the operator-owned identical acceptance run.
6. **Freeze candidates** — commit each candidate without pushing or opening a
   PR. Record `head_sha`, actual changed paths, and a digest of the base diff.
7. **Reject contamination** — stop the paired comparison if base, brief,
   protected paths, worktree ownership, or primary checks differ.

Do not retrofit `TaskGraph`, `SubAgentManager`, MCPMark, or Crucible into this
workflow. They do not provide two independent repository worktrees with a
shared coding acceptance contract.

## Verification Workflow

1. **Identity gate** — verify both `base_sha` and `brief_sha256` values, clean
   candidate commits, distinct worktrees, and recorded runtime identities.
2. **Scope gate** — derive `git diff --name-only <base_sha>...<head_sha>` for
   each arm and reject protected or undeclared paths.
3. **Primary gate** — run the exact same `acceptance_commands` in each
   worktree. Record commands, exit statuses, failures, and intentionally
   skipped live checks.
4. **Independent review** — after freeze, perform read-only review of both
   base diffs. Findings name severity, file/line, violated invariant, and the
   candidate or shared brief defect responsible.
5. **Compare** — rank correctness and invariant preservation first. Then
   compare scope discipline, test quality, simplicity, maintainability, and
   measured resource use. Diff size alone never selects a broken candidate.
6. **Decide** — select GEODE, select Codex, reject both, or authorize a fresh
   hybrid. Record every review finding and disposition.
7. **Reverify hybrids** — build a hybrid in a third clean worktree. It is a new
   candidate and must rerun all primary and repository gates.
8. **Promote normally** — the selected candidate enters the ordinary
   `geode-workflow`: static gates, committed-diff second opinion, PR, CI, and
   human merge. Paired production grants no promotion authority.

## Invalid Pair And Fallback

Do not report a paired result when any of these occurs:

- different base, brief, protected paths, or primary acceptance commands
- a shared or dirty starting worktree
- peer patch leakage before candidate freeze
- missing runtime identity or candidate commit
- scope drift or an unapproved live call
- one candidate receives repair hints unavailable to the other

Preserve the useful candidate if safe, but label the run `not-paired` and fall
back to one producer plus read-only independent review.

## Comparison Record

Use a Markdown table; do not create a schema or scoring service for one run.

| Evidence | GEODE | Codex |
|---|---|---|
| Base / brief identity | | |
| Candidate commit / diff digest | | |
| Actual changed paths | | |
| Primary acceptance results | | |
| Additional checks | | |
| Review findings | | |
| Skipped / assumptions | | |

Decision: `GEODE | Codex | fresh hybrid | reject both`

Rationale: correctness and invariants first; simplicity breaks an otherwise
equivalent tie.

## Grounding

The source-pinned Codex audit, GEODE GAP matrix, and affected scope live in
`docs/plans/2026-08-14-codex-geode-paired-coding-workflow.md`.
