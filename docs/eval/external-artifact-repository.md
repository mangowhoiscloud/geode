# External Evaluation Artifact Repository

GEODE's canonical public raw-artifact store is
[`mangowhoiscloud/geode-eval-artifacts`](https://github.com/mangowhoiscloud/geode-eval-artifacts).
The GEODE repository keeps code, interpretation, comparability boundaries, and
digest pointers; the artifact repository keeps large verifier outputs and
transcripts behind those claims.

This split is deliberate. `artifacts/` remains gitignored in GEODE, while the
external repository is an append-only evidence store. A published result is
durable only when its GEODE ledger names both the artifact path and the exact
artifact-repository commit.

## Path mapping

| Local GEODE path | External path |
|---|---|
| `artifacts/eval/harnesses/mcpmark/results-geode-agentworld/` | `mcpmark/results-geode-agentworld/` |
| `artifacts/eval/harnesses/mcpmark/logs*/` | `mcpmark/logs*/` |
| tau2 simulation result directories | `tau2/simulations/` |
| `artifacts/eval/runs/crucible/campaigns/` | `crucible/runs/campaigns/` |
| `artifacts/eval/runs/crucible/{row-cache,trajectory-snapshots}/` | `crucible/runs/{row-cache,trajectory-snapshots}/` |
| approved Crucible launch/report packets | `crucible/runs/launch-packets/` |

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

There is intentionally no automatic `rsync` from the whole artifact tree. A
manifest-first, allowlisted copy keeps new credential files and unopened
holdouts from becoming public merely because they appeared under a familiar
directory.

## Current Crucible admission packet

The 2026-07-13 family-power admission record is
[`crucible-power-admission-2026-07-13.md`](crucible-power-admission-2026-07-13.md).
Its identifier-free record and power reports are publication-eligible. The
corresponding sealed pack and selection materials remain withheld until the
sealed claim is consumed and separately reviewed.
