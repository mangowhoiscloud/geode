"""PR-F — sub-agent state propagation invariants.

Pins the new ``parent_session_key`` ContextVar pair, the
``Episode.parent_session_key`` field, the bootstrap hook reader, and
the AgenticLoop wire-up so child Episode rows carry the parent's
session id for cross-session attribution (PR-E aggregator dependency).

Concern #3 from the post-sprint frontier matrix.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest
from core.agent.cognitive_state_ctx import (
    get_parent_session_key,
    set_parent_session_key,
)
from core.memory.episodic import Episode, EpisodicStore

# ---------------------------------------------------------------------------
# ContextVar pair
# ---------------------------------------------------------------------------


def test_parent_session_key_default_is_empty() -> None:
    """Unset ContextVar reads must be safe (not raise) — hooks may
    fire outside the agentic loop (e.g. background tool invocation)
    and top-level loops have no parent."""
    # The default state in a fresh asyncio Context is "", but in
    # this test process the var may have been bound by a previous
    # test. Reset to baseline before asserting.
    set_parent_session_key("")
    assert get_parent_session_key() == ""


def test_parent_session_key_set_get_roundtrip() -> None:
    set_parent_session_key("s-parent-001")
    try:
        assert get_parent_session_key() == "s-parent-001"
    finally:
        set_parent_session_key("")


def test_parent_session_key_paired_get_set_exist() -> None:
    """CLAUDE.md ContextVar-injection rule — every getter pairs with
    a setter in the same module. Pin both names so a refactor that
    drops one surfaces here."""
    from core.agent import cognitive_state_ctx

    assert hasattr(cognitive_state_ctx, "get_parent_session_key")
    assert hasattr(cognitive_state_ctx, "set_parent_session_key")
    # Both names are in __all__ so external callers can import them.
    assert "get_parent_session_key" in cognitive_state_ctx.__all__
    assert "set_parent_session_key" in cognitive_state_ctx.__all__


# ---------------------------------------------------------------------------
# Episode dataclass — parent_session_key field
# ---------------------------------------------------------------------------


def test_episode_has_parent_session_key_field() -> None:
    """Defaults to empty string so older readers + hand-constructed
    Episodes don't break."""
    from dataclasses import fields

    field_names = {f.name for f in fields(Episode)}
    assert "parent_session_key" in field_names
    ep = Episode(
        timestamp_ns=1,
        session_id="s-child",
        round=0,
        tool_name="t",
        tool_input_head="",
        success=True,
        error=None,
        duration_ms=0.0,
    )
    assert ep.parent_session_key == ""


def test_episode_jsonl_roundtrip_includes_parent_session_key() -> None:
    ep = Episode(
        timestamp_ns=12345,
        session_id="s-child",
        round=2,
        tool_name="bash",
        tool_input_head="ls",
        success=True,
        error=None,
        duration_ms=10.0,
        parent_session_key="s-parent-xyz",
    )
    payload = json.loads(ep.to_jsonl())
    assert payload["parent_session_key"] == "s-parent-xyz"


def test_episode_store_persists_parent_session_key(tmp_path: Path) -> None:
    """End-to-end: store.append → file → store.recent recovers the
    field. Without this, the parent linkage would be writeable but
    not readable, half-disconnecting the attribution path."""
    path = tmp_path / "episodes.jsonl"
    store = EpisodicStore(path=path)
    ep = Episode(
        timestamp_ns=1,
        session_id="s-child",
        round=0,
        tool_name="bash",
        tool_input_head="",
        success=True,
        error=None,
        duration_ms=0.0,
        parent_session_key="s-parent-abc",
    )
    store.append(ep)
    recovered = store.recent(limit=10)
    assert len(recovered) == 1
    assert recovered[0].parent_session_key == "s-parent-abc"


def test_episode_legacy_rows_without_parent_id_still_parse(tmp_path: Path) -> None:
    """Older JSONL rows (written before PR-F) lack the
    ``parent_session_key`` key. recent() must still return them with
    the default empty string — not skip them."""
    path = tmp_path / "episodes.jsonl"
    # Hand-write a row without parent_session_key (legacy schema)
    legacy_row = {
        "timestamp_ns": 1,
        "session_id": "s-legacy",
        "round": 0,
        "tool_name": "t",
        "tool_input_head": "",
        "success": True,
        "error": None,
        "duration_ms": 0.0,
        "cognitive_state": {},
    }
    path.write_text(json.dumps(legacy_row) + "\n", encoding="utf-8")
    store = EpisodicStore(path=path)
    rows = store.recent()
    # Legacy row parses; parent_session_key defaults to "".
    assert len(rows) == 1
    assert rows[0].session_id == "s-legacy"
    assert rows[0].parent_session_key == ""


# ---------------------------------------------------------------------------
# Bootstrap hook reads the parent_session_key ContextVar
# ---------------------------------------------------------------------------


def test_bootstrap_handler_reads_parent_session_key() -> None:
    """Anti-disconnection — the bootstrap TOOL_EXEC_ENDED handler
    must consult ``get_parent_session_key`` so the value plumbs into
    Episode. Source-pin so a refactor that drops the read surfaces
    here, not at runtime."""
    from core.wiring import bootstrap

    src = inspect.getsource(bootstrap)
    assert "get_parent_session_key" in src
    assert "parent_session_key=parent_session_key" in src


# ---------------------------------------------------------------------------
# AgenticLoop wires the parent key into the ContextVar
# ---------------------------------------------------------------------------


def test_agentic_loop_binds_parent_session_key_from_parent_key() -> None:
    """PR-D Phase 1 extracted session-start signals into a helper.
    The PR-F lineage bind must live in that same helper so a sub-
    agent's first round sees the parent ContextVar bound."""
    from core.agent.loop.agent_loop import AgenticLoop

    src = inspect.getsource(AgenticLoop._emit_session_start_signals)
    assert "set_parent_session_key(self._parent_session_key)" in src


# ---------------------------------------------------------------------------
# AgenticLoop constructor preserves parent_session_key kwarg
# ---------------------------------------------------------------------------


def test_agentic_loop_init_accepts_parent_session_key() -> None:
    """The constructor's parent_session_key kwarg already existed;
    pin it so a future refactor doesn't drop the entry point the
    sub-agent spawner relies on."""
    from core.agent.loop.agent_loop import AgenticLoop

    sig = inspect.signature(AgenticLoop.__init__)
    assert "parent_session_key" in sig.parameters
    assert sig.parameters["parent_session_key"].default == ""


# ---------------------------------------------------------------------------
# Fixture isolation — reset ContextVar between tests
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_parent_session_key() -> None:
    """ContextVar state can leak across tests in the same task.
    Reset to default before each test so per-test assertions about
    the empty default are deterministic."""
    set_parent_session_key("")
    yield
    set_parent_session_key("")
