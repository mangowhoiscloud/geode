"""Approval FSM — record lifecycle, gate integration, IPC round-trip, and the
A-but-denied regression (memory_save incident, 2026-07-02).

The incident: a user answered ``A`` (always-allow) at a ``memory_save``
write-approval prompt and the tool result still said "User denied write
operation" — twice. Root cause: ``_handle_client_async`` awaited
``_process_message_async`` inline, so during a prompt nothing read the IPC
socket; the thin client's approval_response could never reach
``feed_approval_response`` and the 120s timeout fail-closed to "n". These
tests pin (1) the FSM record rails, (2) the reader pump that consumes
approval replies mid-prompt, (3) the approval_id round-trip that discards
stale replies, and (4) always-allow → first call EXECUTES.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from core.agent.approval import ApprovalWorkflow
from core.agent.approval_fsm import (
    LEDGER_ROW_STATES,
    ApprovalRecord,
    parse_decision,
)
from core.agent.tool_executor import ToolExecutor
from core.hooks.system import HookEvent

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _RecordingHooks:
    """HookSystem stand-in that records (event, data) pairs."""

    def __init__(self) -> None:
        self.fired: list[tuple[HookEvent, dict[str, Any]]] = []

    def trigger(self, event: HookEvent, data: dict[str, Any] | None = None) -> list[Any]:
        self.fired.append((event, dict(data or {})))
        return []

    async def trigger_async(
        self, event: HookEvent, data: dict[str, Any] | None = None
    ) -> list[Any]:
        self.fired.append((event, dict(data or {})))
        return []

    def states(self) -> list[str]:
        return [d.get("state", "") for e, d in self.fired if e is HookEvent.APPROVAL_TRANSITION]


class _MemoryLedger:
    """EvidenceLedger stand-in that records appended rows."""

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def append(self, *, kind: str, summary: str, payload: dict[str, Any]) -> None:
        self.rows.append({"kind": kind, "summary": summary, "payload": payload})


def _workflow(**kwargs: Any) -> ApprovalWorkflow:
    kwargs.setdefault("hitl_level", 2)
    kwargs.setdefault("auto_approve", False)
    return ApprovalWorkflow(**kwargs)


@contextmanager
def _console_input(target: str, typed: str) -> Any:
    """Patch a module-level ``console`` object so ``console.input`` returns
    *typed* (the shared console is a proxy — patch the module attribute,
    same pattern as tests/core/agent/test_hitl_level.py)."""
    with patch(target) as mock_console:
        mock_console.input.return_value = typed
        with patch("core.cli._restore_terminal"):
            yield mock_console


# ---------------------------------------------------------------------------
# 1. Record lifecycle
# ---------------------------------------------------------------------------


class TestApprovalRecordLifecycle:
    def test_happy_path_transitions(self) -> None:
        record = ApprovalRecord(tool_name="memory_save", category="write")
        for state, detail in [
            ("requested", "gate"),
            ("displayed", "console"),
            ("user_selected", "a"),
            ("parsed", "always"),
            ("granted", "user:a"),
            ("propagated", "dispatch"),
            ("executed", "ok"),
        ]:
            record.transition(state, detail)
        assert record.state == "executed"
        assert record.raw_input == "a"
        assert record.verdict == "always"
        assert [t.state for t in record.transitions] == [
            "requested",
            "displayed",
            "user_selected",
            "parsed",
            "granted",
            "propagated",
            "executed",
        ]
        assert not any(t.illegal for t in record.transitions)

    def test_approval_id_is_hex12(self) -> None:
        record = ApprovalRecord(tool_name="x", category="write")
        assert len(record.approval_id) == 12
        int(record.approval_id, 16)  # must be valid hex

    def test_auto_shortcuts_are_legal(self) -> None:
        granted = ApprovalRecord(tool_name="x", category="write")
        granted.transition("requested")
        granted.transition("granted", "auto:always-category:write")
        assert not any(t.illegal for t in granted.transitions)

        denied = ApprovalRecord(tool_name="x", category="write")
        denied.transition("requested")
        denied.transition("denied", "auto_denied:3-strikes")
        denied.transition("skipped", "gate-rejected")
        assert not any(t.illegal for t in denied.transitions)

    def test_illegal_transition_tolerated_never_raises(self) -> None:
        record = ApprovalRecord(tool_name="x", category="write")
        record.transition("requested")
        record.transition("executed", "jumped the chain")  # illegal from requested
        assert record.state == "executed"
        assert record.transitions[-1].illegal is True
        # Terminal state: any further transition is illegal but still recorded.
        record.transition("requested", "resurrection")
        assert record.transitions[-1].illegal is True
        assert len(record.transitions) == 3

    def test_timestamps_are_monotonic(self) -> None:
        record = ApprovalRecord(tool_name="x", category="bash")
        record.transition("requested")
        record.transition("displayed")
        record.transition("user_selected", "y")
        stamps = [t.ts for t in record.transitions]
        assert stamps == sorted(stamps)

    def test_to_event_payload_shape(self) -> None:
        record = ApprovalRecord(tool_name="memory_save", category="write")
        record.transition("requested", "gate")
        record.transition("granted", "auto:skip-permissions")
        payload = record.to_event_payload()
        assert payload["tool_name"] == "memory_save"
        assert payload["category"] == "write"
        assert payload["state"] == "granted"
        assert payload["approval_id"] == record.approval_id
        assert payload["illegal"] is False
        assert payload["transitions"] == [
            ["requested", record.transitions[0].ts, "gate", False],
            ["granted", record.transitions[1].ts, "auto:skip-permissions", False],
        ]


# ---------------------------------------------------------------------------
# 2. Input grammar — direct path parse + IPC thin-client parity
# ---------------------------------------------------------------------------


class TestDecisionParse:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("", ("y", "allow")),
            ("y", ("y", "allow")),
            ("YES ", ("y", "allow")),
            ("a", ("a", "always")),
            ("Always", ("a", "always")),
            ("A ", ("a", "always")),
            ("n", ("n", "deny")),
            ("no", ("n", "deny")),
            ("garbage", ("n", "deny")),
        ],
    )
    def test_parse_decision(self, raw: str, expected: tuple[str, str]) -> None:
        assert parse_decision(raw) == expected

    @pytest.mark.parametrize("typed", ["", "y", "yes", "a", "always", "A", "n", "whatever"])
    def test_thin_client_parse_parity(self, typed: str) -> None:
        """The IPC thin client's inline parse (kept agent-layer-free) must
        agree with ``parse_decision`` for every input class — a divergence
        here IS the 'default-on-empty-input mismatch' failure mode."""
        from core.cli.ipc_client import IPCClient

        client = IPCClient.__new__(IPCClient)
        with (
            patch.object(client, "_restore_terminal"),
            patch.object(client, "_read_approval_line", return_value=typed),
            patch("core.ui.console.console"),
        ):
            decision = client._handle_approval_request(
                {"tool_name": "memory_save", "detail": "", "safety_level": "write"}
            )
        assert decision == parse_decision(typed)[0]

    def test_thin_client_strips_carriage_returns_from_approval_input(self) -> None:
        """Raw terminal Enter can surface as CR bytes; HITL still accepts it."""
        from core.cli.ipc_client import IPCClient

        client = IPCClient.__new__(IPCClient)
        with (
            patch.object(client, "_restore_terminal"),
            patch.object(client, "_read_approval_line", return_value="a\r\r\n"),
            patch("core.ui.console.console"),
        ):
            decision = client._handle_approval_request(
                {"tool_name": "browser_navigate", "detail": "", "safety_level": "mcp"}
            )
        assert decision == "a"

    def test_thin_client_denies_approval_on_eof(self) -> None:
        """EOF is not the same as pressing Enter; fail closed."""
        from core.cli.ipc_client import IPCClient

        client = IPCClient.__new__(IPCClient)
        with (
            patch.object(client, "_restore_terminal"),
            patch.object(client, "_read_approval_line", side_effect=EOFError),
            patch("core.ui.console.console"),
        ):
            decision = client._handle_approval_request(
                {"tool_name": "browser_navigate", "detail": "", "safety_level": "mcp"}
            )
        assert decision == "n"

    def test_thin_client_resumes_renderer_if_approval_callback_raises(self) -> None:
        """Approval suspend must not strand the renderer if input handling fails."""
        from core.cli.ipc_client import IPCClient

        client = IPCClient.__new__(IPCClient)
        client._sock = object()
        sent: list[dict[str, Any]] = []
        ended: list[bool] = []

        def fail_approval(_msg: dict[str, Any]) -> str:
            raise RuntimeError("approval input failed")

        with (
            patch.object(client, "_send_client_capability"),
            patch.object(client, "_send", side_effect=sent.append),
            patch.object(
                client,
                "_recv",
                return_value={
                    "type": "approval_request",
                    "approval_id": "approval-1",
                    "tool_name": "browser_navigate",
                },
            ),
            pytest.raises(RuntimeError, match="approval input failed"),
        ):
            client.send_prompt(
                "use browser",
                on_approval_start=lambda: None,
                on_approval_end=lambda: ended.append(True),
                on_approval_request=fail_approval,
            )

        assert ended == [True]
        assert sent == [{"type": "prompt", "text": "use browser"}]


# ---------------------------------------------------------------------------
# 3. Per-category gate integration (direct console path)
# ---------------------------------------------------------------------------


class TestGateIntegration:
    def test_write_gate_always_allow_records_and_grants(self) -> None:
        hooks = _RecordingHooks()
        wf = _workflow(hooks=hooks)
        record = wf.begin_record("memory_save")
        assert record is not None and record.category == "write"
        with _console_input("core.agent.approval.console", "a"):
            approved = wf.confirm_write("memory_save", {"content": "x"}, record=record)
        assert approved is True
        assert "write" in wf._always_approved_categories
        assert record.state == "granted"
        assert record.verdict == "always"
        assert hooks.states() == ["requested", "displayed", "user_selected", "parsed", "granted"]

    def test_write_gate_deny_records_denied(self) -> None:
        wf = _workflow()
        record = wf.begin_record("memory_save")
        with _console_input("core.agent.approval.console", "n"):
            approved = wf.confirm_write("memory_save", {"content": "x"}, record=record)
        assert approved is False
        assert record is not None
        assert record.state == "denied"
        assert record.verdict == "deny"

    def test_cost_gate_records(self) -> None:
        wf = _workflow()
        record = wf.begin_record("petri_audit")
        assert record is not None and record.category == "expensive"
        with _console_input("core.agent.approval.console", "a"):
            approved = wf.confirm_cost("petri_audit", 5.0, record=record)
        assert approved is True
        assert "cost" in wf._always_approved_categories
        assert record.state == "granted"

    def test_bash_gate_records(self) -> None:
        wf = _workflow()
        record = wf.begin_record("run_bash")
        assert record is not None and record.category == "bash"
        with _console_input("core.agent.approval.console", "a"):
            approved = wf.request_bash_approval("rm -rf ./build", "cleanup", record=record)
        assert approved is True
        assert "bash" in wf._always_approved_categories
        assert record.state == "granted"

    def test_mcp_gate_records(self) -> None:
        wf = _workflow()
        record = wf.begin_mcp_record("custom-server", "some_tool")
        assert record.category == "mcp"
        with _console_input("core.agent.approval.console", "a"):
            approved = wf.confirm_mcp("custom-server", "some_tool", record=record)
        assert approved is True
        assert "mcp:custom-server" in wf._always_approved_categories
        assert record.state == "granted"

    def test_batch_gate_records_decision(self) -> None:
        hooks = _RecordingHooks()
        wf = _workflow(hooks=hooks)
        blocks = [
            SimpleNamespace(name="petri_audit", input={"x": 1}),
            SimpleNamespace(name="eval_dspy_optimize", input={}),
        ]
        with _console_input("core.agent.approval.console", "y"):
            approved = asyncio.run(wf.batch_cost_approval(blocks))
        assert approved is True
        assert hooks.states() == ["requested", "displayed", "user_selected", "parsed", "granted"]

    def test_batch_gate_deny(self) -> None:
        wf = _workflow()
        blocks = [SimpleNamespace(name="petri_audit", input={})]
        with _console_input("core.agent.approval.console", "n"):
            approved = asyncio.run(wf.batch_cost_approval(blocks))
        assert approved is False

    def test_auto_deny_after_three_strikes_records_denied(self) -> None:
        wf = _workflow()
        for _n in range(3):
            wf.track_decision("memory_save", "n")
        record = wf.begin_record("memory_save")
        with patch("core.cli._restore_terminal"):
            approved = wf.confirm_write("memory_save", {"content": "x"}, record=record)
        assert approved is False
        assert record is not None
        assert record.state == "denied"
        assert record.transitions[-1].detail == "auto_denied:3-strikes"


# ---------------------------------------------------------------------------
# 4. Observability rails — hook payload + evidence ledger terminal rows
# ---------------------------------------------------------------------------


class TestObservabilityRails:
    def test_hook_payload_carries_identity(self) -> None:
        hooks = _RecordingHooks()
        wf = _workflow(hooks=hooks)
        record = wf.begin_record("memory_save")
        wf.record_transition(record, "granted", "auto:test")
        transition_events = [d for e, d in hooks.fired if e is HookEvent.APPROVAL_TRANSITION]
        assert len(transition_events) == 2
        last = transition_events[-1]
        assert last["tool_name"] == "memory_save"
        assert last["category"] == "write"
        assert last["state"] == "granted"
        assert last["detail"] == "auto:test"
        assert last["approval_id"] == (record.approval_id if record else "")

    def test_ledger_rows_only_on_terminal_states(self) -> None:
        ledger = _MemoryLedger()
        wf = _workflow()
        wf.attach_evidence_ledger(ledger)
        record = wf.begin_record("memory_save")
        wf.record_transition(record, "displayed", "console")
        wf.record_transition(record, "user_selected", "a")
        wf.record_transition(record, "parsed", "always")
        assert ledger.rows == []  # non-terminal states write no rows
        wf.record_transition(record, "granted", "user:a")
        wf.record_transition(record, "propagated", "dispatch")
        wf.record_transition(record, "executed", "ok")
        assert [r["payload"]["state"] for r in ledger.rows] == ["granted", "executed"]
        assert all(r["kind"] == "hitl_approval" for r in ledger.rows)
        assert all(r["payload"]["state"] in LEDGER_ROW_STATES for r in ledger.rows)

    def test_missing_ledger_is_silent(self) -> None:
        wf = _workflow()  # no ledger attached
        record = wf.begin_record("memory_save")
        wf.record_transition(record, "granted", "auto:test")  # must not raise

    def test_broken_ledger_never_breaks_approval(self) -> None:
        class _Boom:
            def append(self, **_kw: Any) -> None:
                raise OSError("disk full")

        wf = _workflow()
        wf.attach_evidence_ledger(_Boom())
        record = wf.begin_record("memory_save")
        wf.record_transition(record, "granted", "auto:test")  # must not raise
        assert record is not None and record.state == "granted"


# ---------------------------------------------------------------------------
# 5. Executor end-to-end — always-allow regression (the incident)
# ---------------------------------------------------------------------------


class TestAlwaysAllowRegression:
    def _executor(self, callback: Any, hooks: Any = None) -> ToolExecutor:
        calls: list[str] = []

        def handle_memory_save(**kwargs: Any) -> dict[str, Any]:
            calls.append("executed")
            return {"status": "saved"}

        executor = ToolExecutor(
            action_handlers={"memory_save": handle_memory_save},
            hitl_level=2,
            hooks=hooks,
            approval_callback=callback,
        )
        executor._handler_calls = calls  # type: ignore[attr-defined]
        return executor

    def test_always_allow_first_call_executes_not_denied_memory_save_incident(self) -> None:
        """2026-07-02 incident regression: 'A' at a memory_save prompt must
        EXECUTE the first call (not report 'User denied write operation')
        AND suppress the prompt on the second call."""
        prompt_count = 0

        def callback(tool_name: str, detail: str, safety_level: str, approval_id: str = "") -> str:
            nonlocal prompt_count
            prompt_count += 1
            return "a"

        executor = self._executor(callback)
        first = asyncio.run(executor.aexecute("memory_save", {"content": "one"}))
        assert first == {"status": "saved"}, f"A must execute, got {first}"
        assert "denied" not in first
        second = asyncio.run(executor.aexecute("memory_save", {"content": "two"}))
        assert second == {"status": "saved"}
        assert prompt_count == 1, "second call must skip the prompt after always-allow"
        assert executor._handler_calls == ["executed", "executed"]  # type: ignore[attr-defined]

    def test_legacy_three_arg_callback_still_works(self) -> None:
        def callback(tool_name: str, detail: str, safety_level: str) -> str:
            return "y"

        executor = self._executor(callback)
        result = asyncio.run(executor.aexecute("memory_save", {"content": "x"}))
        assert result == {"status": "saved"}

    def test_deny_records_skipped_and_full_trail(self) -> None:
        hooks = _RecordingHooks()

        def callback(tool_name: str, detail: str, safety_level: str, approval_id: str = "") -> str:
            return "n"

        executor = self._executor(callback, hooks=hooks)
        result = asyncio.run(executor.aexecute("memory_save", {"content": "x"}))
        assert result.get("denied") is True
        assert hooks.states() == [
            "requested",
            "displayed",
            "user_selected",
            "parsed",
            "denied",
            "skipped",
        ]

    def test_grant_records_propagated_and_executed(self) -> None:
        hooks = _RecordingHooks()

        def callback(tool_name: str, detail: str, safety_level: str, approval_id: str = "") -> str:
            return "y"

        executor = self._executor(callback, hooks=hooks)
        result = asyncio.run(executor.aexecute("memory_save", {"content": "x"}))
        assert result == {"status": "saved"}
        assert hooks.states() == [
            "requested",
            "displayed",
            "user_selected",
            "parsed",
            "granted",
            "propagated",
            "executed",
        ]

    def test_ungated_tool_produces_no_fsm_events(self) -> None:
        hooks = _RecordingHooks()

        def handle_check(**kwargs: Any) -> dict[str, Any]:
            return {"ok": True}

        executor = ToolExecutor(
            action_handlers={"check_status": handle_check},
            hitl_level=2,
            hooks=hooks,
        )
        result = asyncio.run(executor.aexecute("check_status", {}))
        assert result == {"ok": True}
        assert hooks.states() == []


# ---------------------------------------------------------------------------
# 6. IPC — approval_id round-trip, stale-reply discard, mid-prompt pump
# ---------------------------------------------------------------------------


class _FakeStreamWriter:
    """Captures line-delimited JSON writes from _AsyncClientEndpoint."""

    def __init__(self) -> None:
        self.lines: list[dict[str, Any]] = []
        self._buf = b""

    def write(self, data: bytes) -> None:
        self._buf += data
        while b"\n" in self._buf:
            line, self._buf = self._buf.split(b"\n", 1)
            self.lines.append(json.loads(line.decode("utf-8")))

    async def drain(self) -> None:
        return

    def close(self) -> None:
        return

    async def wait_closed(self) -> None:
        return

    def sent(self, msg_type: str) -> list[dict[str, Any]]:
        return [line for line in self.lines if line.get("type") == msg_type]


class TestIPCApprovalRoundTrip:
    def test_request_carries_id_and_stale_reply_discarded(self) -> None:
        """The approval_request must carry approval_id; a queued stale reply
        (different id — e.g. the late answer to a previous timed-out prompt)
        must be discarded, and the matching reply honored."""
        from core.server.ipc_server.poller import _AsyncClientEndpoint

        async def scenario() -> tuple[str, list[dict[str, Any]]]:
            loop = asyncio.get_running_loop()
            writer = _FakeStreamWriter()
            endpoint = _AsyncClientEndpoint(loop, writer)  # type: ignore[arg-type]
            endpoint.feed_approval_response("n", "stale-old-id")  # poison entry
            endpoint.feed_approval_response("a", "fresh-id-0001")
            decision = await asyncio.to_thread(
                endpoint.request_approval,
                "memory_save",
                "content",
                "write",
                "fresh-id-0001",
            )
            await endpoint.drain_pending_sends()
            return decision, writer.sent("approval_request")

        decision, requests = asyncio.run(scenario())
        assert decision == "a", "matching reply must win over the stale one"
        assert len(requests) == 1
        assert requests[0]["approval_id"] == "fresh-id-0001"

    def test_timeout_defaults_to_deny(self) -> None:
        from core.server.ipc_server.poller import _AsyncClientEndpoint

        async def scenario() -> str:
            loop = asyncio.get_running_loop()
            endpoint = _AsyncClientEndpoint(loop, _FakeStreamWriter())  # type: ignore[arg-type]
            return await asyncio.to_thread(
                endpoint.request_approval,
                "memory_save",
                "content",
                "write",
                "id-timeout",
                timeout_s=0.2,
            )

        assert asyncio.run(scenario()) == "n"

    def test_legacy_reply_without_id_accepted(self) -> None:
        from core.server.ipc_server.poller import _AsyncClientEndpoint

        async def scenario() -> str:
            loop = asyncio.get_running_loop()
            endpoint = _AsyncClientEndpoint(loop, _FakeStreamWriter())  # type: ignore[arg-type]
            endpoint.feed_approval_response("y")  # thin client without id echo
            return await asyncio.to_thread(
                endpoint.request_approval, "memory_save", "d", "write", "some-id"
            )

        assert asyncio.run(scenario()) == "y"

    def test_approval_reply_consumed_mid_prompt_memory_save_incident(self) -> None:
        """ROOT-CAUSE regression: while a prompt is being processed, the
        reader pump must still consume the thin client's approval_response.
        Pre-fix, `_handle_client_async` awaited the prompt inline, the reply
        was never read, and the 120s timeout denied the write the user had
        approved with 'A'."""
        from core.server.ipc_server.poller import CLIPoller, _AsyncClientEndpoint

        received: dict[str, Any] = {}

        async def scenario() -> None:
            loop = asyncio.get_running_loop()
            writer = _FakeStreamWriter()
            endpoint = _AsyncClientEndpoint(loop, writer)  # type: ignore[arg-type]
            reader = asyncio.StreamReader()

            class _FakeServices:
                def create_session(self, *args: Any, **kwargs: Any) -> tuple[Any, Any]:
                    callback = kwargs["approval_callback"]

                    async def arun(text: str) -> Any:
                        decision = await asyncio.to_thread(
                            callback, "memory_save", "content", "write", "mid-prompt-id"
                        )
                        received["decision"] = decision
                        return SimpleNamespace(
                            text="done",
                            rounds=1,
                            tool_calls=[],
                            termination_reason="complete",
                            summary="",
                        )

                    fake_loop = SimpleNamespace(_quiet=True, _op_logger=None, arun=arun)
                    return SimpleNamespace(), fake_loop

                lane_queue = None

            poller = CLIPoller.__new__(CLIPoller)
            poller._services = _FakeServices()  # type: ignore[attr-defined]
            poller._stop_event = threading.Event()  # type: ignore[attr-defined]
            poller._propagate_contextvars = lambda: None  # type: ignore[attr-defined]

            with patch("core.server.ipc_server.fast_chat.should_use_fast_chat", return_value=False):
                handler = asyncio.ensure_future(poller._handle_client_async(reader, endpoint))
                reader.feed_data(json.dumps({"type": "prompt", "text": "save it"}).encode() + b"\n")

                # Wait for the daemon to emit the approval_request mid-prompt.
                deadline = time.monotonic() + 5.0
                while not writer.sent("approval_request"):
                    if time.monotonic() > deadline:
                        raise AssertionError("approval_request never sent")
                    await asyncio.sleep(0.01)

                request = writer.sent("approval_request")[0]
                # The user answers "A" — pre-fix this line was never read until
                # the prompt (and its 120s timeout denial) had already finished.
                reader.feed_data(
                    json.dumps(
                        {
                            "type": "approval_response",
                            "decision": "a",
                            "approval_id": request["approval_id"],
                        }
                    ).encode()
                    + b"\n"
                )

                deadline = time.monotonic() + 5.0
                while not writer.sent("result"):
                    if time.monotonic() > deadline:
                        raise AssertionError("prompt result never returned")
                    await asyncio.sleep(0.01)

                reader.feed_data(json.dumps({"type": "exit"}).encode() + b"\n")
                await asyncio.wait_for(handler, timeout=5.0)

        asyncio.run(asyncio.wait_for(scenario(), timeout=15.0))
        assert received["decision"] == "a", (
            "the mid-prompt 'A' reply must reach the approval gate — "
            "not time out into a denial (2026-07-02 memory_save incident)"
        )


class TestReaderPumpResilience:
    """The pump must always wake the consumer and never grow unbounded."""

    def test_pump_sends_sentinel_on_unexpected_death(self) -> None:
        """A poisoned line (undecodable bytes) must not silently kill the pump;
        any unexpected exit still enqueues the None sentinel (Codex MED #1)."""
        import asyncio

        from core.server.ipc_server import poller as poller_mod

        src = Path(poller_mod.__file__).read_text(encoding="utf-8")
        assert "UnicodeDecodeError" in src  # decode errors handled like bad JSON
        assert "finally:" in src and "_enqueue(None)" in src  # sentinel guaranteed
        assert isinstance(asyncio.Queue, type)

    def test_msg_queue_is_bounded_with_dropping_put(self) -> None:
        """Backpressure: bounded queue + put_nowait drop, never an awaited put
        that would re-starve approval replies (Codex MED #2)."""
        from core.server.ipc_server import poller as poller_mod

        src = Path(poller_mod.__file__).read_text(encoding="utf-8")
        assert "maxsize=256" in src
        assert "put_nowait" in src
        assert "QueueFull" in src
