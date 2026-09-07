# Instruction alignment and scaffold cleanup

Scope: all repository Markdown, with semantic corrections focused on maintained
instructions, references, and runtime-loaded guidance.
Base: `c0b365293e10c2e090ebe4be41445f3438b2a1c4` (`origin/develop`).
This is a change receipt, not an architecture-program status ledger or release.

## Basis

The [OpenAI Astra prompting guide](https://developers.openai.com/api/docs/guides/latest-model#prompting-best-practices),
retrieved 2026-09-07, recommends auditing existing instructions and calibrating
follow-through, delegation, writing, and verification. Apply those criteria to
current GEODE contracts; do not change model defaults or frozen benchmarks.

## Decisions

| Surface | Decision | Reason and retained authority |
|---|---|---|
| CLAUDE workflow copies | Shrink | Keep project guardrails and incident rationale; route execution and checks to `docs/workflow.md` and its references. |
| GitFlow diagrams and templates | Consolidate | One procedure in the GitFlow skill; one PR body template in `.github/PULL_REQUEST_TEMPLATE.md`. Preserve CI, exact head, canonical sync, and guarded cleanup. |
| Repeated full checks and mandatory connectors | Update | Risk-based local checks with reusable evidence; independent review uses available tools, and required remote CI remains mandatory before merge. |
| Runtime delegation and fallback | Update | The injected instructions must respect available tools, headless restrictions, and configured model/provider/billing scope. |
| Router completion instruction | Update | A successful tool call does not finish a multi-step request. Preserve the requested scope and update the intentional prompt hash. |
| Release and installation instructions | Update | Ordinary changes remain Unreleased; release, global installation, and restart are separately authorized operations. |
| Removed `plugins` search root and moved config | Update | Search `core`, `evals`, and `evolve`; v1.1.0 reservations still exist in `evals/config.py`. |
| Hand-maintained counts and copied parser regexes | Remove | Generated architecture inventory and actual parser/workflow source own these facts. |
| Historical plans, changelog, and skill case studies | Keep | Dated evidence is not an active instruction; age alone does not justify deletion. |
| Entire skill files and Claude aliases | Keep | All reviewed skills still have consumers and distinct responsibilities; no whole-file deletion is justified. |

The existing paused `harbor-4` automation was narrowed without restarting it:
historical process IDs are not ownership proof, and completion does not expand
into repository tests or GitFlow. Frozen tasks, model, schedule, and limits remain.

## Initial batch verification

All commands ran in the isolated worktree with `PYTHONPATH="$PWD"` and the
existing root-checkout `.venv/bin/python` (`$PY` below). The import
path was checked before testing. No Python dependencies were installed.

| Check | Command / evidence | Result |
|---|---|---|
| Runtime identity and organization | `$PY -m pytest tests/core/agent/test_geode_soul_g1_behavioral.py tests/core/memory/test_organization_memory.py tests/integration/test_prompt_audit_2026_05_12.py -m 'not live' -q` | 36 passed. |
| Workflow, skill surface, preflight | `$PY -m pytest -q tests/test_workflow_scaffold.py tests/test_skill_surface_policy.py tests/scripts/test_preflight.py` | 22 passed. |
| Final prompt correction | `$PY -m pytest -q tests/core/agent/test_geode_soul_g1_behavioral.py tests/core/llm/test_prompt_integrity.py` | 8 passed, including 3 additional prompt-integrity tests; 61 unique cases overall. Organization and integration tests also passed again after the suffix correction (31 cases). |
| Python style | `$PY -m ruff check` and `$PY -m ruff format --check` on the two changed test files and `core/llm/prompts/__init__.py` | Passed after formatting the new assertion. |
| Shell and repository hygiene | `bash -n scripts/preflight.sh`; `$PY scripts/check_repo_hygiene.py`; `git diff --check` | Passed. |
| Edited skills | `quick_validate.py` from the Codex skill-creator on codebase-audit, docs-link-audit, geode-changelog, geode-gitflow, geode-workflow | All five valid. |
| Links | Parsed local Markdown links/anchors; `$PY scripts/check_docs_links.py --quiet` | 42 local links/anchors valid; 714 site occurrences checked, no broken internal links. External HTTP reachability was not tested. |
| Generated inventory | `$PY scripts/architecture_baseline.py --update`, then `--check` | Passed. Roadmap change is only the generated test-LOC row, not execution status. |
| Generated release/docs data | `node site/scripts/sync-stats.mjs`; `$PY scripts/check_llms_version.py --fix` | Passed; version unchanged at 1.0.27. |
| Site | `npm --prefix site run build`; `npm --prefix site run export-md` | Build and TypeScript passed; 241 static pages and 76 Markdown twins. Regenerated `llms-full.txt` has no source diff. |
| Independent review | Combined diff review, then focused review of its three findings | Empty-section test loophole, unconditional review instruction, and premature tool-success completion all resolved; no remaining blocker reported. |

The first site build could not start because the existing shared `node_modules`
lacked TypeScript. The temporary symlink was removed and the existing lockfile
installed only in this worktree with `npm --prefix site ci --ignore-scripts
--no-audit --no-fund`; the build then passed. No dependency or lockfile change.

Intentional suffix hash: `842dcc4a6935` → `05f56b99ba7a`; router-system hash
unchanged. The test now rejects empty behavioral sections without pinning
arbitrary prose. GitFlow guidance shrank from 820 to 237 lines and its duplicate
reference from 130 to 18 lines; CI and ownership protections remain.

## Repository-wide Markdown pass

The expanded scan read all 577 existing tracked/non-ignored Markdown bodies
(7,109,452 bytes, including this receipt), without following the Claude skill
aliases twice. It checked exact-content duplicates, local links and headings,
retired paths, and risky or conflicting instructions. Current consumers and
source implementations were inspected before semantic edits.

This is complete file-level scan coverage, not a claim that every historical
sentence or external URL was independently fact-checked. Dependencies, ignored
artifacts, personal/global documents, and other worktrees were outside scope.

| Surface | Decision and evidence boundary |
|---|---|
| Root/setup/operator guidance | Replace credential dumps, whole-config overwrite examples, and broad process kills with private editing and owner-scoped recovery. Use current credential precedence, commands, and canonical verification references. |
| Runtime project rules | Delete only `.geode/rules/parallel-search-delegation.md`: the fixed search-count delegation rule conflicts with tool availability and duplicates current runtime/research guidance. No name-specific consumer or global fallback was found; Git retains the original. Make scheduling freshness conditional on the supplied date context. |
| Development skills and command alias | Remove mandatory review personas/connectors, arbitrary splitting thresholds, copied implementations, and nonexistent assets. Keep distinct skills and the thin Kent Beck command alias. Required CI, explicit scope, budget, ownership, and failure evidence remain. |
| Loop/operator program | Route configuration, dimensions, fitness, promotion, and artifact paths to current code owners. Preserve the single mutation-call contract, frozen run settings, attempt history, and historical output snapshots. No automatic budget expansion, reset-all recipe, or free-judge claim. |
| Petri role guidance | Correct auditor interaction versus judge scoring, native output contracts, and provider-bias reporting versus optimizer-only enforcement. Role/default-model/default-source/inline-skills YAML values are unchanged; descriptions and bodies now match the implementation. Rubrics, seed scenarios, and measured data are unchanged. |
| Seed generation and runtime skills | Mark the old `seeds_gen1` output placeholder historical; point to the current `geode-eval` CLI, state root, and populated registry. Use the real evolver verdict and search tool name; make persistence, scheduling, and delegation conditional on authorization/availability. Remove the obsolete six-layer review map. |
| Site and visual guidance | Replace Next.js/Vercel boilerplate and retired bridge paths with the actual Pages build and renderer owners. Preserve the consumed `DESIGN.md` §11.1 color-policy anchor. Separate static baseline validation from live font/geometry/glyph measurement and sampled-frame evidence. |
| Historical evidence | Keep 31 byte-identical candidate/survivor snapshot groups: their paths preserve experiment lineage, not redundant instructions. Keep dated formulas, measurements, and design records; label historical authority where needed. |

The scan found and corrected 16 missing file links and four broken heading
anchors. Retired local artifact references now point to their retained internal
location or artifact-repository owner; four migrated GitHub targets were checked
remotely. The changelog edit changes only a broken historical link plus the
existing Unreleased entry; generated site data was synchronized accordingly.

### Expanded verification

| Check | Result |
|---|---|
| Project rule loading, runtime skills, injected behavior, integration audit | 82 passed: `test_project_memory.py`, `test_skill_loader_tiers.py`, `test_geode_soul_g1_behavioral.py`, and `test_prompt_audit_2026_05_12.py`. |
| Mutation program and scaffold contracts | 75 passed across mutate `test_runner.py`, `test_self_improving_minimal_1.py`, `test_self_improving_minimal_2.py`, `test_self_improving_loop_gap_fill.py`, and `test_s5_structure.py`; 36 existing legacy-configuration warnings. |
| Final router hash, behavior, workflow, skill surface, preflight | 30 passed across prompt integrity, G1 behavior, workflow scaffold, skill surface, and preflight tests. |
| Petri role bindings, evolver contract, runtime skills | 59 passed: `tests/evals/petri/test_manifest.py`, `tests/evals/seed_generation/test_evolver.py`, skill-loader tiers, and skill-surface policy. Three edited runtime skills also loaded through the real `SkillLoader`. |
| Test-count reconciliation | The expanded groups contain 229 unique cases after overlap removal. Including the initial batch's 11 organization-memory cases, 240 unique cases passed across this local patch; collection-only confirmed the union, not a second full-suite execution. |
| All-Markdown links and duplicates | 576 retained files, 1,932 parsed links, zero missing local targets or unresolved heading candidates, 31 preserved snapshot duplicate groups. External HTTP reachability was not exhaustively checked. |
| Skill validation | Initial five skills valid; nine additional edited development skills valid. The existing `scandinavian-design` `compatibility` frontmatter field is rejected by Codex's narrow validator; it was preserved rather than silently removing cross-host metadata. Runtime skills use their actual loader checks. |
| Site and generated metadata | Architecture baseline check, site-link checker (714 occurrences), Pages Markdown lint, static build/TypeScript (241 pages), and export (76 Markdown twins) passed. Package version remains 1.0.27. |
| Visual guidance grounding | `verify_hero_layout.py --help` and `--static-check` passed (168 site/language entries). No render, font measurement, or baseline update was performed. |
| Evaluation CLI grounding | `$PY -m evals.cli audit-seeds generate --help` exited 0; `pyproject.toml` maps `geode-eval` to that app. No generation was started. |
| Independent review | Scoped review of workflow/runtime instructions, operator program, root/site guidance, visual-ratchet references, and Petri roles found no remaining blocker after restoring the consumed §11.1 anchor and correcting the current seed-generation CLI entry point. |
| Patch hygiene | `git diff --check` and repository hygiene passed; root checkout remained clean. |

The preflight script is a broad local gate, not full CI parity: its scope does
not include every import/architecture/package gate. Static layout checks likewise
do not remeasure the current render. Neither is described as broader evidence.

## Integration scope

The initial batches remained local on `codex/instruction-alignment-20260907`.
The user then authorized a final omission/alignment review and CI-gated GitFlow
integration. The final review also traced obsolete evaluation CLI names from
Markdown into their user-facing help/next-step messages; those messages are
part of this correction, without changing command dispatch or evaluation logic.

Final integration checks:

- CLI regression group: 47 passed, 8 skipped because the local optional
  `inspect_ai` dependency is absent. The four files are
  `tests/evals/petri/test_cli_audit.py`, `test_eval_archive.py`,
  `test_optimize.py`, and `tests/evals/test_config_cli.py`. One new offline
  case follows the printed commands through extraction, blind labeling,
  resume, and report output. Before CI-driven corrections, local passed coverage
  was 287 unique cases;
  the eight skips are not counted as passes and require the audit-enabled CI.
- Touched-file ruff/format and mypy passed. `scripts/preflight.sh --fast`
  passed all 15 executed gates using the existing environment without sync;
  full pytest and site generation were explicitly skipped by that command.
  The site build and export were run separately after final generation.
- Import-linter kept all seven contracts; architecture exception checks and
  Pages Markdown lint passed. Generated inventory was updated after the new
  regression case. Site build/TypeScript and export passed again.
- The final independent review covered the six corrected CLI messages and
  four affected test files; no remaining P1/P2 was reported.
- The first `check_official_docs.py --skip-build` invocation reached its final
  Git-diff check and failed because the intentional generated changelog diff
  was not staged yet. After verifying and staging the intended generated diff,
  the same command passed on the candidate. The earlier failure is retained.
- The first PR head failed repository hygiene in CI because this new receipt
  included the local interpreter's absolute user-home path. The earlier local
  hygiene pass did not scan the then-untracked receipt. The path was made
  checkout-relative, and the workflow now requires staging the intended new
  files before running the tracked-file hygiene check. CI must pass again on
  the corrected head; the initial failure remains part of the evidence.
- The next full CI suite reported 8 failures, 10,808 passes, and 37 skips
  (80.74% coverage, above the unchanged 75% threshold). Seven failures pinned
  Mode A's old duplicated prose/policy list, and one pinned a line-wrapped
  deep-research sentence. Reviewing their intent also found a real omission:
  the operator guide needed the still-supported Mode B entry point.
  The guide now names the CLI and conditional slash surface. All seven docs
  tests remain, checking valid owner links, the actual mutable policy set,
  dispatcher wiring, history, baseline, and authorization; the skill test
  preserves its assertions while normalizing whitespace. Both affected modules
  passed locally (31 cases), bringing distinct local coverage to 318 passes.
  No test was disabled, no threshold reduced, and independent review found no
  weakening. The full suite must pass on the subsequent PR head before merge.

Root checkout and other sessions' worktrees were preserved during editing;
`harbor-4` remains paused. Live model calls, benchmark reruns, release/tag/package
publication, global GEODE installation, and service restart remain outside
scope. This receipt records local evidence; GitHub PRs and their exact heads own
subsequent remote CI and merge status. Full local pytest and full preflight are
not claimed by the targeted test groups above.
