"""Initial IPC selection admission and the existing public session-end owner."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

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
