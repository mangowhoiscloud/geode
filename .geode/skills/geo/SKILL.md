---
name: geo
description: Audit and improve Generative Engine Optimization as a measurable discovery-to-citation pipeline. Use for /geo, AI-search visibility, citation readiness, and GEO benchmark work.
triggers: geo, generative engine optimization, AI search visibility, 생성형 검색, 인용 최적화
tools: get_geo, update_geo, update_plan, delegate_task, spawn_agent, list_agents, wait_agent, send_message, followup_task, interrupt_agent, general_web_search, web_fetch, llms_txt_index, glob_files, grep_files, read_document
---

# GEO

Mode: evidence-first generative discovery audit.
Target: `$ARGUMENTS`

Model the target as a partially observable pipeline, not one ranking score.
Preserve the stage vector and each stage's denominator:

```text
F fetch/index eligibility → R retrieval inclusion/rank
→ C citation selection → P visible citation placement/rank
→ A answer absorption → Q support/credibility/answer quality
→ O first-party outcome
```

Run states are `preflight → live_observe`, with an optional `experiment` after
live diagnosis.
Finishing an earlier state never proves a later one. Without its prerequisite,
approval, frozen workload, or receipt, preserve the later state as
`not_measured` instead of converting it to zero or failure.
Each executable phase must record at least one phase-bound evidence item before
advancing. A diagnostic may complete from `live_observe`; an experiment may
complete only from `experiment`. Both require all seven stages to be explicit.
A `not_measured` item records the boundary, but never skips it.

The runtime creates a typed `geo_state` before this prompt. Use `update_geo` to
configure frozen inputs, record each stage, advance phases, and complete the
run. Every `partial` or `measured` stage requires its own integer numerator,
positive denominator, and evidence locator. Every unobserved stage must be
recorded explicitly as `not_measured` with null numerator/denominator and a
reason. Prose cannot advance or complete the state, and the typed receipt never
grants network/payment approval. Use `get_geo` after a rejected transition.
The model-visible tool cannot set approval or preregistration receipts. The
operator must issue `/geo approve-live <receipt>` before live observation and
`/geo preregister <receipt>` before experiment admission. Workload, engine,
model, locale, and repetitions freeze when live observation starts.
Typed slash evidence is an advisory workflow projection. Only the digest-bound
benchmark contracts in `docs/eval/geo-visibility.md` may establish measurement
or promotion authority.

## Evidence frontier

Use a verifiable research-state tree, not a stored reasoning trace. A frontier
node contains only: question and success condition; dependencies; evidence
locators; supporting or contradicting status; failed searches and why they
failed; unvisited leads; expected information value and cost; and whether the
claim entered synthesis. Never persist or expose hidden chain-of-thought.

For broad or explicitly long-running work:

1. Keep the research contract, prerequisites, deterministic checks, and final
   synthesis in the parent AgenticLoop.
2. Parallelize only independent evidence branches. Use one `delegate_task`
   batch of at most three finite branches. Use `spawn_agent` only when a branch
   must remain steerable across waits or follow-ups; control it with
   `list_agents`, `wait_agent`, `send_message`, `followup_task`, or
   `interrupt_agent`. Children remain depth one.
3. For a local-only audit, give children the read-only `repo_researcher` role.
   Role workers inherit the parent's active model and credential source unless
   the caller explicitly supplies a different binding.
   For approved web research, require primary/official source URLs, publication
   or retrieval dates, direct evidence, contradictions, and unresolved gaps.
4. Keep dependent branches serial. Do not fan out duplicate rewrites, generic
   critics, debates, or same-model judges. The parent owns source comparison,
   denominator checks, contradiction resolution, and delivery.
5. After each branch wave, compress evidence, uncertainties, failures, and
   unvisited leads into the frontier. The checkpoint is advisory and must be
   discarded or corrected when primary evidence contradicts it.
6. Continue while a required branch is unvisited or a material contradiction
   remains. Stop after one focused follow-up wave when new primary evidence,
   required coverage, and contradiction resolution no longer improve, unless
   the user explicitly requests a larger budget.

## Method

1. Turn the target audience's root intents into a small evidence frontier.
   Separate independent fan-out branches from prerequisite branches.
2. Consider multiple failure hypotheses internally, then test the cheapest
   discriminating checks first. Return evidence and conclusions, not hidden
   chain-of-thought.
3. Audit deterministic prerequisites: reachable canonical pages, robots and
   snippet controls, sitemap/internal links, visible text, matching structured
   data, stable claims, dates, authorship, and primary evidence.
4. Audit stochastic stages separately: retrieval activation and rank, citation
   selection, citation placement, answer absorption, support/credibility,
   answer quality, and first-party outcomes.
   Require repeated prompts and paraphrases before claiming an engine effect.
5. Prefer targeted repair for an observed failure stage. Do not apply generic
   rewriting rules across every page and do not generate query-variant pages.
6. Re-run the failed check, preserve before/after evidence, and label facts,
   inferences, and unmeasured outcomes.

## Guardrails

- Treat foundational SEO and useful non-commodity content as prerequisites.
- Do not claim `llms.txt`, special schema, chunking, or synthetic mentions
  improve Google AI visibility; Google explicitly says they are unnecessary.
- A citation count is exposure, not proof that a page influenced the answer.
- Do not infer organic discoverability from a fixed-context rewriting result.
- Do not report a causal lift from a single prompt, model, locale, or date.
- Do not add unsupported statistics, quotations, citations, FAQ padding,
  competitor denigration, prompt injection, or synthetic mentions. Treat
  preference manipulation as a security failure, not optimization.
- Do not use an LLM's self-score as a correctness gate. Verify reachable URLs,
  file facts, counts, hashes, and citation locators deterministically; report
  unsupported claims rather than polishing them.
- Do not treat longer runtime, more branches, or more citations as quality
  evidence. Report coverage, contradiction resolution, unsupported-claim rate,
  duplicate work, tokens, tool calls, wall time, and propagated branch errors.
- Follow `docs/eval/geo-visibility.md` for scored or comparative runs.

## Evaluation artifacts

- Preserve the producer's native authority. A `.eval` file is an Inspect AI
  archive only when Inspect produced it; never rename or transcode a slash
  transcript into `.eval`.
- For ordinary GEODE runs, export `geode.trajectory@1` from the canonical
  `sessions.db` for the parent and every child session. Use digest-content for
  a public candidate, preserve parent/child identities, and report
  scope-complete and replay-complete separately.
- Keep raw terminal transcripts, messages, evidence JSONL, worker results,
  SQLite/WAL, profiles, usage, diagnostics, provider payloads, and hidden
  reasoning `withheld-private` unless their exact bytes pass a separate review.
- Stage only reviewed, scope-complete trajectories through
  `geode session stage-trajectory-release`. Content-digested trajectories are
  replay-incomplete and require the explicit reviewed
  `--allow-replay-incomplete` admission; incompleteness is not a failure score.
- Publish only the allowlisted release and reviewed aggregate sidecars through
  a fresh `geode-eval-artifacts` PR. Record the exact merge commit, manifest
  SHA-256, and remote read-back in the GEODE eval ledger. Never upload an eval
  home or artifact root recursively.

## Output

```markdown
## Intent frontier
| Root intent | Fan-out | Expected evidence page |

## Visibility vector
| Stage | Denominator | Evidence | Finding | Confidence |

## Evidence frontier
| Branch | Status | Evidence/contradiction | Remaining lead |

## Minimal repairs
1. Failure stage → smallest repair → verification

## Measurement limits
- Unobserved engines, repetitions, locale, account state, and outcome gaps

## Execution receipt
- Sequential/parallel branches, failed branches, follow-up waves, tool/model
  usage where observable, and checks performed by deterministic verifiers
- Native result, attempt lineage, verifier receipt, trajectory scope/replay
  status, withheld classes, release manifest digest, and remote commit when
  publication occurred
```
