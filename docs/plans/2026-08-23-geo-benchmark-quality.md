# GEO benchmark quality closure

Date: 2026-08-23  
Branch: `codex/geo-benchmark-quality`  
Base: `origin/develop@586e29b663a959742ab4b4dac1dafb542b394f73`

## Scope

Close the measurement gap around the typed `/geo` control surface without
turning it into a search-engine executor or changing prompt assembly.

| GAP | Current evidence | Closure |
|---|---|---|
| GEO-B1 | Static export has sitemap/title/noindex checks but no self-canonical contract. | Emit one route-specific canonical URL and reject missing, duplicate, or non-self canonicals in `verify-geo`. |
| GEO-B2 | The canonical 24-query profile is prose-only and live observations have no executable denominator contract. | Validate a frozen workload plus digest-bound native/verifier receipts and emit separate R/C/P/A/Q measurements. |
| GEO-B3 | The public benchmark surface documents Tau2 and MCPMark, not GEO execution or its current evidence boundary. | Add one concise GEO benchmark reference page and sitemap entry. |

## Design

- Reuse `docs/eval/schemas/run-spec.schema.json` and
  `scripts/eval/contract.py`; do not create a second eval ledger.
- Freeze six roots with one root query and three paraphrases each. Bind the
  exact workload bytes into `run-spec.json` before any live call.
- Require every structured observation to resolve back to a SHA-256-bound
  native receipt. Absorption and quality require a separate verifier receipt.
- Emit the vector only. `F` remains owned by the site preflight and `O` by
  first-party analytics; neither is inferred from search responses.
- Leave `/geo` state, SkillRegistry, AgenticLoop, XML regions, prompt hashes,
  and cache boundary unchanged.

## Acceptance

1. A 24-query x K native result matrix validates exactly once per cell and
   rejects drift, missing rows, duplicate rows, digest mismatches, and
   ungrounded verifier fields.
2. Output preserves per-stage numerator/denominator/status and contains no
   aggregate score.
3. Every sitemap URL has exactly one self-canonical in exported HTML.
4. Targeted Python tests, site build/export/metadata/GEO checks, eval catalog,
   ruff, mypy, and relevant package gates pass.
5. A local diagnostic artifact is produced before any publication decision;
   live commercial calls remain governed by a prospective run spec and the
   existing operator approval boundary.

## Non-goals

- Scraping or automating a commercial search UI.
- Treating model judgement as a native outcome.
- Publishing local smoke evidence or synthesizing an Inspect `.eval` file.
- Aggregating `F/R/C/P/A/Q/O` into a 0-100 score.
