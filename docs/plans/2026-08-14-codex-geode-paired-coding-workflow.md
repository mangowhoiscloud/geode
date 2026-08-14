# Codex–GEODE Paired Coding Workflow

Date: 2026-08-14
Status: VERIFIED — paired live exercise deferred
Base: `origin/develop@27f52ff06ce1957f46c63a40d3c718398f518e24`
Implementation branch: `codex/codex-geode-paired-workflow`

## 1. Decision

GEODE already contains the mechanisms needed to author and verify code, but it
does not contain a general workflow that gives the same coding brief to native
Codex and GEODE, freezes both candidates, runs identical acceptance checks,
and records a human-owned selection.

The missing layer is an instruction contract, not another runtime. This change
therefore adds one executable reference to the existing `geode-workflow`
scaffold. It does not add an orchestrator, dependency, provider, score, or
automatic promotion path.

That decision is intentionally narrow: the paired comparison workflow does
not need another runtime, but GEODE does not yet have Codex-grade native coding
runtime parity. The source history, alternative maturity perspectives,
affected scope, and cost-unconstrained modernization program are recorded in
[`Codex Runtime Evolution and GEODE Coding-Agent Modernization`](../research/2026-08-15-codex-runtime-evolution-geode-modernization.md).

Use the operational contract at
`.claude/skills/geode-workflow/references/codex-geode-paired-coding.md`.

## 2. Research Boundary

The Codex audit is pinned to official `openai/codex` commit
[`1c4f42863c1f84eb5175a1a0cfffe84641a63df3`](https://github.com/openai/codex/commit/1c4f42863c1f84eb5175a1a0cfffe84641a63df3).
Claims about current Codex behavior below refer to those source bytes, not an
ambient installation.

The GEODE audit is pinned to the base above. It covers the agent loop, tool
execution, sub-agents, Codex adapters, MCP surface, paired benchmark harness,
Crucible producer, and tracked development workflow.

No live model, account, provider, or remote code execution was used for this
audit.

## 3. Codex Coding-Agent Workflow

Codex is not a hard-coded `analyze -> edit -> test -> review` pipeline. It is a
thread/turn execution kernel whose model repeatedly selects tools. Repository
instructions and skills supply the software-development policy.

| Layer | Code-enforced behavior | Policy left to instructions |
|---|---|---|
| Session | thread start/resume/fork, one active task, turn lineage | what counts as a complete coding task |
| Context | history, AGENTS discovery, skills, permissions, environment and tool snapshot | which files should be read first |
| Loop | model response -> tool call -> result -> next sample; assistant-only response ends the turn | analyze/edit/test ordering |
| Tools | visible schema and executable handler share one router; approval and sandbox are centralized | which test command is sufficient |
| Editing | `apply_patch` grammar and current file contents are checked before dispatch | whether a proposed change is the simplest design |
| Review | dedicated review task and target selection | defect rubric and the no-fix review convention |
| Sub-agents | child Codex threads, filtered history, lineage and capacity | task independence and write-set separation |
| Delivery | app and repository skills can manage worktrees and PR watching | promotion and merge decision |

Primary source paths:

- turn lifecycle and sampling loop:
  [`turn.rs`](https://github.com/openai/codex/blob/1c4f42863c1f84eb5175a1a0cfffe84641a63df3/codex-rs/core/src/session/turn.rs#L139-L490)
- tool construction and routing:
  [`spec_plan.rs`](https://github.com/openai/codex/blob/1c4f42863c1f84eb5175a1a0cfffe84641a63df3/codex-rs/core/src/tools/spec_plan.rs#L892-L1129),
  [`router.rs`](https://github.com/openai/codex/blob/1c4f42863c1f84eb5175a1a0cfffe84641a63df3/codex-rs/core/src/tools/router.rs#L154-L289)
- approval, sandbox, and bounded retry:
  [`orchestrator.rs`](https://github.com/openai/codex/blob/1c4f42863c1f84eb5175a1a0cfffe84641a63df3/codex-rs/core/src/tools/orchestrator.rs#L135-L497)
- review task:
  [`review.rs`](https://github.com/openai/codex/blob/1c4f42863c1f84eb5175a1a0cfffe84641a63df3/codex-rs/core/src/tasks/review.rs#L97-L205)
- sub-agent spawn:
  [`spawn.rs`](https://github.com/openai/codex/blob/1c4f42863c1f84eb5175a1a0cfffe84641a63df3/codex-rs/core/src/tools/handlers/multi_agents_v2/spawn.rs#L192-L239)
- plan checklist, explicitly not an execution scheduler:
  [`plan_tool.rs`](https://github.com/openai/codex/blob/1c4f42863c1f84eb5175a1a0cfffe84641a63df3/codex-rs/protocol/src/plan_tool.rs#L6-L29)
- MCP tools `codex` and `codex-reply`:
  [`message_processor.rs`](https://github.com/openai/codex/blob/1c4f42863c1f84eb5175a1a0cfffe84641a63df3/codex-rs/mcp-server/src/message_processor.rs#L335-L367)

## 4. GEODE Codebase Audit

| Surface | Status | Finding for paired coding |
|---|---|---|
| `core/agent/loop/agent_loop.py` | Existing | Owns GEODE's `while tool_use` runtime; no cross-runtime candidate comparison |
| `core/agent/tool_executor/executor.py` | Existing | Owns write, shell, MCP and delegation dispatch plus approval; reusable as-is |
| `core/agent/subagent_roles.py` | Existing | Declares researcher, patcher, verifier and reviewer roles with output models |
| `core/agent/sub_agent.py` | Partial | Process isolation and role contracts exist, but not Git worktree isolation |
| `core/llm/adapters/codex_oauth.py` | Misfit | Codex model inside the GEODE loop; not an independent native Codex arm |
| `core/llm/adapters/codex_cli.py` | Misfit | Runs `codex exec`, but is a text adapter with no native trajectory or worktree contract |
| `core/mcp_server.py::run_agent` | Partial | Can draft file edits, but headless policy denies `run_bash` and delegation, so it cannot own identical acceptance checks |
| `plugins/benchmark_harness/run_mcpmark_pair.py` | Misfit | True paired evaluation with strong receipts, but fixed to MCPMark rather than repository coding |
| `plugins/crucible/producers/codex_kg.py` | Misfit | Codex edits one frozen candidate surface for Crucible; not a general two-runtime coding workflow |
| `docs/workflow.md` and `geode-workflow` | Partial | Production and verification exist; Codex is only a post-commit second opinion |
| generic paired implementation contract | Absent | No same-base, same-brief, same-check, candidate-freeze and selection workflow |

The historical `codex-mcp-verify` runtime skill was removed because it was
scaffold-only content in the runtime tier. A current local untracked copy is
not a source of truth and names hypothetical `exec`/`review`/`apply` aliases
that the pinned official Codex MCP server does not expose.

## 5. Affected Scope

### Changed

| Path | Effect |
|---|---|
| `docs/plans/2026-08-14-codex-geode-paired-coding-workflow.md` | Source-pinned audit, decision and execution record |
| `.claude/skills/geode-workflow/references/codex-geode-paired-coding.md` | Executable production and verification contract |
| `.claude/skills/geode-workflow/SKILL.md` | Progressive-disclosure route |
| `docs/workflow.md` | Contributor-visible summary and route |
| `tests/test_workflow_scaffold.py` | Contract ratchet for discovery and safety boundaries |

### Read-only adjacent surfaces

`AgenticLoop`, `ToolExecutor`, sub-agent execution, Codex adapters,
`geode-mcp`, MCPMark, Crucible, provider routing, prompts, and GitFlow are
evidence for the decision but receive no behavior change.

### Explicit non-goals

- no new coordinator, schema package, CLI command, or dependency
- no change to headless permissions or MCP server registration
- no automatic merge, score, or promotion authority
- no reuse of benchmark result schemas for code review
- no live Codex or GEODE model call in this documentation change
- no correction of unrelated documentation drift

## 6. Workflow Contract

The smallest comparison record is Markdown. A machine schema is deferred
until repeated runs demonstrate that manual receipts are unreliable.

Required frozen inputs:

- `contract_id` and `task_id`
- exact `base_sha` shared by both candidates
- canonical brief bytes and `brief_sha256`
- `allowed_paths` and `protected_paths`
- identical `acceptance_commands`
- live-test approval state and explicit non-goals
- per-arm runtime/version identity, worktree, branch and candidate commit

Required frozen outputs:

- actual changed paths derived from Git, not self-report
- candidate commit and diff digest
- each acceptance command, exit status and relevant result
- skipped checks and assumptions
- reviewer findings and disposition
- human decision: GEODE, Codex, fresh hybrid, or reject both

## 7. Production Workflow

1. Freeze one brief, exact base SHA, allowed/protected paths, and primary
   acceptance commands.
2. Create separately owned worktrees from that exact SHA.
3. Keep candidate contexts independent until both commits are frozen.
4. Let each runtime inspect and implement inside only its worktree.
5. Commit each candidate and derive changed paths and diff digests from Git.
6. Stop the paired claim if either candidate used another base, brief,
   worktree, or primary check set.

Normal work should continue to use one producer plus independent review. Two
writable candidates are justified only when the task explicitly requests a
comparison or a material design uncertainty remains after the GAP audit.

## 8. Verification Workflow

1. Verify candidate identity, frozen brief, base and worktree separation.
2. Compare actual changed paths against allowed and protected paths.
3. Run the same primary acceptance commands in both worktrees under an
   operator-owned runner.
4. Freeze the results before either runtime sees the other candidate.
5. Perform read-only cross-review and disposition every finding.
6. Compare correctness and invariant preservation first; then scope
   discipline, test quality, simplicity, maintainability and resource cost.
7. If combining candidates, create a fresh integration candidate and rerun
   every gate. Never splice unverified hunks into the selected branch.
8. Keep selection human-owned, then use the ordinary GEODE verification and
   GitFlow gates.

## 9. Verification Record

| Gate | Status | Evidence |
|---|---|---|
| Baseline workflow scaffold | PASS | `uv run pytest -q tests/test_workflow_scaffold.py` — 7 passed before edits |
| Targeted contract test | PASS | `uv run pytest -q tests/test_workflow_scaffold.py` — 8 passed |
| Ruff | PASS | check and format-check passed for `tests/test_workflow_scaffold.py` |
| Markdown diff check | PASS | `git diff --check` |
| Repository hygiene | PASS | `uv run python scripts/check_repo_hygiene.py` |
| Independent review | PASS | corrected the CLI-adapter boundary; final review found no P0/P1 or safe cuts |
| Live two-runtime exercise | NOT RUN | requires a separate task and explicit model-call approval |

## 10. Deferred Observation

`AGENTS.md` still names `PromptAssembler.assemble()` even though
`core/llm/prompt_assembler.py` says that class was removed. It is unrelated to
this workflow contract and should be corrected separately rather than bundled
into this change.
