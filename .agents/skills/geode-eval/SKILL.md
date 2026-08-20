---
name: geode-eval
description: Scope, preregister, execute, audit, normalize, and publish GEODE evaluations with research-question, reproduction, attempt-lineage, trajectory, verifier-receipt, and immutable artifact contracts. Use for benchmark runs or comparisons, eval-artifact audits, GPT or subscription result normalization, research question or hypothesis framing, retry diagnosis, trajectory publication, DPO or reward-data readiness reviews, and requests involving MCPMark, tau2, BFCL, Agent-World, HAL, Terminal-Bench, or Toolathlon.
---

# GEODE Evaluation

Preserve the question, evidence, and judgement as separate authorities. Reuse
the existing native result, trajectory, verifier receipt, and release formats;
do not create a second copy of raw evidence.

## Start With The Catalog

1. Read `docs/eval/index.json`.
2. Select documents by `triggers`, `status`, and `authority`.
3. Read `docs/eval/README.md` only when the catalog does not answer the routing
   question.
4. Load a specialized skill after the general contract when needed:
   - Agent-World or `mean_accuracy@8`: `.claude/skills/agent-world-benchmark/`
   - best-of-N, repair depth, replication, or promotion authority:
     `.claude/skills/stanford-test-time-compute/`

Do not scan every eval document or load `site/public/llms-full.txt` by default.

## Freeze Before Execution

Copy `docs/eval/eval-run-spec.template.json` to the run directory and replace
every placeholder before any model or paid service call. Freeze:

- research question, research gap, and measurable hypothesis;
- primary metric with unit, direction, frozen denominator, and aggregation;
- decision, invalidation, and analysis rules;
- GEODE/harness/model/environment revisions and reset evidence;
- ordered workload IDs, canonical hash, seeds, repetitions, budgets, and route;
- comparator class, comparability, promotion authority, artifact destinations,
  and privacy boundary.

Validate the record:

```bash
uv run python scripts/eval/contract.py validate-run-spec <run-dir>/run-spec.json
```

Live model, account, quota, or remote-service calls require explicit user
approval. Approval belongs in the frozen spec; it does not relax redaction or
publication gates.

## Preserve Attempt Lineage

Create each row from `docs/eval/eval-attempt.template.json` and append it to
`attempts.jsonl`. Never edit or delete an earlier row to make a retry look like
the first attempt.

- Use one run ID and unique, contiguous attempt IDs/sequences.
- Point a retry or repair at an already-recorded parent.
- Record the changed surface and expected effect before interpreting it.
- Keep measurement `validity` separate from semantic `outcome`: a valid full
  run may have `mixed` task outcomes. Infrastructure contamination is
  `invalid`, never a zero score or a semantic failure.
- Record timing as timezone-qualified `exact` with a known offset, zone-less
  `source-naive` plus its source, or all-null `unknown`; `-00:00` is not exact,
  and a historical source never gains an invented timezone.
- A harness-valid semantic failure may retain a failure class and error
  reference. An infrastructure-invalid or aborted attempt uses
  `outcome=unknown`, never a semantic fail score.
- Reference raw output, errors, trajectories, and receipts by run-directory
  relative path plus SHA-256 instead of copying their payload into the row.
  Only portable POSIX-relative paths are accepted; URI, UNC, drive-root,
  backslash, and parent traversal forms are forbidden. Point at a manifest
  when evidence is a directory.
- Select attempts using the frozen rule, not the observed score.

Validate the append-only projection:

```bash
uv run python scripts/eval/contract.py validate-attempts <run-dir>/attempts.jsonl
```

## Keep Authorities Separate

| Surface | Authority | Lifecycle |
|---|---|---|
| Checkpoint | resume state | mutable |
| Session record and attempts | chronological execution and retry lineage | append-only |
| Native harness result | suite score | append-only producer output |
| GEODE trajectory | normalized behavior | append-only projection |
| Verifier receipt or state diff | judgement evidence | append-only producer output |
| Analysis | answer and decision | digest-bound, immutable after publication |
| Trajectory release and artifact manifest | admitted public bytes and integrity | immutable |

Runtime activity such as streaming chunks, heartbeat, cache internals, and
transient retry telemetry stays out of training/evaluation claims unless a
specific evidence reference promotes it deliberately.

## Analyze Against The Frozen Question

Create `analysis.json` from `docs/eval/eval-analysis.template.json`. Bind it to
the SHA-256 of the frozen spec and complete attempts JSONL. Report the primary
metric with numerator and denominator, answer only the preregistered question,
apply the frozen decision/invalidation rules, and preserve limitations.

```bash
uv run python scripts/eval/contract.py validate-analysis <run-dir>/analysis.json \
  --run-spec <run-dir>/run-spec.json \
  --attempts <run-dir>/attempts.jsonl
```

The validator requires selected attempt IDs, evidence digests, primary-metric
unit/counts/source pointer, and registration chronology to match the source
sidecars. A measured primary metric uses RFC 6901 JSON Pointers to read its
value and counts from selected-attempt, digest-bound native JSON, and its
denominator matches the explicitly frozen denominator. If an invalid or
aborted row is selected for provenance, the primary metric is
`not-measurable` with null counts and cannot drive promotion or rejection. Add
new analysis as a superseding artifact; do not rewrite a published analysis
in place.

## Publish Without Inflating Claims

Follow `docs/eval/benchmark-publishing-cycle.md` and
`docs/eval/external-artifact-repository.md`.

1. Keep native score, behavior trajectory, and verifier evidence distinct.
2. Stage stable `geode.trajectory@1` records and
   `geode.trajectory-release@1` manifests when behavior evidence is published.
3. Build `artifact-publish-manifest.template.json`, privacy review the exact
   bytes, publish append-only, and verify remote read-back at the pinned commit.
   Validate portable paths, classification, byte counts, SHA-256 identities,
   and prepared/published state before copying:

   ```bash
   uv run python scripts/eval/contract.py validate-publication \
     <run-dir>/publication-manifest.json
   ```

   Raw prompts/responses, transcripts, messages, SQLite/WAL, evidence JSONL,
   profiles, usage, diagnostics, and provider payloads remain
   `withheld-private` unless their exact bytes receive public approval.
4. Derive the human run report and public page from validated sidecars; do not
   make either another score authority.
5. Label subscription results as product-route evidence. Keep smoke,
   directional, paired-runtime, suite-headline, and promotion claims separate.

For historical runs, set `preregistration.mode=retrospective`, force
`promotion_authority=none`, and add immutable sidecars with explicit unknowns
and source digests. Never invent missing timestamps, seeds, budgets, prompts,
simulator identity, or task selection, and never rewrite old raw receipts.

## Fail Loud

- Reject unresolved `<...>` placeholders.
- Reject workload hash or seed/repetition mismatch.
- Reject duplicate attempts, forward parent links, sequence gaps, mixed run
  IDs, or end times before start times.
- Reject analysis whose source digests or selected attempts do not match.
- Reject prospective attempts that predate the frozen spec, promotion or
  rejection decisions without authority, and authority that does not match a
  direct named comparator and its claim class.
- Reject human preference, factual correctness, or DPO-readiness claims based
  only on a terminal score; require explicit preference/process labels and
  verifier evidence appropriate to the claim.
- Reject publication when secrets, identities, raw private prompts, or any
  POSIX, Windows-drive, UNC, or home-relative machine path crosses the declared
  privacy boundary.

Finish by reporting the research question, invalidity status, selected attempt
lineage, primary numerator/denominator, artifact commit, comparability class,
promotion authority, and the smallest unresolved measurement.
