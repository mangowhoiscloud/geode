from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace
from typing import Any

import pytest
from core.agent.conversation import ConversationContext
from core.agent.loop._sub_agent_announce import check_announced_results
from core.agent.loop.agent_loop import AgenticLoop
from core.agent.sub_agent import SubAgentManager, SubTask
from core.agent.tool_executor import ToolExecutor
from core.agent.worker import WorkerRequest, _load_worker_resume, _run_agentic
from core.hooks import HookName, HookRegistry
from core.llm.agentic_response import AgenticResponse, ResponseUsage, TextBlock, ToolUseBlock
from core.memory.collaboration import CollaborationStore
from core.memory.session_checkpoint import SessionCheckpoint, SessionState
from core.orchestration.isolated_execution import IsolatedRunner, IsolationResult
from core.tools.base import ToolContext


class _ControlledRunner(IsolatedRunner):
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.cancelled = False

    async def arun(self, *_args: Any, **_kwargs: Any) -> IsolationResult:
        self.started.set()
        await self.release.wait()
        if self.cancelled:
            return IsolationResult(session_id="child", success=False, error="killed")
        return IsolationResult(
            session_id="child",
            success=True,
            output=json.dumps({"summary": "finished"}),
        )

    def cancel(self, _session_id: str) -> bool:
        self.cancelled = True
        self.release.set()
        return True


class _ProductionWorkerRunner(IsolatedRunner):
    """Run the real worker lifecycle in-process with a test-only tool allowlist."""

    async def arun(self, request: WorkerRequest, **_kwargs: Any) -> IsolationResult:
        result = await asyncio.to_thread(
            _run_agentic,
            replace(
                request,
                agent_allowed_tools=["commit_effect"],
                emit_activity=False,
            ),
        )
        return IsolationResult(
            session_id=result.task_id,
            success=result.success,
            output=result.output,
            summary=result.summary,
            error=result.error,
            duration_ms=result.duration_ms,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            usd_spent=result.usd_spent,
        )


def test_background_collaboration_rejects_uncancellable_thread_workers(tmp_path) -> None:
    manager = SubAgentManager(
        _ControlledRunner(),
        collaboration_store=CollaborationStore(tmp_path / "sessions.db"),
    )
    with pytest.raises(ValueError, match="agentic subprocess"):
        asyncio.run(
            manager.aspawn(
                [SubTask("child-thread", "inspect", "analyze")],
                parent_session_id="parent-1",
            )
        )


def test_background_child_mailbox_wait_and_completion(tmp_path) -> None:
    async def scenario() -> None:
        runner = _ControlledRunner()
        store = CollaborationStore(tmp_path / "sessions.db")
        manager = SubAgentManager(runner, action_handlers={}, collaboration_store=store)
        runs = await manager.aspawn(
            [SubTask("child-1", "inspect", "analyze")],
            parent_session_id="parent-1",
        )
        assert runs[0].status == "pending"
        await runner.started.wait()

        waiting = await manager.wait_for_task("parent-1", "child-1", timeout_s=0)
        assert waiting is not None and waiting.status == "running"
        manager.send_task_message("parent-1", "child-1", "check the tests")
        assert store.drain_mailbox("child-1")[0].payload["message"] == "check the tests"

        runner.release.set()
        completed = await manager.wait_for_task("parent-1", "child-1", timeout_s=1)
        assert completed is not None
        assert completed.status == "completed"
        assert completed.summary == "finished"
        assert store.drain_mailbox("parent-1")[0].payload["status"] == "completed"
        with pytest.raises(ValueError, match="not running"):
            manager.send_task_message("parent-1", "child-1", "too late")

    asyncio.run(scenario())


def test_interrupt_and_resume_generation(tmp_path) -> None:
    async def scenario() -> None:
        runner = _ControlledRunner()
        store = CollaborationStore(tmp_path / "sessions.db")
        stopped: list[dict[str, Any]] = []
        registry = HookRegistry()
        registry.register(HookName.SUBAGENT_STOP, lambda event: stopped.append(dict(event.payload)))
        manager = SubAgentManager(
            runner,
            action_handlers={},
            collaboration_store=store,
            hook_registry=registry,
        )
        await manager.aspawn(
            [SubTask("child-2", "inspect", "analyze", role="reviewer")],
            parent_session_id="parent-1",
        )
        await runner.started.wait()
        assert manager.interrupt_task("parent-1", "child-2")
        interrupted = await manager.wait_for_task("parent-1", "child-2", timeout_s=1)
        assert interrupted is not None and interrupted.status == "interrupted"
        assert [event["status"] for event in stopped] == ["interrupted"]

        from core.agent import sub_agent

        sub_agent._background_interrupting.add("child-2")
        runner.started = asyncio.Event()
        runner.release = asyncio.Event()
        runner.cancelled = False
        resumed = await manager.aresume(
            "parent-1",
            "child-2",
            prompt="address the finding",
        )
        assert resumed.generation == 2
        await runner.started.wait()
        runner.release.set()
        terminal = await manager.wait_for_task("parent-1", "child-2", timeout_s=1)
        assert terminal is not None and terminal.status == "completed"
        assert [event["status"] for event in stopped] == ["interrupted", "completed"]

    asyncio.run(scenario())


def test_wait_polls_durable_state_without_a_local_control(tmp_path) -> None:
    async def scenario() -> None:
        store = CollaborationStore(tmp_path / "sessions.db")
        store.begin_run(
            task_id="child-remote",
            parent_session_id="parent-1",
            task_type="analyze",
        )
        assert store.mark_running("parent-1", "child-remote", 1)
        manager = SubAgentManager(
            _ControlledRunner(),
            action_handlers={},
            collaboration_store=store,
        )

        async def finish() -> None:
            await asyncio.sleep(0.01)
            store.finish_run(
                parent_session_id="parent-1",
                task_id="child-remote",
                generation=1,
                status="completed",
            )

        finisher = asyncio.create_task(finish())
        run = await manager.wait_for_task("parent-1", "child-remote", timeout_s=1)
        await finisher
        assert run is not None and run.status == "completed"

    asyncio.run(scenario())


def test_worker_request_marks_resume_without_changing_fresh_default(tmp_path) -> None:
    manager = SubAgentManager(
        _ControlledRunner(),
        action_handlers={},
        collaboration_store=CollaborationStore(tmp_path / "sessions.db"),
    )
    task = SubTask("child-3", "continue", "analyze")
    assert manager._build_worker_request(task).resume is False
    assert manager._build_worker_request(task, resume=True).resume is True


def test_worker_resume_loads_existing_child_messages(tmp_path, monkeypatch) -> None:
    from core.memory import session_checkpoint

    monkeypatch.setattr(session_checkpoint, "DEFAULT_SESSION_DIR", tmp_path)
    SessionCheckpoint(tmp_path).save(
        SessionState(
            session_id="child-4",
            messages=[{"role": "user", "content": "original task"}],
            cognitive_state={"goal": "original task"},
        )
    )
    conversation = ConversationContext(max_turns=200)
    state, checkpoint = _load_worker_resume(
        WorkerRequest(task_id="child-4", resume=True),
        conversation,
    )
    assert state.session_id == "child-4"
    assert conversation.messages[0]["role"] == "user"
    assert conversation.messages[0]["content"] == "original task"
    assert checkpoint.session_dir == tmp_path


def test_agent_loop_boundary_drains_durable_mailbox(tmp_path, monkeypatch) -> None:
    from core import paths

    monkeypatch.setattr(paths, "resolve_sessions_dir", lambda: tmp_path)
    store = CollaborationStore(tmp_path / "sessions.db")
    store.append_message(
        sender_session_id="parent-1",
        recipient_session_id="child-5",
        kind="message",
        payload={"message": "use the failing assertion", "generation": 1},
    )
    loop = SimpleNamespace(
        _parent_session_key="",
        _session_id="child-5",
        _session_generation=1,
        context=ConversationContext(),
    )
    provider_messages: list[dict[str, Any]] = []
    assert check_announced_results(loop, provider_messages) == 1
    assert "Parent follow-up" in provider_messages[0]["content"]
    assert check_announced_results(loop, provider_messages) == 0


def test_agent_loop_boundary_discards_mail_from_prior_generation(tmp_path, monkeypatch) -> None:
    from core import paths

    monkeypatch.setattr(paths, "resolve_sessions_dir", lambda: tmp_path)
    store = CollaborationStore(tmp_path / "sessions.db")
    for index in range(51):
        store.append_message(
            sender_session_id="parent-1",
            recipient_session_id="child-5",
            kind="message",
            payload={"message": f"old {index}", "generation": 1},
        )
    store.append_message(
        sender_session_id="parent-1",
        recipient_session_id="child-5",
        kind="message",
        payload={"message": "generation 2", "generation": 2},
    )
    loop = SimpleNamespace(
        _parent_session_key="",
        _session_id="child-5",
        _session_generation=2,
        context=ConversationContext(),
    )
    provider_messages: list[dict[str, Any]] = []

    assert check_announced_results(loop, provider_messages) == 1
    assert "generation 2" in provider_messages[0]["content"]


def test_tool_surface_dispatches_and_controls_background_child(tmp_path) -> None:
    async def scenario() -> None:
        runner = _ControlledRunner()
        store = CollaborationStore(tmp_path / "sessions.db")
        manager = SubAgentManager(runner, action_handlers={}, collaboration_store=store)
        executor = ToolExecutor(sub_agent_manager=manager, auto_approve=True, hitl_level=0)
        context = ToolContext(session_id="parent-tool", model="gpt-test")
        dispatched = await executor.aexecute(
            "delegate_task",
            {"task_description": "inspect", "background": True},
            context=context,
        )
        assert dispatched["status"] == "dispatched"
        assert "owner_id" not in dispatched["tasks"][0]
        task_id = dispatched["tasks"][0]["task_id"]
        await runner.started.wait()

        listed = await executor.aexecute("manage_subagents", {"action": "list"}, context=context)
        assert listed["tasks"][0]["task_id"] == task_id
        sent = await executor.aexecute(
            "manage_subagents",
            {"action": "send_message", "task_id": task_id, "message": "focus on tests"},
            context=context,
        )
        assert sent["turn_triggered"] is False
        assert store.drain_mailbox(task_id)[0].payload["message"] == "focus on tests"
        followed = await executor.aexecute(
            "manage_subagents",
            {"action": "follow_up", "task_id": task_id, "message": "also inspect types"},
            context=context,
        )
        assert followed["resumed"] is False
        assert followed["turn_triggered"] is False
        runner.release.set()
        await manager.wait_for_task("parent-tool", task_id, timeout_s=1)

    asyncio.run(scenario())


def test_collaboration_e2e_characterizes_depth_and_resume_side_effects(
    tmp_path, monkeypatch
) -> None:
    """Run parent controls through the production worker and checkpoint lifecycle."""

    async def scenario() -> None:
        from core.cli import tool_handlers
        from core.memory import session_checkpoint
        from core.wiring import bootstrap

        monkeypatch.setattr(session_checkpoint, "DEFAULT_SESSION_DIR", tmp_path / "checkpoints")
        effect_log = tmp_path / "effects.log"

        async def commit_effect(operation_id: str) -> dict[str, str]:
            with effect_log.open("a", encoding="utf-8") as stream:
                stream.write(f"{operation_id}\n")
            return {"status": "committed", "operation_id": operation_id}

        monkeypatch.setattr(
            tool_handlers,
            "_build_tool_handlers",
            lambda *, verbose=False: {"commit_effect": commit_effect},
        )
        monkeypatch.setattr(bootstrap, "build_worker_hooks", lambda **_kwargs: None)

        mutation_round_zero_messages: list[str] = []
        verify_round_zero_messages: list[str] = []

        async def scripted_llm(
            loop: AgenticLoop,
            _system: str,
            messages: list[dict[str, Any]],
            *,
            round_idx: int = 0,
            **_kwargs: Any,
        ) -> AgenticResponse:
            history = json.dumps(messages, ensure_ascii=False, default=str)
            usage = ResponseUsage(input_tokens=1, output_tokens=1)
            if "externally visible effect" in history:
                if round_idx == 0:
                    mutation_round_zero_messages.append(history)
                    return AgenticResponse(
                        content=[
                            ToolUseBlock(
                                id=f"effect-{len(mutation_round_zero_messages)}",
                                name="commit_effect",
                                input={"operation_id": loop._session_id},
                            )
                        ],
                        stop_reason="tool_use",
                        usage=usage,
                    )
                return AgenticResponse(
                    content=[TextBlock(text=json.dumps({"summary": "mutation complete"}))],
                    usage=usage,
                )
            if round_idx == 0:
                if "verify dependency" in history:
                    verify_round_zero_messages.append(history)
                return AgenticResponse(
                    content=[
                        ToolUseBlock(
                            id=f"nested-{loop._session_id}",
                            name="delegate_task",
                            input={"task_description": "nested work"},
                        )
                    ],
                    stop_reason="tool_use",
                    usage=usage,
                )
            has_dependency = "verify dependency" in history and "research artifact" in history
            summary = "verified research artifact" if has_dependency else "research artifact"
            return AgenticResponse(
                content=[TextBlock(text=json.dumps({"summary": summary}))],
                usage=usage,
            )

        async def skip_auxiliary_reflection(
            _loop: AgenticLoop, _tool_results: list[dict[str, Any]]
        ) -> None:
            return None

        monkeypatch.setattr(AgenticLoop, "_call_llm", scripted_llm)
        monkeypatch.setattr(AgenticLoop, "_maybe_reflect", skip_auxiliary_reflection)

        runner = _ProductionWorkerRunner()
        manager = SubAgentManager(
            runner,
            action_handlers={},
            collaboration_store=CollaborationStore(tmp_path / "sessions.db"),
        )
        executor = ToolExecutor(sub_agent_manager=manager, auto_approve=True, hitl_level=0)
        context = ToolContext(
            session_id="parent-e2e",
            model="gpt-5.4",
            source="subscription",
        )

        research = await executor.aexecute(
            "delegate_task",
            {
                "task_description": "run research stage",
                "task_type": "search",
                "background": True,
            },
            context=context,
        )
        research_id = research["tasks"][0]["task_id"]
        research_wait = await executor.aexecute(
            "manage_subagents",
            {"action": "wait", "task_id": research_id, "timeout_seconds": 5},
            context=context,
        )
        assert research_wait["task"]["status"] == "completed"
        assert research_wait["task"]["summary"] == "research artifact"

        verify = await executor.aexecute(
            "delegate_task",
            {
                "task_description": (
                    f"verify dependency from parent: {research_wait['task']['summary']}"
                ),
                "task_type": "compare",
                "background": True,
            },
            context=context,
        )
        verify_id = verify["tasks"][0]["task_id"]
        verify_wait = await executor.aexecute(
            "manage_subagents",
            {"action": "wait", "task_id": verify_id, "timeout_seconds": 5},
            context=context,
        )
        assert verify_wait["task"]["status"] == "completed"
        assert verify_wait["task"]["summary"] == "verified research artifact"
        assert len(verify_round_zero_messages) == 1
        assert "research artifact" in verify_round_zero_messages[0]

        mutation = await executor.aexecute(
            "delegate_task",
            {
                "task_description": "commit one externally visible effect",
                "task_type": "analyze",
                "background": True,
            },
            context=context,
        )
        mutation_id = mutation["tasks"][0]["task_id"]
        completed = await executor.aexecute(
            "manage_subagents",
            {"action": "wait", "task_id": mutation_id, "timeout_seconds": 5},
            context=context,
        )
        assert completed["task"]["status"] == "completed"

        resumed_run = await executor.aexecute(
            "manage_subagents",
            {
                "action": "resume",
                "task_id": mutation_id,
                "message": "repeat the mutation turn from its saved checkpoint",
            },
            context=context,
        )
        assert resumed_run["resumed"] is True
        assert resumed_run["task"]["generation"] == 2
        resumed = await executor.aexecute(
            "manage_subagents",
            {"action": "wait", "task_id": mutation_id, "timeout_seconds": 5},
            context=context,
        )
        assert resumed["task"]["status"] == "completed"

        effects = effect_log.read_text(encoding="utf-8").splitlines()
        checkpoint = SessionCheckpoint()
        research_state = checkpoint.load(research_id)
        verify_state = checkpoint.load(verify_id)
        listed = await executor.aexecute(
            "manage_subagents",
            {"action": "list"},
            context=context,
        )
        assert research_state is not None and verify_state is not None
        for state in (research_state, verify_state):
            durable_history = json.dumps(state.messages, ensure_ascii=False, default=str)
            assert "delegate_task" in durable_history
            tool_results = [
                json.loads(block["content"])
                for message in state.messages
                for block in message.get("content", [])
                if isinstance(block, dict) and block.get("type") == "tool_result"
            ]
            assert any(result.get("denied") is True for result in tool_results)
        assert len(mutation_round_zero_messages) == 2
        assert "commit_effect" in mutation_round_zero_messages[1]
        assert "committed" in mutation_round_zero_messages[1]
        assert listed["total"] == 3
        assert {research_id, verify_id}.issubset({task["task_id"] for task in listed["tasks"]})
        # Characterization: explicit resume restores history but has no operation receipt.
        assert effects == [mutation_id, mutation_id]

    asyncio.run(scenario())
