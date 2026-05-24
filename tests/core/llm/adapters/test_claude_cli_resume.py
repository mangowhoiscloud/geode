"""PR2 (V) — paperclip ``--resume`` + per-agent sessionId tests.

Pins invariants from
``docs/plans/2026-05-24-transcript-standardization-and-claude-resume.md`` §3.4
(V.1 contract + V.2 argv + V.2 parser + V.3 round-trip + V.4 persistence).

PR-COMM-3c (2026-05-24) — adds the ``isolate_sessions_db`` autouse
fixture so the V.4 round-trip tests don't pollute the developer's
``~/.geode/projects/.../sessions.db`` via the dual-write path. The
``_persist_session_id`` helper now writes to BOTH the legacy
``session.json`` AND the SQLite ``agent_runtime_state.claude_cli_session_id``
column; without isolation the SQLite write would land in the user's
real DB.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolate_sessions_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect the sessions.db default path to ``tmp_path`` for the
    duration of each test + reset the ``agent_runtime_state`` module's
    cached connection so it picks up the override."""
    from core.memory.session_manager import SessionManager

    from core.observability import agent_runtime_state as ars

    db = tmp_path / "sessions.db"
    SessionManager(db_path=db)
    monkeypatch.setattr("core.memory.session_manager._get_default_db_path", lambda: db)
    ars._reset_for_tests(db_path=db)
    yield db
    ars._reset_for_tests()


# ---------------------------------------------------------------------------
# V.1 — AdapterCallRequest / AdapterCallResult new fields
# ---------------------------------------------------------------------------


def test_v1_request_has_resume_session_id_field() -> None:
    """``AdapterCallRequest.resume_session_id`` defaults to empty
    (legacy fresh-session behaviour). Non-empty value triggers
    ``--resume`` in claude-cli adapter."""
    from core.llm.adapters.base import AdapterCallRequest

    req_default = AdapterCallRequest(model="claude-opus-4-7", messages=[])
    assert req_default.resume_session_id == ""

    req_resume = AdapterCallRequest(
        model="claude-opus-4-7", messages=[], resume_session_id="prior-sess-xyz"
    )
    assert req_resume.resume_session_id == "prior-sess-xyz"


def test_v1_result_has_session_id_field() -> None:
    """``AdapterCallResult.session_id`` defaults to empty
    (non-claude-cli adapters). claude-cli sets it from the
    ``system.init`` event."""
    from core.llm.adapters.base import AdapterCallResult, UsageSummary

    res_default = AdapterCallResult(text="hi", usage=UsageSummary(), stop_reason="end_turn")
    assert res_default.session_id == ""

    res_with_session = AdapterCallResult(
        text="hi", usage=UsageSummary(), stop_reason="end_turn", session_id="new-sess-456"
    )
    assert res_with_session.session_id == "new-sess-456"


# ---------------------------------------------------------------------------
# V.2 — build_claude_cli_argv + extract_session_id_from_events
# ---------------------------------------------------------------------------


def test_v2_argv_includes_resume_flag_when_session_id_supplied() -> None:
    """paperclip ``execute.ts:680`` parity — ``--resume <session_id>``
    precedes ``--model`` so claude-cli pulls the cached model from the
    resumed session."""
    from plugins.petri_audit.claude_cli_provider import build_claude_cli_argv

    argv = build_claude_cli_argv(
        binary="/x/claude", model_name="claude-opus-4-7", resume_session_id="abc123"
    )
    assert "--resume" in argv
    resume_index = argv.index("--resume")
    assert argv[resume_index + 1] == "abc123"
    model_index = argv.index("--model")
    # --resume comes BEFORE --model so the cached model wins.
    assert resume_index < model_index


def test_v2_argv_omits_resume_flag_when_session_id_empty() -> None:
    """When ``resume_session_id`` is None/empty the argv is byte-equivalent
    to the pre-PR-V form (no behaviour change for first-turn callers)."""
    from plugins.petri_audit.claude_cli_provider import build_claude_cli_argv

    argv_none = build_claude_cli_argv(binary="/x/claude", model_name="claude-opus-4-7")
    argv_empty = build_claude_cli_argv(
        binary="/x/claude", model_name="claude-opus-4-7", resume_session_id=""
    )
    assert "--resume" not in argv_none
    assert "--resume" not in argv_empty


def test_v2_extract_session_id_from_system_init_event() -> None:
    """paperclip ``parse.ts:30-33`` parity — ``system.init`` event's
    ``session_id`` field is the freshly-allocated session for this turn."""
    from plugins.petri_audit.claude_cli_provider import (
        extract_session_id_from_events,
        parse_stream_json_events,
    )

    stdout = (
        json.dumps({"type": "system", "subtype": "init", "session_id": "sess-abc-123"})
        + "\n"
        + json.dumps({"type": "assistant", "message": {"content": []}})
        + "\n"
    )
    events = parse_stream_json_events(stdout)
    assert extract_session_id_from_events(events) == "sess-abc-123"


def test_v2_extract_session_id_returns_empty_when_no_init() -> None:
    """When claude-cli crashes before the ``system.init`` event the
    extractor returns empty string (not None / not raise) so the
    caller can fall back to a fresh next-turn session."""
    from plugins.petri_audit.claude_cli_provider import (
        extract_session_id_from_events,
        parse_stream_json_events,
    )

    # Only assistant event, no system.init
    stdout = json.dumps({"type": "assistant", "message": {"content": []}}) + "\n"
    events = parse_stream_json_events(stdout)
    assert extract_session_id_from_events(events) == ""


def test_v2_extract_session_id_ignores_non_init_system_events() -> None:
    """Only ``subtype == "init"`` events carry the session-id contract;
    other system events (``error`` / ``warning``) must NOT be misread."""
    from plugins.petri_audit.claude_cli_provider import (
        extract_session_id_from_events,
        parse_stream_json_events,
    )

    stdout = json.dumps({"type": "system", "subtype": "error", "session_id": "wrong"}) + "\n"
    events = parse_stream_json_events(stdout)
    assert extract_session_id_from_events(events) == ""


# ---------------------------------------------------------------------------
# V.4 — AgenticLoop session.json persistence (paperclip
# agent_runtime_state equivalent)
# ---------------------------------------------------------------------------


def test_v4_session_json_roundtrip_under_run_dir_scope() -> None:
    """``<run_dir>/sub_agents/<task_id>/session.json`` is the single-row
    per-agent state (paperclip ``agent_runtime_state`` parity). Persist
    then load returns the same session_id."""
    from core.agent.loop.agent_loop import _load_prior_session_id, _persist_session_id
    from core.observability.run_dir import run_dir_scope

    task_id = "gen-gen1-001-bd2e3854"
    with tempfile.TemporaryDirectory() as tmp, run_dir_scope(tmp):
        _persist_session_id(task_id, "sess-abc-123")
        session_path = Path(tmp) / "sub_agents" / task_id / "session.json"
        assert session_path.exists()
        data = json.loads(session_path.read_text())
        assert data["claude_cli_session_id"] == "sess-abc-123"
        assert "updated_at" in data
        # Round-trip
        assert _load_prior_session_id(task_id) == "sess-abc-123"


def test_v4_load_prior_session_id_no_op_outside_scope() -> None:
    """Outside ``run_dir_scope`` (REPL / gateway / tests) the load
    returns empty string — non-seed-gen callers are unaffected and
    fall back to fresh sessions."""
    from core.agent.loop.agent_loop import _load_prior_session_id

    assert _load_prior_session_id("any-task") == ""


def test_v4_persist_empty_session_id_is_noop() -> None:
    """Non-claude-cli adapters return ``session_id=""`` (no resumable
    session). Persisting empty must NOT overwrite a prior session.json
    so cross-cycle resume is preserved when a different adapter ran
    in the middle."""
    from core.agent.loop.agent_loop import _load_prior_session_id, _persist_session_id
    from core.observability.run_dir import run_dir_scope

    task_id = "gen-task-002"
    with tempfile.TemporaryDirectory() as tmp, run_dir_scope(tmp):
        _persist_session_id(task_id, "sess-original-789")
        _persist_session_id(task_id, "")  # empty must be no-op
        assert _load_prior_session_id(task_id) == "sess-original-789"


def test_v3_adapter_round_trip_threads_resume_and_emits_session_id() -> None:
    """V.3 — request.resume_session_id → ``--resume`` argv → claude-cli
    emits system.init session_id → result.session_id. Codex MCP review
    of #1588 flagged this round-trip was implemented but not directly
    tested."""
    import asyncio
    from unittest.mock import patch

    from core.llm.adapters.base import AdapterCallRequest
    from core.llm.adapters.claude_cli import ClaudeCliAdapter

    adapter = ClaudeCliAdapter()
    # claude-cli stdout: system.init carries session_id + assistant + result
    stdout = (
        json.dumps({"type": "system", "subtype": "init", "session_id": "emitted-session-789"})
        + "\n"
        + json.dumps(
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "hi"}]}}
        )
        + "\n"
        + json.dumps({"type": "result", "stop_reason": "end_turn", "result": "hi"})
        + "\n"
    )
    captured_argv: list[str] = []

    async def _fake_subprocess(
        argv: list[str], stdin_text: str, timeout_s: float
    ) -> tuple[str, str, int]:
        captured_argv.extend(argv)
        return (stdout, "", 0)

    def _passthrough_lane(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        # Sync function returning an async context manager — matches
        # the actual ``acquire_claude_cli_lane_async`` shape (it's a
        # sync helper that returns the CM, not itself an awaitable).
        class _Ctx:
            async def __aenter__(self):  # type: ignore[no-untyped-def]
                return None

            async def __aexit__(self, *_exc):  # type: ignore[no-untyped-def]
                return None

        return _Ctx()

    with (
        patch(
            "plugins.petri_audit.claude_cli_provider._resolve_claude_binary",
            return_value="/fake/claude",
        ),
        patch(
            "plugins.petri_audit.claude_cli_provider._run_claude_subprocess",
            _fake_subprocess,
        ),
        patch(
            "core.orchestration.claude_cli_lane.acquire_claude_cli_lane_async",
            _passthrough_lane,
        ),
    ):
        req = AdapterCallRequest(
            model="claude-opus-4-7", messages=(), resume_session_id="prior-sess-xyz"
        )
        result = asyncio.run(adapter.acomplete(req))
    # argv must carry --resume <prior-sess-xyz>
    assert "--resume" in captured_argv
    assert captured_argv[captured_argv.index("--resume") + 1] == "prior-sess-xyz"
    # result must carry the new session_id from system.init
    assert result.session_id == "emitted-session-789"


def test_v3_subprocess_stdin_skips_system_prompt_when_resuming() -> None:
    """paperclip ``execute.ts:694-698`` parity (Codex MCP fix of #1588):
    when resuming a session the system prompt is in the backend cache
    — re-injecting via stdin wastes 5-10K tokens per turn. This is the
    actual mechanism by which PR-V's CHANGELOG-claimed quota savings
    materialise. First-turn callers (empty resume_session_id) must
    still send the prompt so claude-cli caches it for next turn."""
    from core.llm.adapters._subprocess_common import build_subprocess_stdin
    from core.llm.adapters.base import AdapterCallRequest, Message

    system_prompt = "You are a Petri seed generator. Output JSON only."
    user_msg = Message(role="user", content="Generate seed for X")

    # First turn — system prompt MUST be in stdin (cache priming).
    req_first = AdapterCallRequest(
        model="claude-opus-4-7",
        messages=[user_msg],
        system_prompt=system_prompt,
        resume_session_id="",
    )
    stdin_first = build_subprocess_stdin(req_first)
    assert "[SYSTEM]" in stdin_first
    assert system_prompt in stdin_first

    # Resume turn — system prompt MUST NOT be re-sent (cache hit).
    req_resume = AdapterCallRequest(
        model="claude-opus-4-7",
        messages=[user_msg],
        system_prompt=system_prompt,
        resume_session_id="prior-sess-xyz",
    )
    stdin_resume = build_subprocess_stdin(req_resume)
    assert "[SYSTEM]" not in stdin_resume
    assert system_prompt not in stdin_resume
    # User turn must still be present (only system is skipped).
    assert "Generate seed for X" in stdin_resume


def test_v4_load_prior_session_id_returns_empty_when_file_missing() -> None:
    """First turn of a fresh sub-agent — no session.json yet.
    Must return empty so the adapter falls back to fresh session."""
    from core.agent.loop.agent_loop import _load_prior_session_id
    from core.observability.run_dir import run_dir_scope

    with tempfile.TemporaryDirectory() as tmp, run_dir_scope(tmp):
        # Never persisted — file doesn't exist.
        assert _load_prior_session_id("fresh-task") == ""
