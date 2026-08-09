---
eval_id: benchmark-publishing-cycle
eval_family: benchmark-publishing
eval_kind: workflow
eval_status: canonical
eval_authority: process
eval_summary: End-to-end workflow from preregistered benchmark scope through evidence preservation, publication, and deployment.
eval_triggers:
  - benchmark run
  - publish evaluation
  - eval artifact
  - run spec
  - attempts JSONL
eval_contracts:
  - docs/eval/artifact-publish-manifest.template.json
  - docs/eval/eval-analysis.template.json
  - docs/eval/eval-attempt.template.json
  - docs/eval/eval-run-spec.template.json
  - docs/eval/schemas/analysis.schema.json
  - docs/eval/schemas/attempt.schema.json
  - docs/eval/schemas/run-spec.schema.json
---

# Benchmark Publishing Cycle

> Scaffold for turning a live GEODE benchmark run into a published official
> docs page. Use this for MCPMark, BFCL V4, tau2-bench, and later benchmark
> suites that need a reproducible ledger plus GitHub Pages deployment.

## Cycle Contract

One complete cycle has six gates:

| Gate | Exit evidence |
|---|---|
| 1. Scope | Research question, gap, hypothesis, metric, decision/invalidation rules, benchmark, route, budget, and live-test approval are frozen in `run-spec.json` |
| 2. Harness | Upstream source, version, local path, install command, and smoke result are recorded |
| 3. Run | Every retry is appended to `attempts.jsonl`; raw results, verifier outputs, trajectories, token/time totals, and failures remain referenced evidence |
| 4. Interpret | Digest-bound `analysis.json` answers the frozen question; comparability boundaries and external baselines stay separate from GEODE scores |
| 5. Publish | Internal ledger and public docs page are updated from the same run record |
| 6. Deploy | Feature PR merges to `develop`, `develop` merges to `main`, Pages deploy succeeds, live URL is checked |

The cycle is not complete until the public GitHub Pages URL returns the new
score and the final report names the merge commit and Pages workflow run.

## Contract Stack

Use one small sidecar per authority boundary:

| Record | Mutability | Owns | Does not own |
|---|---|---|---|
| `run-spec.json` (`geode.eval-run-spec@1`) | frozen before execution | research intent, measurement, reproduction, artifact destinations | observed score |
| `attempts.jsonl` (`geode.eval-attempt@1`) | append-only | retry lineage, measurement validity, semantic outcome, per-attempt change/expectation, timing provenance, failure class, evidence path + SHA-256 | native result bytes |
| native result / trajectory / verifier receipt | append-only by producer | score, behavior, judgement evidence respectively | research decision |
| `analysis.json` (`geode.eval-analysis@1`) | immutable after publication | answer, metric numerator/denominator, decision, limitations, selected attempts and exact evidence digests | raw evidence copies |
| trajectory release / artifact manifest | immutable | admitted public bytes, hashes, privacy/read-back attestation | benchmark interpretation |

Start from `eval-run-spec.template.json`, `eval-attempt.template.json`, and
`eval-analysis.template.json`. A historical run may gain these as immutable
sidecars with `preregistration.mode=retrospective`, but its raw results and
receipts must never be rewritten. Retrospective specs always have
`promotion_authority=none`.

A non-`none` promotion authority is valid only for a direct, named comparator:
`suite-headline → suite-native`, `paired-runtime → paired-runtime`, or
`regression → release-gate`. Smoke, diagnostic, directional paper-reference,
and retrospective records can preserve evidence but cannot promote state.

The canonical workload hash is SHA-256 over the compact UTF-8 JSON array of
ordered workload IDs (`ensure_ascii=false`, separators `,` and `:`). The
validator recomputes it and requires one seed per repetition. Freeze the
primary denominator explicitly because pass@k and per-repetition accuracy do
not always use the same denominator. A derived ratio or percentage may be
rounded to four significant decimal places.

`exact` timing requires a known timezone offset; RFC 3339 `-00:00` remains
unknown and is rejected. Evidence references are portable POSIX-relative and
digest-bound: URI, UNC, drive-root, backslash, and parent traversal forms are rejected.
If an invalid or aborted attempt is selected for provenance, the primary metric
must be `not-measurable` with null counts and the decision cannot promote or
reject.
Every measured primary metric uses RFC 6901 JSON Pointers to read value,
numerator, and denominator from one digest-bound `native-result` JSON file.
Its denominator must also equal the run spec's frozen denominator; a
nonexistent locator, changed source count, or ratio-preserving count inflation
is invalid. A secondary metric remains digest-bound but may leave
`source_locator` null when its evidence is text, CSV, or another non-JSON
format; when locators are present, they are verified against JSON bytes.
Promotion and rejection both require explicit authority.

```bash
uv run python scripts/eval/contract.py catalog --check
uv run python scripts/eval/contract.py validate-run-spec <run-dir>/run-spec.json
uv run python scripts/eval/contract.py validate-attempts <run-dir>/attempts.jsonl
uv run python scripts/eval/contract.py validate-analysis <run-dir>/analysis.json \
  --run-spec <run-dir>/run-spec.json \
  --attempts <run-dir>/attempts.jsonl
```

## Required Fields

Each benchmark run must record these fields before publication:

| Field | Required content |
|---|---|
| Run ID | Stable slug: `<benchmark>-<suite>-<model>-<reasoning>-<yyyymmdd>` |
| Research contract | Question, evidence gap, measurable hypothesis, primary metric, decision rule, invalidation rule, and analysis plan |
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
| Attempt lineage | Stable attempt IDs, parent link, validity versus semantic outcome, exact/source-naive/unknown timing provenance, changed surface, expected effect, observed result, failure class, selected rows, and evidence SHA-256 |

Freeze `docs/eval/eval-run-spec.template.json` before execution. Use
`docs/eval/benchmark-run-record.template.md` only as the human-readable report
derived from validated sidecars and evidence.

## Directory Convention

Keep third-party harnesses and heavy outputs out of git unless a small artifact
is intentionally promoted.

```text
artifacts/eval/harnesses/<benchmark>/        # ignored third-party checkout
artifacts/eval/runs/<run-id>/                # ignored raw run collection
docs/eval/<benchmark-or-cluster>.md          # internal evidence ledger
site/src/app/docs/benchmarks/<...>/page.tsx  # public page
```

Published raw bytes are copied append-only to
[`mangowhoiscloud/geode-eval-artifacts`](https://github.com/mangowhoiscloud/geode-eval-artifacts)
using the mapping and disclosure contract in
[`external-artifact-repository.md`](external-artifact-repository.md). Start
each publication from `artifact-publish-manifest.template.json`; record the
artifact-repository commit in the GEODE run ledger. Local ignored paths alone
are not a durable public citation.

Do not publish machine-local absolute paths, API keys, OAuth tokens, or copied
subscription credentials. Public docs should use `<geode-worktree>` and route
labels such as `source=subscription` instead.

## Operator Loop

### 1. Scope and Ground

1. Confirm branch/worktree state and create a feature worktree from `develop`.
2. Freeze the research question, gap, hypothesis, metric, decision rule,
   invalidation rule, analysis plan, and reproduction envelope in `run-spec.json`.
3. Validate the frozen run spec before making any model call.
4. Confirm live-test approval if a model call, web service, account quota, or
   paid API may be used.
5. Verify current harness instructions from upstream primary sources.
6. Search for same-suite external cases before claiming novelty or comparison.

### 2. Prepare the Harness

1. Install the harness under `artifacts/eval/harnesses/<benchmark>`.
2. Pin the upstream commit or package version.
3. Run the cheapest no-LLM or single-task smoke that proves setup and verifier
   wiring.
4. Record setup commands and any environment placeholder, such as
   `OPENAI_API_KEY=dummy`, separately from the actual GEODE auth route.

### 3. Run and Preserve

1. Use a stable `--exp-name` / output directory that includes run ID fields.
2. Append one typed attempt row before interpreting or retrying; a retry names
   its already-recorded parent and preserves the same run ID.
3. Preserve raw verifier output before summarizing.
4. Extract per-task result, time, rounds, tokens, and errors.
5. Capture any code change needed to make the benchmark valid, such as MCP
   argument normalization or EOF offload.
6. If a task fails, keep the failure as data unless the harness setup itself is
   invalid.
7. Classify every artifact as public or withheld before copying. Unopened
   Crucible sealed packs, selected-row manifests, and selection salts remain
   withheld until the one-shot claim is consumed and disclosure is reviewed.

### 4. Interpret

1. Validate `attempts.jsonl`, then select rows according to the frozen rule.
2. Bind `analysis.json` to the exact run-spec, attempts, and selected evidence
   digests.
3. Answer the frozen research question and apply its decision/invalidation rules.
4. Separate the raw benchmark score from smoke/regression interpretation.
5. State direct comparators and directional-only comparators.
6. Do not average across benchmark families.
7. Do not mix MCPMark Verified with pre-Verified MCP-Mark or an `easy` smoke
   score without a version label.
8. For subscription routes, state that the result is product-route evidence,
   not API-key leaderboard evidence.

### 5. Publish

1. Build and verify an artifact publication manifest.
2. Copy only public entries to `geode-eval-artifacts` through its own PR; keep
   the destination commit and paths.
3. Update the internal ledger in `docs/eval/` with those immutable links.
4. Add or update a public docs page under `site/src/app/docs/benchmarks/`.
5. Add the page to `site/src/lib/geode-docs/sitemap.ts`.
6. If a public page includes commands, scrub local usernames and secrets.
7. Run site checks before opening the GEODE PR.

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
- The frozen run spec, append-only attempts, and digest-bound analysis validate.
- Public raw artifacts are mirrored append-only to `geode-eval-artifacts`, and
  the GEODE ledger records the artifact-repository commit.
- Internal ledger explains setup, result, and comparability.
- Public docs page exposes the score, command, artifact pointer, and caveats.
- CI passed on the feature PR.
- Feature PR was merged to `develop`.
- `develop` was promoted to `main`.
- GitHub Pages deployment succeeded.
- The live URL was fetched and contains the new result.
