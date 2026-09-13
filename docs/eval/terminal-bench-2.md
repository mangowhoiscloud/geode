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

## Historical Sol paired replay

The frozen `terminalbench21-sol-max-fullsuite-paired-20260827t190300z` run
has a [public paired replay](https://mangowhoiscloud.github.io/geode/benchmarks/terminal-bench/replay/).
The reviewed bytes and receipts are pinned to
[artifact commit 52b7d0e](https://github.com/mangowhoiscloud/geode-eval-artifacts/tree/52b7d0eab37ec9122492ec51d77e1502d5b9e085/terminal-bench/terminalbench21-sol-max-fullsuite-paired-20260827t190300z/recording/replay-v19-20260905)
from artifact PR #42. Public HTML SHA-256:
`ef15b986535d6c04b395645afe9bf877c937a53e5fdfc489a0f69ac53d1a05d3`.

All 445 task/repetition pairs are navigable, with GEODE left and Codex right.
Of 890 planned cells, 835 have ATIF-derived tool events, 35 have receipts only,
and 20 were prospectively excluded. The view adds the already-preserved
`supplement-042-native` ATIF for `dna-insert` repetition 2 to the earlier
834-cell cast coverage; it does not alter a source or score. The 16,244
tool-event projections exclude command/output bodies and all model messages.
UTC event timestamps are displayed in KST; the five-events/second cadence is
editorial, not original PTY timing or proof of simultaneous arm execution.

The full-suite primary remains not measurable. Secondary common valid cells
remain GEODE 339/429 and native Codex 331/429. The view distinguishes raw
verifier reward from selected reward, including 18 canonical timeout/refusal
cells with raw verifier one and selected zero. Twenty `bn-fit-modify` and
`tune-mjcf` cells were excluded before model calls because the amd64
oracle/verifier could not complete normally on the arm64 host; six other
native cells remain infrastructure-invalid. None are silently turned into
passes or semantic zeroes.

The official replay now uses a native Next.js App Router page with a React
client player and TypeScript projection types at
`site/src/app/benchmarks/terminal-bench/replay/`. The unchanged v19 metadata
JSON is published separately at
[artifact commit dd547bd](https://github.com/mangowhoiscloud/geode-eval-artifacts/tree/dd547bdf892581fabd6cb89a440b0dedb44691c4/terminal-bench/terminalbench21-sol-max-fullsuite-paired-20260827t190300z/recording/replay-data-v19-20260906)
from artifact PR #43. Its SHA-256 is
`fd934ee47e6c26b250378bfcf57ad25146d03579c87f757faf8bc44e7b3eaeed`.
This is the existing public projection, not a new raw store or eval schema.

The client fetches those pinned bytes without credentials, verifies SHA-256,
then renders text through React. A failed download or digest blocks playback.
No external HTML, iframe or artifact script runs. The legacy `replay.html`
link redirects while retaining its pair/language query. The site remains
statically exported to GitHub Pages; no server or new dependency is required.
`site/scripts/verify-terminal-replay.mjs` checks digest rejection, fetch
failure, playback transitions, KST formatting and the compatibility redirect
in every build. Its optional JSON argument audits every consumed field across
all 445 pairs. Original HTML, video and Astra smoke evidence remain unchanged.

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
cast automatically. For subscription authentication, set `CODEX_FORCE_AUTH_JSON=1`
in the Harbor **process environment**, not `agent.env` in its job configuration.
Harbor 0.22.0 treats AUTH-named configuration values as secrets and can replace
every `1` in trial files with `[REDACTED]`, corrupting JSON, rewards and ATIF.
The instrumented adapter rejects this configuration before execution; actual
credential redaction remains enabled. Freeze and verify the process-level route.

Closed historical jobs can be audited and backfilled
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

### Opt-in full-runtime candidate

`evals.platforms.harbor_runtime:GeodeRuntimeHarborAgent` uses Harbor 0.22.0's
`BaseInstalledAgent` lifecycle and installs a hash-pinned GEODE source bundle
inside each task container. Harbor retains job/trial, isolation, timeout,
verifier and result ownership. Native GEODE factories create the runtime,
tools, internal services and workers; no external scaffold-search loop runs.
This candidate is not interchangeable with the historical one-tool control.

The entry point requires a container-local home, explicit subscription routing,
an absolute required model policy, and no API-key environment variables.
Root effort, worker-difficulty settings and auxiliary defaults are distinct.
The fresh task-container profile permits dangerous tools so the native shell
is available; this does not change host policy or bypass worker-role toolkits.
The adapter's `verify_mode` option defaults to `rule_based`; freeze `reflexion`
explicitly when evaluating LLM-assisted repair. Mode, judge model and shell
admission are checked before inference. GEODE verification supplies runtime
feedback, not the Harbor task verifier's score authority.
Native state is preserved under the trial's `agent/geode-home/`; credentials
are transferred outside the collected logs. These are private sources until
separate secret, PII and local-path scans authorize a public derivative.
Missing cache observations stay null, and AgenticLoop usage subtotals do not
populate Harbor whole-runtime totals while auxiliary calls remain unobserved.

Use Harbor's `--install-only` for the no-model installation gate. Every live
study needs the existing run-spec/attempt contracts and its frozen admission
rules. The ladder below describes paired comparisons and their publication;
a candidate-only development gate can instead preregister one runtime, its
no-model preflights and a private evidence destination. It does not acquire
paired-comparison or public-release authority by passing that gate.

1. Pin Harbor version, dataset version/digest, task manifest, GEODE revision,
   model route, reasoning effort, timeout, concurrency, repetitions, and
   exclusion rule in a validated prospective run spec.
2. Fail closed on Docker, task architecture, subscription auth, adapter import,
   and canonical verifier availability.
3. Run a no-model oracle smoke.
4. For a paired comparison, run one paid GEODE/native smoke without changing
   the frozen task.
5. Expand a paired comparison only after both arms are infrastructure-valid.
6. Preserve semantic failures as valid reward 0; retry only recorded
   infrastructure-invalid attempts under the preregistered retry rule.
7. Validate run spec, attempt lineage, native result, trajectory, verifier and
   outcome receipts, analysis and source hashes. Before public publication,
   also validate the publication manifest and privacy scans; verify remote
   read-back after uploading the admitted bytes.

## 2026-09-13 full-runtime G-code development gate

The separate `terminalbench21-sol-max-reflexion-ratchet-r3-20260913` run
completed five fresh `gcode-to-text` trials: **5/5 official verifier passes,
zero invalid attempts**. It measured source
`815f75950af580b42cbd52dcc78b0b3ea0017a8f` with OpenAI subscription
`gpt-5.6-sol`, actor effort `max`, Harbor 0.22.0, `verify_mode=reflexion`,
a 900-second agent limit, concurrency 1 and zero automatic retries. The task
image and external scorer were unchanged; earlier candidates were not pooled.

The [development record](../plans/2026-09-13-reflexion-gcode-ratchet.md)
preserves candidate failures, source/spec hashes, admission checks and the
intermediate candidate's unresolved SHM custody incident. The final run's
existing canonical bundle passed validation. Its private raw evidence remains
local; a public artifact package or updated film is not implied by this report.

All five internal judges accepted candidate attempt 0; no repair occurred.
The 87 recorded AgenticLoop calls have no missing input/output/cached-input
fields, but this remains scoped accounting, not whole-runtime cost or billing.
This task was used for candidate selection. There is no fresh baseline/native
Codex comparator, held-out claim, measured repair effect or change to the
historical full-suite primary's not-measurable status.

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
