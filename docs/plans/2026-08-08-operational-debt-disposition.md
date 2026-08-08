# Operational debt disposition — 2026-08-08

> Evidence note, not a competing status ledger. Runtime implementation status
> remains in code and `CHANGELOG.md`; architecture package status remains in
> `docs/architecture/extensibility-roadmap.md`.

## Decision summary

| Item | Measured state | Decision |
|---|---|---|
| Detached serve readiness | Default helper window was 10 seconds; the local 13-MCP boot reached readiness in about 21 seconds | Raise the existing window to the documented 30 seconds; do not add another configuration surface |
| Full-suite scheduler logging | Runtime wiring tests loaded project/legacy scheduler state and leaked owned threads beyond test teardown | Isolate scheduler paths and close every test-created `GeodeRuntime` |
| Non-live credential leakage | Test collection loaded operator `.env` files globally, allowing an unmarked agent path to issue a real PAYG reflection call | Strip provider credentials before imports; load credentials only inside explicitly `live` tests |
| R1.1 / BND-001 claim | Active since 2026-07-18, with no implementation PR | Release through the roadmap's abandonment reconciliation; require a fresh claim and re-audit before resumption |
| `feature/crucible-reentry-hardening` | No PR; 37 branch-only commits on a base hundreds of commits behind current `develop` | Drop the stale branch after recording the salvage audit below |
| Reward-memory convergence plan | One documentation commit in an owner-protected worktree | Preserve; do not copy or delete another session's work |
| Four untracked telecom calibration files | No caller, command registration, or documentation; two tests only pin the orphan scripts | Do not promote them into the product; move them to the operator Trash for recoverable cleanup |

## Scheduler root cause and contract

`GeodeRuntime.create()` owns both `TriggerManager` and `SchedulerService`.
Two wiring-test modules constructed runtimes repeatedly without calling
`shutdown()`. Because the scheduler defaults are module-level project and
legacy paths, those tests also loaded real `.geode/scheduled_tasks.json` rows.
Two enabled operator jobs then aged out and fired from leaked daemon threads
later in the suite. Pytest had already closed the originating capture stream,
so ordinary scheduler and hook logging raised:

```text
ValueError: I/O operation on closed file
core/scheduler/service.py::_loop -> check_due_jobs
core/wiring/scheduling.py::_trigger_logger
```

The correction belongs at the test ownership boundary:

1. Replace scheduler store, log, and legacy-migration paths with one per-test
   temporary root before constructing a runtime.
2. Track each runtime constructed by those modules.
3. Call `runtime.shutdown()` during fixture teardown while pytest capture is
   still valid.
4. Preserve the `classmethod` factory contract and roll back scheduler threads
   if staged construction fails before a runtime can be returned.

Suppressing logging or catching `ValueError` would hide an actual lifecycle
leak and leave operator jobs executable inside tests, so those options are
rejected.

The same isolation rule applies to credentials: `-m "not live"` must be a
spend boundary, not merely a naming convention. Unit tests inject synthetic
keys locally and bootstrap without daemon dotenv promotion; live tests resolve
operator credentials only after pytest has selected the explicit `live`
marker.

## Crucible branch salvage audit

The stale branch changed 53 Python files relative to its merge base. An AST
census found only six files with top-level symbols absent by name on current
`origin/develop`:

- Tau2 trajectory path construction is now delegated to
  `plugins.benchmark_harness.trajectory_artifacts` and retained as a local
  compatibility alias.
- Window preflight functions moved from the CLI script into
  `plugins.crucible.preflight`, giving the CLI and campaign preparation one
  implementation.
- The old `_harvest_partial` helper depended on `cached-row.v1`. Current
  execution intentionally refuses that cache because it cannot bind the
  runtime profile and attempt manifest required by Tau2 snapshot v4. Restoring
  the helper would weaken evidence identity.
- Remaining missing names are stale tests for those retired shapes.

The branch therefore has no independently salvageable production primitive.
Its historical commits may still be inspected through local recovery until
the explicit branch cleanup, but it must not be rebased or merged wholesale.

## Deferred, not silently absorbed

The reward-memory convergence plan remains under a different `.owner` marker.
This pass reads it as evidence only. A future session may re-ground its phases
against #2903, #2915, and later runtime changes, but this work does not steal
the checkout, rewrite the commit, or claim that the plan has shipped.
