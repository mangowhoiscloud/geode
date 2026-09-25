"""Initial IPC selection admission and the existing public session-end owner."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from core.server.ipc_server.poller import CLIPoller


def _bare_poller() -> CLIPoller:
    # client_capability handling touches no instance state — skip __init__.
    return object.__new__(CLIPoller)


def _capability_msg(**extra: object) -> dict[str, object]:
    return {"type": "client_capability", "is_tty": True, "width": 120, "_client": None, **extra}


def _loop(model="gpt-6-sol"):
    from core.agent.conversation import ConversationContext
    from core.agent.loop import AgenticLoop, AgenticLoopConfig
    from core.agent.tool_executor import ToolExecutor
    from core.config.session import SessionModelConfig

    policy = SessionModelConfig(model=model, effort="low", source="payg")
    return AgenticLoop(
        ConversationContext(),
        ToolExecutor(),
        model=model,
        provider="openai",
        config=AgenticLoopConfig(source="payg", effort="low", model_settings=policy),
        quiet=True,
    )


@pytest.mark.parametrize("failure", ["", "invalid", "tools"])
def test_resume_admits_saved_selection_before_history_and_reopen(tmp_path, monkeypatch, failure):
    from core.config.session import SessionModelConfig
    from core.memory.session_checkpoint import SessionCheckpoint, SessionState

    monkeypatch.setattr("core.memory.session_checkpoint.DEFAULT_SESSION_DIR", tmp_path)
    loop = _loop()
    loop.context.add_user_message("current conversation")
    old_id = loop._session_id
    old_policy = loop._model_settings
    old_messages = list(loop.context.messages)
    saved = SessionModelConfig(
        model="gpt-6-sol",
        effort="turbo" if failure == "invalid" else "medium",
        source="subscription",
        judge_model="gpt-6-luna",
        judge_source="payg",
        reflection_max_tokens=321,
    )
    cp = SessionCheckpoint(tmp_path)
    cp.save(
        SessionState(
            session_id="saved",
            model="gpt-6-sol",
            provider="openai",
            status="completed",
            messages=[{"role": "user", "content": "saved conversation"}],
            model_settings=saved,
        )
    )
    if failure == "tools":

        def fail():
            raise RuntimeError("tool binding failed")

        monkeypatch.setattr(loop, "refresh_tools", fail)
    result = asyncio.run(
        _bare_poller()._handle_resume(
            {"session_id": "saved"},
            loop,
            loop.context,
        )
    )
    if failure:
        assert result["type"] == "resume_error"
        assert loop._model_settings == old_policy
        assert loop._session_id == old_id and loop.context.messages == old_messages
        assert str(cp.current_status("saved")) == "completed"
    else:
        assert result["type"] == "resumed"
        assert result["model_config"] == saved.model_dump()
        assert result["model_config_origin"] == "checkpoint"
        assert loop._model_settings == saved and loop._source == "subscription"
        assert loop._effort == "medium" and loop._session_id == "saved"
        assert loop.context.messages[0]["content"] == "saved conversation"
        assert str(cp.current_status("saved")) == "active"


def test_legacy_resume_keeps_current_admitted_selection(tmp_path, monkeypatch):
    from core.memory.session_checkpoint import SessionCheckpoint, SessionState

    monkeypatch.setattr("core.memory.session_checkpoint.DEFAULT_SESSION_DIR", tmp_path)
    loop = _loop()
    policy = loop._model_settings
    SessionCheckpoint(tmp_path).save(SessionState(session_id="legacy", model="obsolete-model"))
    result = asyncio.run(
        _bare_poller()._handle_resume(
            {"session_id": "legacy"},
            loop,
            loop.context,
        )
    )
    assert result["type"] == "resumed"
    assert result["model"] == loop.model == policy.model
    assert result["model_config_origin"] == "current"
    assert result["model_config"] == policy.model_dump()
    assert loop._model_settings == policy


def test_client_capability_adopts_cli_project_model() -> None:
    from core.ipc_protocol import IPC_FEATURES, IPC_PROTOCOL_VERSION

    poller = _bare_poller()
    loop = _loop()
    candidate = loop._model_settings.updated({"model": "gpt-6-luna"})
    result = asyncio.run(
        poller._process_message_async(
            _capability_msg(
                model_config=candidate.model_dump(),
                protocol_version=IPC_PROTOCOL_VERSION,
                features=list(IPC_FEATURES),
            ),
            loop,
            loop.context,
            "cli-test",
        )
    )
    assert result["type"] == "ack" and result["status"] == "applied"
    assert loop.model == "gpt-6-luna"
    assert result["model_config"] == loop._model_settings.model_dump() == candidate.model_dump()


def test_client_capability_no_model_rejects_legacy_peer_without_swap() -> None:
    poller = _bare_poller()
    loop = _loop()
    result = asyncio.run(
        poller._process_message_async(_capability_msg(), loop, loop.context, "cli-test")
    )
    assert result["type"] == "error"
    assert "unsupported" in result["message"]
    assert loop.model == "gpt-6-sol"


def test_client_capability_same_complete_selection_is_noop() -> None:
    from core.ipc_protocol import IPC_FEATURES, IPC_PROTOCOL_VERSION

    poller = _bare_poller()
    loop = _loop()
    original = loop._model_settings
    result = asyncio.run(
        poller._process_message_async(
            _capability_msg(
                model_config=original.model_dump(),
                protocol_version=IPC_PROTOCOL_VERSION,
                features=list(IPC_FEATURES),
            ),
            loop,
            loop.context,
            "cli-test",
        )
    )
    assert result["type"] == "ack" and result["status"] == "applied"
    assert loop._model_settings is original
    assert loop.context.is_empty


def test_async_exit_uses_public_session_end_owner() -> None:
    poller = _bare_poller()
    loop = MagicMock()
    loop.amark_session_completed = AsyncMock()

    result = asyncio.run(
        poller._process_message_async(
            {"type": "exit"},
            loop,
            MagicMock(),
            "cli-test",
        )
    )

    assert result is None
    loop.amark_session_completed.assert_awaited_once()
