# Handoff — GPT-5.4 model surface and Tau2 cycle

Status: implementation, live evidence, and local verification complete. The
merge vehicle is [GEODE PR #2857](https://github.com/mangowhoiscloud/geode/pull/2857).
This document is an operational handoff, not a second design ledger.

## Read first

1. The design, GAP audit, diagram, and measured result live in
   [2026-08-01-openai-model-surface-alignment.md](2026-08-01-openai-model-surface-alignment.md).
2. The reviewed public evidence is immutable at
   [`geode-eval-artifacts@f588ce9`](https://github.com/mangowhoiscloud/geode-eval-artifacts/commit/f588ce9fd23b9123732b45c4dbe202136691d3fe).
3. Do not rerun the paid Tau2 diagnostics merely to reconstruct state. The
   native receipts, normalized trajectories, hashes, privacy review, and
   remote read-back already exist.

## Final operator surface

The curated OpenAI block is ordered as follows:

1. `gpt-5.6-sol` — dual lane, effort `none` through `max`
2. `gpt-5.6-terra` — dual lane, effort `none` through `max`
3. `gpt-5.6-luna` — dual lane, effort `none` through `max`
4. `gpt-5.5` — ChatGPT subscription only, effort `none` through `xhigh`
5. `gpt-5.4` — dual lane, effort `none` through `xhigh`
6. `gpt-5.4-mini` — dual lane, effort `none` through `xhigh`
7. `gpt-5.3-codex` — labelled legacy management row

`dual lane` means provider `openai` with runtime credential-source inference:
OAuth selects the ChatGPT subscription backend and an API-key profile selects
PAYG. Picker effort values come from the adapter's `OpenAIModelSpec`; they are
not a second enum.

An off-catalog `[model.defaults].openai` value or active
primary/reflection/mutator selection appears as one provider-grouped
`Configured` management row. This is compatibility and operator control, not a
claim that the row belongs to the curated current catalog. A no-op Enter keeps
both the model and a persisted legacy OpenAI `minimal` effort; the first arrow
migrates `minimal` left to `none` or right to `low`.

## Live evidence receipt

- Measured GEODE revision: `afaab52ba2fc0ee8b0ffcdf251371e65be6f0933`
- Tau2 harness revision:
  `1901a301961cbbe3fd11f3e84a2a376530c759e3` (`tau2==1.0.0`)
- Agent and GEODE user: `gpt-5.4`, `source=subscription`, effort `high`
- Mock `create_task_1`: reward/pass `0.0/0.000`; exact-action mismatch from an
  added empty optional description; no provider, route, adapter, or user error
- Telecom-small fixed first task: reward/pass `1.0/1.000`; 127 events and
  eight exact tool pairs; no missing or orphaned calls
- External manifest SHA-256:
  `2dc79cb569f03e5f44ce008b32fd8af86f8388ab04341ee8f91c74fdffb6aa6b`
- Evidence boundary: two GEODE subscription-route diagnostics, not a native
  Tau2 user-simulator aggregate or leaderboard claim; `promotion_authority=none`

## Verification already completed

- Full Python gates: ruff, format, mypy (542 files), import contracts,
  architecture baseline, and 10,420 non-live tests
- Final picker follow-up: the complete `tests/core/cli` suite
- Package: sdist and wheel built; `geode version` reported v1.0.11
- Site: Next 16.2.12 production export generated all 237 pages; lint had zero
  errors; `npm audit --omit=optional` had zero advisories
- Review: GPT-5.4/high subscription review found two picker defects during the
  branch; both were fixed. Its final review of `640d89967` reported no
  actionable defects.
- Evidence: artifact PR #10 merged and remote read-back revalidated the
  manifest plus both public native copies at the immutable commit.

The full npm install still reports two high advisories through optional
`sharp<0.35.0`; Next 16.2.12 currently constrains `sharp` to `^0.34.5`. This is
documented as an upstream optional-native boundary, not reported as zero.

## Continuation / recovery

1. Inspect PR #2857. If it is open, require all CI checks green and squash it
   into `develop`; do not recreate the live runs.
2. Fetch again. Verify `main` has no content that `develop` lacks before
   opening the normal `develop -> main` merge PR. Follow the repository's
   trusted-sync rule if the branches have diverged.
3. Require the main PR's CI, merge with a merge commit, and verify the Pages
   deployment plus the public Tau2 page by HTTP read-back.
4. Remove only task-owned generated storage after merge: the ignored Tau2
   harness/venv, site `.next` and `node_modules`, and clean merged worktrees.
   Do not touch active Claude/Codex session logs, VM/swap, or another worktree.

If PR #2857 and the subsequent main PR are already merged, the GitHub PR and
Pages states are the completion receipts; no branch archaeology is required.
