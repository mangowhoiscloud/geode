"""PR-4 C-3 — Episodic action-outcome memory invariants.

Pins the contract for ``core/memory/episodic.py`` (Episode dataclass,
EpisodicStore append + rotate + recent), the ContextVar bridge
(``core/agent/cognitive_state_ctx.py``), and the bootstrap hook
that records one Episode per TOOL_EXEC_ENDED event.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest
from core.memory.episodic import (
    EPISODE_LOG_MAX_ROWS,
    Episode,
    EpisodicStore,
    _summarise_tool_input,
)

# ---------------------------------------------------------------------------
# Episode dataclass
# ---------------------------------------------------------------------------


def test_episode_to_jsonl_roundtrip() -> None:
    ep = Episode(
        timestamp_ns=12345,
        session_id="s-abc",
        round=3,
        tool_name="bash",
        tool_input_head="ls",
        success=True,
        error=None,
        duration_ms=42.0,
        cognitive_state={"goal": "x", "round_count": 3},
    )
    line = ep.to_jsonl()
    payload = json.loads(line)
    assert payload["tool_name"] == "bash"
    assert payload["success"] is True
    assert payload["round"] == 3
    assert payload["cognitive_state"]["goal"] == "x"


def test_episode_to_jsonl_no_trailing_newline() -> None:
    """``append`` writes the newline; ``to_jsonl`` returns the row only.
    Otherwise the file ends up double-newline-separated."""
    ep = Episode(
        timestamp_ns=1,
        session_id="s",
        round=0,
        tool_name="t",
        tool_input_head="",
        success=True,
        error=None,
        duration_ms=0.0,
    )
    assert not ep.to_jsonl().endswith("\n")


# ---------------------------------------------------------------------------
# _summarise_tool_input
# ---------------------------------------------------------------------------


def test_summarise_tool_input_none() -> None:
    assert _summarise_tool_input(None) == ""


def test_summarise_tool_input_str_passthrough() -> None:
    assert _summarise_tool_input("hello") == "hello"


def test_summarise_tool_input_dict_to_json() -> None:
    out = _summarise_tool_input({"path": "./foo.txt", "mode": "r"})
    assert "path" in out and "foo.txt" in out


def test_summarise_tool_input_caps_long() -> None:
    out = _summarise_tool_input("x" * 500)
    assert out.endswith("…")
    # 200 head + ellipsis
    assert len(out) == 201


# ---------------------------------------------------------------------------
# EpisodicStore — append + rotate + recent
# ---------------------------------------------------------------------------


def _make_episode(i: int, *, tool: str = "bash", session: str = "s-1") -> Episode:
    return Episode(
        timestamp_ns=i,
        session_id=session,
        round=i,
        tool_name=tool,
        tool_input_head=f"input{i}",
        success=True,
        error=None,
        duration_ms=float(i),
    )


def test_store_append_creates_file_and_writes_row(tmp_path: Path) -> None:
    store = EpisodicStore(path=tmp_path / "episodes.jsonl")
    store.append(_make_episode(1))
    assert store.path.exists()
    rows = store.path.read_text(encoding="utf-8").strip().splitlines()
    assert len(rows) == 1
    assert json.loads(rows[0])["timestamp_ns"] == 1


def test_store_append_creates_parent_dir(tmp_path: Path) -> None:
    """Parent dir is created on first append — the writer must not
    assume the global ~/.geode/memory/ dir exists."""
    nested = tmp_path / "deep" / "nested" / "memory"
    store = EpisodicStore(path=nested / "episodes.jsonl")
    store.append(_make_episode(1))
    assert (nested / "episodes.jsonl").exists()


def test_store_rotate_triggers_at_25pct_overshoot(tmp_path: Path) -> None:
    """Rotation fires when row count exceeds ``max_rows + max_rows//4``.
    Append exactly max_rows + 1 over the threshold to force one
    rotation; verify the file then holds exactly ``max_rows`` rows
    AND the newest entry survives."""
    store = EpisodicStore(path=tmp_path / "episodes.jsonl", max_rows=100)
    threshold = 100 + 100 // 4  # 125
    for i in range(1, threshold + 2):  # 126 rows → rotation triggers on the 126th
        store.append(_make_episode(i))
    rows = store.path.read_text(encoding="utf-8").strip().splitlines()
    assert len(rows) == 100, f"expected 100 after rotation, got {len(rows)}"
    last = json.loads(rows[-1])
    first = json.loads(rows[0])
    assert last["timestamp_ns"] == 126
    # Oldest kept = 126 - 100 + 1 = 27
    assert first["timestamp_ns"] == 27


def test_store_rotate_keeps_growth_bounded(tmp_path: Path) -> None:
    """Long-running: 130 appends with cap 100 leaves the file holding
    at most ``max_rows * 1.25`` (125) rows — the 25% overshoot is the
    documented worst case."""
    store = EpisodicStore(path=tmp_path / "episodes.jsonl", max_rows=100)
    for i in range(1, 131):
        store.append(_make_episode(i))
    rows = store.path.read_text(encoding="utf-8").strip().splitlines()
    assert len(rows) <= 125
    last = json.loads(rows[-1])
    assert last["timestamp_ns"] == 130


def test_store_no_rotate_below_threshold(tmp_path: Path) -> None:
    """At max + 24% (just under 25% overshoot) the rotate does NOT
    fire — avoid thrashing on the boundary."""
    store = EpisodicStore(path=tmp_path / "episodes.jsonl", max_rows=100)
    for i in range(1, 125):  # 124 rows = max + 24%
        store.append(_make_episode(i))
    rows = store.path.read_text(encoding="utf-8").strip().splitlines()
    assert len(rows) == 124


def test_store_recent_returns_newest_first(tmp_path: Path) -> None:
    store = EpisodicStore(path=tmp_path / "episodes.jsonl", max_rows=100)
    for i in range(1, 11):
        store.append(_make_episode(i))
    recent = store.recent(limit=3)
    assert len(recent) == 3
    assert [e.timestamp_ns for e in recent] == [10, 9, 8]


def test_store_recent_filters_by_tool_name(tmp_path: Path) -> None:
    store = EpisodicStore(path=tmp_path / "episodes.jsonl", max_rows=100)
    for i in range(1, 6):
        store.append(_make_episode(i, tool="bash"))
    for i in range(6, 11):
        store.append(_make_episode(i, tool="read"))
    recent = store.recent(tool_name="bash", limit=10)
    assert len(recent) == 5
    assert all(e.tool_name == "bash" for e in recent)


def test_store_recent_filters_by_session_id(tmp_path: Path) -> None:
    store = EpisodicStore(path=tmp_path / "episodes.jsonl", max_rows=100)
    store.append(_make_episode(1, session="s-A"))
    store.append(_make_episode(2, session="s-B"))
    store.append(_make_episode(3, session="s-A"))
    recent = store.recent(session_id="s-A")
    assert len(recent) == 2
    assert all(e.session_id == "s-A" for e in recent)


def test_store_recent_empty_log_returns_empty_list(tmp_path: Path) -> None:
    store = EpisodicStore(path=tmp_path / "absent.jsonl")
    assert store.recent() == []


def test_store_recent_skips_malformed_rows(tmp_path: Path) -> None:
    """Anti-deception — partial writes / legacy schemas must not
    raise; they're skipped with a WARN. PR-5 retrieval runs against
    the live log on every audit."""
    path = tmp_path / "episodes.jsonl"
    path.write_text(
        "\n".join(
            [
                _make_episode(1).to_jsonl(),
                "this is not json",
                _make_episode(2).to_jsonl(),
                "{}",  # valid JSON but missing schema fields
                _make_episode(3).to_jsonl(),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    store = EpisodicStore(path=path)
    recent = store.recent(limit=10)
    assert [e.timestamp_ns for e in recent] == [3, 2, 1]


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


def test_default_max_rows_is_1000() -> None:
    """Plan Q4 — cap 1000 episodes (rolling)."""
    assert EPISODE_LOG_MAX_ROWS == 1000


def test_global_paths_constants_exist() -> None:
    from core.paths import GLOBAL_EPISODES_LOG, GLOBAL_MEMORY_DIR

    assert GLOBAL_MEMORY_DIR.name == "memory"
    assert GLOBAL_EPISODES_LOG.name == "episodes.jsonl"
    assert GLOBAL_EPISODES_LOG.parent == GLOBAL_MEMORY_DIR


# ---------------------------------------------------------------------------
# ContextVar bridge — get/set parity
# ---------------------------------------------------------------------------


def test_cognitive_state_ctx_has_paired_get_set() -> None:
    """CLAUDE.md "ContextVar injection" — every get_*() must pair
    with a set_*(). Both pairs live in cognitive_state_ctx."""
    from core.agent import cognitive_state_ctx

    assert hasattr(cognitive_state_ctx, "get_cognitive_state")
    assert hasattr(cognitive_state_ctx, "set_cognitive_state")
    assert hasattr(cognitive_state_ctx, "get_session_id")
    assert hasattr(cognitive_state_ctx, "set_session_id")


def test_cognitive_state_ctx_default_is_none() -> None:
    """Unset ContextVar reads must be safe (not raise) — hooks may
    fire outside the agentic loop (e.g. background tool execution)."""
    from core.agent.cognitive_state_ctx import get_cognitive_state, get_session_id

    # No bind — defaults
    assert get_cognitive_state() is None
    assert get_session_id() == ""


def test_cognitive_state_ctx_set_get_roundtrip() -> None:
    from core.agent.cognitive_state import CognitiveState
    from core.agent.cognitive_state_ctx import (
        get_cognitive_state,
        get_session_id,
        set_cognitive_state,
        set_session_id,
    )

    state = CognitiveState(goal="x")
    set_cognitive_state(state)
    set_session_id("s-ctx-test")
    try:
        assert get_cognitive_state() is state
        assert get_session_id() == "s-ctx-test"
    finally:
        # clean up so other tests aren't affected
        set_cognitive_state(None)
        set_session_id("")


# ---------------------------------------------------------------------------
# Bootstrap wiring — TOOL_EXEC_ENDED handler registered
# ---------------------------------------------------------------------------


def test_bootstrap_registers_episodic_memory_hook() -> None:
    """Pin the bootstrap registration. Without this, the recorder
    would exist but never fire (Handler exists ≠ handler fires —
    CLAUDE.md Hook registration rule)."""
    from core.wiring import bootstrap

    src = inspect.getsource(bootstrap)
    # the plugin registration call
    assert '"episodic_memory_hook"' in src
    # registers on TOOL_EXEC_ENDED
    assert "HookEvent.TOOL_EXEC_ENDED" in src
    assert "episodic_memory_recorder" in src


def test_agentic_loop_arun_binds_contextvars() -> None:
    """Pin the writer side of the ContextVar parity. arun() must
    bind both ContextVars at session start so the bootstrap hook
    handler sees a bound state.

    PR-D Phase 1 (2026-05-21) — the bind moved from ``arun``'s body
    into the extracted ``_emit_session_start_signals`` helper which
    ``arun`` always awaits before the while-loop. Either call site
    satisfies the contract; check both."""
    from core.agent.loop.agent_loop import AgenticLoop

    arun_src = inspect.getsource(AgenticLoop.arun)
    helper_src = inspect.getsource(AgenticLoop._emit_session_start_signals)
    # arun must AT LEAST call the helper that owns the bind.
    assert "_emit_session_start_signals" in arun_src
    # And the helper must do the bind (so the parity claim holds
    # transitively).
    assert "set_cognitive_state(self.cognitive_state)" in helper_src
    assert "set_session_id(self._session_id)" in helper_src


@pytest.fixture(autouse=True)
def _reset_singleton() -> None:
    """Reset the EpisodicStore singleton between tests so each test
    that uses the global accessor starts clean."""
    from core.memory.episodic import set_episodic_store

    set_episodic_store(None)
    yield
    set_episodic_store(None)


def test_get_episodic_store_returns_singleton() -> None:
    from core.memory.episodic import get_episodic_store

    a = get_episodic_store()
    b = get_episodic_store()
    assert a is b


def test_set_episodic_store_overrides_singleton(tmp_path: Path) -> None:
    from core.memory.episodic import get_episodic_store, set_episodic_store

    custom = EpisodicStore(path=tmp_path / "x.jsonl")
    set_episodic_store(custom)
    assert get_episodic_store() is custom
