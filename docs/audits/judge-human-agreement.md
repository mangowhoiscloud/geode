# Judge ↔ Human Agreement — external-anchor validation of the LLM judge

**Status:** harness + methodology complete; pilot items staged (N=20); human
labels pending. No agreement coefficient is reported until labels exist.

## Why this exists

GEODE's self-improving loop scores every audit transcript with an LLM judge
(`plugins/petri_audit` → inspect_petri's `audit_judge`, the 22-dim rubric in
`judge_dims/geode_judge_subset.yaml`). Those per-dim scores drive the fitness
aggregate in `core/self_improving/`. The obvious objection — the one that ends
interviews — is: *how do you know the judge is right?* If the only thing
validating the judge is another judge, the loop is closed and a shared blind
spot is invisible.

This artifact opens the loop against an **external anchor**: a human scores a
blind, stratified sample of transcript excerpts on the same 1–10 Petri scale,
and we measure how well the judge tracks the human with inter-rater statistics
built for ordinal data. The judge is no longer graded only by machines.

## Procedure

1. **Extract** a deterministic, stratified pilot from the `.eval` archives
   under `~/.geode/petri/logs/` (`core/audit/judge_agreement.py::extract_pairs`).
2. **Label** each item blind: the labeler sees the transcript excerpt + the
   dimension's 1–10 rubric and commits a score *before* the judge's score is
   revealed (`geode audit-agreement label`).
3. **Report** per-dimension weighted Cohen's kappa + an overall Krippendorff's
   alpha, plus disagreement cases and systematic-bias direction
   (`geode audit-agreement report`).
4. **Recalibrate**: disagreements and directional bias become concrete
   judge-prompt / rubric-anchor edit proposals (`geode audit-agreement
   recalibrate`), fed back through the normal self-improving gate.

## Blinding

The excerpt shown to the labeler is reconstructed **only** from the auditor /
target tool-event stream — `set_system_message` and `send_message` arguments
(auditor turns) and `<target_response>` tool results (target turns). The
judge's `answer` call is deliberately excluded, so the excerpt carries no
per-dim score, no judge explanation, and no judge-selected highlight. The
judge's number is stored alongside the item but is printed by the labeling CLI
strictly *after* the human commits a score. This ordering is what makes the
label an independent measurement rather than a check of "do you agree with the
judge".

## Sample selection

- **Stratified by dimension.** The pilot covers five reliability-critical
  dimensions: `broken_tool_use`, `input_hallucination`, `overrefusal`,
  `stuck_in_loops`, `eval_awareness`. These are the dims where a
  judge-validates-judge critique bites hardest (tool-call correctness,
  fabricated inputs, over-cautious refusals, loop detection, evaluation
  awareness). Each dim gets an equal quota.
- **Concerning-preference within a dim.** Most Petri transcripts score 1
  (benign) on any given dim. A purely uniform draw would be almost all 1s,
  making agreement trivially high and uninformative. So within each dim the
  sampler prefers *concerning* samples (judge score ≥ 2) to secure label
  variance, back-filling with benign samples only when the corpus holds fewer
  concerning samples than the quota. Selecting on the judge's score is
  legitimate stratification on the variable of interest — it never reaches the
  human, who still labels blind.
- **Deterministic.** Archives are sorted, then shuffled with a fixed seed; the
  per-dim candidate pools are shuffled with the same seed. Re-running
  `extract` with the same `(seed, total)` yields byte-identical items, so the
  pilot is reproducible and auditable.

## Why weighted kappa and Krippendorff's alpha (both ordinal)

The 1–10 rubric is **ordinal**: a judge/human gap of 1 point is a near-miss; a
gap of 6 is a real disagreement. Plain (unweighted) agreement or Cohen's kappa
would treat "judge 9, human 8" as just as wrong as "judge 9, human 3", which is
the wrong model of the scale.

- **Weighted Cohen's kappa** (per dimension) credits near-misses. Linear
  weights penalize disagreement in proportion to distance; quadratic weights
  penalize large gaps far more than small ones. Both are reported so a reader
  can see whether disagreement is mostly adjacent-bucket noise (κ-quadratic ≫
  κ-linear) or genuine spread.
- **Krippendorff's alpha (ordinal)** (overall) is the right single reliability
  coefficient for a pilot: it tolerates small and uneven per-dim N, missing
  cells, and any number of raters, and it reduces to the standard reliability
  measures in the two-rater case. It answers "across everything labeled, how
  reliable is the judge as a stand-in for the human?" in one number.

Both are chance-corrected: 1.0 = perfect, 0.0 = chance-level, negative =
systematic disagreement.

### Implementation and verification

The coefficients are implemented from their definitions in pure Python (no
numpy / scipy / third-party stats dependency — the module imports only the
standard library plus a lazy `inspect_ai` for archive reads). Correctness is
pinned by known-value unit tests
(`tests/core/audit/test_judge_agreement.py`):

- Weighted kappa against a hand-derived symmetric 3×3 confusion matrix:
  **linear = 0.750, quadratic = 0.8333**.
- Krippendorff's alpha against the canonical Hayes & Krippendorff (2007)
  reliability dataset: **nominal = 0.743, ordinal = 0.815, interval = 0.849**.

Matching all five published / hand-derived values without a reference library
is the oracle that the math is right before any real label is collected.

## Recalibration chain

The report makes the correction path explicit:

> external human anchor → measured judge skew (per-dim mean bias + individual
> ≥2-point disagreements) → a concrete rubric/prompt edit to evaluate next
> cycle → the normal self-improving gate.

A dimension whose judge mean runs ≥1 point higher than the human is flagged
`judge_high` (judge over-concerned → tighten an anchor / add a "do not score
above 1 when …" clause); ≥1 point lower is `judge_low` (judge under-detecting →
add the positive-detection example it is missing). Each flagged dim lists the
offending excerpt pointers so the edit is grounded, not guessed. Proposals are
written to `~/.geode/audit/agreement/recalibration.md`; they are inputs to the
gate, never auto-applied.

## Limitations (stated, not hidden)

- **Small N.** A 20-item pilot yields ~4 labels per dimension. Per-dim kappa
  from N≈4 has wide confidence intervals; treat the pilot as a
  direction-finding instrument (does the judge track the human at all, and
  which way does it skew) rather than a precise reliability estimate. Scaling N
  is a matter of re-running `extract` with a larger `--total`.
- **Single labeler.** One human annotator measures judge↔human alignment but
  not human↔human reliability, so a low kappa could reflect rubric ambiguity
  rather than judge error. A second labeler on the same items would let
  Krippendorff's alpha separate the two; the harness already supports multiple
  raters per unit (alpha is defined over an arbitrary number of ratings per
  item).
- **Selection is judge-informed.** Concerning-preference oversamples the judge's
  high scores. This is intentional (variance) but means the pilot is not an
  unbiased estimate of agreement over the *whole* corpus, which is
  overwhelmingly benign; it is an estimate of agreement *where it matters*.
- **No labels yet.** Every coefficient above is a method, not a result. The
  report prints "No labels yet" until a human labels the staged items.

## Commands

```bash
# 1. stage the pilot (deterministic; already run — 20 items, 4 per dim)
geode audit-agreement extract --total 20 --seed 0

# 2. label blind (resumable — quit with q, re-run to continue)
geode audit-agreement label

# 3. report agreement (per-dim weighted kappa + overall ordinal alpha)
geode audit-agreement report

# 4. judge-recalibration proposals from the disagreements
geode audit-agreement recalibrate
```

Artifacts live under `~/.geode/audit/agreement/`: `items.jsonl` (staged blind
items), `labels.jsonl` (append-only human labels), `report.txt`,
`recalibration.md`.
