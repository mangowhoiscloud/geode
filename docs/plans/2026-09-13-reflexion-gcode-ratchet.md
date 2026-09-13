# Evidence-grounded verification within one execution budget

## Question and boundary

Can GEODE finish five fresh development attempts of `gcode-to-text` under
the unchanged 900-second Harbor agent limit after fixing verification and
deadline handling? This task has already been inspected: 5/5 is a development
ratchet, not held-out accuracy, a generalization claim, or a causal comparison
against historical Codex results. All five attempts count; failed candidates
and their entire attempt sets remain preserved.

## Observed gaps and smallest changes

| Gap at develop a2126a2b | Change | Check |
|---|---|---|
| Short text, historical tool errors and keyword overlap veto semantic review | Remove those heuristic verdicts; retain mechanical empty/action-required checks | Recovered errors and concise correct responses reach the LLM judge |
| Judge-unavailable legacy path can become a structural pass | Both LLM verification modes fail closed | None, malformed and timed-out responses never pass |
| Global head truncation can omit the last observations; images are absent | Bound each observation and reuse already-observed image evidence without new access | Latest evidence survives; images become image inputs, not text blobs |
| Verification continuations restart local elapsed time | Keep one root-turn clock | A repair cannot buy another execution budget |
| A text-length guard can discard a revised candidate before review | Remove the overthinking stop heuristic | Long candidates reach verification; refusal and cost guards remain |
| Late candidate formation leaves no feedback time | For bounded Reflexion, reserve up to the final third (maximum 300 seconds) for review and repair | First candidate checkpoint allows later repair tools, never extends deadline |

Trace Harbor's timeout through the full runtime and delegated workers before
altering propagation. Reuse existing session, hook, usage and trajectory owners;
do not add a judge store, a benchmark-answer prompt, or a second raw store.

The first-candidate checkpoint is tested between model calls; it cannot promise
that an in-flight call yields exactly at the threshold. Harbor's outer timeout
remains the hard cap. Child workers inherit session duration, not the parent's
remaining-time clock; parent cancellation still terminates late delegation.

## Research grounding

[Reflexion](https://arxiv.org/abs/2303.11366) conditions subsequent attempts on
linguistic feedback retained from execution. Its [original implementation](https://github.com/noahshinn/reflexion)
separates interaction, feedback and reflection. GEODE reuses its existing bounded
continuation instead of adding a framework or updating model weights.
[Anthropic's evaluator-optimizer pattern](https://www.anthropic.com/engineering/building-effective-agents)
likewise uses an evaluator call to provide actionable feedback. Neither source
makes an LLM verdict equivalent to an external executable test.

Here, the runtime judge sees only authorized request and observed evidence.
Harbor's unchanged task verifier alone assigns the benchmark reward after the
agent closes. Five measurement repetitions are distinct from up to two repairs
inside each attempt. The old full-suite result and its exclusions stay immutable.

## Execution and integration

1. Apply targeted tests, lint, types and independent review to the candidate.
2. Commit source and prospectively freeze a new run spec, task/image digests,
   OpenAI subscription `gpt-5.6-sol` route, effort policy, five sequential fresh
   attempts, 900 seconds each, concurrency 1 and zero automatic trial retries.
3. Run fail-closed install, oracle, auth and optional separately budgeted canary
   gates. Retain operator capture, native output, verifier, trajectory and usage.
4. Complete the frozen five-attempt batch. Valid semantic failures and canonical
   timeouts remain zero. Infrastructure/evidence failures stop further calls and
   retain the missing denominator. New revisions require a new frozen batch.
5. Accept the development ratchet only for a complete valid 5/5 batch, then use
   feature-to-develop PR and required green CI. No release, tag, PyPI publication
   or modification of historical benchmark bytes is authorized.

## First candidate: a judge pass was not sufficient

Source `d1e742081117b78f80fb7cdf173fd0133069b5ce` completed all five frozen
attempts: **2/5 passed the official verifier; all five attempts were valid**.
All five received an internal judge pass on the first candidate, so none
entered repair. This is evidence of three false-positive internal verdicts,
not evidence that the repair path improved correctness.

The failed attempts had successful image reads and an untruncated final-file
readback. Their content was nevertheless incorrect. They produced seven,
nine and nine image observations; the passing fourth attempt used two.
The frozen selector kept at most two recent images. In the third attempt,
ordinary tool calls also pushed earlier images outside its 12-call window.
This establishes a source-level evidence-selection loss. No persisted judge-input
receipt establishes actual visual attention, and these few observations do not
establish that the selector caused the score difference.

The next candidate therefore targets evidence delivery, not the task answer:

- Keep text observations bounded to the latest 12 calls, but select images from
  the latest 12 image-bearing, originally logged and matched calls in the same
  verification chain. Retain image-size, aggregate-size and privacy limits.
- Label current versus prior attempt observations and disclose visual omissions.
  Old source material may remain relevant; it is not a new post-feedback check.
- Preserve the runtime's existing LLM feedback and bounded tool-enabled repair.
  Do not add a new mandatory-tool heuristic or alter the official verifier.
- Replace the per-call remaining-time number with the configured total budget.
  The old number changed Codex `instructions` before the otherwise identical
  conversation input. Keep computed checkpoints and hard deadlines unchanged.
  [OpenAI's cache documentation](https://developers.openai.com/api/docs/guides/prompt-caching)
  requires an identical rendered prefix for reuse. A stable prefix removes this
  avoidable mutation; it does not establish measured cache or latency gains, or
  subscription support for optional platform cache controls.

Local evidence remains under
`artifacts/eval/runs/terminalbench21-sol-max-reflexion-ratchet-r1-20260913/`.
Harbor's original trial IDs and paths remain unchanged; the canonical attempt-ID
projection must normalize their uppercase suffixes to the existing lowercase
schema. This is an output-normalization correction, not a new score or trial.

## Subsequent candidate admission

The first candidate's complete-five rule stays frozen. For subsequent candidates,
prospectively stop at the first valid verifier zero or infrastructure-invalid
attempt. Retain every executed attempt and mark the remainder unexecuted, not
zero. A partial candidate has no measured five-attempt pass rate; omit an analysis
that the current schema cannot truthfully represent. Only five fresh valid
passes under one unchanged source/spec pass the development gate. Do not combine
successful attempts across candidates, or infer general quality from this
development-exposed stopping rule.

## Second candidate: visual access did not eliminate false acceptance

Source `c863c7162509b74af7f533003eb28f2c370e623c` produced valid rewards
`[1, 0]` and stopped prospectively; three trials were not executed. This is a
failed development gate, not a measured five-trial rate. Both internal verdicts
passed without repair. The failed submission had two character substitutions
despite successful image observations and an untruncated readback.

The judge's concise feedback treated candidate/file agreement as support, then
proposed comparison against that same candidate. Prompt anchoring is a plausible
hypothesis, not an established cause. More concretely, all three delegated
workers failed before inference: an omitted model on the bundled analyst became
an Anthropic default while retaining the OpenAI parent's subscription route.
There was no independent worker assessment.

The next source therefore repairs inherited model selection, presents observations
before candidate claims, and removes the success-filled judge example. Material
ambiguity should request an independent, permitted check through the existing
repair path. No expected task answer, additional judge framework or altered scorer
is introduced. Completed Codex requests should retain bounded image-dispatch
metadata through the existing event owner, so selected images are not confused
with serialized inputs or model attention.

[Intrinsic self-correction research](https://arxiv.org/abs/2310.01798) reports
failures without external feedback in its studied models and tasks; it is not a
universal claim about current models.
[CRITIC](https://arxiv.org/abs/2305.11738) studies tool-grounded checking before
revision. These motivate distinguishing independent observations from repeated
self-consistency, while the unchanged external verifier remains score authority.

A post-admission audit changed the first trial's rebuildable SQLite SHM bytes.
DB, WAL and all other admission-bound files still match. The original admission
is preserved; canonical closure is blocked pending explicit custody review, not
silently rehashed or reported as validated. See the run-local incident receipt.
Future inspections use copied DB/WAL snapshots, never open original databases.

## Third candidate: the five-attempt development gate passed

Source `815f75950af580b42cbd52dcc78b0b3ea0017a8f` completed five fresh
sequential trials with official rewards **[1, 1, 1, 1, 1]**: numerator 5,
denominator 5, invalid attempts 0. The unchanged task image and verifier,
OpenAI subscription `gpt-5.6-sol` route, actor `max` effort, 900-second agent
limit, concurrency 1 and zero retries remained frozen. No earlier candidate's
pass was selected. Trials ran on 2026-09-13 from 10:05 to 10:49 UTC
(19:05 to 19:49 KST); observer PTY and operator logs were retained for each.

The existing attempt ledger, analysis and run-bundle validators passed. All
five admissions validated source/config, model route, trajectory/DB binding,
completed-call pairing, serialized-image receipts and official verifier
receipts. Across 87 recorded AgenticLoop calls, input/output/cached-input
fields were present: 2,264,797 input tokens, 58,579 output tokens and 946,432
cached-input tokens. These are recorded-call totals, not complete runtime
cost accounting. Dollar cost remains unknown. The five judge requests contained
5, 3, 1, 4 and 4 images respectively; this establishes local serialization,
not attention or interpretation by the provider.

All five internal judges accepted candidate attempt 0. No feedback-conditioned
repair was observed. Therefore this closes the requested development gate,
not a claim that repair caused the passes. The task was used for candidate
selection; no fresh baseline or native-Codex control was run. Held-out quality,
full-suite eligibility and the historical results are unchanged.

The private canonical run remains under
`artifacts/eval/runs/terminalbench21-sol-max-reflexion-ratchet-r3-20260913/`.
Closure hashes (SHA-256):

| Artifact | Hash |
|---|---|
| `run-spec.json` | `349a35016fce026e783155295ccb617e8ecbe05dde3b770f0908175c56217b0e` |
| `attempts.jsonl` | `b6cbf02742506341454f4dcb8fdda775c9fdaf01fcf34a971c0e1d01d3458ff2` |
| `analysis.json` | `c23045215e093e02b09f8843bad71374f25f4e64b6e073ebd93276a917bba48c` |
| `closure-receipt.json` | `d74febff9afad3fb4430676379aabb3cf5354cba52ec8aadb6afbf2b08d3de8a` |

The runtime source passed the complete non-live test suite, targeted tests,
ruff, mypy, import contracts, local fast gates and the site build before the
model calls. This results-only documentation update does not change that frozen
runtime. Required remote CI on the final PR head remains a separate merge gate;
neither a release nor public artifact publication is implied by local closure.
