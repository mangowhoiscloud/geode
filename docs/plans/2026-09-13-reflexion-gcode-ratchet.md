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
