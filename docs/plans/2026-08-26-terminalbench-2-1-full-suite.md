# Terminal-Bench 2.1 full-suite paired evaluation

## Problem

GEODE has a three-task paired diagnostic, but its Harbor adapter does not emit
official ATIF and imposes a fixed 1,200-second internal agent budget instead of
leaving the canonical task timeout to Harbor. Those gaps prevent a protocol-
aligned 89-task, five-repetition comparison with native Codex.

## Socratic Gate

| # | Question | Answer |
|---|---|---|
| Q1 | Does it already exist in code? | Partly. `evals.platforms.harbor` already owns the execution boundary and `sessions.db:session_events` already owns the complete GEODE history. Only the ATIF projection and timeout correction are missing. |
| Q2 | What breaks if we do nothing? | Rewarded GEODE trials lack the official trajectory format, and long tasks may terminate under a non-canonical fixed budget. |
| Q3 | How is the effect measured? | Harbor ATIF validation, canonical digest checks, valid-attempt counts, verifier passes/total trials, and same-model paired deltas. |
| Q4 | What is the simplest implementation? | Project the existing full GEODE trajectory inside `evals/platforms/harbor.py`, validate it with Harbor's own model, write `trajectory.json`, and set the internal time budget to zero. |
| Q5 | Is this pattern present upstream? | Yes. Harbor agents emit ATIF at the adapter boundary; Codex supplies the native same-model control; Prime Agent requires native-harness comparisons; OpenClaw/autoresearch motivate durable lanes and frozen budgets. |

## Frozen protocol

| Field | Value |
|---|---|
| Dataset | `terminal-bench/terminal-bench-2-1` |
| Dataset digest | `sha256:7d7bdc1cbedad549fc1140404bd4dc45e5fd0ea7c4186773687d177ad3a0699a` |
| Harness | Harbor `0.22.0` |
| Task set | Canonical 89 tasks; no exclusions |
| Container/verifier | Canonical task-owned container, resources, timeout, and verifier; multiplier `1.0`; no overrides |
| Model route | OpenAI subscription, `gpt-5.6-sol`, reasoning `max` |
| GEODE arm | `evals.platforms.harbor:GeodeHarborAgent` |
| Control arm | Harbor native Codex, installed Codex `0.145.0` |
| Repetitions | `k=5` per task per arm |
| Seed | Unsupported by Harbor `0.22.0`; no invented seed |
| Concurrency | Start at `1`; raise only after a recorded resource-valid calibration |
| Attempt rule | Semantic failures remain valid reward `0`; only infrastructure-invalid attempts may be retried and all attempts are retained |
| Official authority | Internal protocol-aligned result only; community submissions are closed and maintainer reward-hacking review is unavailable |

The primary result is verifier successes / all canonical trials. GEODE versus
native Codex is the direct same-model comparison. Public leaderboard rows and
the repository-only Codex/Sol submission record remain separate contextual
comparisons and are never presented as the same rank table.

## Execution ladder

| Phase | Gate | Workload per arm | Promotion condition |
|---|---|---:|---|
| P0 | Adapter contract | no-model/unit plus one live ATIF smoke | ATIF schema, canonical lineage, auth, Docker, verifier, and secret checks pass |
| P1 | Repetition gate | 3 frozen tasks x 5 = 15 | both arms produce 15 infrastructure-valid canonical trials |
| P2 | Breadth gate | 12 frozen tasks x 5 = 60 | both arms produce 60 infrastructure-valid canonical trials without changing the manifest |
| P3 | Full suite | 89 tasks x 5 = 445 | both arms produce 445 canonical trials; any invalid attempts remain visible |

P1 reuses `regex-log`, `openssl-selfsigned-cert`, and `cancel-async-tasks` as
an operational gate, not as an estimator. P2 is outcome-independent: sort all
89 canonical task names by `sha256("terminalbench21-p2-20260826-v1:" + name)`
and freeze the first twelve:

1. `modernize-scientific-stack`
2. `path-tracing`
3. `git-multibranch`
4. `query-optimize`
5. `portfolio-optimization`
6. `sqlite-db-truncate`
7. `custom-memory-heap-crash`
8. `extract-moves-from-video`
9. `vulnerable-secret`
10. `circuit-fibsqrt`
11. `build-pmars`
12. `qemu-startup`

## Frontier decision matrix

| Source | Original pattern | Local state | Decision |
|---|---|---|---|
| Terminal-Bench 2.1 / Harbor | Canonical task digests, task-owned verifier, ATIF, errors retained, maintainer reward-hacking review | Dataset/verifier already reused; ATIF missing | Keep the upstream contract and add only the missing adapter projection |
| Codex | Native harness records ATIF and runs the same Sol/max model | Existing direct comparator works | Keep as the control arm |
| Prime Agent | Compare a harness with the model-native harness and disclose protocol gaps | Existing diagnostic follows this shape | Keep direct and public comparisons separate |
| OpenClaw | Bounded lanes and durable operational history | Harbor owns concurrency; watcher retains logs | Adapt only durable monitoring and start at concurrency one |
| autoresearch | Frozen wall budget and append-only evidence | Run spec and artifact schemas exist | Reuse the existing preregistration and publication contracts |
| GEODE | Canonical session timeline plus `geode.trajectory@1` | Complete source history already exists | Reuse it; do not add a raw store or a duplicate schema |

## Minimal P0 change

| File | Change |
|---|---|
| `evals/platforms/harbor.py` | Disable the extra fixed internal timeout; map canonical GEODE events to ATIF 1.7; validate and atomically write `trajectory.json`; declare ATIF support. |
| `tests/evals/benchmarks/test_harbor_geode_agent.py` | One focused mapping/validation test and timeout default assertion. |
| `docs/eval/terminal-bench-2.md` | Replace the known ATIF/timeout gap with the verified boundary and its limitations. |
| `CHANGELOG.md` | Record the functional adapter correction under Unreleased. |

The mapping preserves the user prompt, assistant messages, tool call IDs,
arguments, results, timestamps, model, effort, and aggregate metrics. Because
the current canonical event schema does not retain exact LLM-response grouping,
tool calls are projected as transparent one-call agent steps and
`llm_call_count` is left null as ATIF 1.7 permits. Missing/orphan tool pairs or
an incomplete canonical session fail closed.

## Recording and publication

P3 writes an append-only, timestamped operator log before rendering. The
upload-ready MP4 is a sanitized terminal replay with a top-right phase/task/
repetition/arm/valid/pass overlay, chapter markers, and a final aggregate card.
Raw provider reasoning, credentials, tokens, PII, and local paths are excluded.
The video, source log, chapter file, run spec, attempt lineage, native results,
ATIF/GEODE trajectories, verifier receipts, outcomes, analysis, publication
manifest, and hashes are retained. Public eval artifacts go to the append-only
`mangowhoiscloud/geode-eval-artifacts` repository with remote readback. YouTube
upload, release, tag, and PyPI publication are out of scope.

## Acceptance

- P0 feature PR targets `develop`, required CI is green, and the merged SHA is
  the execution revision.
- P1 and P2 pass their infrastructure-valid gates before P3 starts.
- P3 reports valid and invalid attempt counts and exact numerators and
  denominators for both arms; no missing task/repetition is silently dropped.
- Comparability is downgraded for ARM emulation, lack of official maintainer
  execution/judging, or any remaining protocol difference.
- Every public file passes schema validation, secret/identity scan, hash check,
  append-only publication, and remote readback.

## Primary references

- [Terminal-Bench 2.1 submission contract](https://github.com/harbor-framework/terminal-bench-2-1/blob/7131e4375048a0e408a8fb404b5f499d726b695b/leaderboard/SUBMIT.md)
- [Terminal-Bench 2.1 static analysis](https://github.com/harbor-framework/terminal-bench-2-1/blob/7131e4375048a0e408a8fb404b5f499d726b695b/leaderboard/src/leaderboard/ci/static_analysis.py)
- [Terminal-Bench 2.1 metric implementation](https://github.com/harbor-framework/terminal-bench-2-1/blob/7131e4375048a0e408a8fb404b5f499d726b695b/leaderboard/src/leaderboard/core/metrics.py)
- [Leaderboard integrity update](https://www.tbench.ai/news/leaderboard-integrity-update)
- [Terminal-Bench 2.1 release](https://www.tbench.ai/news/terminal-bench-2-1)
- [Current official leaderboard](https://www.tbench.ai/leaderboard/terminal-bench/2.1)
