"""Interactive fleet view — Stage 2 (docs/plans/2026-07-03-fleet-view.md).

Tests the pure render/format helpers + the session-scoped last-snapshot holder.
The full-screen ``prompt_toolkit`` Application event loop is intentionally NOT
spun here (it needs a real TTY) — Stage 1/1.5 tested the parsers, not the
subprocess, and Stage 2 tests the row/detail builders, not the app loop.
"""

from __future__ import annotations

from typing import Any

import core.ui.fleet as fleet_mod
import pytest
from core.ui.fleet import (
    FleetAgent,
    FleetRegistry,
    get_last_fleet_snapshot,
    set_last_fleet_snapshot,
)
from core.ui.fleet_view import (
    EMPTY_MESSAGE,
    build_detail_lines,
    build_fleet_rows,
    compact_elapsed,
    compact_tokens,
    run_fleet_view,
)


class TestCompactTokens:
    def test_thousands_round_to_k(self) -> None:
        assert compact_tokens(160_000) == "↓160k"
        assert compact_tokens(73_000) == "↓73k"

    def test_millions_show_one_decimal(self) -> None:
        assert compact_tokens(1_200_000) == "↓1.2M"
        assert compact_tokens(2_000_000) == "↓2M"  # trailing .0 dropped

    def test_small_counts_raw_and_zero_is_blank(self) -> None:
        assert compact_tokens(512) == "↓512"
        # 0 / negative → "" (subscription / CLI exposes no usage; never faked)
        assert compact_tokens(0) == ""
        assert compact_tokens(-5) == ""


class TestCompactElapsed:
    def test_matches_screenshot_shape(self) -> None:
        assert compact_elapsed(288) == "4m48s"  # 4*60 + 48
        assert compact_elapsed(171) == "2m51s"  # 2*60 + 51

    def test_sub_minute_and_hours(self) -> None:
        assert compact_elapsed(9) == "9s"
        assert compact_elapsed(0) == "0s"
        assert compact_elapsed(3840) == "1h04m"  # 64 minutes


def _agent(**kw: Any) -> FleetAgent:
    base: dict[str, Any] = {"task_id": "t", "start_ts": 100.0}
    base.update(kw)
    return FleetAgent(**base)


class TestBuildFleetRows:
    def test_row_shape_role_activity_elapsed_tokens(self) -> None:
        agent = _agent(
            task_id="t1",
            role="general-purpose",
            status="running",
            end_ts=100.0 + 288.0,
            tokens=160_000,
            current_activity="Reading _render_activity",
        )
        rows = build_fleet_rows([agent], width=200)
        assert len(rows) == 1
        row = rows[0]
        assert "general-purpose" in row
        assert "Reading _render_activity" in row
        assert "4m48s" in row
        assert "↓160k" in row
        assert row.startswith("  ")  # unselected → 2-space pointer gap

    def test_selected_row_gets_pointer(self) -> None:
        agent = _agent(task_id="t1", role="patcher", status="done", end_ts=100.0)
        rows = build_fleet_rows([agent], selected_index=0, width=200)
        assert rows[0].startswith("❯ ")

    def test_zero_tokens_and_no_activity_are_dropped(self) -> None:
        # done agent: current_activity cleared, subscription call → 0 tokens.
        agent = _agent(task_id="t1", role="scout", status="done", end_ts=100.0 + 5.0)
        row = build_fleet_rows([agent], width=200)[0]
        assert "↓" not in row  # no token segment
        # only glyph+role and elapsed remain → exactly one dot separator
        assert row.count(" · ") == 1
        assert "5s" in row

    def test_running_first_ordering_flows_through_snapshot(self) -> None:
        reg = FleetRegistry()
        # dispatched earlier but already done ...
        reg.on_dispatch("done1", role="finished", start_ts=100.0)
        reg.on_state("done1", status="done", elapsed_s=5.0)
        # ... vs dispatched later but still running.
        reg.on_dispatch("run1", role="alive", start_ts=200.0)
        rows = build_fleet_rows(reg.snapshot(), width=200)
        assert len(rows) == 2
        # snapshot() puts running first, and build_fleet_rows preserves order.
        assert "alive" in rows[0]
        assert "finished" in rows[1]

    def test_truncation_respects_width(self) -> None:
        agent = _agent(
            task_id="t1",
            role="a-very-long-role-name-that-exceeds",
            status="running",
            current_activity="and a very long activity string as well",
        )
        row = build_fleet_rows([agent], width=20)[0]
        assert len(row) == 20
        assert row.endswith("…")

    def test_empty_agents_returns_empty_list(self) -> None:
        assert build_fleet_rows([], width=200) == []


class TestBuildDetailLines:
    def test_detail_pane_carries_all_fields(self) -> None:
        agent = _agent(
            task_id="task-abc",
            role="general-purpose",
            description="research the fleet view design",
            status="done",
            end_ts=100.0 + 288.0,
            tokens=160_000,
        )
        lines = build_detail_lines(agent)
        blob = "\n".join(lines)
        assert "task-abc" in blob
        assert "general-purpose" in blob
        assert "research the fleet view design" in blob
        assert "done" in blob
        assert "4m48s" in blob
        assert "↓160k" in blob

    def test_missing_fields_render_none_placeholder(self) -> None:
        agent = _agent(task_id="t1", status="done", end_ts=100.0)
        lines = build_detail_lines(agent)
        blob = "\n".join(lines)
        assert "role       (none)" in blob
        assert "tokens     (none)" in blob  # 0 tokens → (none)
        assert "activity   (none)" in blob


class TestLastSnapshotHolder:
    def test_set_get_roundtrip_returns_copy(self) -> None:
        agents = [_agent(task_id="t1", role="r1"), _agent(task_id="t2", role="r2")]
        set_last_fleet_snapshot(agents)
        got = get_last_fleet_snapshot()
        assert [a.task_id for a in got] == ["t1", "t2"]
        # A copy of the list — mutating the returned list must not affect the holder.
        got.append(_agent(task_id="t3"))
        assert len(get_last_fleet_snapshot()) == 2

    def test_holder_starts_empty_after_reset(self) -> None:
        set_last_fleet_snapshot([])
        assert get_last_fleet_snapshot() == []

    def test_holder_is_module_level_single_owner(self) -> None:
        # The holder is the fleet module global the /fleet handler reads.
        set_last_fleet_snapshot([_agent(task_id="only")])
        assert len(fleet_mod._LAST_SNAPSHOT) == 1
        assert fleet_mod._LAST_SNAPSHOT[0].task_id == "only"


class TestRunFleetViewEmpty:
    def test_empty_snapshot_prints_message_no_app(self, capsys: pytest.CaptureFixture[str]) -> None:
        # Empty fleet must NOT spin a full-screen app (which would need a TTY);
        # it prints the honest one-liner and returns.
        run_fleet_view([])
        out = capsys.readouterr().out
        assert EMPTY_MESSAGE in out


def test_compact_tokens_boundary_promotes_to_m() -> None:
    """Codex: 999_500+ rounds to 1000k → must promote to 1M, not '↓1000k'."""
    from core.ui.fleet_view import compact_tokens

    assert compact_tokens(999_499) == "↓999k"
    assert compact_tokens(999_500) == "↓1M"
    assert compact_tokens(1_000_000) == "↓1M"


def test_clear_last_fleet_snapshot_drops_prior_session() -> None:
    """Codex: a new session must not see the prior session's fleet."""
    from core.ui.fleet import (
        FleetRegistry,
        clear_last_fleet_snapshot,
        get_last_fleet_snapshot,
        set_last_fleet_snapshot,
    )

    reg = FleetRegistry()
    reg.on_dispatch("t1", role="patcher")
    set_last_fleet_snapshot(reg.snapshot())
    assert get_last_fleet_snapshot()  # non-empty
    clear_last_fleet_snapshot()
    assert get_last_fleet_snapshot() == []
