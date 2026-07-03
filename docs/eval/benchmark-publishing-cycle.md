# Benchmark Publishing Cycle

> Scaffold for turning a live GEODE benchmark run into a published official
> docs page. Use this for MCPMark, BFCL V4, tau2-bench, and later benchmark
> suites that need a reproducible ledger plus GitHub Pages deployment.

## Cycle Contract

One complete cycle has six gates:

| Gate | Exit evidence |
|---|---|
| 1. Scope | Benchmark, suite, model route, reasoning setting, budget, and live-test approval are written down |
| 2. Harness | Upstream source, version, local path, install command, and smoke result are recorded |
| 3. Run | Raw result artifacts, verifier outputs, transcripts, token/time totals, and failures are preserved |
| 4. Interpret | Comparability boundaries and external baselines are separated from GEODE scores |
| 5. Publish | Internal ledger and public docs page are updated from the same run record |
| 6. Deploy | Feature PR merges to `develop`, `develop` merges to `main`, Pages deploy succeeds, live URL is checked |

The cycle is not complete until the public GitHub Pages URL returns the new
score and the final report names the merge commit and Pages workflow run.

## Required Fields

Each benchmark run must record these fields before publication:

| Field | Required content |
|---|---|
| Run ID | Stable slug: `<benchmark>-<suite>-<model>-<reasoning>-<yyyymmdd>` |
| GEODE revision | Commit SHA, branch, and whether local changes were present |
| Harness revision | Repo URL, commit/package version, server versions, and task-set label |
| Model route | Provider, model label, subscription/API route, and auth caveat |
| Reasoning setting | Exact setting as passed to GEODE or the benchmark harness |
| Task scope | Domain, suite, task count, `k`, pass@k or accuracy definition |
| User simulator | Required for tau2-style benchmarks |
| Tool path | Native provider tools, GEODE function tools, MCP server, browser, or emulation |
| Budget | Timeout, wall time, cost estimate or subscription-limit note |
| Artifacts | Raw result directory, transcripts, verifier reports, logs, and generated summaries |
| Result | Passed/failed counts, aggregate score, per-task rows, and category/domain rollups |
| Comparability | What can be compared directly, what is directional only, and what must not be averaged |

Use `docs/eval/benchmark-run-record.template.md` for the run record.

## Directory Convention

Keep third-party harnesses and heavy outputs out of git unless a small artifact
is intentionally promoted.

```text
artifacts/eval/harnesses/<benchmark>/        # ignored third-party checkout
artifacts/eval/runs/<run-id>/                # ignored raw run collection
docs/eval/<benchmark-or-cluster>.md          # internal evidence ledger
site/src/app/docs/benchmarks/<...>/page.tsx  # public page
```

Do not publish machine-local absolute paths, API keys, OAuth tokens, or copied
subscription credentials. Public docs should use `<geode-worktree>` and route
labels such as `source=subscription` instead.

## Operator Loop

### 1. Scope and Ground

1. Confirm branch/worktree state and create a feature worktree from `develop`.
2. Record the exact benchmark objective and non-goals.
3. Confirm live-test approval if a model call, web service, account quota, or
   paid API may be used.
4. Verify current harness instructions from upstream primary sources.
5. Search for same-suite external cases before claiming novelty or comparison.

### 2. Prepare the Harness

1. Install the harness under `artifacts/eval/harnesses/<benchmark>`.
2. Pin the upstream commit or package version.
3. Run the cheapest no-LLM or single-task smoke that proves setup and verifier
   wiring.
4. Record setup commands and any environment placeholder, such as
   `OPENAI_API_KEY=dummy`, separately from the actual GEODE auth route.

### 3. Run and Preserve

1. Use a stable `--exp-name` / output directory that includes run ID fields.
2. Preserve raw verifier output before summarizing.
3. Extract per-task result, time, rounds, tokens, and errors.
4. Capture any code change needed to make the benchmark valid, such as MCP
   argument normalization or EOF offload.
5. If a task fails, keep the failure as data unless the harness setup itself is
   invalid.

### 4. Interpret

1. Separate the raw benchmark score from smoke/regression interpretation.
2. State direct comparators and directional-only comparators.
3. Do not average across benchmark families.
4. Do not mix MCPMark Verified with pre-Verified MCP-Mark or an `easy` smoke
   score without a version label.
5. For subscription routes, state that the result is product-route evidence,
   not API-key leaderboard evidence.

### 5. Publish

1. Update the internal ledger in `docs/eval/`.
2. Add or update a public docs page under `site/src/app/docs/benchmarks/`.
3. Add the page to `site/src/lib/geode-docs/sitemap.ts`.
4. If a public page includes commands, scrub local usernames and secrets.
5. Run site checks before opening the PR.

### 6. Merge and Deploy

Use the normal GEODE GitFlow:

```text
feature/<benchmark-cycle> -> develop -> main
```

Feature PRs squash into `develop`. Before promoting `develop -> main`, sync
`main -> develop` if `main` has progressed. The final `develop -> main` PR uses
a merge commit. After main merge, watch the Pages workflow and verify the live
URL with `curl`.

## Verification Checklist

Run the narrowest useful checks for the changed surface:

```bash
git diff --check
npx eslint site/src/app/docs/benchmarks/<path>/page.tsx
cd site && npm run build
```

For functional GEODE changes that were needed by the benchmark, also run the
touched Python checks, for example:

```bash
uv run pytest tests/<target>.py
uv run ruff check <changed-python-files>
uv run ruff format --check <changed-python-files>
uv run mypy <changed-python-modules>
```

After merge to `main`:

```bash
gh run list --workflow "Deploy site to GitHub Pages" --branch main --limit 5
gh run watch <run-id> --exit-status
curl -L https://mangowhoiscloud.github.io/geode/docs/benchmarks/<path> | rg "<score|run-id|model>"
```

## Done Definition

A benchmark publishing cycle is done when all of these are true:

- Raw artifacts are preserved in an ignored artifact directory.
- Internal ledger explains setup, result, and comparability.
- Public docs page exposes the score, command, artifact pointer, and caveats.
- CI passed on the feature PR.
- Feature PR was merged to `develop`.
- `develop` was promoted to `main`.
- GitHub Pages deployment succeeded.
- The live URL was fetched and contains the new result.
