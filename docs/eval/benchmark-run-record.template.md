# Benchmark Run Record Template

Copy this file into the relevant eval ledger or run note, then replace every
placeholder before publication.

## Identity

| Field | Value |
|---|---|
| Run ID | `<benchmark>-<suite>-<model>-<reasoning>-<yyyymmdd>` |
| Date | `<YYYY-MM-DD>` |
| Operator | `<name or role>` |
| GEODE commit | `<sha>` |
| GEODE branch | `<branch>` |
| Dirty worktree? | `<clean / explain local changes>` |

## Benchmark

| Field | Value |
|---|---|
| Benchmark | `<MCPMark / BFCL V4 / tau2-bench / other>` |
| Suite/domain | `<suite>` |
| Task count | `<n>` |
| Trials | `<k / pass@k>` |
| Harness source | `<repo URL>` |
| Harness revision | `<commit / package version>` |
| Server versions | `<MCP or service versions>` |
| User simulator | `<tau2 only, or n/a>` |

## Model Route

| Field | Value |
|---|---|
| Provider | `<openai-codex / openai-api / anthropic / other>` |
| Model label | `<exact label>` |
| Route source | `<subscription / api / local / other>` |
| Reasoning setting | `<xhigh / high / medium / none / n/a>` |
| Auth note | `<for example: OPENAI_API_KEY=dummy was harness placeholder; actual calls used source=subscription>` |

## Command

```bash
<redacted command>
```

## Artifacts

| Artifact | Path |
|---|---|
| Raw result directory | `<artifacts/eval/...>` |
| Verifier output | `<path>` |
| Transcript | `<path>` |
| Summary JSON/CSV | `<path>` |
| Logs | `<path>` |

## Result

| Metric | Value |
|---|---:|
| Passed | `<n>` |
| Failed | `<n>` |
| Accuracy / pass rate | `<percent>` |
| Total wall time | `<seconds>` |
| Average task time | `<seconds>` |
| Total GEODE rounds | `<n>` |
| Average GEODE rounds | `<n>` |
| Input tokens | `<n>` |
| Output tokens | `<n>` |
| Total tokens | `<n>` |

## Per-Task Rows

| Task | Result | Time | Rounds | Tokens | Notes |
|---|---|---:|---:|---:|---|
| `<task>` | `<PASS/FAIL>` | `<s>` | `<n>` | `<n>` | `<note>` |

## Rollup

| Category/domain | Tasks | Accuracy | Average time | Tokens | Average rounds |
|---|---:|---:|---:|---:|---:|
| `<category>` | `<n>` | `<percent>` | `<s>` | `<n>` | `<n>` |

## Comparability

| Comparator | Status |
|---|---|
| `<same suite>` | `<directly comparable / directional / not comparable>` |
| `<leaderboard>` | `<directly comparable / directional / not comparable>` |

## Interpretation

- `<What this score means.>`
- `<What it does not mean.>`
- `<Whether this is a smoke baseline, verified score, or full benchmark.>`

## Publication Checklist

- [ ] Internal ledger updated under `docs/eval/`.
- [ ] Public docs page added or updated under `site/src/app/docs/benchmarks/`.
- [ ] Sitemap entry added in `site/src/lib/geode-docs/sitemap.ts`.
- [ ] Local usernames, keys, tokens, and account identifiers scrubbed.
- [ ] `git diff --check` passed.
- [ ] Targeted site lint passed.
- [ ] `site` build passed.
- [ ] Feature PR merged to `develop`.
- [ ] `develop -> main` PR merged.
- [ ] Pages deploy succeeded.
- [ ] Live URL checked with `curl`.
