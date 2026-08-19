# GEODE agent anti-pattern audit — 2026-08-19

> Verdict: **targeted cleanup completed; no evidence for a whole-repository
> deletion campaign.**
>
> Audited base: `origin/develop@45aba3ca7ba18bf8d19839e42520b102f4b6669e`
>
> This is dated evidence, not a status ledger. It does not authorize deleting
> a candidate solely because a static lens reported it.

## Executive result

The scan found five P1 correction surfaces and three P2 cleanup surfaces. The
accepted APX-001–005 and APX-007–008 corrections are now applied; APX-006
remains `MEASURE`. It found **zero production symbols that pass the full
deletion gate**. GEODE's
structured termination, deferred tool loading, role-scoped tool enforcement,
context bounds, and non-interactive coding-agent subprocess paths are
contributing mechanisms and should stay.

The largest lesson is about audit quality rather than code volume:

- the current slop audit reports `199` dead-private and `126` duplicate-name
  candidates, but its leading dead-private samples are live dynamic handlers;
- its unused-import lens reports `0` even when the Ruff subprocess exits `127`
  or returns invalid JSON;
- an older codebase-audit skill still recommends deletion from import count and
  treats duplicate names as a design flaw without proving runtime identity;
- machine-facing and operator-facing docs still name the deleted
  `PromptAssembler` path;
- source-inspection tests are widespread and a small high-risk subset can pass
  on lexical presence rather than executed behavior.

The appropriate next step is a few narrow fixes, not a new analyzer, universal
threshold, or mega-refactor.

## Scope and coverage

Tracked inventory at the frozen base:

| Bucket | Files | Audit coverage |
|---|---:|---|
| `core/**/*.py` | 437 | lint, type, dependency, import boundary, six AP lenses, reachability samples |
| `plugins/**/*.py` | 114 | same, including provider/entrypoint/manifest routes |
| `scripts/**/*.py` | 48 | lint plus analyzer/error-boundary review |
| Existing `tests/**/*.py` | 686 | collection, skip/source-inspection census, anti-deception review |
| New scaffold test | 1 | focused Ruff and pytest |
| Total collected tests | 10,396 total / 10,395 non-live selected across 658 collected files | collection passed; CI-equivalent non-live result recorded below |

The audit covered every tracked production/test file through deterministic
passes. Manual tracing then sampled every anti-pattern class and each candidate
class that could justify deletion. Generated assets, historical version
snapshots, vendored dependencies, build output, local credentials, and live or
paid provider calls were excluded.

## Method

The shared [`agent-anti-pattern`](../../.agents/skills/agent-anti-pattern/SKILL.md)
skill was generated with the repository's standard skill creator and validated
before use. Static hits were treated as candidates. Each final finding names a
current owner/consumer, a falsifiable harm, a false-positive check, and one of
`KEEP`, `SHRINK`, `DELETE`, `MEASURE`, or `DEFER`.

Deletion required all of the following: no static/dynamic/registry/public
consumer, no import-time effect, no persisted-state or rollback authority, all
provider routes checked, and a surviving behavior invariant. Unknowns were not
rounded up to deletion.

## Findings

### APX-001 — unused-import audit fails open when Ruff fails

- Verdict/severity: **SHRINK / P1**
- Surface: `scripts/slop_audit.py::lens_unused_imports` and
  `tests/integration/test_slop_audit.py`
- Evidence: the lens invokes Ruff with `check=False`, ignores
  `proc.returncode`, converts empty stdout to `[]`, and converts
  `JSONDecodeError` to `[]`. A controlled probe returned
  `{reported_count: 0, severity: info}` for both exit `127` with empty stdout
  and exit `2` with invalid JSON.
- Harm: an unavailable or crashed analyzer is presented as a clean audit. The
  current test only asserts a coarse `<= 50` result and therefore preserves the
  false success.
- Source grade: A — local executable behavior and test.
- False-positive check: ordinary Ruff `0` and Ruff `1` with valid JSON remain
  legitimate result shapes; the issue is failure or malformed output, not a
  nonzero finding count.
- Smallest correction: accept only valid JSON from expected Ruff exits and
  raise/report an audit error otherwise; add one subprocess-failure regression.
- Resolution: implemented. Exit codes outside `0/1`, missing JSON for Ruff
  findings, malformed JSON, and non-list payloads now fail closed; expected
  Ruff findings remain accepted by a focused regression.

### APX-002 — codebase-audit skill promotes discovery heuristics to deletion rules

- Verdict/severity: **SHRINK / P1**
- Surface: `.claude/skills/codebase-audit/SKILL.md`
- Evidence: the skill states that same-name functions are a design flaw and
  classifies “0 imports, only tests exist” as immediate deletion. The local
  repository has import-by-string adapters, entry points, manifests,
  decorators, import-time registration, and dynamic dispatch, none of which
  that rule proves absent.
- Harm: the instruction can cause an agent to delete public, registered, or
  side-effectful code together with the only tests that exposed it.
- Source grade: A — tracked agent instruction plus local dynamic mechanisms.
- False-positive check: exact duplicate implementation can still be debt, and
  a test-only production helper can still be dead. Both require the deletion
  gate, not a different blanket rule.
- Smallest correction: route the skill's triage through
  `agent-anti-pattern`; change its outputs to candidates and remove numeric
  split/delete mandates.
- Resolution: implemented in both codebase/slop skills without adding another
  analyzer or threshold.

### APX-003 — current instructions still describe a deleted prompt authority

- Verdict/severity: **SHRINK / P1**
- Surface: `AGENTS.md` and `docs/self-improving/loop-overview.md`
- Evidence: `AGENTS.md` says `PromptAssembler.assemble()` performs a six-step
  immutable assembly, and the loop overview says `PromptAssembler` reads the
  wrapper override. `core/llm/prompt_assembler.py` explicitly states that the
  class was removed; the active path is `core.agent.system_prompt` plus the
  per-round `AgenticLoop` context path. The removal is also recorded in the
  changelog and ADR-007 update.
- Harm: an implementation agent is directed toward a nonexistent owner and can
  recreate the exact parallel prompt authority previously deleted as slop.
- Source grade: A — current code and machine-facing instructions.
- False-positive check: historical version snapshots and the proposed section
  of ADR-007 are retained as history; only current navigation/operation claims
  require correction.
- Smallest correction: update the two current documents to the active path.
  Do not add another prompt facade.
- Resolution: implemented; current navigation now points to product
  policy-source composition, `core.agent.system_prompt`, and loop context.

### APX-004 — critical wiring tests use lexical presence as behavior proof

- Verdict/severity: **SHRINK / P2**
- Surface: representative cases in
  `tests/core/llm/test_geode_target_adapter_bootstrap.py`,
  `tests/core/test_mcp_server_tools.py`, and
  `tests/plugins/benchmark_harness/test_mcpmark_adapter.py`
- Evidence: the tests read or inspect production source and assert exact
  substrings such as
  `bootstrap_builtins(policy_sources=policy_sources)`,
  `async def run_agent(`, and `await arun_agentic_oneshot(`. Across the suite,
  111 files use `inspect.getsource` or equivalent source reads, with 253 such
  read sites. Many are intentional architecture pins; lexical presence alone,
  however, does not prove execution, order, reachability, or that a matching
  string is not in a comment/dead branch.
- Harm: the original regressions were fake-success wiring failures, but these
  particular guards can themselves be false-green while resisting harmless
  refactors.
- Source grade: A — current tests.
- False-positive check: source attestation, forbidden-import checks, and
  reproducibility pins can legitimately inspect source. The finding is limited
  to tests whose stated invariant is runtime invocation or ordering.
- Smallest correction: replace only the high-risk runtime-wiring assertions
  with a call spy/monkeypatch or AST call check. Do not mechanically rewrite
  all 111 files.
- Resolution: implemented for the three representative wiring groups using
  function-scoped AST call checks. The broader source-attestation inventory
  remains unchanged.

### APX-005 — slop audit documentation overstates its heuristic and disagrees on baseline location

- Verdict/severity: **SHRINK / P2**
- Surface: `scripts/slop_audit.py` and `.geode/skills/slop-audit/SKILL.md`
- Evidence: the script calls its private-function pass “vulture-style” and
  says cross-module callers are rare, but the implementation only counts a
  name inside its defining file. Its top five reported dead functions are
  `EventRenderer._handle_*` methods invoked by
  `getattr(self, f"_handle_{etype}")`. The 2026-05-18 absolute-count snapshot
  also drifted to dead-private `139→199`, duplicate names `76→126`, and bypass
  markers `91→164`, while the actual promotion gate is
  `scripts/check_slop_ratchet.py`.
- Harm: candidate counts read like confirmed debt, and the wrong baseline path
  sends maintainers to a non-authoritative artifact.
- Source grade: A — executable scanner, dynamic dispatch, and tracked skill.
- False-positive check: the pass remains useful as a cheap candidate generator.
  Its output should not be removed; its claim should be narrowed.
- Smallest correction: label the result explicitly as in-file lexical
  candidates, retire the obsolete check authority, preserve its provenance as
  a dated reference, and point interpretation to the deletion gate.
- Resolution: implemented; the historical counts remain unchanged at
  `docs/reference/2026-05-18-slop-audit-baseline.md`, and the scanner is
  diagnostic-only.

### APX-006 — generic review is write-denied but not a frozen code-review target

- Verdict/severity: **MEASURE / P2**
- Surface: `core/agent/subagent_roles.py`, `core/agent/sub_agent.py`, and the
  paired-coding workflow reference
- Evidence: the built-in reviewer is genuinely narrowed to `grep_files` and
  `read_document`; the denylist also covers provider-native computer tools and
  structured output is validated. The generic runtime request does not bind a
  Git base/head/diff digest or recheck drift. The paired-coding document does
  freeze those values operationally after commits.
- Harm: only a problem if callers start treating the generic reviewer result as
  review of one immutable patch. No such automatic promotion authority was
  found.
- Source grade: A — runtime code and tracked workflow.
- False-positive check: tool restriction and review-target identity solve
  different problems; the existing reviewer is not dead or unsafe merely
  because it is generic.
- Smallest correction: none now. Register a runtime gap only after a named
  consumer needs reusable frozen review and a drift test can fail.

### APX-007 — desktop doctor test asserts the obsolete install route

- Verdict/severity: **SHRINK / P1**
- Surface:
  `tests/core/cli/test_doctor_bootstrap.py::TestCheckDesktopComputerUse::test_missing_host_dependency_fails`
- Evidence: the test expects `uv sync --extra desktop`, while the current
  environment-aware implementation returns the editable-tool repair command
  `uv tool install -e ".[desktop]" --force`. Adjacent tests explicitly pin the
  editable-tool and wheel-install variants. The test fails under the canonical
  non-live command after isolation from the user home.
- Harm: a stale broad assertion makes the full gate red even though the more
  specific current contracts pass; changing installation mode can also change
  its result.
- Source grade: A — current implementation and executable test.
- False-positive check: the missing dependency must remain a failure with an
  actionable desktop-extra repair. Only the obsolete route is redundant.
- Smallest correction: make this test assert the invariant common to every
  install mode and leave exact commands to the two variant tests.
- Resolution: implemented; the broad test now checks the desktop-extra
  invariant while dedicated tests retain exact editable/wheel commands.

### APX-008 — empty seed export imports an optional backend before proving work exists

- Verdict/severity: **SHRINK / P1**
- Surface: `plugins/seed_generation/eval_export.py::export_run_to_evals` and
  `tests/plugins/seed_generation/test_seed_eval_export.py`
- Evidence: `export_run_to_evals` imports `inspect_ai` before reading the run
  directory/state. On the default environment without the audit extra, both an
  empty run and a missing `state.json` raise `ModuleNotFoundError`, despite the
  function contract and tests requiring `[]`. Four tests fail; only one later
  test uses `pytest.importorskip("inspect_ai")`.
- Harm: a documented no-op path unnecessarily depends on an optional heavy
  backend, and the default non-live suite is red when that extra is absent.
- Source grade: A — current runtime and tests.
- False-positive check: producing real `.eval` files genuinely requires
  `inspect_ai`; it should not be reimplemented or made a core dependency.
- Smallest correction: validate the run and return `[]` before optional
  imports; gate only positive export tests on the audit extra.
- Resolution: implemented. Missing/empty runs stay executable without
  `inspect_ai`; the three positive export tests are explicitly optional-extra
  tests rather than hiding the no-op invariants.

## Representative KEEP decisions

### Structured lifecycle — KEEP

`AgenticLoop` terminates from provider `stop_reason`, a closed
`TerminationReason` alphabet, and explicit time/cost/refusal/convergence
guards. `DEFAULT_MAX_ROUNDS = 0` makes round count a secondary opt-in cap, not
the primary completion parser. No success regex over assistant prose was found.

### Tool inventory and role surfaces — KEEP

The 87 definitions are not evidence of 87 always-visible tools. Anthropic and
OpenAI share one deferred-loading policy above 16 tools; 17 high-frequency
tools remain immediate, and registered subagent roles invert small allowlists
into the executor's deny rail, including provider-native computer tools.
Provider support and task policy still matter, so tool relevance should be
measured per routed request rather than replaced by a universal “4–5 tools”
limit.

### Dynamic event handlers — KEEP

The slop scan's first five dead-private samples are called through
`EventRenderer.on_event()` using `_handle_{event_type}` dynamic dispatch. This
is a canonical false positive and should remain in the audit as calibration.

### Context owners — KEEP, with documentation cleanup

`ContextAssembler` is documented as an explicit five-tier facade, while the
default loop prompt is assembled by `core.agent.system_prompt` plus loop
context. They serve different call surfaces; no evidence justified merging
them. Provider-aware compaction, tool-result bounds, and cache boundaries are
active. The defect is stale authority prose, not an immediately proven second
runtime owner.

### Coding-agent subprocesses — KEEP

Codex paths use `codex exec`/`--json` or `--full-auto`, stdin, bounded waits,
return-code checks, and captured stdout/stderr. Claude audit paths use the
non-interactive print surface. Interactive `console.input` calls found in the
repository belong to operator CLI/onboarding/approval flows rather than CI
agent invocation.

## Candidate counts are not deletion counts

| Existing lens | Result | Audit disposition |
|---|---:|---|
| Ruff F401 through slop audit | 0 | valid only when Ruff invocation is proven; direct Ruff passed |
| Dead private lexical candidates | 199 | candidate-only; leading samples are dynamic KEEP |
| Duplicate-name candidates | 126 | candidate-only; `main`, `stop`, `create`, and protocol methods dominate samples |
| Abandoned TODO candidates | 0 | no action |
| Bypass markers | 164 | ratchet passed; inspect additions per diff |
| Stale configured references | 0 | narrow configured vocabulary only |
| Proven DELETE findings | **0** | no item passed the full deletion gate |

## Test-set audit

- Collection: 10,396 total tests; 10,395 non-live tests selected across 658
  collected test files.
- Source inspection: 111 files / 253 source-read sites. This is an inventory,
  not a demand to remove them; source-attestation tests remain valid.
- Skip/xfail/importorskip: 89 sites at the audit base and 91 after this change;
  both new sites are in an already-counted file. Sampled cases were scoped
  to optional extras, platforms, local archives, or live credentials. One test
  skips when an operator-local skill policy exists; this is environment
  sensitive and should be kept isolated from hermetic core assertions.
- Two positive seed-export cases now use the same `inspect_ai` optional-extra
  skip as the existing validator case. The empty/missing-run invariants remain
  active without that extra. Two obsolete baseline/check contract tests were
  removed and replaced by historical-reference and obsolete-flag fail-loud
  tests; no surviving invariant was weakened. No xfail, threshold decrease,
  or type ignore was introduced.

## Verification evidence

| Command | Result |
|---|---|
| `ruff check core/ tests/ plugins/ scripts/` | PASS |
| `ruff format --check core/ tests/ plugins/ scripts/` | PASS — 1,286 files formatted |
| `mypy core/ plugins/` | PASS — 551 source files |
| `deptry .` | PASS — no dependency issues |
| `lint-imports` | PASS — 5 contracts, 435 files, 1,577 dependencies |
| `scripts/check_slop_ratchet.py` | PASS — 250/2/0/83 baselines |
| `scripts/slop_audit.py` | PASS — diagnostic scan completed; historical absolute counts are not an execution gate |
| `pytest --collect-only` | PASS — 10,396 total / 10,395 non-live selected across 658 files |
| skill `quick_validate.py` | PASS |
| focused cleanup/scaffold pytest | PASS — 86 passed, 3 optional-extra skips |
| architecture baseline check | PASS after generated inventory update: 551 production / 687 test Python files |
| CI-equivalent full pytest (`-n auto --dist=loadfile --cov=core`) | PASS — 10,342 passed, 65 skipped; 80.96% coverage |
| site webpack build / structured-metadata verifier / markdown export | PASS — 237 pages / `SoftwareSourceCode` v1.0.22 / 13 citations / 74 markdown twins |

A sandboxed serial diagnostic was stopped after its network, socket, subprocess,
and operator-home tests failed on the execution sandbox's denied capabilities;
it is not counted as product evidence. The same current bytes passed the
CI-equivalent full suite outside that sandbox. No live model, provider, gateway,
browser, credential, or paid-service test was run.

## Cleanup result and remaining work

Completed: fail-closed Ruff handling, safe heuristic instructions, current
prompt-owner documentation, desktop/seed-export test isolation, and the three
representative wiring-test conversions. Static gates, generated inventory,
targeted tests, and the current-byte CI-equivalent full non-live suite were
re-run.

No slop threshold was lowered because no measured heuristic count shrank. Do not
start persistent process, review-task, context-store, tool-registry, or
universal-ledger work from this audit. APX-006 remains `MEASURE` until a current
consumer supplies a failing drift invariant.

## Source basis

The audit taxonomy and numeric caveats are frozen in the
[approved plan](../plans/2026-08-19-agent-anti-pattern-audit-and-slop-reduction.md).
Primary references include Anthropic's
[Building effective agents](https://www.anthropic.com/engineering/building-effective-agents),
[multi-agent research system](https://www.anthropic.com/engineering/multi-agent-research-system),
[context engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents),
and [advanced tool use](https://www.anthropic.com/engineering/advanced-tool-use),
plus Liu et al.'s
[Lost in the Middle](https://aclanthology.org/2024.tacl-1.9/). The linked recap
and original talk were discovery sources; their 4–5 tool and 150K-token numbers
were not promoted to universal GEODE constraints.
