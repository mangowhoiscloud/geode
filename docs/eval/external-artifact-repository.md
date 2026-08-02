# External Evaluation Artifact Repository

GEODE's canonical public evaluation-artifact store is
[`mangowhoiscloud/geode-eval-artifacts`](https://github.com/mangowhoiscloud/geode-eval-artifacts).
The GEODE repository keeps code, interpretation, comparability boundaries, and
digest pointers; the artifact repository keeps large verifier outputs and
transcripts behind those claims.

This split is deliberate. `artifacts/` remains gitignored in GEODE, while the
external repository is an append-only evidence store. A published result is
durable only when its GEODE ledger names both the artifact path and the exact
artifact-repository commit.

“Artifact repository” here means a reviewed Git branch/PR and immutable commit,
not JFrog Artifactory or an opaque object-store upload. The publication unit is
an allowlisted directory, and GitHub read-back from the exact merge commit is
part of the evidence.

The 2026-08-02 GPT-5.4 Tau2 regression publication is pinned to artifact
commit
[`f588ce9`](https://github.com/mangowhoiscloud/geode-eval-artifacts/commit/f588ce9fd23b9123732b45c4dbe202136691d3fe)
from
[`geode-eval-artifacts#10`](https://github.com/mangowhoiscloud/geode-eval-artifacts/pull/10).
Its two `geode.trajectory@1` files contain 158 canonical events and ten exact
tool pairs with no missing IDs or orphaned calls. The immutable
[`manifest.json`](https://github.com/mangowhoiscloud/geode-eval-artifacts/blob/f588ce9fd23b9123732b45c4dbe202136691d3fe/trajectories/tau2-geode-gpt54-afaab52b-mock-telecom-small-20260801T173245Z-2dc79cb569f0/manifest.json)
has SHA-256
`2dc79cb569f03e5f44ce008b32fd8af86f8388ab04341ee8f91c74fdffb6aa6b`.
The four public native files have path-set digest
`117a1f7f6e88bcdc792c0c17a58c5aff96c7df1ffa0e2aa216bbd565871b9a39`;
the Telecom result is an explicitly redacted public copy rather than the raw
Crucible receipt. Remote read-back at the exact merge commit revalidated the
manifest, mock bytes, and redacted Telecom bytes. The release remains
diagnostic with `promotion_authority=none` and does not alter Tau2's native
`results.json` score authority.

## Path mapping

| Local GEODE path | External path |
|---|---|
| `artifacts/eval/harnesses/mcpmark/results-geode-agentworld/` | `mcpmark/results-geode-agentworld/` |
| `artifacts/eval/harnesses/mcpmark/logs*/` | `mcpmark/logs*/` |
| tau2 simulation result directories | `tau2/simulations/` |
| `artifacts/eval/runs/crucible/campaigns/` | `crucible/runs/campaigns/` |
| `artifacts/eval/runs/crucible/{row-cache,trajectory-snapshots}/` | `crucible/runs/{row-cache,trajectory-snapshots}/` |
| approved Crucible launch/report packets | `crucible/runs/launch-packets/` |
| `docs/audits/` dated Petri analysis reports + score matrices (migrated 2026-07-13) | `sil/audit-reports/` |
| `docs/e2e/` dated validation records (migrated 2026-07-13) | `reports/e2e-validation/` |
| `docs/eval/crucible-power-admission-2026-07-13.md` (migrated 2026-07-13) | `crucible/gate-provenance/` |
| normalized trajectory releases (`TRAJECTORIES.md` contract; first release 2026-07-28, MCP spec-response E2E) | `trajectories/<source>-<scope>-<published-utc>-<digest12>/` |

The 2026-07-31 GEODE hook/middleware behavior release is pinned to artifact
commit
[`3e5b35f`](https://github.com/mangowhoiscloud/geode-eval-artifacts/commit/3e5b35f4505a4a2dc76d595b24862e8e73e668ff).
Its public allowlist contains only the normalized trajectory and manifest;
runtime checkpoints, provider reasoning, SQLite/WAL, JSONL, usage, and
diagnostic files remain withheld. Its manifest supersedes the first run
without deleting or rewriting that append-only record.

The first stable-schema hook/middleware behavior release is pinned to artifact
commit
[`b979268`](https://github.com/mangowhoiscloud/geode-eval-artifacts/commit/b979268d7e64c99ca27b51c025a2cd25022cc1a5)
from
[`geode-eval-artifacts#8`](https://github.com/mangowhoiscloud/geode-eval-artifacts/pull/8).
The immutable
[`manifest.json`](https://github.com/mangowhoiscloud/geode-eval-artifacts/blob/b979268d7e64c99ca27b51c025a2cd25022cc1a5/trajectories/geode-agenticloop-hook-middleware-behavior-e2e-20260731T091808Z-d418e55ff8aa/manifest.json)
has SHA-256
`d418e55ff8aa4cae22db9e6c59ac0ecbe060be78ffcc46c900da1e23a6f7b994`;
remote read-back from the merged commit independently revalidated its one
`geode.trajectory@1` file, 27 events, complete scope correlation, structured
privacy review, and zero findings in every configured secret-scan class.
`replay_complete=false` is deliberate: the public behavior trajectory omits
private provider reasoning and non-allowlisted runtime state while retaining
the complete observed public hook/middleware scope.

The 2026-07-31 GPT-5.6 benchmark publication is pinned to artifact commit
[`9c00ecf`](https://github.com/mangowhoiscloud/geode-eval-artifacts/commit/9c00ecf4a3b5a68ee65db9afe185b2271da46b49).
It contains masked MCPMark and tau2 receipts plus twelve normalized
dialogue/tool trajectories. Manifest directory digests are
`b86f5071cbe0` (MCPMark) and `4ec1c13434d1` (tau2). Runtime homes, session
SQLite, JSONL mirrors, hidden reasoning, and credential files remain
withheld. Local usernames and synthetic telecom personal fields are redacted
in the public copies.

The post-release `v1.0.11` behavior regression is pinned to
[`16a54f0`](https://github.com/mangowhoiscloud/geode-eval-artifacts/commit/16a54f08450db771c02e30c73bdc3867f6282f83)
from
[`geode-eval-artifacts#9`](https://github.com/mangowhoiscloud/geode-eval-artifacts/pull/9).
It preserves the native MCPMark 10/10 receipt and tau2 mock 0/1 plus
Telecom-small 1/1 receipts, and publishes two stable trajectory releases:

- [MCPMark release](https://github.com/mangowhoiscloud/geode-eval-artifacts/tree/16a54f08450db771c02e30c73bdc3867f6282f83/trajectories/mcpmark-geode-gpt56-v1.0.11-686ff372-filesystem-easy-20260731T105713Z-82fe94b01a25):
  10 trajectories, 226 events, 78 exact tool pairs, manifest SHA-256
  `82fe94b01a25e7e9f8c504d511f018129cb058ad532dbcbc315de9c6819db0fb`.
- [Tau2 release](https://github.com/mangowhoiscloud/geode-eval-artifacts/tree/16a54f08450db771c02e30c73bdc3867f6282f83/trajectories/tau2-geode-gpt56-v1.0.11-686ff372-mock-telecom-small-20260731T105713Z-a71155f7006c):
  2 trajectories, 142 events, 9 exact tool pairs, manifest SHA-256
  `a71155f7006c8dd412af8d1471e7d2380e5f072cc8f0495924fa86f26d69a9a2`.

Both releases are scope-complete and deliberately replay-incomplete because
non-public message/tool bodies are represented by digests. Every trajectory
matched its isolated canonical SQLite event set exactly. Secret, identity,
credential, path, duplicate-ID, missing-correlation, and orphan-pair findings
were all zero. An independent GitHub API read-back of the exact merge commit
revalidated both releases rather than trusting the staging worktree.

Raw native evidence and public disclosure bytes have separate identities.
MCPMark's public receipt set contains 31 files / 554,366 bytes with path-set
digest `3ffcdeebc39be91f5d957b66f1a5e48bd1408645f83120e84346bba7beef6417`.
Tau2's contains 4 files / 114,004 bytes with path-set digest
`a5d2a2f6b8dd719f22f050e16afe4ad8bf65345c35a65552e5467745b3eeda5f`.
For the Telecom result specifically, the authoritative raw receipt digest is
`eda3cdbdb9cd0c2f993db3f9fe2e813cdbc06fe9cf112e23ba60c7ea9d98a45b`;
the public, synthetic-phone/email-redacted copy is separately hashed as
`506f906cfa1d6e8e4320ba284be1aa0f7ec26ea2fc47b43e7b36f69e3643a9d4`.
This preserves Crucible's native evidence authority without leaking reviewed
fields or falsely claiming transformed bytes are identical.

Those historical releases use the dated
`geode.trajectory@2026-07-29`/`@2026-07-31` envelope and stay immutable. New
GEODE producers emit `geode.trajectory@1`; public staging writes a separate
`geode.trajectory-release@1` manifest. The core read adapter accepts the dated
shape and recomputes v1 ordering/pairing quality without rewriting the public
source.

Artifact PR #8 updated the repository policy to recognize stable
`geode.trajectory@1`/`geode.trajectory-release@1` records and
`events[].ordinal`. Historical dated releases and their `events[].sequence`
fields remain immutable and are normalized only in memory.

Still in the GEODE repository after the 2026-07-13 migration: the live
`docs/audits/eval-logs/` manifest ledger (`core/audit/manifest.py` appends to
it on every `geode audit --live`), the code-referenced
`docs/audits/2026-05-21-self-improving-loop-5-slot-reader-audit.md` and
`docs/audits/judge-human-agreement.md`, and the three caveat reports the
published petri-bundle README cross-links
(`2026-05-12-petri-geode-audit-v3.md`, `2026-05-12-petri-insights.md`,
`2026-05-12-petri-multi-model-partial.md`; pinned by
`tests/integration/test_render_lint_config.py::test_caveat_files_exist`).
Comments and older documents citing another `docs/audits/<dated-report>.md`
path resolve under `sil/audit-reports/` in the artifact repository.

Do not mirror third-party harness checkouts, package caches, evaluator scratch
worktrees, credentials, or byte-reproducible temporary environments.

## Publication boundary

Every candidate file is classified before copying:

| Class | Rule |
|---|---|
| `public` | Verifier output, completed-run transcript, config, receipt, or opaque aggregate that has passed secret and identity review |
| `withheld-sealed` | Unopened sealed pack, selected-row manifest, task/family/content identities, selection salt or preregistration that makes the hidden rows derivable |
| `private-secret` | Tokens, auth headers, cookies, environment files, DB URIs, provider credentials; never publish |
| `reproducible-cache` | Package caches, scratch checkouts, evaluator homes; omit and record the pinned sources instead |

An unopened Crucible pack stays `withheld-sealed` even when its task IDs were
not printed. Publishing the pack, selection manifest, or deterministic salt
would destroy the one-shot holdout boundary. Opaque counts, digests, and power
reports may be public when they contain no selected identity.

## Publication cycle

1. Preserve the source run under GEODE's ignored `artifacts/` tree.
2. Copy `artifact-publish-manifest.template.json` beside the run record and
   replace every placeholder.
3. Verify each source byte count and SHA-256. Mark withheld entries explicitly;
   never omit them silently from the disclosure accounting.
4. Scan public entries for credentials, local usernames, auth headers, and
   environment files.
5. Copy only `public` entries into a fresh branch/worktree of
   `geode-eval-artifacts`; do not rewrite an existing run directory.
6. Open and merge a PR in the artifact repository.
7. Record its merge commit and immutable blob/tree links in the GEODE run
   ledger before publishing a score or improvement claim.

For normalized trajectories, steps 2–5 use
`core.observability.trajectory_release.stage_trajectory_release()`. Its local
gate always requires schema validity, scope completeness, per-trajectory
privacy review, zero configured secret-scan findings, and a scope-bound
structured privacy review record. Replay completeness is required unless the
release admission explicitly allows content-digested replay. Every
`artifact_digests` reference must resolve to source bytes and match SHA-256
before staging. The digest-bound manifest, append-only destination, and local
read-back close the local half; the artifact-repository PR still performs an
independently anchored remote read-back in step 7.

The review record is public metadata, not a copy of private evidence:

```json
{
  "reviewer": "release owner or review team",
  "reviewed_at": "2026-07-31T12:00:00Z",
  "method": "allowlist review plus secret and identity scan",
  "scope": "the exact --scope value",
  "attestation": "Only the declared normalized trajectories are approved."
}
```

A concrete trajectory publication is:

```bash
geode session stage-trajectory-release trajectory.json \
  --destination /tmp/geode-trajectory-releases \
  --source sil \
  --scope campaign-2026-07-31 \
  --privacy-review privacy-review.json \
  --source-artifact run.eval=/absolute/path/to/run.eval

# Copy the new content-addressed directory only into a fresh
# geode-eval-artifacts worktree/branch, open a PR, and merge it.

geode session verify-trajectory-release <merged-release-dir> \
  --expected-manifest-sha256 <digest-recorded-before-copy>
```

For SIL, `export-trajectory --sil-eval run.eval` creates the typed
`inspect_ai.eval@native` evidence reference and source digest. This bridge is
an explicit promotion operation, not an automatic campaign-finalization side
effect. For Crucible, a tau2 native receipt is always a `native_receipt`;
`crucible_evidence` is added only after frozen-contract identity preflight.
Neither bridge delegates scoring or promotion authority to GEODE's release
manifest.

The publication is scripted deterministically by `scripts/eval/publish_crucible_artifacts.py` (`stage` copies one run's allowlisted subset and masks the local username; `mask` re-masks an existing tree idempotently). Both refuse sealed material by name and never rewrite an existing run directory.

There is intentionally no automatic `rsync` from the whole artifact tree. A
manifest-first, allowlisted copy keeps new credential files and unopened
holdouts from becoming public merely because they appeared under a familiar
directory.

## Current Crucible admission packet

The 2026-07-13 family-power admission record is
[`crucible-power-admission-2026-07-13.md`](https://github.com/mangowhoiscloud/geode-eval-artifacts/blob/main/crucible/gate-provenance/crucible-power-admission-2026-07-13.md).
Its identifier-free record and power reports are publication-eligible. The
corresponding sealed pack and selection materials remain withheld until the
sealed claim is consumed and separately reviewed.
