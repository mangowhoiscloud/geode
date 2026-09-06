# Modernization safety corrections and second review

Base: `origin/develop@67c20ce545b887b24f061cded36fe8521b9ac1f2`.
Date: 2026-09-06. This records causal bug fixes and review evidence, not an
architecture-program claim or a prediction of merge completion. Canonical
architecture status remains in `docs/architecture/extensibility-roadmap.md`.

## Scope and plan

The earlier local audit contains 28 candidates. M26-01 (preflight failure
aggregation) and M26-28 (pytest authentication isolation) already reached main.
Recheck the remaining candidates against this base before carrying them forward.

| Work | Smallest correction | Acceptance |
|---|---|---|
| M26-02: skill write/delete boundary | One local validator shared by create/remove; preserve user-tier order and reject traversal, symlink escape, and bundled writes | Invalid targets never reach mkdir/write/rmtree; valid temporary project/personal skills retain behavior |
| M26-27: unreachable private gitignore helper | Remove only its public-only call and dead private branch after checking consumers | Public skills remain project-owned, private skills remain personal; no project gitignore mutation |
| M26-03: uninstall ownership and false success | Exclude project source and development caches; validate the configured runtime home; preserve keep targets in place; report failed stop/delete/package removal | Temporary unrelated project files survive, kept bytes/modes remain, failures cannot report completion through either CLI caller |
| M26-04/05: configuration/credential selection | Preserve invalid-input errors and explicit field presence through existing readers | Real config-to-resolver tests fail closed without credentials or provider calls |
| M26-06: implicit billing conversion | Reuse the existing credential resolver without treating a model-name heuristic as API-key authorization | Strict auto/forced OAuth cannot silently become PAYG; explicit API-key selection and explicit fallback remain usable |
| M26-12/13/14/15: scaffold drift | Correct executable commands and unsafe/stale guidance; retain canonical policy links | Commands resolve, links exist, no automatic reinstall/global process termination or count-based deletion instructions |
| Remaining audit candidates | Trace producers, consumers, ownership, and surviving tests before deciding | Classify KEEP/SHRINK/DELETE/MEASURE/DEFER; no static hit alone justifies deletion |

Do not add a generic deletion framework, second model registry, global setting
store, or duplicate status ledger. Structural scope that genuinely expands the
architecture program must follow registration/readiness/claim before implementation.

## Review coverage and ownership

Four parallel lenses cover CLI/configuration, runtime services/tools, evaluation/
evolution, and site/scripts/CI/development skills. Report search coverage separately
from functions read in depth and from executable regression evidence.

Other sessions' cache-accounting, Harbor observability, and landing worktrees are
read-only inputs for overlap checks. Their dirty code, system MDs, skills, and
frozen benchmark artifacts are not copied, reverted, or removed here.

No live model/benchmark calls, credential-file inspection, actual uninstall,
daemon stop/restart, release/tag/PyPI publication, or unrelated resource cleanup.

## Verification and integration

Run narrow RED/GREEN regressions in temporary directories with inert process
substitutes. Then run Ruff/format, strict mypy, import contracts, generated
inventory/doc checks, and full non-live preflight. Freeze committed diffs for
independent review before the CI-gated feature→develop→main path. Test deletion
requires a named surviving invariant, never a weakened threshold or exclusion.

Implementation, review findings, and completed command evidence will be recorded
below as they occur; the plan above is not completion evidence.

## Second-review findings and dispositions

`M26-*` identifiers are local audit candidates, not canonical architecture GAP
IDs. "Implemented" below means present in this patch, not released or merged.

| Candidates | Disposition at this patch | Evidence / remaining boundary |
|---|---|---|
| M26-02/03/27 | Implemented | Shared skill path guard; uninstall ownership and failure handling; dead private-gitignore branch removed. Tests preserve project/personal priority, bundled files, sibling projects, keep-target modes, and partial-failure reporting. |
| M26-04/05 | Implemented | Config errors propagate before credential selection; Pydantic field presence preserves explicit API-key authorization. Missing configuration remains safe; this does not claim every credential loader is isolated. |
| M26-06 | Billing guard implemented; model metadata DEFER | Model-name heuristics no longer authorize API-key fallback under strict policy; resolver errors propagate. Model listing uses a display-only manifest prefix. Concrete subscription/API-key pins retain resolver-based authorization, including suppression. Bare-id OAuth coverage still uses GPT prefixes and differs from runtime/manifest routes; price/reasoning metadata is not account entitlement. No live eligibility claim. |
| M26-07 | DEFER, policy decision | `core/agent/verify.py` reads flat error/name fields while the processor records nested result/tool fields. Historical failed attempts survive later recovery. Treating every historical error as unresolved could trigger a fresh physical turn and new side effects. Separate historical diagnostics from terminal failure before changing retry authority. |
| M26-08 | Description corrected; host coordination DEFER | `audit_lane.py` now states process-local scope. Independent interpreter probe acquired a lane while the parent held its lane. A host-wide guarantee requires a separate ownership/coordination design. |
| M26-09 | DEFER, run-input ownership | `evolve/scaffold_search/measure.py` writes a shared wrapper override before acquiring the lane; two synthetic writers overwrite the same path. Existing campaign workers already isolate `GEODE_STATE_ROOT`. Use a run-owned override lifetime, not another global lock or an atomic-write-only claim. |
| M26-10/11/26 | DEFER, compatibility | Init directories, deprecated load-only model fields, and `~/.geode_history` need explicit migration/legacy-read decisions. No existing user state or historical records were moved or deleted. |
| M26-12/14/15 | Implemented in scoped scaffold | Current dependency direction and explicit wiring replace obsolete layer/service-DI guidance; historical examples are labeled; five broken links corrected or retired. Scanner wording now describes lexical heuristics, not proven dead code. |
| M26-13 | Partially implemented; owner overlap remains | Prompt-integrity command, mypy scope, GitFlow authority and unsafe reinstall/kill guidance corrected. Manual AGENTS/CLAUDE/workflow edits overlap the cache-accounting worktree and remain there; only generated roadmap inventory changes here. |
| M26-16/17/18 | Implemented | Fresh-interpreter OTel assertions and negative environment-loader assertion; two private-source assertions removed while behavior tests survive unchanged. |
| M26-19 | DEFER, latent site parser defect | Current census found 76 valid inline leaves, not an observed missing page. Shared sync/export regex can omit multiline leaves; independent route comparison must be repaired and wired before claiming coverage. Coordinate with landing owner. |
| M26-20 | Follow-up site correction | MarkdownLite advertises italic but lacks it for real changelog input. Preserve code/link/math/escaping when adding emphasis in the existing renderer. |
| M26-21 | Implemented | Pages now runs the existing `npm run lint` after install and before build, without conditional/error bypass. It remains distinct from Markdown/YAML/JSON render lint. Local ESLint passed with 0 errors and 44 existing warnings. |
| M26-22/23/24 | MEASURE / deletion candidates | Seed model projections currently agree; import-time phase-order no-op has only self-references; shared UI/scaffolder consumers need owner confirmation. No result/bundle-size improvement is claimed. |
| M26-25 | DEFER, landing owner | Private function/CSS/useState assertions overlap dirty landing tests. Preserve public link/install/security contracts while moving only implementation-shape checks. |
| M26-29, new | Implemented: cancelled Lane waiter | Direct `Lane` and `SessionLane` now reuse the existing cancel-safe off-thread acquisition used by `LaneQueue`; late grants are released. No public API or concurrency policy added. |
| M26-30, new | Implemented: cancelled Bash task | External task cancellation invokes the existing process-group cleanup path, cancels/drains child waiters, and re-raises cancellation. Mock proof covers single cancellation and cleanup failure. The existing helper returns once the shell has exited; surviving descendants and repeated cancellation need OS-scoped evidence and remain follow-up work. |
| M26-31/32/33, new | Implemented: lifecycle diagnostics | Symlink-target bytes no longer count toward removed file data; failed socket probes close; nonzero Git status cannot imply a clean checkout. Each failed its new regression before correction. |
| M26-34, new | Implemented: checkpoint shape | Completion listing reuses the validated loader and requires phase identity, success, and the existing hydration identity fields. Malformed snapshots and partial ranker files cannot imply phase completion. |
| M26-35, new | DEFER: iteration completion authority | Iteration-0 phase checkpoints can imply an entire multi-iteration run is complete. A synthetic evolved-candidate snapshot reproduced the false-complete CLI path. Do not add a cursor/schema silently; first define supported later-cycle resume or an explicit incomplete/unsupported result. |
| M26-36, new | Implemented: filesystem aliases | Temporary APFS aliases reproduced lexical-boundary bypass and case-variant keep failures. A small shared `core.paths.is_path_within` predicate uses actual file identity; both CLI consumers reuse it. Default home comes from the existing path authority. Keep flags conservatively retain case variants, even on case-sensitive filesystems. No hostile concurrent filesystem-swap protection is claimed. |
| M26-37, new | Implemented: target binding failure | Policy errors propagate before bootstrap. Named catalog and catalog-external targets for Petri-managed providers use the same binding/resolver boundary. Native providers outside the Petri manifest retain native source selection only without a discarded target pin. `model=None` validates policy but deliberately retains native settings/source drift; this is not later-model SIL subscription/suppression enforcement. |

### Coverage, not an exhaustive correctness claim

The tracked-file census covered all top-level areas: core (424 files), evals
(140), evolve (85), tests (751), scripts (60), site (340), development skills,
workflow/configuration, and historical/generated docs (5,257). These are file
counts, not bug counts or manually reviewed-function counts. The generated
inventory remains authoritative for Python/tool/event totals.

Runtime review searched 237 production Python files and 226 test files;
eval/evolution review searched 166 production and 195 test files. Deep traces
covered CLI ownership, config-to-provider selection, verifier record production
and continuation, Lane/provider callers, Bash/executor cancellation, checkpoint
producer/reader/resume, MCP failed-connect cleanup, scheduling rollback, site
generator consumers, and workflow gates. Other hits were classified, not assumed
defects. Memory tiers, every service adapter, and historical artifact bodies were
not individually semantically reviewed.

KEEP decisions: existing queue partial-acquire release, MCP failed-connect close,
middleware cancellation/result preservation, scheduling rollback, source/wheel
installation provenance, normal checkpoint ordering, partial ranker recovery,
and frozen benchmark score/artifact authority.

### Independent review

Separate reviewers checked credential and cancellation diffs without editing
them. CLI review found a sibling-project deletion boundary and a no-op mock that
hid partial-removal behavior; both were corrected, with two new RED cases and
real temporary-directory deletion in the failure tests. A direct-parent-symlink
case was added separately from the sibling-project marker test.

A final runtime reviewer found no production ContextVar consumer in either
`_raw_acquire` implementation and no production override/subclass, so reusing
the existing executor helper has no demonstrated context-propagation regression.
This does not claim that `run_in_executor` copies context like `to_thread`.
Another reviewer independently confirmed the APFS boundary/keep-name gaps;
ten new regressions failed before the correction. Inspection errors propagate,
and the legitimate default-home alias remains usable in a temporary fixture.

A final CLI reviewer found no production blocker but identified a vacuous
dry-run test. It now reaches the preview branch with real temporary data and a
verified tool receipt, asserting no process, deletion, or package call. Parent
review also caught a concrete subscription-pin regression in the proposed
mapper fix; six RED cases led to preserving pins through the existing settings
reader and credential resolver, with an additional suppression regression.

No callable Codex MCP second-opinion integration was available in this task.
The independent-agent review is a disclosed substitute, not a Codex MCP result.

### Executed narrow checks

- Skill boundary: initial RED 13 failures; final CLI/lifecycle subset after
  independent review: 108 passed. No actual user uninstall or process stop.
- Lifecycle diagnostics: RED 3 failures for symlink bytes/socket close/Git status;
  sibling-project boundary: RED 2 failures; included in the final 108-pass subset.
- Credential/config: RED 17 failures; seven related test files 216 passed with
  one existing retired-CLI warning; production modules passed scoped mypy.
- Lane/Bash: RED 3 failures; 111 passed, one pre-existing 50MB file-size case
  deselected in the narrow agent run. Full-suite acceptance must include it.
- OTel/bootstrap: 22 passed, one opt-in integration skip. New interpreter tests
  do not call an OTLP backend.
- Checkpoint: RED 14 failures; producer/reader/resume/CLI subset 93 passed.
- Scaffold: skill schema validation, local reference existence, and real
  `verify_prompt_integrity(raise_on_drift=True)` passed. These do not prove
  every instruction semantically correct.
- Removed lexical assertions: surviving listing-recovery and stale-dimension
  behavior tests passed; scanner executable AST unchanged by wording edits.
- Site sync/build/export completed: 241 generated routes, 76 Markdown twins;
  changelog body intentionally omitted from llms-full by the existing size cap.
- APFS/path correction: 134 CLI/path tests passed, including all ten new RED
  cases, default alias compatibility, and non-absence inspection errors. The
  case-alias cases skip only where the filesystem has no such alias; keep-name
  preservation runs on every filesystem. Ruff/format and scoped mypy passed.
- Model billing boundary: initial RED 10 cases plus concrete-pin RED 6 cases;
  later suppression RED 2 and manifest lookup RED 1. Mapper/credential/OAuth-
  judge/registry/overrides subset 202 passed, one existing Pydantic warning.
  Two legacy fallback tests now explicitly supply a synthetic available API
  key; a separate no-credential test requires resolution failure. No model
  entitlement, HTTP call, or live credential was involved.
- Architecture performance: all 13 existing limits passed, including first
  turn 32.558 ms (300 ms limit), cold import 91.059 ms (400 ms), and runtime
  create/shutdown 686.211 ms (2,500 ms). This is a local synthetic probe, not
  live agent or benchmark performance.
- Target credential boundary: 9 RED cases led to 12 passing boundary cases;
  the five-file target/scaffold/usage subset finished with 71 passed and one
  expected absent-audit-path skip. Existing prompt/usage fixtures explicitly
  select a synthetic API-key route; their behavioral assertions remain intact.
  Ruff/format and production-module mypy passed. The unpinned default and
  providers outside Petri's credential contract retain the limits in M26-37.
- Checkpoint decoding: independent review found that delegating to the canonical
  reader exposed its missing UTF-8 error handling. Three temporary byte-corruption
  cases failed before both existing reader exception tuples were corrected;
  checkpoint/resume/ranker/orchestrator checks then passed all 86 tests.

### Full-gate attempts

The first local attempt found a formatting miss and generated inventory drift;
pytest did not run because the shared environment lacked the optional audit
extra. Both misses were corrected and `uv sync --extra audit --frozen` installed
the required extra in this worktree's own environment, without changing the
root checkout environment.

The second full preflight failed only at pytest (20 cached failed cases).
Nineteen involved an inappropriate command-level `GEODE_STATE_ROOT` override,
which redirected tracked state despite tests explicitly checking repository
locations. The remaining failure caught the duplicated default-home literal in
the new CLI guard. Removing that test-run override and reusing the canonical
default-home constant resolved the affected subsets: 54 state/lineage tests and
the 134 CLI/path tests passed. No test exclusion or threshold was weakened.
All other second-attempt gates, including site generation, passed.

The third attempt passed static/generated gates, then was deliberately
interrupted during pytest (exit 130), not counted as a pass or code failure.
Independent review found two legacy fail-open callers: mapper fallback after
all sources were suppressed, and target fallback after binding/config errors.
The process group was checked against this worktree before interruption; no
other task process was stopped. Logs remain in the root checkout's ignored
`.audit/modernization-safety-20260906/` directory. These findings require a new
full run after correction.

The fourth attempt passed static/generated gates and was interrupted during
pytest (exit 130) after independent review reproduced the UTF-8 checkpoint
regression above. Its process-group ownership was verified before interruption.
It is not counted as a full pass. Import contracts separately passed (578 files,
2,165 dependencies, seven kept/zero broken); exception-debt and official-doc
checks passed, and site ESLint had zero errors with 44 existing warnings.

The fifth full attempt finished with 10,749 passed / 22 skipped, zero failures
or errors (JUnit: 563.108 seconds). Skips were optional OTel integration (1),
absent-extra-only branches while audit is installed (2), missing visualization
extra (5), absent rendered EN/KO video inputs (12), and absent uharfbuzz (2).
Site sync/build/export succeeded, but its final drift check caught a generated
changelog-body size label changing from 1,549 KB to 1,550 KB. That generated
line was accepted and a fresh full preflight uses two xdist workers with
loadfile scheduling, matching CI's parallel isolation pattern without excluding
tests. The fifth attempt remains an overall failed gate, not a full pass.

The sixth full preflight exited 0 with `all gates passed`, including site
sync/build/export and committed-generator drift checks. The same 10,771 cases
finished with 10,749 passed / 22 skipped, zero failures/errors (JUnit: 245.773
seconds, two xdist workers with loadfile scheduling). No live tests or cases
were newly excluded. The final synthetic performance probe passed all 13
existing limits: first turn 29.004 ms, cold import 86.356 ms, runtime
create/shutdown 679.446 ms. These numbers are local gate evidence, not agent
benchmark results or a causal speedup claim.

Committed-head review and remote merge evidence remain pending at this
checkpoint. No release or completed deployment is implied.
