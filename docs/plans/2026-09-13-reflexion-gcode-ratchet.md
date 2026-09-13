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
