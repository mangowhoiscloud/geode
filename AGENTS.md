# AGENTS.md

Shared contributor instructions for coding agents working on GEODE.
Claude Code reads this same file through `CLAUDE.md`'s `@AGENTS.md` import;
do not duplicate the contract in a host-specific entry point.

## Project at a glance

GEODE is a self-hosting autonomous-agent harness built around an AgenticLoop
(`while tool_use`). Python 3.12+, type-hinted, managed with uv.

- `core/` — runtime and operator surface; does not depend on `evals` or `evolve`.
- `evals/` — measurement and audit consumers of the runtime.
- `evolve/` — scaffold search and hill-climbing over runtime/evaluation evidence.
- `site/` — Next.js static-export public documentation.
- `docs/` — internal architecture, contracts, and contributor guidance.

Run `uv sync` for a local development environment. CLI entry points are declared
in `pyproject.toml`; do not install globally or restart a service without scope.

## Choose the instruction owner

This is a contributor navigation map, not GEODE's runtime system prompt.
Read the relevant owner, then inspect its caller and test before editing.

| Need | Owner and actual consumer |
|---|---|
| Repository changes, tests, and integration | This file → [workflow](docs/workflow.md) → `.claude/skills/geode-workflow/`; read by the coding agent, not automatically loaded by GEODE |
| Runtime identity and conduct | Four selected `GEODE.md` sections → `core/agent/system_prompt.py`; persona-off and audit modes omit identity |
| Shared completion and failure behavior | `core/llm/prompts/router.md` agentic suffix → prompt composition, including identity overrides; hashes in `core/llm/prompts/__init__.py` |
| Task-specific runtime guidance | `.geode/skills/` → `use_skill`; `.agents/skills/` is the separate development scaffold |

`CLAUDE.md` is Claude Code project context, not a replacement for its system
prompt or an enforcement mechanism. Actual permission checks, hooks, and
sandboxing remain separate. The shared-file pattern follows the
[official Claude Code import guidance](https://code.claude.com/docs/en/memory#agentsmd).

### Task-to-source routing

| Task | Read first |
|---|---|
| Ordinary development | [Evidence-first workflow](docs/workflow.md) and `.agents/skills/geode-workflow/` |
| Branches, PRs, merge, cleanup | `.agents/skills/geode-gitflow/`; `.github/PULL_REQUEST_TEMPLATE.md` |
| Codebase audit, deduplication, or pruning | `.agents/skills/codebase-audit/`; trace consumers and surviving behavior before deletion |
| Abstraction, naming, types, schemas, tests, compatibility | [Naming conventions](docs/architecture/naming-conventions.md) and `.agents/skills/geode-code-conventions/` |
| Public hooks, middleware, runtime events | [Hook contracts](docs/architecture/hook-system.md) and `.agents/skills/geode-code-conventions/`; distinguish decisions, trusted transforms, and observation |
| Architecture/extensibility program | [Extensibility roadmap](docs/architecture/extensibility-roadmap.md), the single execution SOT for GAP IDs, order, status, acceptance, and closure evidence |
| Package ownership | [Package classification](docs/architecture/package-classification.md) |
| Coding-agent state, recovery, workspace/process limits | [Coding runtime authority](docs/architecture/coding-runtime-authority.md) before adding a record or store |
| Model/provider support, OAuth, capabilities | `core/llm/model_catalog.py`, provider/adapters call path, and `.agents/skills/model-onboarding/` |
| Prompt text or assembly | `.agents/skills/prompt-writing/`, `core/agent/system_prompt.py`, and loop context assembly |
| Usage/cache/cost and artifact accounting | [Usage accounting](docs/architecture/usage-accounting.md) and the workflow observability reference |
| Benchmark execution, attempts, publication | Generated `docs/eval/index.json` and `.agents/skills/geode-eval/` |
| Agent-World comparisons | [Comparison contract](docs/eval/agent-world-comparison-contract.md) and `.agents/skills/agent-world-benchmark/`; do not label its undisclosed wrapper `no loop` |
| Test-time compute / best-of-N / verifier scheduling | `.agents/skills/stanford-test-time-compute/`; separate candidate width, repair depth, measurement replication, and promotion authority |
| `/geo` or `/grill` | `.agents/skills/geo/` or `.agents/skills/grilling/`; runtime behavior stays in the corresponding `.geode/skills/` contract |
| Public docs, generated maps, visual design | [Official docs generation](docs/architecture/official-docs-generation.md), `site/DESIGN.md`, and `site/src/app/docs/` |
| Release and packaging | `.agents/skills/geode-changelog/`, `.agents/skills/geode-distribution/`, and GitFlow's release path |

Other task-specific development skills are indexed in
[the scaffold catalog](docs/scaffold-skills.md). `.claude/skills/` uses relative
per-skill aliases to `.agents/skills/`, so both hosts read the same bytes.
A same-named development skill links to its runtime contract instead of copying it.

## Module map

Inspect the changed module, its callers, and mirrored tests. Cross-cutting work
must trace every affected boundary; this table is routing, not an API census.

| Area | Entry and responsibility |
|---|---|
| `core/agent/` | `loop/agent_loop.py` drives turns; `loop/models.py` owns termination reasons; `system_prompt.py` assembles static/dynamic context; `sub_agent.py` manages child execution |
| `core/llm/` | `adapters/` owns async SDK clients; `providers/` owns provider shaping/auth helpers; `fallback.py` and loop/router callers own application retry policy |
| Prompt content | `prompts/router.md` and opt-in `prompts/reviewer.md` are hash-pinned; `prompt_assembler.py` is only the math-output helper, not a second system assembler |
| `core/tools/` | Handler in its category module → `registry.py` registration → `definitions.json` schema; deferred loading is adapter-owned (`core/llm/tool_defer.py`) |
| `core/mcp/` | `manager.py` delegates config, connections, invocation/trace, and lifecycle to concrete owners; client tools use raw server names, not external-host `mcp__geode__*` names |
| `core/memory/` | `context.py` assembles Identity/Profile/Org/Project/Session; `goals.py` owns explicit persistent objectives, not advisory Plan or automatic Plan-and-Execute |
| `core/hooks/` | `public.py` owns bounded hook decisions; `middleware.py` owns trusted transforms/execution wrappers; `system.py` owns runtime observation; trace registration through bootstrap |
| `core/wiring/` | Bootstrap, explicit service injection, serve, shutdown, and request-local binding/reset |
| `core/server/` | CLI↔daemon IPC, capability negotiation, and lifecycle |
| `core/skills/` | `skills.py`: bundled → global-user → project discovery; `use_skill` loads a selected body on demand, not trigger-based automatic injection |
| `core/cli/`, `core/gateway/` | Typer/slash operator surface; messaging adapters and lane queues |
| `core/scheduler/`, `core/orchestration/` | Scheduling and TaskGraph; do not infer either from a conversational plan |
| `core/audit/` | Per-call diagnostics; preserve usage coverage and audit-mode boundaries |
| `evals/petri/` | `cli_audit.py` → runner/audit mode/judge schema; seeds and judge dimensions own their evaluation contracts |

<!-- generated:architecture-baseline:start -->
The generated architecture inventory lives at
`site/src/data/geode/architecture-baseline.json`. Refresh it with
`uv run python scripts/architecture_baseline.py --update`; CI uses `--check`.
The current snapshot records 600 production Python files,
763 test Python files,
86 tool definitions, and
57 `RuntimeEvent` members.
<!-- generated:architecture-baseline:end -->

The inventory owns file/tool/event counts, not executable test-case totals.
Use `uv run pytest --collect-only` for the latter. Public release metadata in
`site/src/data/geode/sot.ts` is generated by `npm run sync-stats` and owns only
the package version and sync date.

## Working contract

These are repository rules. Detailed procedures live with their owners above;
do not turn an incident-specific fix into an unconditional rule for every task.

1. **Scope and inspect.** Check `git status --short --branch`, ownership, and
   actual call paths. Review/status requests stay read-only. For implementation,
   classify existing/partial/absent behavior and state the smallest measurable
   plan. Simple fixes need no separate planning document. Resolve ambiguous
   deletion scope before deleting; preserve unrelated dirty work.
2. **Isolate.** Fetch before allocating from the authorized remote base. Never
   commit on `main`/`develop`, switch branches inside a worktree, or remove
   another session's worktree/branch. Preserve mismatched `.owner` markers.
   Implementation and ordinary roadmap work start from `origin/develop`;
   main-maintained tracking work uses `origin/main`. The roadmap's §0.3 owns
   its narrow readiness/claim/GAP/reconciliation/full-ledger exceptions.
   Independent writes start after `check_repo_hygiene.py assert-write-workspace`
   passes; delegates return the workflow's [handoff contract](docs/workflow.md#execution-scope);
   CI recovery stops at GitFlow's [budget](.agents/skills/geode-gitflow/SKILL.md#post-pr-ci-ratchet)
   and hands off.
3. **Implement at the owner.** Reuse existing registries and helpers. Trace
   producer → field/state → reader → decision, including explicit/automatic
   input branches and refresh/invalidation. Process services cross constructors,
   grouped config, or `ToolContext`; reserve `ContextVar` for request-local
   identity, diagnostics, state, and caches. See the workflow's
   [contract checks](docs/workflow.md#contract-checks) for boundary verification.
4. **Preserve prompt boundaries.** `GEODE.md` is the runtime SOUL surface, not
   a contributor rulebook. Use the prompt-writing skill for authored text;
   GEODE's local style is English metadata/behavioral clauses rather than
   `You are ...`/`Act as ...`. This is not a vendor requirement or permission
   to translate user content. Prompt-file edits update `_PINNED_HASHES` in the
   same commit and test the relevant identity/override/audit modes.
5. **Verify honestly.** Run narrow checks first, broaden for changed risk or
   failures. Use the [verification gates](.agents/skills/geode-workflow/references/verification-gates.md)
   for ruff, mypy, pytest, prompt integrity, and independent review. Do not hide
   non-zero exits behind pipes/chaining, disable tests to manufacture green,
   add blanket type ignores, or report stubs/partial work as complete.
   Unknown measurements are not zero; latest evidence is not promoted evidence.
6. **Ground external claims.** Verify SDK/backend/model capabilities against
   primary docs/source. Unsupported or ambiguous acceptance stays guarded;
   live tests, paid calls, publication, global installs, and service changes
   require authorization. An explicit persistent objective is required before
   creating a goal; ordinary research remains bounded.
7. **Synchronize docs.** Functional commits update `[Unreleased]` in
   `CHANGELOG.md`. Update affected code-to-doc mappings, public behavior docs,
   and generated mirrors through their owner commands. Do not hand-maintain
   parallel metrics or bump a version without an authorized release.
8. **Integrate through GitFlow.** No direct push to protected branches.
   Feature → develop and develop → main both use merge commits. Incorporate
   missing main history into the feature branch before its CI and merge; never
   open a standalone main → develop sync PR. Never squash/rebase PRs; follow GitFlow's
   [Don't cases](.agents/skills/geode-gitflow/SKILL.md#dont-cases).
   Verify content with `git diff A B --stat`,
   not commit counts alone. `scripts/merge_pr.py` rechecks main ancestry, exact PR-head
   required CI, and trust before merge. Missing/stale checks never prove green;
   local success is not remote CI success.
9. **Clean up with proof.** After an owned feature PR merges, run
   `scripts/check_repo_hygiene.py free-merged-worktree` from outside that
   checkout. Follow GitFlow's owner/cleanliness/merge-proof checks; never
   force-delete an unverified worktree. Merge does not authorize release.

## Source discipline

The navigation pattern borrows from the pinned
[Dioxus agent guide](https://github.com/DioxusLabs/dioxus/blob/ada3b67c73c1c5484dd2e8408cb21c470b200423/AGENTS.md):
route to the owner, then verify fields, calls, failure branches, and tests in
current code. Numbered architecture documents are topics, not execution order.
Older audits and dated plans are evidence, not competing status ledgers.

For frontier comparisons, use `.agents/skills/frontier-harness-research/` and
the [cited source inventory](site/src/app/docs/reference/external-references).
Pin the native task, prompt, workspace, verifier, and result authority before
claiming benchmark or harness equivalence. Do not substitute a scoped test,
replay, or successful tool call for verifier-backed task completion.
