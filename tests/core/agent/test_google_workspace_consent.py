"""Google Workspace personal-data and mutation safety boundaries."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from core.agent.approval import ApprovalWorkflow
from core.agent.cognitive_state import CognitiveState
from core.agent.loop.agent_loop import AgenticLoop
from core.agent.safety import (
    HEADLESS_DENIED_TOOLS,
    SENSITIVE_TOOLS,
    WRITE_TOOLS,
    _skip_permissions_var,
)
from core.agent.sub_agent import SUBAGENT_DENIED_TOOLS
from core.hooks import HookEvent
from core.memory.session_checkpoint import SessionCheckpoint, SessionState

READ_TOOLS = {
    "gmail_search",
    "google_drive_search",
    "google_docs_read",
    "google_sheets_read",
    "google_tasks_list",
    "google_contacts_list",
    "calendar_list_events",
}

WRITE_GOOGLE_TOOLS = {
    "gmail_send",
    "google_drive_create",
    "google_docs_write",
    "google_sheets_write",
    "google_tasks_write",
    "calendar_create_event",
    "calendar_sync_scheduler",
}


def test_google_reads_require_personal_data_consent() -> None:
    assert READ_TOOLS <= SENSITIVE_TOOLS
    assert READ_TOOLS <= HEADLESS_DENIED_TOOLS
    assert READ_TOOLS <= SUBAGENT_DENIED_TOOLS


def test_google_mutations_require_write_approval() -> None:
    assert WRITE_GOOGLE_TOOLS <= WRITE_TOOLS
    assert WRITE_GOOGLE_TOOLS <= SENSITIVE_TOOLS
    assert WRITE_GOOGLE_TOOLS <= HEADLESS_DENIED_TOOLS
    assert WRITE_GOOGLE_TOOLS <= SUBAGENT_DENIED_TOOLS


def test_sensitive_denial_fails_closed_with_no_execution() -> None:
    seen: list[tuple[str, str, str]] = []

    def deny(tool_name: str, detail: str, safety_level: str) -> str:
        seen.append((tool_name, safety_level, detail))
        return "n"

    workflow = ApprovalWorkflow(hitl_level=2, approval_callback=deny)
    rejection, approved = workflow.apply_safety_gates(
        "gmail_search",
        {"query": "from:private@example.com"},
    )
    assert approved is False
    assert rejection is not None and rejection["denied"] is True
    assert seen[0][:2] == ("gmail_search", "sensitive")
    assert "configured LLM provider" in seen[0][2]
    assert "from:private@example.com" in seen[0][2]


def test_sensitive_approval_is_recorded() -> None:
    workflow = ApprovalWorkflow(
        hitl_level=2,
        approval_callback=lambda _name, _detail, _level: "y",
    )
    rejection, approved = workflow.apply_safety_gates("google_docs_read", {"document_id": "d1"})
    assert rejection is None
    assert approved is True


def test_sensitive_access_cannot_be_always_allowed() -> None:
    calls = 0

    def always(_name: str, _detail: str, _level: str) -> str:
        nonlocal calls
        calls += 1
        return "a"

    workflow = ApprovalWorkflow(hitl_level=0, approval_callback=always)
    for _ in range(2):
        rejection, approved = workflow.apply_safety_gates("gmail_search", {"query": "is:unread"})
        assert approved is False
        assert rejection is not None and rejection["denied"] is True
    assert calls == 2


def test_google_mutation_ignores_skip_permissions_and_cached_write_allow() -> None:
    calls = 0

    def approve(_name: str, _detail: str, _level: str) -> str:
        nonlocal calls
        calls += 1
        return "y"

    workflow = ApprovalWorkflow(hitl_level=0, approval_callback=approve)
    workflow._always_approved_categories.add("write")
    token = _skip_permissions_var.set(True)
    try:
        for _ in range(2):
            rejection, approved = workflow.apply_safety_gates(
                "gmail_send",
                {"to": "reader@example.com", "subject": "Review", "body": "private"},
            )
            assert rejection is None
            assert approved is True
    finally:
        _skip_permissions_var.reset(token)
    assert calls == 2


def test_google_write_summaries_show_the_material_change() -> None:
    assert (
        ApprovalWorkflow._write_summary(
            "gmail_send",
            {"to": "reader@example.com", "subject": "Review", "body": "secret"},
        )
        == "to=reader@example.com subject=Review"
    )
    docs = ApprovalWorkflow._write_summary(
        "google_docs_write",
        {"action": "append", "document_id": "doc-1", "text": "proposed text"},
    )
    assert "document=doc-1" in docs
    assert "proposed text" in docs


def test_personal_result_skips_reflection_and_cognitive_persistence(tmp_path: Path) -> None:
    private_echo = "private-mail-echo-7d83f3"
    tool_results = [
        {
            "type": "tool_result",
            "tool_use_id": "google-call-1",
            "content": private_echo,
        }
    ]

    class _Processor:
        async def process(self, _response: Any) -> list[dict[str, Any]]:
            return tool_results

    class _Loop:
        def __init__(self) -> None:
            self.cognitive_state = CognitiveState(goal="inspect mail")
            self._tool_processor = _Processor()
            self.reflected = False

        async def _emit_cognitive(self, _event: HookEvent, **_payload: Any) -> None:
            return

        async def _maybe_reflect(self, results: list[dict[str, Any]]) -> None:
            self.reflected = True
            self.cognitive_state.hypotheses = [str(results[0]["content"])]

    loop = _Loop()
    response = SimpleNamespace(
        content=[
            SimpleNamespace(
                type="tool_use",
                name="gmail_search",
                id="google-call-1",
                input={"query": "private"},
            )
        ]
    )

    returned = asyncio.run(AgenticLoop._run_cognitive_act_observe_cycle(loop, response, 0))

    assert returned == tool_results
    assert private_echo in returned[0]["content"]
    assert loop.reflected is False
    checkpoint = SessionCheckpoint(tmp_path / "sessions")
    checkpoint.save(
        SessionState(
            session_id="personal-reflection",
            cognitive_state=loop.cognitive_state.to_snapshot(),
        )
    )
    loaded = checkpoint.load("personal-reflection")
    assert loaded is not None
    assert private_echo not in json.dumps(loaded.cognitive_state)
    state_json = tmp_path / "sessions" / "personal-reflection" / "state.json"
    assert private_echo not in state_json.read_text(encoding="utf-8")
    assert private_echo.encode() not in (tmp_path / "sessions" / "sessions.db").read_bytes()
