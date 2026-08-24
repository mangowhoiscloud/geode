# GEO live-only simplification and subscription measurement

Date: 2026-08-24
Status: implemented; native 24×5 complete; A/Q verification in progress
Working branch: `codex/geo-benchmark-quality@b16e6aa0a`
Implementation sync target: `origin/develop@0ac0eecc0`

## Decision

Remove `offline_measure` from the active GEO product and benchmark contract.
GEO remains a stage-aware evidence system, and its canonical acceptance run
uses the existing GPT subscription adapter path. Other supported live adapter
profiles remain possible only when prospectively frozen; none may fall back to
an offline substitute. Deterministic site preflight remains local and
non-model; it is a prerequisite, not an offline visibility runner.

The active state machine becomes:

```text
preflight --operator approval + frozen workload--> live_observe
live_observe --diagnostic close-------------------> complete
live_observe --operator preregistration----------> experiment --> complete
```

`experiment` is optional for a diagnostic and mandatory for a treatment or
promotion claim. Missing A, Q, or O evidence remains `not_measured`; removing
the offline phase does not authorize placeholders or inferred values.

## Why

The repository has SQLite FTS5/BM25 for session-message recall, but it is not a
web-document corpus, reranker, or generative-search simulator. Reusing that
path would add a second execution system while producing results that are not
comparable with the subscription search surface being diagnosed.

The current collector already uses `web_search_via_adapters`. Its nominal
`observation_mode=offline` branch does not provide a separate offline runner,
so retaining the label adds schema and state complexity without adding an
evidence authority. The useful boundary is smaller:

- local/public-host preflight establishes F;
- GPT subscription native receipts establish exposed R, C, and P;
- a separately bound verifier may establish A and the supported-claim portion
  of Q;
- first-party analytics may establish O later;
- a preregistered live baseline/treatment comparison is required for a change
  claim.

## GAP audit

| ID | Current state | Problem | Planned closure |
|---|---|---|---|
| GEO-L1 | Runtime phases are `preflight → offline_measure → live_observe → experiment`. | The product requires a phase with no executable measurement producer. | Remove active offline admission and allow diagnostic completion from `live_observe`. |
| GEO-L2 | The branch-only workload and vector v1 accept `observation_mode=offline`. | Live-shaped fields become dummy values before this unreleased contract has any compatibility value. | Correct the unreleased v1 contracts in place; do not manufacture a v2 or a fake retention burden. |
| GEO-L3 | `geo_collect.py` branches on the mode but always calls a provider adapter. | The branch advertises behavior it does not implement. | Reject legacy/offline inputs and remove the mode branch from the canonical collector. |
| GEO-L4 | Model-visible `update_geo(record)` accepts shape-valid numbers and locators. | Typed shape does not prove a validated measurement artifact. | Keep slash state explicitly advisory; grant measurement authority only to the separately schema- and digest-validated eval bundle instead of importing it into mutable state. |
| GEO-L5 | Runtime completion requires experiment evidence. | A non-promotional diagnostic cannot close honestly. | Add `completion_kind=diagnostic|experiment`; diagnostic closes after live, experiment closes after a preregistered comparison. |
| GEO-L6 | A/Q verification re-fetches cited sources at verification time. | The source may drift after the native response. | Bind fetch time, content digest, TLS result, and exact source receipt before verifier admission; invalidate drift. |
| GEO-L7 | The current public result has only a surface comparator. | More repetitions cannot create causal authority. | Keep diagnostic authority at `none`; require a named paired live comparator and matched observation window for experiment claims. |

## Removal inventory

The implementation removes active behavior, not immutable evidence.

| Surface | Remove or disconnect | Preserve |
|---|---|---|
| `evals/geo.py` | `GeoPhase.OFFLINE_MEASURE`, transition guards, tool-visible phase | migration-only recognition of legacy rows and their session-event history |
| `.geode/skills/geo/SKILL.md` | offline phase instructions and compulsory traversal | F/R/C/P/A/Q/O denominators, approval, evidence frontier, no scalar score |
| `.agents/skills/geo/SKILL.md` | scaffold wording that asks for offline measurement | runtime loader checks, subscription approval, trajectory/publication rules |
| `geo-workload` | canonical `observation_mode` switch | frozen queries, model, locale, account state, K, result limit, approval digest |
| `geo-vector` | active `offline_measure` evidence phase and mode field | separate stage metrics, producer/verifier/outcome digests |
| `geo_collect.py` / `geo_visibility.py` | offline branches and fallback phase selection | strict 24×K matrix and provider-native source/citation projection |
| tests | fake offline traversal and offline-shaped fixtures | legacy migration test, mocked subscription route tests, real live marker |
| public docs | offline-runner and frozen-corpus claims | local preflight, live measurement, diagnostic/experiment distinction |
| FTS5/BM25 | any GEO coupling, corpus schema, qrels, reranker scaffolding | existing session-memory behavior unchanged |

Historical plan text and existing local receipts are not rewritten. They remain
dated evidence, but the branch-only v1 schema is not a published compatibility
surface and therefore receives no validator-only legacy path.

## Canonical live measurement contract

### Route

The acceptance run uses the in-process adapter registry, not a CLI subprocess:

```text
provider=openai
credential_source=subscription
adapter=codex-oauth
model=gpt-5.6-sol
effort=medium
```

The exact model label and adapter revision are frozen in `run-spec.json` and
`workload.json`. If the installed subscription surface does not expose that
model or native search/citation fields, the run is infrastructure-invalid; it
does not silently fall back to PAYG, another model, answer-prose parsing, or an
offline substitute.

### Execution stages

1. **Preflight**: build/export, internal-link receipt, deployed-host HTTP/HTML,
   canonical/noindex/robots checks. No model call.
2. **Route canary**: one non-score-bearing frozen query verifies OpenAI /
   subscription / `codex-oauth`, model identity, search activation, native
   source fields, citation fields, timeout, quota, and redaction behavior.
3. **Diagnostic matrix**: after the canary passes, run the frozen 24 queries at
   K=5 in fresh observations. The prospective approval receipt binds the exact
   engine, model, locale, account state, repetitions, and workload digest.
4. **A/Q overlay**: verify only target-cited observations. Preserve verifier
   producer, revision, model, rubric digest, cited-source digest, claim
   universe, exact quote, and support verdict. Same-model judgement is
   advisory until calibrated against a human sample.
5. **O overlay**: attach only a completed first-party Search Console, referral,
   or conversion window. Otherwise keep O `not_measured`.
6. **Experiment**: run only after a separately frozen baseline/treatment
   contract. Match workload, subscription route, model, locale, account state,
   budget, and observation schedule. Index-state uncertainty remains an
   invalidation condition rather than being hidden by repetition.

### Evidence authority

| Evidence | Authority |
|---|---|
| site/link/host receipt | F prerequisites |
| provider-native subscription receipt | R/C/P and answer source |
| verifier + cited-source receipts | A and supported-claim Q only |
| first-party analytics receipt | O only |
| `geode.trajectory@1` | runtime behavior and tool correlation only |
| `analysis.json` | interpretation of the frozen question |
| publication manifest | exact public bytes and disclosure state |

No terminal transcript, model self-score, trajectory, or judge score may
replace a provider-native observation.

## Schema and migration boundary

1. Correct the unreleased `geode.geo-workload@1` and
   `geode.geo-vector@1` contracts in place. Do not include
   `observation_mode`; the profile itself is live-only.
2. Bind the run-spec digest into the canonical native result and bind native,
   verifier, preflight, and outcome digests into the vector.
3. Rebuild the SQLite GEO projection schema without the offline phase.
   Migration removes offline-phase measurements from the mutable projection,
   records a bounded `legacy_offline_retired` marker, and leaves append-only
   session events untouched.
4. A legacy run parked in `offline_measure` returns to `preflight`; it cannot
   enter live observation until a new operator approval and frozen live
   workload are attached. Runs already in live/experiment/complete retain
   their phase, but legacy offline measurements do not acquire live authority.

## Prompt, cache, and trajectory invariants

- Do not add a GEO executor, parser, TaskGraph, FTS index, reranker abstraction,
  or second agent loop.
- Keep typed GEO state inside the existing bounded dynamic XML region. The
  static prefix and prompt-cache boundary must remain byte-identical.
- Approval and preregistration remain operator-owned slash actions. A model
  tool cannot mint either receipt or select a credential source.
- Export parent and child trajectories from canonical `sessions.db`; require
  turn/call correlation and scope completeness. Private bodies remain digested
  for a public candidate.
- Preserve native result, verifier result, attempt lineage, analysis, and
  publication manifest as separate digest-bound authorities. Do not create an
  Inspect `.eval` unless Inspect produced the run.

## Implementation order

1. Sync this feature worktree with current `origin/develop` and resolve the
   plan/doc surfaces before modifying runtime code.
2. Add the live-only state transition and projection migration, with focused
   store/tool tests.
3. Make the branch-only v1 schemas live-only and switch the
   collector/measurement/bundle validation to the corrected contract.
4. Remove offline wording and branches from runtime/scaffold skills, public
   docs, schemas, scripts, and active E2E fixtures. Add an `rg` residual gate.
5. Prove that slash completion remains advisory and that only the eval bundle
   validator can grant measurement authority.
6. Run mocked subscription adapter tests, state migration tests, prompt
   XML/cache checks, targeted Ruff/Mypy/Pytest, and the non-live package gate.
7. Freeze the prospective run spec and approval, then execute the one-query
   GPT subscription canary. Stop on route/model/native-field drift.
8. If the canary is valid, execute the full 24×5 subscription diagnostic,
   produce attempts/analysis/trajectory candidates, and inspect failures before
   any publication or content change.
9. Only after the diagnostic is clean, preregister a separate live
   baseline/treatment experiment for a specific repair. Do not promote from
   the diagnostic.

## Post-diagnostic repair plan

This continuation is planned, not implemented. The current live diagnostic
must finish and pass receipt, vector, verifier, trajectory, and publication
audits before any item below starts.

1. **Targeted repair candidate**: for one observed failure stage and one
   operator-owned Markdown/HTML target, produce the smallest unified diff.
   Bind the base digest, patch digest, failure evidence, changed lines, source
   support, and deterministic build/link/schema checks. Do not publish it.
2. **Paired live experiment**: after operator preregistration and preview-host
   publication, run baseline and treatment with the same frozen query matrix,
   subscription adapter, model, locale, account state, repetitions, budget,
   and observation schedule. Reject route, index-state, or timing drift.
3. **Verdict and release boundary**: require the target stage to improve
   without F/R or source-supported Q regression, including held-out
   paraphrases. Preserve a rollback reference and keep release authority with
   the operator. The first OSS release path is a reviewed Git patch/PR; CMS
   adapters are out of scope.
4. **Strategy distillation**: only after independent valid experiments span
   multiple documents or domains, reuse the existing SIL mutation surface to
   retain stage-, engine-, and domain-scoped repair patterns. Do not add a
   surrogate critic, MAP-Elites, or a global strategy bank before that evidence
   exists.

The repair candidate, paired result, native provider receipts, verifier
receipts, first-party outcome receipt, and `geode.trajectory@1` remain separate
digest-bound authorities. No Inspect `.eval` is created unless Inspect
produced the run, and no aggregate GEO score is introduced.

## Acceptance criteria

1. Active runtime, tool schema, runtime skill, scaffold skill, canonical v1
   schemas, collector, measurement script, public docs, and current tests
   contain no `offline_measure` or offline visibility path.
2. Remaining `offline_measure` literals are allowlisted only in dated
   historical plans/receipts, v1 validation, and the bounded migration code and
   test; no active call graph reaches them.
3. A diagnostic run can complete after valid live evidence without an
   experiment receipt. A treatment claim cannot complete without
   preregistration and experiment evidence.
4. The frozen acceptance profile accepts only OpenAI subscription /
   `codex-oauth` and fails closed on route or model drift. Another supported
   live adapter requires its own prospective profile and evidence class.
5. The route canary proves actual subscription adapter reachability and native
   search/citation receipt production before the 120-observation matrix starts.
6. The live matrix has exactly 24×5 unique workload cells; missing, duplicate,
   reordered, pre-freeze, digest-mismatched, or prose-derived observations fail.
7. F/R/C/P/A/Q/O retain independent denominators and no aggregate GEO score is
   introduced. Missing A/Q/O remain `not_measured`.
8. Runtime state cannot grant benchmark or promotion authority. A model cannot
   grant approval or preregister; model-authored numerators remain advisory,
   while only the schema- and digest-validated eval bundle is measurement
   evidence.
9. Prompt static prefix/cache key, balanced dynamic XML, trajectory call/result
   correlation, privacy classification, and artifact bundle validation pass.
10. No live result is published until exact-byte privacy review, release
    staging, immutable artifact commit, and remote read-back succeed.
11. A failed live cell leaves frozen-workload-matched native checkpoints but
    no final matrix; rerunning the same frozen run resumes those cells and
    rejects unexpected or drifted checkpoint bytes.
12. A failed A/Q call likewise preserves validated source and verifier
    receipts, emits no final overlay, and resumes only missing observations
    after rejecting source, rubric, model, or producer drift. A shape, claim,
    or exact-quote validation failure permits one correction request and then
    fails closed without weakening the validator.

## Non-goals

- local/BYO corpus ingestion, qrels, FTS5/BM25 GEO search, reranking, or an
  offline generative-search simulator;
- scraping or automating a commercial search UI;
- silent PAYG or cross-provider fallback;
- treating GPT subscription observations as a universal search-engine score;
- filling O without first-party data;
- rewriting historical receipts or calling a diagnostic a causal experiment.
