# R11.2 Native Skill Attribution Validity

Status: implementation contract complete; no live provider execution authorized.

GAPs: EVAL-003, EVAL-004.

## Question and boundary

The immutable R11.1 result answers a narrow question: under one synthetic
fixture, does making a target Skill available change verifier pass? Its three
repetition deltas (`+4`, `-3`, `-1`) do not identify whether variation came
from Skill selection, successful activation, task execution, or sampling.

R11.2 asks a prospective question instead:

> Within each native task family, what is the source-example intention-to-treat
> (ITT) effect of target-Skill availability on deterministic verifier pass?

The treatment is availability only. Selection, successful activation, token
use, elapsed time, irrelevant action, and safety are process outcomes, not
parts of the primary score. No across-family composite has promotion authority.

## Frontier evidence

| Source | Observed contract | GEODE decision |
|---|---|---|
| [ACES 2608.20614](https://arxiv.org/abs/2608.20614) | Paired live trials hold model, sandbox, and grading policy fixed and report outcome and process metrics. | Retain matched arms, but use family-conditioned verifier ITT rather than the paper's equal-weight composite. |
| [Anthropic agent eval guidance](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents) | A trial has a trajectory and a separately graded environment outcome; non-determinism requires repeated trials. | Keep verifier outcome, activation, trajectory, and cost separate; repetitions remain under one source-example lineage. |
| [OpenAI coding-eval audit](https://openai.com/index/separating-signal-from-noise-coding-evaluations/) | Overly strict tests, underspecified prompts, low coverage, and misleading prompts can make an eval broken. | Isolate design from final evaluation, use task-specific response contracts, and reject post-hoc verifier repair. |
| [Inspect `Epochs`](https://github.com/UKGovernmentBEIS/inspect_ai/blob/253d38f255256a5d010836a921fdf9ac0917b86e/src/inspect_ai/_eval/task/epochs.py) | Epochs repeat samples and reduce their scores; they do not create new source samples. | Group arms and repetitions by `example_id`; cluster uncertainty over example means. |
| [Prime Verifiers overview](https://github.com/PrimeIntellect-ai/verifiers/blob/71690b03861719026185e3db746bf4c371d05a90/docs/overview.md) | Current environments are organized around tasksets, harnesses, and traces. | Freeze task data separately from the GEODE harness and reuse existing trajectory/reward/result authorities. |
| [Codex app-server Skills](https://github.com/openai/codex/blob/2b7c279735d0d096cf7b34fe98938f46792f4d4f/codex-rs/app-server/README.md#skills) | Explicit skill input injects the body; name-only lookup asks the model to locate it. | Record selection and successful activation separately from mere availability. |
| [OpenClaw Skills](https://github.com/openclaw/openclaw/blob/d9031e4648a492c1a093ed10c5ed3dbca08cd5b5/docs/tools/skills.md) | Skill eligibility and tool authorization are separate; third-party Skills are untrusted. | Matched tool schemas never change between arms, and Skill availability grants no additional tool authority. |

## Frozen suite

The tracked
[`skill-attribution-native.json`](../../evals/benchmarks/fixtures/skill-attribution-native.json)
contains 18 source examples. The six-example design split may validate prompts,
workspace materialization, and receipts. Its examples and results never enter
the 12-example final-evaluation split.

| Family | Target Skill | Native tools held fixed across arms | Design | Final evaluation |
|---|---|---|---:|---:|
| Web | `deep-researcher` | `general_web_search`, `web_fetch`, `use_skill` | 1 aligned + 1 control | 3 aligned + 1 control |
| Repository | `slop-audit` | `glob_files`, `grep_files`, `read_document`, `use_skill` | 1 aligned + 1 control | 3 aligned + 1 control |
| Delegation | `deep-researcher` | `delegate_task`, `use_skill` | 1 aligned + 1 control | 3 aligned + 1 control |

`spawn_agent` is intentionally absent: `delegate_task` is the one native
delegation primitive needed to measure this question. Adding a second
equivalent control path would enlarge the intervention without identifying a
new estimand.

Each web source is pinned to an upstream commit and content SHA-256. Repository
cases materialize only their synthetic files in a fresh isolated workspace.
Delegation cases expose only the frozen subtask briefs. Evaluator requirements
remain outside `native_model_view()`.

## Causal and leakage contract

1. The primary estimand is the mean paired verifier-pass difference, first
   averaged across repetitions of one `example_id`, then across aligned source
   examples within one family.
2. A deterministic 95% percentile cluster bootstrap resamples source-example
   means. Repetitions are never treated as independent examples.
3. Negative controls are excluded from the ITT. Their verifier pass, selection,
   and activation rates are reported separately.
4. `pair_native_skill_arms()` rejects response-schema, tool-schema, workspace,
   reset-state, verifier, repetition, or non-target availability drift.
5. The deterministic verifier checks the family-specific JSON response and
   required/forbidden native tool receipts. It does not require `use_skill` for
   an outcome pass, so activation cannot become a proxy grader.
6. Model-facing schemas stay within the OpenAI Responses subset; uniqueness is
   enforced by the evaluator, not `uniqueItems`.
7. Null and adverse results remain reportable. Neither R11.1 nor R11.2 grants
   release or runtime-promotion authority.

## Existing authorities reused

No new result or transcript store is introduced. A future execution must write
the existing `geode.eval-run-spec@1`, `geode.eval-attempt@1`, native result,
verifier receipt, `geode.trajectory@1`, `geode.eval-reward@1`,
`geode.eval-analysis@1`, and publication manifest. The R11.1 72-arm bundle is
not read or rewritten by the new code.

`validate_native_run_spec()` binds exactly one split, the suite digest, serial
execution, clean revision, matched comparator, and `promotion_authority=none`.
`preflight_native_tool_surfaces()` compiles the real production tool plan and
proves that each family's with/without arms expose the same schema without a
model call.

## Live execution gate and expected load

No live call is part of this closure transaction. A later execution requires a
new run ID, exact clean revision, model route, privacy boundary, time/usage
budget, and explicit approval.

At the frozen minimum, the design split is 12 parent arms and the final split
is 72 parent arms. Positive delegation cases can add up to 40 delegated model
completions across both phases, for an upper-bound plan of 124 model
completions before multi-turn retries. That estimate must be revisited against
the selected subscription route before approval; it is not a cost claim.

## Acceptance evidence

- Loader tests prove exact family/split/control counts and disjoint lineages.
- Verifier tests prove task-specific outcomes do not depend on Skill activation.
- Pair tests poison reset and treatment fields and fail closed.
- Analysis tests prove three family results, source-example clustering,
  separate process metrics, controls, and no composite.
- Production tool-plan preflight proves matched model-visible schemas.
- Run-spec tests prove that validation is offline while execution fails without
  explicit live approval.
