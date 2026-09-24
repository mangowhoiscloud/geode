---
eval_id: jev-verdict-publication-20260924
eval_family: typesafe-decision-handoff
eval_kind: ledger
eval_status: reference
eval_authority: diagnostic
eval_summary: Reviewed public projections of the retained M4 natural, M5 snapshot and M6 recovery diagnostics; native evidence remains separate from normalized trajectories.
eval_triggers: [jev, rollout, normalization, publication]
eval_contracts:
  - docs/eval/typesafe-decision-handoff.md
  - docs/eval/external-artifact-repository.md
---

# Jev verdict diagnostics: public evidence

Publication was merged and read back from the exact artifact commit on
2026-09-24. No new model execution is represented by this record. The frozen
[experiment contract](typesafe-decision-handoff.md) owns the
comparison; the subsequent official runtime option changes cadence and must
receive its own revision-bound E2E evidence.

## Retained observations

| Cohort | Measurement unit | Valid result | Interpretation |
|---|---|---|---|
| M4 natural | Three complete-candidate inbox tasks × two repetitions × two arms | 12/12 task-verifier passes; LLM 6/6, Jev 6/6 | Paired diagnostic, not a general capability or leaderboard estimate |
| M5 snapshots | Three identical states × two judgment engines | Six calls; expected labels 3/3 per arm | Component diagnostic without subsequent root execution; not six rollouts |
| M6 r3 recovery | One task × two injected defects × two arms | 4/4 task-verifier passes; recovery 2/2 per arm | Controlled recovery; initial detailed label match LLM 2/2, Jev 1/2 |

Admission runs remain outside these denominators. Initial M4 collector failure,
M6 installation failure and M6 r2 timeout retain invalid/superseded lineage,
including unexecuted cells. Their primary outcome is not measurable, not zero.
The two negative M6 labels lead to the same correction branch but carry distinct
feedback text and hashes. Final success does not erase that difference.

## Native, normalized and public records

The publication uses the existing `geode.trajectory@1` schema: 12 M4 and four
M6 trajectories. They are scope-complete and replay-incomplete; message content
was withheld/digested. Harbor ATIF, private full-content trajectories and the
film replay remain separate artifacts. A normalized trace does not replace a
native task verifier or establish full dialogue replay.

The artifact report records the exact input/output SHA-256 for each public
projection, removed fields, preserved metric pointers, privacy classification
and release manifests. Public copies remove machine paths and private model
payloads. Original run specs, attempts, raw logs and verifier bytes remain
unchanged locally. Retrospective publication sidecars have no promotion authority.

Two historical M4 file paths refer to a cleaned worktree. Both frozen payloads
(`decision-handoff-inbox.json` and `uv.lock`) are recoverable byte-for-byte from
the preserved source archive. The transformation receipt binds archive member
and SHA instead of changing the original freeze.

The Terminal-Bench-specific learning-view projector is not used: its hardcoded
suite, effort and repetition fields would mislabel these Astra/xhigh diagnostic
runs. No training-ready or Terminal-Bench claim is made.

## Publication gates

1. Validate the retained eight run bundles and 16 trajectory integrity records.
2. Review the exact allowlist; scan TypeSafe/OpenRouter key formats, credentials,
   local identities and private payload fields before staging.
3. Stage scope-bound public trajectory releases with replay-incomplete declared.
4. Validate public manifest bytes, hashes and analysis bindings; keep a separate
   private admission manifest for withheld original files.
5. Review and merge the artifact PR, then read every public file at its exact
   merge commit. Record that commit and read-back receipt here.

Actual account charges remain unknown. Provider-reported consumption, API-price
equivalents and input-only Jev tariff estimates retain their own provenance.

## Publication receipt

[Artifact PR #45](https://github.com/mangowhoiscloud/geode-eval-artifacts/pull/45)
was merged with a merge commit, then independently read back:
`f1d5f4ed6d65fe40a18d72a210ff860c8144cb24`.

- [Report and cohort index](https://github.com/mangowhoiscloud/geode-eval-artifacts/tree/f1d5f4ed6d65fe40a18d72a210ff860c8144cb24/reports/e2e-validation/jev-verdict-20260924)
- [Normalization procedure and field ownership](https://github.com/mangowhoiscloud/geode-eval-artifacts/blob/f1d5f4ed6d65fe40a18d72a210ff860c8144cb24/reports/e2e-validation/jev-verdict-20260924/NORMALIZATION.md)
- [Public file manifest](https://github.com/mangowhoiscloud/geode-eval-artifacts/blob/f1d5f4ed6d65fe40a18d72a210ff860c8144cb24/reports/e2e-validation/jev-verdict-20260924/publication-manifest.json)
- [Natural trajectory release](https://github.com/mangowhoiscloud/geode-eval-artifacts/tree/f1d5f4ed6d65fe40a18d72a210ff860c8144cb24/trajectories/geode-jev-jev-verdict-natural-20260924-20260924T080210Z-3be360b94a41)
- [Recovery trajectory release](https://github.com/mangowhoiscloud/geode-eval-artifacts/tree/f1d5f4ed6d65fe40a18d72a210ff860c8144cb24/trajectories/geode-jev-jev-verdict-recovery-20260924-20260924T080210Z-619f85690b63)

Read-back compared all 240 changed files (239 additions and the root README)
with the reviewed local bytes: 2,719,674 bytes matched. The report manifest
binds 220 entries; two trajectory releases contain 18 files including their
manifests. Four key JSON files were additionally compared through GitHub's raw
API. All 16 trajectories remain scope-complete and content-replay-incomplete;
the public credential scan found no matches. The repository had no Actions
workflows or check runs, so this evidence is not a remote-CI claim.

| Receipt | SHA-256 |
|---|---|
| Report publication manifest | `83cb2d330c866afa19a1b68e270a8b5e4392477480d7f04edab1d74885af5d06` |
| Native-bound judgment timings | `d046aa241b8faad672f54f944410dda84528355332789b361089a16ee0554bf2` |
| Natural trajectory manifest | `3be360b94a411acbfb7789fd714cdb192277347af5863b064084d85265fce284` |
| Recovery trajectory manifest | `619f85690b631f12a1aa86dbdc8b8f7271f5e2db7619d0235c108f9d8d3f614f` |
| Local post-merge read-back receipt | `4c328c4d90821c1aa7aa8c4400efb76e90b342827ef3a0b7c7164baed5cf0242` |

The last receipt is retained at
`.geode/eval-runs/jev-verdict-publication-20260924/remote-readback.json`.
It records post-merge facts separately; the frozen public manifest's
`prepared` status and all original experiment evidence remain unchanged.
