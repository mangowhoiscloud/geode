# Verification Gates

Run targeted checks first, then broaden based on blast radius. Read-only audits
need source evidence, not a full test run. For documentation-only edits, check
affected links, examples, or generated output; runtime-loaded prompts also need
the relevant assembly and mode-boundary tests.

For a changed behavior, preserve the smallest meaningful regression check.
Do not add tests that only repeat arbitrary wording or implementation details.
Once the required checks pass, reuse results for unchanged code, configuration,
and verification environment. Repeat or broaden only after changes, failures,
or unresolved concerns. Record the tested revision or diff and exact commands.
Required remote CI must still pass on the actual PR head before merge.

## Failure-to-rule review

Use this after a failed check or when consolidating instructions. Record the
case in the existing task receipt; keep reusable rules here rather than copying
incident logs into every prompt or adding a new ledger.

- **Manual: inspect the check's inputs and consumers.** Locate code and tests
  that consume changed guidance before selecting targeted checks. Identify the
  files, environment, revision, and property the check actually covers; use the
  [hygiene procedure](#repo-hygiene-ratchet) for tracked-file scans. When merging
  docs, preserve a usable route to supported entry points, constraints, and
  recovery. A valid link alone does not prove that contract survived.
- **Karpathy: preserve the acceptance criteria.** Keep failures and subsequent
  results distinguishable, change the smallest responsible surface, and verify
  against the same contract. A broken test is not permission to lower a gate.
  If the test encodes obsolete prose, replace it only after identifying the
  intended contract and checking that the replacement still detects its loss.
- **Tao: test the assumptions.** Ask what precondition made the
  check applicable and what counterexample would disprove the diagnosis.
  Distinguish missing behavior or guidance from stale wording. Normalize prose
  whitespace only when formatting is not the contract; parsed syntax, command
  identifiers, and prompt hashes remain exact. Reuse passing evidence only
  under the unchanged-input conditions above.

These are GEODE procedures, not a new framework or mandatory reviewer personas.
The [autoresearch program](https://github.com/karpathy/autoresearch/blob/master/program.md)
provides the fixed-evaluation and simplicity reference; its reset and unbounded
loop instructions do not transfer permission to GEODE. For the assumption-check
lens, see Terence Tao's
[discussion of hypotheses, examples, and simpler sufficient results](https://terrytao.wordpress.com/career-advice/learn-and-relearn-your-field/).
Applying that mathematical advice to software checks is our analogy, not a
published Tao agent algorithm.

## Targeted

```bash
uv run pytest -q tests/<targeted_path>.py
```

Use targeted suites for new modules, changed adapters, lifecycle events,
tool handlers, prompt assembly, or schema changes.

## Static Gates

```bash
uv run ruff check core/ evals/ evolve/ tests/ scripts/
uv run ruff format --check core/ evals/ evolve/ tests/ scripts/
uv run mypy core/ evals/ evolve/ scripts/
uv run lint-imports
git diff --check
```

Do not pipe gate output through commands that can hide non-zero exit codes.

## Prompt Integrity

Run this when `core/llm/prompts/` changed:

```bash
uv run python - <<'PY'
from core.llm.prompts import verify_prompt_integrity
verify_prompt_integrity(raise_on_drift=True)
PY
```

## Full Suite

For broad runtime changes, use `scripts/preflight.sh` and inspect its results
and skips. The full Python suite is:

```bash
uv run pytest tests/ -m "not live"
```

A known environment or fixture failure remains a failed check: report exact
groups and the remaining verification. `--fast`, missing optional dependencies,
and unavailable site tooling do not establish a full pass.

## Live Tests

Live provider checks require explicit user approval. Without approval, mark
ambiguous provider acceptance as `live_test_required` and keep the production
path guarded.

## Independent Review

Non-trivial changes get an independent, read-only review when a suitable
reviewer is available. Before dispatch, the parent fixes the final artifact
revision (base/head/diff or a saved content digest), goal, acceptance contract,
source evidence, and excluded scope. Supply the necessary original evidence;
withhold producer rationale and previous review scores unless the task needs
them. Verify findings locally and resolve or explicitly disposition them.
Re-review changed or unresolved parts, not an unchanged, already-reviewed
artifact.

Use the [Codex MCP skill](../../codex-mcp-verify/SKILL.md) when its user-request
and tool-availability conditions hold. Otherwise an available independent
subagent can review; if no reviewer is available, disclose that limit instead
of inventing tools, reading credentials, or blocking indefinitely. Review is
evidence, not a replacement for deterministic checks or required CI.

### Adversarial Review

Use this optional focus for consequential documents, designs, PRs, or
publication decisions when their claims need challenge. In GEODE, call
`delegate_task` with `role="reviewer"`; its behavior lives in the
[canonical reviewer prompt](../../../../core/llm/prompts/reviewer.md).
Reuse that contract instead of adding another role, score, or review ledger.

The reviewer can only use its permitted `grep_files` and `read_document`
tools. It returns the existing `findings[{file,line,severity,summary}]` schema,
not an approval. The parent keeps inspected and unverified scope in the task
receipt and checks findings against the original evidence. Schema validation
success or an empty findings list does not establish a pass, authorize a
merge, or replace missing checks. Report evidence limits without fabricating
findings to fill them.

### Architecture Program Review

For architecture/extensibility **implementation PRs**, verification also
confirms that canonical `develop` contains the selected package's
`IN_PROGRESS` active claim, the implementation branch/owner match it, the
implementation diff does not prospectively change status, and a post-merge
reconciliation path exists. Roadmap-only readiness, claim, GAP-registration,
reconciliation, full-ledger audit, and main-based tracking PRs perform ledger
maintenance and are exempt from the implementation active-claim prerequisite.
A registration PR adds only `OPEN` scope and does not authorize implementation.
Neither local gates nor review can justify a prospective `IN_DEVELOP` or `DONE`
status in an implementation PR.

Every roadmap-only PR runs the canonical ledger validator
against its actual target: `--base-ref origin/develop` for ordinary ledger
work and `--base-ref origin/main` for a tracking-only closure PR.

## Repo Hygiene Ratchet

Run before every push (CI's Lint & Format job includes it; local ruff does not):

Stage the intended candidate first. This check scans tracked files, so a pass
before adding a new file does not cover that file.

```bash
uv run python scripts/check_repo_hygiene.py
```

Catches hardcoded home paths with real usernames (placeholders like
``/Users/x/…`` are allowlisted in ``_PLACEHOLDER_USERS``), dangling/absolute
symlinks, and orphan worktrees.
