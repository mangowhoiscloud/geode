---
eval_id: geo-visibility
eval_family: geo-visibility
eval_kind: benchmark
eval_status: canonical
eval_authority: suite-profile
eval_summary: Reproducible GEODE profile for measuring generative discovery, citation selection, answer absorption, and fidelity without collapsing them into one GEO score.
eval_triggers:
  - GEO
  - AI search visibility
  - citation benchmark
  - generative engine optimization
  - query fan-out
eval_contracts:
  - core/observability/schemas/trajectory-release.schema.json
  - core/observability/schemas/trajectory.schema.json
  - docs/eval/artifact-publish-manifest.template.json
  - docs/eval/schemas/geo-host-preflight.schema.json
  - docs/eval/schemas/geo-link-audit.schema.json
  - docs/eval/schemas/geo-live-approval.schema.json
  - docs/eval/schemas/geo-native-results.schema.json
  - docs/eval/schemas/geo-outcome.schema.json
  - docs/eval/schemas/geo-preflight.schema.json
  - docs/eval/schemas/geo-workload.schema.json
  - docs/eval/schemas/publication.schema.json
  - docs/eval/schemas/run-spec.schema.json
---

# GEO Visibility Benchmark

## Research question

Which GEODE pages are discoverable, selected, cited, absorbed into answers, and
represented faithfully for real user intents? The benchmark never substitutes
one of those stages for another.

## Evidence basis

- [Google's generative AI optimization guide](https://developers.google.com/search/docs/fundamentals/ai-optimization-guide)
  keeps foundational SEO, crawlability, useful non-commodity content, and
  Search Console measurement as the official path; it rejects special GEO
  schema, unnecessary AI text files, and query-variant content farms.
- [Bing AI Performance](https://blogs.bing.com/webmaster/February-2026/Introducing-AI-Performance-in-Bing-Webmaster-Tools-Public-Preview)
  separates total citations, cited pages, grounding queries, and trends, and
  warns that citation count is not ranking or page importance.
- [GEO: Generative Engine Optimization](https://arxiv.org/abs/2311.09735)
  measures visibility changes in its experimental setting; its reported gains
  are not a universal organic-discovery guarantee.
- [C-SEO Bench](https://proceedings.neurips.cc/paper_files/paper/2025/hash/27aa3aeff0f8460a7b43d30fa6c5c032-Abstract-Datasets_and_Benchmarks_Track.html)
  finds most tested rewrites ineffective or harmful across retrieval rank,
  domains, models, and multiple optimizing actors.
- [SAGEO Arena](https://arxiv.org/abs/2602.12187) re-runs the complete
  retrieval-to-generation pipeline and reports that body-only changes can
  degrade multiple stages; it is a preprint, not settled product evidence.
- [Citation selection vs absorption](https://arxiv.org/abs/2604.25707)
  shows that citation breadth and answer influence diverge.
- [AgentGEO](https://arxiv.org/abs/2603.09296) motivates failure-stage
  diagnosis and targeted repair instead of generic rewriting.
- [AttributionBench](https://aclanthology.org/2024.findings-acl.886/) shows that
  automated citation entailment itself needs calibration and human audit.
- [Adversarial SEO for LLMs](https://proceedings.iclr.cc/paper_files/paper/2025/hash/0f12b3c36a781120c4f60e90e855868d-Abstract-Conference.html)
  makes preference manipulation, prompt injection, and competitor denigration
  security failures rather than optimization techniques.

Artifact handling follows four additional primary contracts:

- [Inspect AI log files](https://inspect.aisi.org.uk/eval-logs.html) define
  `.eval` as Inspect's binary native log format and require its log API rather
  than ad hoc JSON parsing. A GEODE slash transcript is therefore not renamed
  or transcoded into `.eval`.
- [OpenAI Agents SDK tracing](https://openai.github.io/openai-agents-python/tracing/)
  models a workflow as a trace of nested spans and warns that generation and
  tool spans may contain sensitive inputs and outputs. GEODE public releases
  retain structural events while digesting private bodies.
- [OpenTelemetry trace links](https://opentelemetry.io/docs/specs/otel/trace/api/)
  support asynchronous and batched relationships. GEODE preserves parent and
  child session identities rather than flattening a parallel `/geo` run into
  one terminal transcript.
- [W3C PROV](https://www.w3.org/TR/prov-overview/) separates entities,
  activities, agents, and derivations; [SLSA v1.2](https://slsa.dev/spec/v1.2/)
  similarly binds outputs to producer and input provenance. GEODE consequently
  keeps native result, attempt lineage, trajectory, verifier judgement,
  analysis, and release manifest as separate authorities joined by digests.

## Canonical root intent set v1

This suite freezes the six roots and expected evidence families below. Each
live run must derive exactly three paraphrases per root and freeze all 24 exact
strings, in order, in its workload artifact referenced by `run-spec.json`
before any engine call. Engine, model surface, locale, account state, and budget
remain run-specific, so this suite profile does not pretend they are already
preregistered.

| ID | Root intent | Fan-out branches | Expected GEODE evidence |
|---|---|---|---|
| GEO-01 | What is GEODE? | identity, self-hosting, target user | landing, portfolio |
| GEO-02 | How does GEODE's AgenticLoop work? | termination, tools, context | agentic-loop docs |
| GEO-03 | How does GEODE compare with Codex and OpenClaw? | loop, gateway, goals | lineage/references |
| GEO-04 | Which models and auth routes does GEODE support? | provider, subscription, PAYG | provider/auth docs |
| GEO-05 | What benchmark evidence supports GEODE? | suite, score, limitation | eval index/run records |
| GEO-06 | How does GEODE implement Goal and planning? | persistence, advisory plan, continuation | research/runtime docs |

## Evidence states and measurement vector

Runs progress through `preflight → offline_measure → live_observe → experiment`.
An earlier state never proves a later state. Preserve `not_measured` when a
prerequisite, approval, frozen workload, or receipt is absent. Do not publish
an aggregate GEO score.

One query run is one observation. The live profile has 6 roots × 4 frozen
wordings × K=5 repetitions, so C uses 120 observations. Other stages preserve
their own eligible populations rather than silently treating missing evidence
as failure.

| Code | Stage | Numerator | Denominator |
|---|---|---|---|
| F | Fetch/index eligibility | URLs passing each preflight condition | audited target URLs |
| R | Retrieval inclusion/rank | runs whose exposed retrieval list contains a target URL | 24×K runs that expose retrieval |
| C | Citation selection | runs citing a target URL | all 24×K query runs |
| P | Visible placement/rank | target-cited runs with `visible_rank ≤ 3` | target-cited runs |
| A | Answer absorption | runs where a verifier confirms target use | target-cited runs with an A verdict |
| Q | Claim support submetric | supported target-linked claims | verifier-declared target-linked claims audited in full |
| O | First-party outcome | observed referrals, engagement, or conversions | eligible first-party impressions, referrals, or sessions |

The executable v1 validator measures only the claim-support component of Q.
It therefore reports Q as `partial` even when every target-cited response has a
verifier receipt; completeness, authority, and factuality need their own frozen
rubrics and receipts.

## Protocol

1. Run deterministic preflight first. Local export evidence is intentionally
   `partial`; F becomes `measured` only when a separate public-host receipt
   binds the same URL-set digest and passes HTTP, HTML, self-canonical,
   noindex, and host-root robots checks:

   ```bash
   cd site
   npm run build
   npm run export-md
   npm run verify-metadata
   node scripts/verify-geo-preflight.mjs --receipt <run-dir>/site-preflight.json
   cd ..
   uv run python scripts/check_docs_links.py --receipt <run-dir>/link-audit.json
   uv run python scripts/eval/geo_host_preflight.py \
     --base-url https://mangowhoiscloud.github.io/geode/ \
     --expected-sitemap site/out/sitemap.xml \
     --out <run-dir>/host-preflight.json
   ```
2. For live engines, use every frozen root and paraphrase in fresh sessions at
   `k=5` repetitions per engine. Record engine/model surface, locale, account
   state, timestamp, search activation, cited URLs, answer, and screenshots or
   native receipts where permitted. The frozen workload must digest-bind an
   operator-owned `geode.geo-live-approval@1` receipt for the same run, engine,
   model, locale, account state, and repetition count.
   Collect only provider-native retrieval and citation fields through the
   existing adapter registry, then bind the frozen workload and receipts
   through the measurement contract:

   ```bash
   uv run python scripts/eval/geo_collect.py \
     --run-spec <run-dir>/run-spec.json \
     --workload <run-dir>/workload.json \
     --site-preflight <run-dir>/site-preflight.json \
     --link-audit <run-dir>/link-audit.json \
     --host-preflight <run-dir>/host-preflight.json \
     --out <run-dir>/native-results.json

   uv run python scripts/eval/geo_visibility.py \
     --run-spec <run-dir>/run-spec.json \
     --workload <run-dir>/workload.json \
     --native-results <run-dir>/native-results.json \
     --out <run-dir>/geo-vector.json
   ```

   The command validates the complete 24×K observation matrix and emits
   separate R/C/P/A/Q denominators, the run-spec digest, native producer,
   verifier/rubric identity, preflight/outcome receipt digests, and audited-claim
   coverage. Requested result count is an input constraint, not a promise that
   the provider will expose exactly that many sources. The collector retains
   every provider-native source and citation and never parses answer prose into
   either field. It has no aggregate score field.
3. For offline intervention evaluation, hash original, sham, and targeted
   repair arms; reindex every arm and re-run retrieval, reranking, and
   generation. Include initial-rank controls and a multi-actor adoption arm.
4. Audit citation entailment at claim level. Automatic judgments are secondary
   until a human reviews disagreements and a calibration subset.
5. Invalidate causal claims when prompt order, engine version, indexing state,
   competing pages, or observation windows differ between arms.

## Long-running execution benchmark

Freeze one workload, model route, effort, corpus/web state, tool policy, and
budget, then compare:

- A — sequential ReAct `/geo`;
- B — A plus epoch checkpoints of evidence, uncertainty, failures, and
  unvisited leads;
- C — B plus a parent-supervised batch of at most three independent read-only
  branches.

The parent performs prerequisites, join, contradiction resolution,
deterministic checks, synthesis, and all writes. A branch result is bounded to
claims, evidence locators, contradictions, confidence, and unresolved gaps.
Same-model critique is advisory, not a correctness gate.

Record required-question coverage, primary-source recall, locator entailment,
contradiction discovery/resolution, unsupported-claim rate, forgotten-branch
rate, duplicate tool calls, propagated branch errors, checkpoint quality gain,
tokens, tool calls, context size, and wall time. Run each strategy at least
three times before comparing quality or efficiency. Keep frozen-corpus and live
web results in different comparability classes; a single live smoke proves only
that the execution path worked.

## Current execution boundary

Repository and public-HTTP preflight are non-paid and may run in CI/E2E. Live
commercial-engine repetitions can spend quota and expose account-dependent
state, so they require an explicit prospective run spec and user approval.
Until then, `/geo` output is an audit and implementation probe, not a scored
visibility claim.

The project can publish `/geode/sitemap.xml`, but this repository cannot own
the GitHub Pages host-root `/robots.txt`. Record host-root behavior as an
environment observation instead of claiming this project controls it.

Provider-native citation annotations establish C and P, not A or Q. A requires
a separate target-use verdict; Q requires a separately digest-bound claim
universe, cited source content, rubric, and verifier identity. O likewise needs
a first-party Search Console, referral, or conversion receipt whose observation
window has ended. Missing receipts remain `not_measured`; they are never filled
from model prose or a same-run judge.

A diagnostic visibility run deliberately retains `promotion_authority=none`.
Promotion is a different preregistered experiment: it needs a direct named
comparator, frozen arms, matching index and observation windows, and the
authority corresponding to its run-spec claim class. More data in one
diagnostic run cannot manufacture that authority.

## Trajectory and artifact publication

### Authority and format selection

| Evidence | Canonical form | Publication rule |
|---|---|---|
| Inspect-produced evaluation | Native `.eval` plus SHA-256 reference | Preserve byte-identically; do not parse or synthesize it as the GEODE score authority |
| GEODE slash behavior | `geode.trajectory@1` exported from `sessions.db` | Export parent and every child; use digest-content for a public candidate |
| Suite/route outcome | Native result | Keep separate from trajectory and verifier judgement |
| Retry history | `attempts.jsonl` | Append-only; never remove failed or contaminated attempts |
| Judgement | Verifier receipt or state diff | Keep separate from native outcome |
| Interpretation | Digest-bound `analysis.json` | Answer only the frozen question; no promotion for smoke runs |
| Public bytes | `geode.trajectory-release@1` plus artifact publication manifest | Allowlist, privacy review, SHA-256, immutable external commit, remote read-back |

Do not create a `.eval` compatibility wrapper for `/geo`. If a future GEO
benchmark actually runs under Inspect, retain its native `.eval` and bind it to
the normalized trajectory with `geode session export-trajectory --sil-eval`.
Otherwise the canonical source is GEODE's session-event store.

Export one trajectory for the parent and each child so a fan-out failure does
not disappear inside a single aggregate transcript:

```bash
geode session export-trajectory <session-id> \
  --sessions-dir <isolated-session-dir> \
  --digest-content \
  --out <run-dir>/trajectory-candidates/<session-id>.json
```

The source SQLite/WAL, raw terminal transcript, messages, evidence JSONL,
worker results, profiles, usage, diagnostics, provider payloads, and hidden
reasoning are `withheld-private` by default. Credentials and environment files
are `private-secret`; scratch checkouts and complete evaluator homes are
`reproducible-cache`. None is copied recursively. A transformed public copy has
its own byte count and digest and never claims the raw artifact's identity.

After exact-byte privacy review, stage only the reviewed trajectories:

```bash
geode session stage-trajectory-release \
  <run-dir>/trajectory-candidates/*.json \
  --destination <staging-root> \
  --source geode-agenticloop \
  --scope <run-id> \
  --privacy-review <privacy-review.json> \
  --allow-replay-incomplete

geode session verify-trajectory-release <release-dir> \
  --expected-manifest-sha256 <sha256>
```

`--allow-replay-incomplete` is appropriate only because public payload bodies
are content-digested; scope completeness remains mandatory. Copy the resulting
content-addressed release and reviewed aggregate sidecars into fresh paths in a
fresh `geode-eval-artifacts` branch. Recommended destinations are:

```text
trajectories/geode-agenticloop-<run-id>-<published-utc>-<digest12>/
reports/e2e-validation/<run-id>/
```

Open an artifact-repository PR, merge it append-only, and independently read
back the exact files from the merge commit. Only then record the artifact
commit, immutable links, and manifest SHA-256 in the GEODE eval ledger. Do not
publish a score or improvement claim from a local path alone.

### 2026-08-20 parallel smoke publication preflight

The prospective run
`gpt56-sol-geo-parallel-isolated-20260820t070700z` remains an internal,
non-comparable smoke with `promotion_authority=none`. Its frozen privacy class
is `internal`, so its raw `live-cli.typescript` and isolated runtime home are
not public candidates.

The existing exporter reconstructed four digest-content trajectory candidates
from the parent plus three child sessions: 549 canonical events, 254 tool calls
paired with 254 results, zero orphan calls/results, and four scope-complete
trajectories. All four are deliberately replay-incomplete because private
payload bodies are omitted. They remain local candidates until an exact-byte
privacy review changes `privacy.review_state` to `reviewed` and the release
staging gate passes. No `.eval` was produced because Inspect AI was not the
producer, and no remote artifact upload occurred during this feature work.
