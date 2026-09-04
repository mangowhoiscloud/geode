---
eval_id: terminal-bench-2
eval_family: terminal-bench-2
eval_kind: benchmark
eval_status: canonical
eval_authority: suite-profile
eval_summary: GEODE adoption profile for canonical Terminal-Bench 2.1 execution through Harbor, including official-submission and diagnostic comparability boundaries.
eval_triggers:
  - Terminal-Bench 2
  - Terminal-Bench 2.1
  - shell benchmark
  - Harbor
  - container verifier
eval_contracts:
  - docs/eval/schemas/run-spec.schema.json
  - docs/eval/schemas/attempt.schema.json
  - docs/eval/schemas/analysis.schema.json
  - core/observability/schemas/trajectory.schema.json
---

# Terminal-Bench 2.1 — GEODE execution profile

## Canonical identity

Terminal-Bench 2.1은 89개 containerized terminal task를 Harbor로 실행하고
task별 verifier로 채점한다. 2.1은 2026-05-06 공개되었고 89개 중 28개
task를 수정했다.

| Field | Canonical value |
|---|---|
| Release | [Terminal-Bench 2.1 announcement](https://www.tbench.ai/news/terminal-bench-2-1) |
| Task repository | [harbor-framework/terminal-bench-2-1](https://github.com/harbor-framework/terminal-bench-2-1) |
| Dataset | [terminal-bench/terminal-bench-2-1@6](https://hub.harborframework.com/datasets/terminal-bench/terminal-bench-2-1/6) |
| Dataset digest | sha256:7d7bdc1cbedad549fc1140404bd4dc45e5fd0ea7c4186773687d177ad3a0699a |
| Task count | 89 |
| Harness | [Harbor](https://github.com/laude-institute/harbor) |
| Scoring | task-owned verifier reward; errors remain reward 0 for official submission metrics |
| Environment | fresh task container; task-owned CPU, memory, storage, GPU, build, agent, and verifier limits |

The repository filename remains terminal-bench-2.md for stable internal links;
the canonical suite version is 2.1.

## Official submission contract

The [official submission instructions](https://github.com/harbor-framework/terminal-bench-2-1/blob/7131e4375048a0e408a8fb404b5f499d726b695b/leaderboard/SUBMIT.md)
and static checker require:

- the exact canonical dataset and per-task digests;
- all 89 tasks with at least five trials each (89 × 5 = 445);
- default timeout multiplier and no agent, verifier, or resource override;
- errored trials retained as reward 0;
- an ATIF trajectory for every rewarded trial;
- maintainer static analysis plus reward-hacking review.

Community submissions are currently closed; only maintainer-run submissions are
accepted. Therefore a local GEODE run cannot claim an official rank merely by
uploading artifacts.

    harbor run -d terminal-bench/terminal-bench-2-1 -a <agent> -m <model> -k 5

Harbor exposes repetitions (-k) and concurrency (-n) but no run seed option
in 0.22.0. Record this as unsupported rather than inventing a seed.

## GEODE adapter

The active custom-agent adapter is
evals.platforms.harbor:GeodeHarborAgent; the compatibility import remains
evals.benchmarks.harbor_geode_agent.

It:

- gives AgenticLoop one terminal_exec tool backed by Harbor's isolated
  environment.exec;
- uses the frozen provider, route, effort, and model while leaving the agent
  timeout at zero so Harbor's canonical task limit remains authoritative;
- leaves task/container/verifier ownership with Harbor;
- exports a digest-oriented geode.trajectory@1 sidecar and an ATIF 1.7
  `trajectory.json` projected from the same canonical session timeline;
- reconstructs `recording.cast` from the finalized ATIF trace and binds it to
  the source with `recording.receipt.json`.

Harbor's job layout permits `agent/recording.cast`, but its contents are owned
by each agent implementation. Terminus-2 performs a raw asciinema capture;
GEODE and the instrumented native Codex adapter instead emit an asciicast v2
reconstruction after ATIF finalization. The reconstruction is replay evidence,
not a raw PTY capture or score authority. It omits provider reasoning, redacts
known secret forms, and remains private until a separate PII/path/publication
review. Observer-side `script -r` files separately record the operator console
and must not be described as Harbor-native trial recordings.

Use `evals.platforms.harbor:RecordedCodexHarborAgent` instead of the built-in
Codex name when future paired runs require the native arm to emit the derived
cast automatically. Closed historical jobs can be audited and backfilled
without changing result or trajectory files:

    uv run python -m evals.platforms.harbor <job-or-run-root> --dry-run
    uv run python -m evals.platforms.harbor <job-or-run-root>

The adapter declares `SUPPORTS_ATIF=true` only after validating the projection
with Harbor's own ATIF model. Scope-incomplete session history or unmatched
tool events fail closed. GEODE's event contract does not retain exact LLM-call
grouping, so the projection emits one tool call per agent step and leaves
ATIF's `llm_call_count` unknown; this limitation is recorded in every root
trajectory. Official submission authority still requires the canonical full
suite, Hub upload, static analysis, and maintainer reward-hacking review.

## Required execution ladder

1. Pin Harbor version, dataset version/digest, task manifest, GEODE revision,
   model route, reasoning effort, timeout, concurrency, repetitions, and
   exclusion rule in a validated prospective run spec.
2. Fail closed on Docker, task architecture, subscription auth, adapter import,
   and canonical verifier availability.
3. Run a no-model oracle smoke.
4. Run one paid GEODE/native smoke without changing the frozen task.
5. Expand only after both arms are infrastructure-valid.
6. Preserve semantic failures as valid reward 0; retry only recorded
   infrastructure-invalid attempts under the preregistered retry rule.
7. Validate run spec, attempt lineage, native result, trajectory, verifier and
   outcome receipts, analysis, publication manifest, source hashes, secret
   scan, and remote read-back.

## Comparability grades

| Comparison | Grade | Required wording |
|---|---|---|
| Same frozen local tasks, dataset digest, verifier, model, route, effort, timeout, and concurrency; harness differs | direct paired-runtime diagnostic | Report exact numerator/denominator and harness-internal differences |
| Different task subset, repetition count, machine architecture, CLI version, or execution date | directional only | Never present as one rank table |
| Local subset versus official 89-task k>=5 maintainer-reviewed leaderboard | not comparable | No official rank or suite accuracy claim |

Official leaderboard values are reference context only. They do not replace a
same-protocol comparator and must remain separate from local paired results.

## 2026-09-05 GPT-6 Astra subscription E2E smoke

The current account completed one preregistered
`openssl-selfsigned-cert` trial through GEODE 1.0.27, Harbor 0.22.0,
`gpt-6-astra`, reasoning `high`, and the OpenAI subscription route. The
canonical result was **1/1 reward**, all **6/6 verifier checks** passed, and
there was no retry or fallback.

The [run record](2026-09-05-terminalbench-astra-openssl-smoke.md) binds the
frozen contract, attempt lineage, publication manifest, and limitation set.
The [append-only artifact bundle](https://github.com/mangowhoiscloud/geode-eval-artifacts/tree/a32abcbf78ab6100ea1e85540a2ace9436dc6f76/terminalbench/results-smoke/terminalbench21-astra-high-openssl-smoke-20260904t202725z)
was read back byte-for-byte from its merge commit.

This result establishes account-scoped route and task execution for one
scenario only. It has no suite, rank, paired-comparison, promotion, or general
account-availability authority.

## 2026-08-26 diagnostic

The first current-contract Sol/max paired run is recorded in
[2026-08-26-terminalbench-2-1-sol-max-paired.md](2026-08-26-terminalbench-2-1-sol-max-paired.md).
GEODE and native Codex each passed 3/3 on the frozen diagnostic subset; the
result has paired-runtime diagnostic authority only.
