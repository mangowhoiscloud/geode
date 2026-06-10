"""PR-D Phase 1 — ``_emit_session_start_signals`` extraction invariants.

Pins the structural extraction: the session-start signal block that
used to live inline in ``AgenticLoop.arun`` now lives in the dedicated
helper. Phase 1 is pure refactor (zero behaviour change); the helper
returns ``None`` on the happy path and an ``AgenticResult`` on the
sole early-exit (USER_INPUT_RECEIVED interceptor block).

Subsequent phases will extract the per-round body so the full Claude
Code declarative ``while + structured stop_reason`` pattern emerges
incrementally. PR-D Phase 1 only does the session-start portion.
"""

from __future__ import annotations

import inspect

from core.agent.loop.agent_loop import AgenticLoop

# ---------------------------------------------------------------------------
# Method exists with the right signature
# ---------------------------------------------------------------------------


def test_emit_session_start_signals_method_exists() -> None:
    assert hasattr(AgenticLoop, "_emit_session_start_signals")
    method = AgenticLoop._emit_session_start_signals
    sig = inspect.signature(method)
    assert "user_input" in sig.parameters
    # Returns AgenticResult | None — pin the annotation so a future
    # refactor that changes the contract surfaces here.
    assert "AgenticResult | None" in str(sig.return_annotation) or sig.return_annotation in (
        # ``from __future__ import annotations`` makes the annotation
        # a string; either form is acceptable.
        "AgenticResult | None",
    )


def test_emit_session_start_signals_is_coroutine() -> None:
    """Hook calls inside are async — the helper must be a coroutine
    so the await chain in ``arun`` stays consistent."""
    assert inspect.iscoroutinefunction(AgenticLoop._emit_session_start_signals)


# ---------------------------------------------------------------------------
# Helper body owns the right session-start responsibilities
# ---------------------------------------------------------------------------


def test_helper_owns_user_input_received_interceptor() -> None:
    """The interceptor + block-result construction must live in the
    helper, not in ``arun`` — otherwise the extraction is half-done."""
    src = inspect.getsource(AgenticLoop._emit_session_start_signals)
    assert "HookEvent.USER_INPUT_RECEIVED" in src
    assert 'termination_reason="input_blocked"' in src


def test_helper_owns_cognitive_state_goal_init() -> None:
    """PR-2 C-1 goal-init runs only once per session (first arun);
    the helper preserves the ``if not self.cognitive_state.goal``
    guard."""
    src = inspect.getsource(AgenticLoop._emit_session_start_signals)
    assert "if not self.cognitive_state.goal" in src
    assert "self.cognitive_state.goal = user_input" in src


def test_helper_owns_contextvar_binds() -> None:
    """PR-4 C-3 ContextVar bind — both set_cognitive_state and
    set_session_id must live in the helper so the bootstrap hook
    handler still sees a bound state when TOOL_EXEC_ENDED fires."""
    src = inspect.getsource(AgenticLoop._emit_session_start_signals)
    assert "set_cognitive_state(self.cognitive_state)" in src
    assert "set_session_id(self._session_id)" in src


def test_helper_owns_cognitive_perceive_emit() -> None:
    """PR-2 C-6 — the first event of the cognitive cycle must fire
    from the session-start block."""
    src = inspect.getsource(AgenticLoop._emit_session_start_signals)
    assert "HookEvent.COGNITIVE_PERCEIVE" in src


def test_helper_owns_transcript_start_record() -> None:
    """Tier-1 transcript records session start + user message. Must
    stay in the helper so the JSONL ordering is preserved."""
    src = inspect.getsource(AgenticLoop._emit_session_start_signals)
    assert "record_session_start" in src
    assert "record_user_message" in src


def test_helper_owns_session_started_hook() -> None:
    """OpenClaw agent:bootstrap pattern — SESSION_STARTED fires after
    transcript records so subscribers see the session row before the
    pipeline-level lifecycle event."""
    src = inspect.getsource(AgenticLoop._emit_session_start_signals)
    assert "HookEvent.SESSION_STARTED" in src


# ---------------------------------------------------------------------------
# arun delegates to the helper
# ---------------------------------------------------------------------------


def test_arun_calls_session_start_helper() -> None:
    """``arun`` body must call the helper exactly once before the
    while-loop. Without this the extraction is dead code and
    behaviour silently reverts to pre-refactor (inline block missing).
    Mirrors the DONT-table "stub disguise" lens."""
    src = inspect.getsource(AgenticLoop.arun)
    assert "await self._emit_session_start_signals(user_input)" in src


def test_arun_surfaces_intercept_result_verbatim() -> None:
    """If the helper returns an AgenticResult (blocked), ``arun``
    must return it directly — not wrap it, not log + drop it. Pin
    the early-exit pattern so a future refactor doesn't accidentally
    swallow the blocked result."""
    src = inspect.getsource(AgenticLoop.arun)
    # The exact pattern arun uses:
    assert "intercept_result = await self._emit_session_start_signals(user_input)" in src
    assert "if intercept_result is not None:\n            return intercept_result" in src


def test_arun_no_longer_inlines_session_start_block() -> None:
    """Anti-residue guard — the extracted lines must NOT remain in
    ``arun``'s body (would double-fire hooks + double-record
    transcript)."""
    src = inspect.getsource(AgenticLoop.arun)
    # USER_INPUT_RECEIVED hook should now live ONLY in the helper.
    assert "HookEvent.USER_INPUT_RECEIVED" not in src
    # SESSION_STARTED moved too.
    assert "HookEvent.SESSION_STARTED" not in src
    # COGNITIVE_PERCEIVE emit is in the helper now.
    assert "HookEvent.COGNITIVE_PERCEIVE" not in src
    # Transcript session record calls moved.
    assert "record_session_start" not in src
    assert "record_user_message" not in src
