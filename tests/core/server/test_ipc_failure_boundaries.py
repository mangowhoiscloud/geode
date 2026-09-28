"""Failure is preserved from runtime result through the IPC boundary."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from core.agent.loop.models import AgenticResult
from core.server.ipc_server.poller import CLIPoller, _AsyncClientEndpoint


def test_final_result_preserves_runtime_error_and_failure_status():
    poller = CLIPoller(SimpleNamespace())
    result = poller._build_prompt_result(
        SimpleNamespace(model="fixture"),
        AgenticResult(text="", error="upstream failed", termination_reason="llm_error"),
    )
    assert result["error"] == "upstream failed"
    assert result["status"] == "error"
    assert result["termination"] == "llm_error"


def test_exit_checkpoint_failure_cannot_acknowledge_completion():
    async def run():
        loop = SimpleNamespace(amark_session_completed=AsyncMock(side_effect=OSError("disk full")))
        response = await CLIPoller(SimpleNamespace())._process_message_async(
            {"type": "exit", "request_id": "exit-failed"}, loop, None, "session"
        )
        assert response is not None
        assert response["type"] == "error"
        assert response["error_type"] == "OSError"
        assert "disk full" in response["message"]

    asyncio.run(run())


def test_scheduled_stream_encoding_failure_survives_until_drain():
    from core.ipc_protocol import MAX_IPC_MESSAGE_BYTES, IPCProtocolError

    async def run():
        endpoint = _AsyncClientEndpoint(asyncio.get_running_loop(), SimpleNamespace())
        endpoint.send_json_nowait({"type": "stream", "data": "x" * MAX_IPC_MESSAGE_BYTES})
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        with pytest.raises(IPCProtocolError):
            await endpoint.drain_pending_sends()

    asyncio.run(run())


def test_exit_propagates_failure_from_actual_lifecycle_owner():
    from unittest.mock import Mock

    from core.agent.loop.agent_loop import AgenticLoop

    async def run():
        owner = object.__new__(AgenticLoop)
        owner._session_id = "session"
        owner._checkpoint = SimpleNamespace(mark_completed=Mock(side_effect=OSError("disk full")))
        response = await CLIPoller(SimpleNamespace())._process_message_async(
            {"type": "exit", "request_id": "exit-failed"}, owner, None, "session"
        )
        assert response["type"] == "error"
        assert response["error_type"] == "OSError"

    asyncio.run(run())


def test_interactive_login_is_rejected_before_daemon_dispatch():
    from unittest.mock import Mock

    async def run():
        handler = Mock()
        poller = CLIPoller(SimpleNamespace(command_registry=None))
        poller._command_handler = handler
        response = await poller._handle_command_on_server(
            {"type": "command", "cmd": "/login", "args": "openai"}, SimpleNamespace()
        )
        assert response["error_type"] == "terminal_required"
        handler.assert_not_called()

    asyncio.run(run())


def test_wire_errors_are_redacted_bounded_and_keep_request_context(caplog):
    from core.ipc_protocol import ipc_error_response

    secret = "sk-" + "a" * 40
    response = ipc_error_response(ValueError(f"Authorization: Bearer {secret} " + "x" * 4096))
    assert secret not in response["message"]
    assert len(response["message"]) < 2100  # bounded prefix plus truncation accounting
    assert "[truncated:" in response["message"]
    assert response["error_type"] == "ValueError"

    async def run():
        owner = SimpleNamespace(
            amark_session_completed=AsyncMock(side_effect=OSError("disk full")),
            _session_id="stable-session",
        )
        await CLIPoller(SimpleNamespace())._process_message_async(
            {"type": "exit", "request_id": "correlation"}, owner, None, "session"
        )

    asyncio.run(run())
    record = next(
        record for record in caplog.records if record.message == "CLI session completion failed"
    )
    assert record.request_id == "correlation"
    assert record.session_id == "stable-session"
    assert record.exception_type == "OSError"


@pytest.mark.parametrize("mode", ["cancel", "queued", "disconnect"])
def test_connection_cancellation_is_correlated_and_does_not_replay(monkeypatch, mode):
    from core.ipc_protocol import IPC_FEATURES, decode_message, encode_message

    async def run():
        started = asyncio.Event()
        stopped = asyncio.Event()
        starts = []
        replies = asyncio.Queue()

        async def arun(text):
            starts.append(text)
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()

        class Writer:
            def write(self, data):
                replies.put_nowait(decode_message(data.strip()))

            async def drain(self):
                pass

        owner = SimpleNamespace(
            arun=arun,
            _session_id="session",
            model="fixture",
            _quiet=True,
            amark_session_completed=AsyncMock(),
        )
        services = SimpleNamespace(
            create_session=lambda *_args, **_kwargs: (None, owner), lane_queue=None
        )
        poller = CLIPoller(services)
        monkeypatch.setattr(poller, "_propagate_contextvars", lambda: None)
        endpoint = _AsyncClientEndpoint(asyncio.get_running_loop(), Writer())
        endpoint.session_model_config_applied = True
        endpoint.features = IPC_FEATURES
        reader = asyncio.StreamReader()
        task = asyncio.create_task(poller._handle_client_async(reader, endpoint))

        def send(message):
            reader.feed_data(encode_message(message))

        async def response_for(request_id):
            while True:
                response = await asyncio.wait_for(replies.get(), timeout=1)
                if response.get("request_id") == request_id:
                    return response

        await asyncio.wait_for(replies.get(), timeout=1)  # greeting
        send({"type": "prompt", "request_id": "first", "text": "first"})
        await asyncio.wait_for(started.wait(), timeout=1)
        if mode == "disconnect":
            send({"type": "prompt", "request_id": "second", "text": "second"})
            reader.feed_eof()
        else:
            # A foreign request id cannot cancel this connection's active task.
            send({"type": "cancel", "request_id": "wrong", "target_request_id": "foreign"})
            assert (await response_for("wrong"))["type"] == "protocol_error"
            assert not stopped.is_set()
            if mode == "queued":
                send({"type": "prompt", "request_id": "second", "text": "second"})
                send(
                    {"type": "cancel", "request_id": "cancel-second", "target_request_id": "second"}
                )
                assert (await response_for("cancel-second"))["status"] == "cancellation_requested"
            send({"type": "cancel", "request_id": "cancel-first", "target_request_id": "first"})
            response = await response_for("first")
            assert response["status"] == "cancelled"
            assert stopped.is_set()  # cleanup happened before the terminal response
            if mode == "queued":
                assert (await response_for("second"))["status"] == "cancelled"
            send({"type": "exit", "request_id": "exit"})
        await asyncio.wait_for(task, timeout=1)
        assert stopped.is_set()
        assert starts == ["first"]

    asyncio.run(run())


def test_connection_context_survives_cancellable_request_task(monkeypatch):
    from core.agent.safety import current_skip_permissions, set_skip_permissions
    from core.ipc_protocol import decode_message, encode_message

    async def run():
        replies = asyncio.Queue()
        observations = []

        class Writer:
            def write(self, data):
                replies.put_nowait(decode_message(data.strip()))

            async def drain(self):
                pass

        async def process(msg, *_args):
            if msg["type"] == "client_capability":
                set_skip_permissions(msg["dangerously_skip_permissions"])
                return {"type": "ack"}
            if msg["type"] == "prompt":
                observations.append(current_skip_permissions())
                return {"type": "result"}
            return None

        services = SimpleNamespace(create_session=lambda *_args, **_kwargs: (None, object()))
        poller = CLIPoller(services)
        monkeypatch.setattr(poller, "_propagate_contextvars", lambda: None)
        monkeypatch.setattr(poller, "_process_message_async", process)
        reader = asyncio.StreamReader()
        endpoint = _AsyncClientEndpoint(asyncio.get_running_loop(), Writer())
        task = asyncio.create_task(poller._handle_client_async(reader, endpoint))
        await replies.get()
        for enabled in (True, False):
            reader.feed_data(
                encode_message(
                    {"type": "client_capability", "dangerously_skip_permissions": enabled}
                )
            )
            await asyncio.wait_for(replies.get(), timeout=1)
            reader.feed_data(encode_message({"type": "prompt", "text": "test"}))
            await asyncio.wait_for(replies.get(), timeout=1)
        reader.feed_data(encode_message({"type": "exit"}))
        await asyncio.wait_for(task, timeout=1)
        assert observations == [True, False]

    asyncio.run(run())
