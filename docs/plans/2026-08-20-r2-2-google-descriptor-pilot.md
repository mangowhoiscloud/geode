# R2.2 Google Descriptor Consumer Migration

Status: implementation authorized by roadmap claim [#3046](https://github.com/mangowhoiscloud/geode/pull/3046)

Base: `origin/develop@52f3f853108f56c726ef0a9bc8fb9a1dd88686b4`

GAP: `CAP-004`

## Outcome

Keep the eight existing `GoogleServiceDescriptor` records as the service SOT
and add one frozen tool-to-service association catalog. Derive OAuth scope
hints, personal-data
classification, write policy, approval, and headless/sub-agent projections from
that immutable catalog without changing the 14 tool names, schemas, handlers,
consent prompts, or API behavior.

This package does not add another registry. `definitions.json` remains the model
schema SOT, the existing handler composer remains the execution SOT, and R2.1's
`ToolPlan` remains the validated snapshot boundary. The definitions edit surface
cannot close honestly before R2.3 makes providers consume the plan, so this
package remains `IN_DEVELOP` until that registered follow-up supplies the final
R2.2 exit evidence.

## Measured gap

- eight service descriptors own scopes, risk, API service IDs, implications,
  and recommended defaults, but no tool associations;
- fourteen Google/Calendar names are repeated across personal-data, safety,
  profile policy, approval, delegated handlers, and schemas;
- the eleven Workspace classes and Calendar adapter repeat OAuth scope choices;
- current behavior already has strong consent, OAuth, keyring, headless,
  sub-agent, bounded-result, and request-shape tests.

## Boundary

1. Add one frozen tool association record with read/write service alternatives;
   reject duplicate tools and unknown services before exposing the catalog.
2. Derive immutable tool-to-service, read, write, and personal-data projections.
3. Point the existing Google consumers at those projections. Keep handler class
   construction local to the existing delegated-handler owner.
4. Preserve `/login google`, scope implication, multi-account persistence,
   per-call consent, headless/sub-agent denial, redaction, and bounded results.
5. Update `[Unreleased]`, then run targeted and repository gates.

## Non-goals

- R2.3 handler ownership, provider/deferred projection, or live plan consumption;
- R2.4 resource-key or data-policy derivation;
- a runtime API-availability probe, plugin system, or mutable global registry;
- changing tool schemas, wire names, approval copy, or Google request payloads.
- claiming `DONE` while `definitions.json` remains an independent schema edit
  surface; R2.3 owns that convergence.

## Acceptance

- all 14 Google/Calendar tools have one association; Calendar and Tasks retain
  their existing read-or-write scope alternatives and Calendar remains usable
  through its non-Google adapters;
- read/write/personal/headless/sub-agent projections are descriptor-derived and
  byte-for-byte equivalent to the existing behavior;
- implied write services authorize the existing read scope behavior;
- all eleven Workspace tools and Calendar read/write calls use descriptor-owned
  scope requirements;
- adding or moving a tool association cannot silently leave a stale independent
  Google name list in the five runtime consumers migrated here; the sixth,
  `definitions.json`, is an explicit R2.3 closure dependency rather than a
  second schema authority;
- targeted tests, ruff, format, mypy, import-linter, architecture baseline,
  package/install checks, official docs, and the full non-live suite pass.

## GitFlow

One functional PR from `feature/r2-2-google-descriptor-pilot` targets `develop`.
After merge, a roadmap-only reconciliation records evidence, removes the claim,
and performs the next whole-ledger readiness audit. Main promotion waits until
the remaining planned packages have converged on `develop`.
