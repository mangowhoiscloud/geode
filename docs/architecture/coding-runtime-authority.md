# Coding Runtime Authority Contract

> Current architecture contract for coding-agent state ownership. Audited
> against `origin/develop@32ca5cb678828c0520a826397bf1cf2a5373cd02`.
> This contract introduces no runtime type, store, hook, or migration.

The prospective shapes considered here come from the
[`Codex runtime evolution research`](../research/2026-08-15-codex-runtime-evolution-geode-modernization.md);
this document decides ownership and registration boundaries, not a class list.

## Decision

GEODE does not have, and does not need, one universal coding-task record.
Coding work crosses several domains whose existing authorities have different
lifetimes and failure semantics. A new aggregate would duplicate those
authorities and make recovery ambiguous.

The fixed rules are:

1. [`SessionCheckpoint`](../../core/memory/session_checkpoint.py) and its
   SQLite messages are conversation-recovery authority. JSON messages are a
   compatibility fallback; [`SessionTimeline`](../../core/observability/session_timeline.py)
   is append-only execution history and is never replayed as active state.
2. [`GoalStore`](../../core/memory/goals.py),
   [`SchedulerService`](../../core/scheduler/service.py),
   [`CollaborationStore`](../../core/memory/collaboration.py), and evaluation
   or promotion artifacts remain their domain sources of truth.
3. [`TaskGraph`](../../core/orchestration/task_system.py) and advisory
   [`Plan`](../../core/agent/plan.py) do not become a durable universal task
   ledger. Only the advisory Plan is part of the checkpoint guard snapshot.
4. Files, git, and processes are external state. A checkpoint does not claim
   to roll them back, reattach them, or prove their base revision.
5. Tool policy, approval, persistence, and redaction remain owned by the
   immutable ToolPlan and its runtime consumers. This contract adds no policy
   plane or review hook.

## Live source-and-test census

| Surface | Current writers and readers | Lifecycle and persistence | Recovery owner | Executable evidence |
|---|---|---|---|---|
| Coding task | [`task_preflight.py`](../../core/agent/task_preflight.py) derives routing hints; [`tool_handlers/task.py`](../../core/cli/tool_handlers/task.py) mutates the process-local [`TaskGraph`](../../core/orchestration/task_system.py); [`Plan`](../../core/agent/plan.py) is advisory loop intent | TaskGraph is context-local and in-memory; Plan is immutable and serialized in checkpoint `loop_guards` | Plan restores through the checkpoint; TaskGraph has no crash-recovery promise | [`test_tool_handlers_task.py`](../../tests/core/cli/test_tool_handlers_task.py), [`test_task_system.py`](../../tests/core/orchestration/test_task_system.py) |
| Session and turn | [`StepSnapshot`](../../core/agent/loop/models.py) freezes per-step inputs; `TurnState` owns one physical turn; lifecycle code writes messages, cognitive state, and loop guards | SQLite messages plus `state.json` commit marker; JSON message cache is migration compatibility | [`SessionCheckpoint`](../../core/memory/session_checkpoint.py) through the single loop restore path | [`test_session_checkpoint.py`](../../tests/core/memory/test_session_checkpoint.py), [`test_loop_state_machine.py`](../../tests/core/agent/test_loop_state_machine.py) |
| Workspace | [`get_project_root()`](../../core/paths.py) freezes the resolved first project root; file and bash tools mutate the selected filesystem/worktree | Filesystem and git state outlive the process; no durable `ExecutionWorkspace` record exists | Git, filesystem, and operator workflow; not SessionCheckpoint | [`test_file_tools.py`](../../tests/core/tools/test_file_tools.py), [`test_bash_tool.py`](../../tests/core/tools/test_bash_tool.py), [`test_bash_sandbox.py`](../../tests/core/tools/test_bash_sandbox.py) |
| Process | [`BashTool`](../../core/tools/bash_tool.py) owns one subprocess/process group; isolated execution owns worker process launch and teardown | One-shot process lifetime; timeout and cancellation terminate the tree; no PTY/reconnect session is persisted | No reattach. A failed invocation is recorded and a later invocation starts a new process | [`test_bash_tool.py`](../../tests/core/tools/test_bash_tool.py), [`test_isolated_execution.py`](../../tests/core/orchestration/test_isolated_execution.py), [`test_isolated_subprocess.py`](../../tests/core/orchestration/test_isolated_subprocess.py) |
| Mutation and diff | File tools and approved bash commands write external state; ToolExecutor applies policy, approval, and resource serialization before dispatch | Mutations may survive a failed turn; no turn-wide `ChangeSet` or preimage store exists | Git/filesystem/operator recovery; checkpoints recover conversation only | [`test_file_tools.py`](../../tests/core/tools/test_file_tools.py), [`test_tool_plan_runtime_policy.py`](../../tests/core/agent/test_tool_plan_runtime_policy.py) |
| Review | Reviewer sub-agent schemas produce `ReviewFinding`; [`VerifyResult`](../../core/agent/verify.py), public post-verify hooks, privacy review, and evaluation/promotion each own their result | Result lifetime follows its owning turn, event, or evaluation artifact; no generic review ledger | The owning checkpoint, hook event, or evaluation artifact; never a synthetic common review store | [`test_subagent_roles.py`](../../tests/core/agent/test_subagent_roles.py), [`test_verify.py`](../../tests/core/agent/test_verify.py) |
| Instructions and context | [`system_prompt.py`](../../core/agent/system_prompt.py), [`ContextAssembler`](../../core/memory/context.py), [`SkillLoader`](../../core/skills/skills.py), `AGENTS.md`, `GEODE.md`, and project files assemble current context | Inputs are read from their current stores; prompt hash may be checkpointed, but the full instruction set and repository base are not | Reassembly from current sources; no frozen instruction snapshot guarantee | prompt hash ratchet, [`test_context_assembler.py`](../../tests/core/memory/test_context_assembler.py), [`test_skill_loader_tiers.py`](../../tests/core/skills/test_skill_loader_tiers.py), checkpoint restore tests |
| Cross-domain task lookup | GoalStore, CollaborationStore, SchedulerService, local TaskGraph, and evaluation/promotion artifacts each write their domain records | Domain-specific SQLite, JSON/JSONL, or process-local state; no cross-domain writer | Each domain owner independently | [`test_goals.py`](../../tests/core/memory/test_goals.py), [`test_collaboration.py`](../../tests/core/memory/test_collaboration.py), [`test_scheduler.py`](../../tests/core/scheduler/test_scheduler.py), [`test_eval_contract.py`](../../tests/scripts/test_eval_contract.py) |

## Authority matrix

`None` below is an intentional contract, not an unimplemented recovery path.

| Surface | Durability | Recovery | Migration | Compatibility | Redaction | Failure | Rollback |
|---|---|---|---|---|---|---|---|
| Coding task | Plan only through checkpoint; TaskGraph none | Restore Plan; rebuild TaskGraph if needed | No TaskGraph persistence migration | Task handlers keep current process-local behavior | Tool inputs/results follow ToolPlan and durable sink rules | Lost TaskGraph is visible as absent local state | No automatic task-side-effect rollback |
| Session/turn | SQLite messages plus checkpoint state | Single `restore_from_checkpoint` path | JSON message cache is fallback-only debt | Legacy checkpoint fields load with defaults | Durable stores use their existing bounded/redacted projections | Corrupt or unknown status fails closed as ERROR | Reopen is explicit; external effects are untouched |
| Workspace | Filesystem/git | Operator or git recovery | None until a reproducible-resume consumer exists | Current project-root and sandbox rules remain | Secrets/personal data are governed before durable observation, not by workspace snapshotting | Drift and partial writes remain observable external state | Git/filesystem operation only |
| Process | None beyond result/event records | Start a new invocation | None until reconnectable process demand exists | One-shot bash and isolated worker contracts remain | Durable result/event projections apply existing redaction | Timeout/cancel terminates the owned process tree | No process reattach or side-effect rollback |
| Mutation/diff | External target plus existing event/result records | Inspect target and retry deliberately | None until a review or rollback consumer exists | Existing file/bash semantics remain | ToolPlan policy and durable sinks own redaction | Partial mutation is possible and must not be disguised as checkpoint rollback | Git/filesystem/operator only |
| Review | Owning turn, hook event, or evaluation artifact | Restore/recompute through that owner | No generic review migration | Existing reviewer, verifier, privacy, and promotion APIs remain separate | Each owner persists only its bounded/redacted projection | Missing review is visible to its caller; it does not silently become approval | Owner-specific only |
| Instructions/context | Current source files; selected hashes/metadata only | Reassemble current context | None until base-drift reproduction is required | Current prompt/context/skill readers remain | Context and prompt durable projections use existing scrubbers | Changed sources can produce a different resumed context | Revert source/config; checkpoint does not restore them |
| Cross-domain lookup | Domain stores only | Domain owner | A future index may migrate reads, never domain writes | Existing Goal/scheduler/collaboration/evaluation keys stay stable | Domain projection rules apply before indexing | A partial index must report staleness and never fabricate source state | Rebuild the derived index from domain sources |

## Contract overlap dispositions

| Existing contract | Disposition | Boundary |
|---|---|---|
| LOOP / session and step lifetime | **Reuse** | StepSnapshot, TurnState, checkpoint guards, and the session state machine already own loop lifetime. A coding wrapper must not shadow them. |
| PROTO / public events | **Extend after dependency** | Add an event only when a registered consumer needs a new public lifecycle fact. Do not create coding-specific aliases for existing session/tool/verify events. |
| CAP / ToolPlan | **Reuse** | Tool availability, executable binding, provider projection, generation/hash, and diagnostics remain ToolPlan-owned. |
| TRUST / policy and approval | **Reuse** | Safety metadata, resource keys, redaction, and approval decisions remain the existing minimum-policy authority. |
| HOOK / observation | **Reuse** | Existing hook events and persistence are observation surfaces, not active coding state or recovery. |
| STORE / persistence | **Extend after dependency** | A new coding record requires a registered writer, reader, migration, retention, and recovery contract; otherwise use the owning domain store. |
| COLLAB / worker ownership | **Reuse** | CollaborationStore owns mutable worker/task projections and append-only events/messages own rollout history. |
| GOAL / persistent objective | **Reuse** | GoalStore owns explicit multi-turn objectives. A coding task must not become an implicit Goal. |
| Memory and context | **Reuse** | SessionCheckpoint, ContextAssembler, project memory, and vault keep their present boundaries. A universal world-state snapshot is rejected. |

## Prospective records

The modernization research named useful shapes, not pre-approved modules. Their
dispositions are fixed here:

| Candidate | Disposition |
|---|---|
| `CodingTask` | **Separate measured GAP** only when a root-steer or multi-client consumer cannot be served by Goal, collaboration, or local TaskGraph identifiers |
| Thread / Turn records | **Reuse** existing session identity, TurnState, and StepSnapshot |
| `ExecutionWorkspace` / `InstructionSnapshot` | **Separate measured GAP** only when reproducible resume must detect a repository-base or instruction drift |
| Generic `WorldState` | **Reject**; use bounded projections from the actual owners |
| `PermissionDecision` | **Reuse** ToolPlan safety, approval workflow, and trust contracts |
| `ProcessSession` | **Separate measured GAP** only when a real PTY/write/poll/reconnect consumer exists |
| `ChangeSet` | **Separate measured GAP** only when a review, drift, or rollback consumer requires preimages and an atomic boundary |
| `ReviewFinding` protocol | **Reuse** the reviewer role until an independent typed client requires a public protocol |
| Universal task lookup | **Derived read model only**; it may index domain identifiers but never write their state |

## Deferred registration candidates

A candidate below is not implementation authority. It becomes eligible only
through its own roadmap registration transaction after the trigger is observed.

| Candidate | Current consumer or failure | Exact affected path | Measurable exit | Independently mergeable boundary |
|---|---|---|---|---|
| Durable coding-task identity | Root steer or two clients cannot correlate one coding operation through existing Goal/collaboration/session IDs | `core/agent/task_preflight.py`, `core/orchestration/task_system.py`, caller protocol | One stable identifier joins those callers without copying their mutable state; crash/reopen tests prove ownership | Record/projection plus migration and caller tests; no tool/provider change |
| Workspace/instruction snapshot | A resumed coding session must detect repository-base or instruction drift before mutation | `core/paths.py`, `core/agent/system_prompt.py`, `core/memory/context.py`, checkpoint schema | Resume reports exact base/instruction mismatch and a deterministic operator choice; no silent recomputation claim | Snapshot metadata and restore validation; no filesystem rollback |
| Reconnectable process session | A shipped client needs PTY input, polling, or reconnect after request return | `core/tools/bash_tool.py`, `core/orchestration/isolated_execution.py` | Lifecycle tests cover spawn/write/poll/terminate/reconnect and owner death without orphaning | Process service and protocol only; no general task ledger |
| Turn-wide ChangeSet | A concrete reviewer or rollback operation needs exact preimages across file and bash mutations | `core/tools/file_tools.py`, `core/tools/bash_tool.py`, ToolExecutor dispatch | Tests detect base drift, partial application, review projection, and bounded rollback for declared targets | Change capture and one consumer; no universal workspace state |
| Typed review protocol | A non-sub-agent client must consume findings independently of VerifyResult or evaluation | `core/agent/subagent_roles.py`, `core/agent/verify.py`, hook catalog | Schema/version tests prove one writer and one external reader without duplicating approval or promotion | Protocol plus adapter; existing verifier/evaluation stores unchanged |
| Cross-domain lookup | An operator query must join Goal, collaboration, scheduler, local tasks, and evaluation identifiers | `core/memory/goals.py`, `core/memory/collaboration.py`, `core/scheduler/service.py`, evaluation index | Rebuildable index reports source/version/staleness; domain mutation through it is impossible | Read-only projection and rebuild test |
| Verify-state mirror cleanup | The SessionManager verify columns remain write-only while checkpoint guards own restore | `core/agent/loop/_lifecycle.py::_persist_verify_state`, `core/memory/session_manager.py::get_verify_state` | Production writes and accessor are removed or demoted; legacy schema loads without becoming recovery authority | Cleanup plus compatibility test; no new schema |
| Replan/verification provenance | A reproduced failure shows ambiguous one-shot replan ownership, duplicate failure prompt ownership, missing effective-mode provenance, or missing session/turn/generation correlation | `core/agent/loop/_lifecycle.py`, `core/agent/verify.py`, cognitive/verify payload writers | One named consumer and one failure test define the missing field or owner; no parallel verifier state | One narrow record/event change after its owning dependency |

## Failure-mode acceptance

| Failure mode | Observable contract | Existing or required test |
|---|---|---|
| Crash | Messages and loop guards recover from the last committed checkpoint; TaskGraph, process, and uncommitted external mutations do not masquerade as recovered | checkpoint crash/restore and corrupt-status tests |
| Race | SessionLane and ToolPlan resource locks protect only their documented scopes; a wider lifetime needs a separately registered lease | session lane, shared resource-pool, and collaboration concurrency tests |
| Partial mutation | File/bash failure reports the failure while leaving external state inspectable; no checkpoint rollback claim | file-tool failure and bash timeout/cancel tests |
| Drift | Current resume recomputes workspace/instructions. A future drift contract must compare stored base metadata and fail visibly before mutation | prospective workspace/instruction snapshot test |
| Redaction | Personal/secret tool material is omitted from durable hooks, timelines, checkpoints, logs, and recovery attempts while the active call may use it | ToolPlan runtime-policy and durable redaction tests |
| Rollback | Session reopen restores conversation state only. Files, git, processes, Goal, scheduler, collaboration, and evaluation use their own rollback or repair path | session reopen plus domain-specific recovery tests |
| Process timeout/cancel | The owned process tree terminates or the result records loss; it is never presented as reconnectable | bash and isolated-subprocess tests |
| Review disagreement | Reviewer, verifier, privacy review, and promotion report through their own result contracts; no implicit approval is synthesized | reviewer-role, verify, and evaluation tests |

## Anti-deception checks

Closure of CODE-001 requires all of the following to remain true:

- no production Python file, database schema, public event, prompt, or runtime
  configuration changes with this contract;
- every link above resolves and every named test path exists;
- architecture-roadmap validation passes without changing CODE-001's exit
  condition or another package's claim;
- the active R8.3 publication clock remains untouched;
- any later runtime proposal starts with one of the measured triggers above,
  not with a speculative aggregate type.
