# Crucible Family-Power Admission — 2026-07-13

## Status

This is an internal design-admission record, not a benchmark score or a
promotion claim. No provider call was made. The hidden pack is represented only
by counts and digests; task IDs, family IDs, content hashes, and selected rows
are intentionally omitted.

| Field | Value |
|---|---|
| Feature revision | `76a09a394b5e9ffa5794c8848adcefda48303a94` |
| Power method | `paired-bernoulli-monte-carlo.v1` |
| Simulations | 20,000 per scenario |
| Seed | `20260713` |
| Minimum power | `0.80` using the 95% Wilson lower bound |
| Frozen promotion rule | family-mean `paired_bootstrap.v2`, 10,000 bootstrap samples, confidence `0.885`, materiality `0.25`, candidate floor `0.50` |
| Live provider calls | 0 |

## Digest-bound assumptions

The audit does not fit a noise model. It evaluates two explicit sensitivity
scenarios and requires both to pass:

| Scenario | Baseline pass probability | Target improvement | Regression on baseline success | Basis |
|---|---:|---:|---:|---|
| r14 observed-effect sensitivity | 0.5000 | +0.3333 | 0 | r14 train verdict SHA-256 `d8f84c2de8f298f129200e1f42eb305d070beea840d6df1dd62d4bf0a085b88e` |
| r24 baseline with r14 effect | 0.5833 | +0.3333 | 0 | r24 baseline evidence SHA-256 `8ce8d9776726d5792aa0bd8a17890a5c0653f147c426584ada25e5470664cd07` |

The shared bounded basis document has SHA-256
`96e8e585b9fd4d585f219731f44527e2a91ea717930fac47d3eb6e0047830275`.
Train KEEP magnitude is selection-biased and is used here only as a planning
sensitivity input. It is not an estimate of production improvement.

r25's 0.8333 baseline is retained as reachability incident evidence rather
than forced into an impossible +0.3333 scenario. The reachability screen, not
repeated measurement until a low baseline appears, owns that ceiling case.

## Admission result

| Design | Tasks / families | Trials | Scenario KEEP probability | 95% lower-bound range | Admission |
|---|---:|---:|---:|---:|---|
| Historical r26 train | 9 / 9 | 2 | 0.7676–0.7682 | 0.7617–0.7623 | REJECT |
| Replacement train | 9 / 9 | 3 | 0.8419–0.8455 | 0.8367–0.8404 | PASS |
| Historical r26 sealed | 6 / 6 | 1 | 0.6492–0.6513 | 0.6425–0.6446 | REJECT |
| Replacement sealed | 6 / 6 | 2 | 0.8137–0.8147 | 0.8082–0.8092 | PASS |

Replacement train power report:

- task-pack SHA-256: `e8abc61405cbb8b9d3979f96511dcaca030199e0786d4187313dbda4d84cec98`
- report SHA-256: `69143af469bcac2e165b309cd835ffb2c73ea1a6b4ba3c61716ab7f1e4c8a0c2`
- power-audit ID: `3e01fd16aef29869ca9a159866cd63fb1e68183a9d76da94038f893722d87eb2`

Replacement sealed power report:

- task-pack SHA-256: `f3661c297446c0477130f62a19d9d5757b8126667ae5a0989b3c9ea528244a36`
- report SHA-256: `01c723a1deccc63782d95cea179ee944fbce1c0182456e4c7bc482b245480135`
- power-audit ID: `f5b062476743668dc0ab10aaeb587a713a4b0d3b70a524a55539a404f8f7e787`

## Integrity checks

- Replacement task identities are byte-for-byte unchanged from r26; only
  `trials_per_task` changed (train 2→3, sealed 1→2).
- Train versus sealed overlap is zero for task ID, content SHA-256, and family
  ID.
- The sealed selection artifact SHA-256 remains
  `220cdc4596dc62efdb7f916ddcaab8c655e5ba9b4f8c68089d9821940803a8ff`,
  identical to r26, so trial replication did not select new hidden rows.
- Neither power report contains a train or sealed task/family identifier.
- Central `prepare.py` produced a config at the feature revision and the same
  `SupervisorConfig.load` used by the loop accepted it. The bound evaluator
  digest was `819155c781bdbe92a933de590320bce8dd3abe21ae2f5033ccb34ccb1b986b8f`;
  the harness digest remained
  `e4596eb05b9917fa098db094448f731028f5a5762ac13dc5c0ff2622c2c0697d`.

## Launch boundary

The prepared feature-revision config is not reusable after merge. A paid run
requires a new campaign ID, a fresh central-prepare invocation against the
merged develop SHA, a passing quota-window preflight, and explicit live-test
approval. Statistical power is conditional on the two named scenarios and all
non-statistical vetoes passing; it is not the probability that the producer
will invent a real improvement.

## External artifact disposition

The canonical raw store is
[`mangowhoiscloud/geode-eval-artifacts`](https://github.com/mangowhoiscloud/geode-eval-artifacts)
(observed main revision
`7e6a4374ba6af7f576700046d42fb6efff42abc7` during this audit). This record is
safe to publish, as are the two identifier-free power reports. The unopened
sealed pack, selected-row manifest, and deterministic selection preregistration
remain withheld: publishing any of them would reveal or make derivable the
one-shot test rows before use. After the sealed claim is consumed, publication
requires a separate disclosure review and append-only artifact-repository PR.
