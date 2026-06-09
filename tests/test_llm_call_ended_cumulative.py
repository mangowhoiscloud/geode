"""PR-COMM-3d — AgenticLoop._call_llm LLM_CALL_ENDED emit + cumulative
tokens handler tests.

PR-COMM-3 #1593 landed the SQLite ``agent_runtime_state.total_*_tokens``
columns. PR-COMM-3b #1594 wired SESSION_ENDED + SUBAGENT_COMPLETED.
The ``accumulate_tokens_and_cost`` writer was registered but no LLM call
site fired ``LLM_CALL_ENDED`` with the required ``session_id`` + ``usage``
payload — the writer was effectively dead code.

PR-COMM-3d closes that gap:

1. AgenticLoop._call_llm emits ``LLM_CALL_STARTED`` before
   ``adapter.acomplete`` and ``LLM_CALL_ENDED`` after (both success +
   error paths). The success payload carries ``session_id``, ``model``,
   ``provider``, ``adapter``, ``latency_ms``, ``usage`` dict
   (``input_tokens`` / ``output_tokens`` / ``cached_input_tokens``),
   and ``cost_usd`` (computed via ``token_tracker.calculate_cost``).
2. bootstrap.py adds ``agent_runtime_llm_call_ended`` handler that
   forwards the payload into ``accumulate_tokens_and_cost``.

Coverage map:

* :class:`TestHookHandlerCumulativeAccumulation` — bootstrap-registered
  handler accumulates correctly across multiple LLM_CALL_ENDED fires.
* :class:`TestZeroPayloadIgnored` — router/calls/* legacy callers that
  fire LLM_CALL_ENDED without ``usage`` don't pollute the table.
* :class:`TestMissingSessionIdIgnored` — empty ``session_id`` no-ops.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from core.memory.session_manager import SessionManager

from core.observability import agent_runtime_state as ars


@pytest.fixture(autouse=True)
def isolate_sessions_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "sessions.db"
    SessionManager(db_path=db)
    monkeypatch.setattr("core.memory.session_manager._get_default_db_path", lambda: db)
    ars._reset_for_tests(db_path=db)
    yield db
    ars._reset_for_tests()


class TestHookHandlerCumulativeAccumulation:
    """End-to-end: bootstrap's ``agent_runtime_llm_call_ended`` handler
    consumes the AgenticLoop's LLM_CALL_ENDED payload and writes the
    cumulative totals into ``agent_runtime_state``."""

    def test_single_call_writes_totals(self, tmp_path: Path) -> None:
        from core.wiring.bootstrap import build_hooks

        from core.hooks import HookEvent

        hooks, _, _ = build_hooks(session_key="t", run_id="r-1", log_dir=tmp_path)

        hooks.trigger(
            HookEvent.LLM_CALL_ENDED,
            {
                "session_id": "s-llm-1",
                "model": "claude-sonnet-4-6",
                "provider": "anthropic",
                "adapter": "claude-cli",
                "latency_ms": 432.1,
                "error": None,
                "usage": {
                    "input_tokens": 1000,
                    "output_tokens": 500,
                    "cached_input_tokens": 200,
                },
                "cost_usd": 0.045,
            },
        )

        state = ars.get_agent_runtime_state("s-llm-1")
        assert state is not None
        assert state.total_input_tokens == 1000
        assert state.total_output_tokens == 500
        assert state.total_cached_input_tokens == 200
        # round(0.045 * 100) = 4 (round-half-even → 4)
        assert state.total_cost_cents == 4

    def test_multiple_calls_sum_cumulatively(self, tmp_path: Path) -> None:
        from core.wiring.bootstrap import build_hooks

        from core.hooks import HookEvent

        hooks, _, _ = build_hooks(session_key="t", run_id="r-1", log_dir=tmp_path)

        for in_tok, out_tok, cost in [(100, 50, 0.005), (200, 100, 0.010), (300, 150, 0.015)]:
            hooks.trigger(
                HookEvent.LLM_CALL_ENDED,
                {
                    "session_id": "s-llm-sum",
                    "model": "claude-sonnet-4-6",
                    "usage": {
                        "input_tokens": in_tok,
                        "output_tokens": out_tok,
                        "cached_input_tokens": 0,
                    },
                    "cost_usd": cost,
                    "error": None,
                },
            )

        state = ars.get_agent_runtime_state("s-llm-sum")
        assert state is not None
        assert state.total_input_tokens == 600
        assert state.total_output_tokens == 300
        # round(0.5)+round(1.0)+round(1.5) = 0 + 1 + 2 = 3 (banker's rounding)
        assert state.total_cost_cents == 3


class TestZeroPayloadIgnored:
    """Router/calls/*.py one-off LLM_CALL_ENDED emitters fire with
    ``model`` / ``provider`` / ``latency_ms`` but NO ``usage`` /
    ``session_id``. The handler must skip those instead of inserting
    placeholder rows for every adapter heartbeat."""

    def test_no_usage_dict_is_noop(self, tmp_path: Path) -> None:
        import sqlite3

        from core.wiring.bootstrap import build_hooks

        from core.hooks import HookEvent

        hooks, _, _ = build_hooks(session_key="t", run_id="r-1", log_dir=tmp_path)
        # Legacy router/calls/* payload — no session_id, no usage.
        hooks.trigger(
            HookEvent.LLM_CALL_ENDED,
            {
                "model": "claude-sonnet-4-6",
                "provider": "anthropic",
                "function": "call_llm",
                "latency_ms": 100.0,
                "error": None,
            },
        )
        conn = sqlite3.connect(str(tmp_path / "sessions.db"))
        count = conn.execute("SELECT COUNT(*) FROM agent_runtime_state").fetchone()[0]
        assert count == 0

    def test_zero_token_payload_is_noop(self, tmp_path: Path) -> None:
        """Even when session_id is set, a zero-token payload (e.g. failure
        path that fires LLM_CALL_ENDED with empty usage) must not create
        a placeholder row."""
        from core.wiring.bootstrap import build_hooks

        from core.hooks import HookEvent

        hooks, _, _ = build_hooks(session_key="t", run_id="r-1", log_dir=tmp_path)
        hooks.trigger(
            HookEvent.LLM_CALL_ENDED,
            {
                "session_id": "s-zero",
                "usage": {"input_tokens": 0, "output_tokens": 0, "cached_input_tokens": 0},
                "cost_usd": 0.0,
            },
        )
        assert ars.get_agent_runtime_state("s-zero") is None


class TestMissingSessionIdIgnored:
    def test_no_session_id_skips_write(self, tmp_path: Path) -> None:
        import sqlite3

        from core.wiring.bootstrap import build_hooks

        from core.hooks import HookEvent

        hooks, _, _ = build_hooks(session_key="t", run_id="r-1", log_dir=tmp_path)
        hooks.trigger(
            HookEvent.LLM_CALL_ENDED,
            {
                "usage": {"input_tokens": 100, "output_tokens": 50},
                "cost_usd": 0.01,
                "error": None,
            },
        )
        conn = sqlite3.connect(str(tmp_path / "sessions.db"))
        count = conn.execute("SELECT COUNT(*) FROM agent_runtime_state").fetchone()[0]
        assert count == 0
