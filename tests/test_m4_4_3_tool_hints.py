"""ADR-012 M4.4.3 — tool_hints reader + orchestrator wiring invariants.

Pins:
- ``load_recent_episodes`` returns ``[]`` on missing ledger / read
  failure / import failure (graceful).
- ``find_failing_tools`` aggregates by tool, applies min_invocations +
  fail_rate threshold, sorts by fail_rate desc with total desc
  tiebreak, caps at top_k.
- Per-tool ``recent_error`` captures the *most-recent* non-empty error
  string (episodes pass in newest-first order).
- ``format_tool_hints_block`` renders a ``<tool-hints>`` block; empty
  list → empty string. Tools without recent_error get a shorter line.
- Orchestrator: ``tool_hints`` slot active + episodes have failing tools
  → ``<tool-hints>`` block prepended to system prompt.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest


@dataclass
class _StubEpisode:
    """Minimal duck-typed Episode for testing (avoid importing the real one)."""

    tool_name: str
    success: bool
    error: str | None = None


# load_recent_episodes ------------------------------------------------------


def test_load_recent_returns_empty_on_store_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """``EpisodicStore`` raise → graceful ``[]``."""
    from core.self_improving_loop import tool_hints as th

    class _BoomStore:
        def __init__(self) -> None:
            raise RuntimeError("synthetic")

    monkeypatch.setattr("core.memory.episodic.EpisodicStore", _BoomStore)
    assert th.load_recent_episodes() == []


def test_load_recent_returns_list_from_store(monkeypatch: pytest.MonkeyPatch) -> None:
    from core.self_improving_loop import tool_hints as th

    class _StubStore:
        def __init__(self) -> None:
            pass

        def recent(self, *, limit: int) -> list[_StubEpisode]:
            return [_StubEpisode("X", True), _StubEpisode("Y", False, "err")]

    monkeypatch.setattr("core.memory.episodic.EpisodicStore", _StubStore)
    eps = th.load_recent_episodes(limit=5)
    assert len(eps) == 2


# find_failing_tools --------------------------------------------------------


def test_find_returns_empty_for_top_k_zero() -> None:
    from core.self_improving_loop.tool_hints import find_failing_tools

    assert find_failing_tools([_StubEpisode("X", False, "e")] * 5, top_k=0) == []


def test_find_filters_below_min_invocations() -> None:
    """Tool with only 1-2 calls is below default ``MIN_INVOCATIONS=3``."""
    from core.self_improving_loop.tool_hints import find_failing_tools

    episodes = [_StubEpisode("X", False, "err")] * 2  # only 2 calls
    assert find_failing_tools(episodes, top_k=5) == []


def test_find_filters_below_fail_rate_threshold() -> None:
    """5 success + 1 fail = 1/6 = 0.166 < 0.34 threshold."""
    from core.self_improving_loop.tool_hints import find_failing_tools

    episodes = [
        _StubEpisode("X", True),
        _StubEpisode("X", True),
        _StubEpisode("X", True),
        _StubEpisode("X", True),
        _StubEpisode("X", True),
        _StubEpisode("X", False, "rare error"),
    ]
    assert find_failing_tools(episodes, top_k=5) == []


def test_find_surfaces_failing_tools() -> None:
    """3 calls, 2 failures = 2/3 = 0.667 ≥ threshold → emit."""
    from core.self_improving_loop.tool_hints import find_failing_tools

    episodes = [
        _StubEpisode("Bash", False, "command not found"),
        _StubEpisode("Bash", False, "permission denied"),
        _StubEpisode("Bash", True),
    ]
    hints = find_failing_tools(episodes, top_k=5)
    assert len(hints) == 1
    assert hints[0].tool_name == "Bash"
    assert hints[0].fail_count == 2
    assert hints[0].total == 3


def test_find_uses_most_recent_error_per_tool() -> None:
    """Episodes are newest-first; the first non-empty error wins."""
    from core.self_improving_loop.tool_hints import find_failing_tools

    # Newest first: failing with "RECENT", then earlier failure with "OLD"
    episodes = [
        _StubEpisode("Tool", False, "RECENT error"),
        _StubEpisode("Tool", False, "OLD error"),
        _StubEpisode("Tool", False, "OLDER error"),
    ]
    hints = find_failing_tools(episodes, top_k=5)
    assert hints[0].recent_error == "RECENT error"


def test_find_sorts_by_fail_rate_desc_then_total() -> None:
    """Higher fail_rate ranks first; tie on rate → higher total wins."""
    from core.self_improving_loop.tool_hints import find_failing_tools

    episodes = [
        # Tool A: 4/4 = 1.0 fail rate, 4 calls
        _StubEpisode("A", False, "ea"),
        _StubEpisode("A", False, "ea"),
        _StubEpisode("A", False, "ea"),
        _StubEpisode("A", False, "ea"),
        # Tool B: 3/3 = 1.0 fail rate, 3 calls
        _StubEpisode("B", False, "eb"),
        _StubEpisode("B", False, "eb"),
        _StubEpisode("B", False, "eb"),
        # Tool C: 2/4 = 0.5 fail rate, 4 calls (just above threshold)
        _StubEpisode("C", False, "ec"),
        _StubEpisode("C", False, "ec"),
        _StubEpisode("C", True),
        _StubEpisode("C", True),
    ]
    hints = find_failing_tools(episodes, top_k=5)
    # Order: A (1.0 rate, 4 total), B (1.0 rate, 3 total — same rate, lower total),
    # then C (0.5 rate)
    assert [h.tool_name for h in hints] == ["A", "B", "C"]


def test_find_top_k_caps_results() -> None:
    from core.self_improving_loop.tool_hints import find_failing_tools

    episodes = []
    for tool in "ABCDE":
        episodes.extend([_StubEpisode(tool, False, "e")] * 3)
    hints = find_failing_tools(episodes, top_k=2)
    assert len(hints) == 2


def test_find_skips_non_string_tool_names() -> None:
    """Defensive: malformed episode with non-str tool_name → skipped."""
    from core.self_improving_loop.tool_hints import find_failing_tools

    @dataclass
    class _BadEpisode:
        tool_name: object = None  # not a str
        success: bool = False
        error: str | None = "e"

    good = [_StubEpisode("Good", False, "e")] * 3
    bad = [_BadEpisode()] * 3
    hints = find_failing_tools(good + bad, top_k=5)
    assert [h.tool_name for h in hints] == ["Good"]


def test_find_truncates_long_error_strings() -> None:
    """Recent error trimmed to 80 chars + ellipsis."""
    from core.self_improving_loop.tool_hints import find_failing_tools

    long_err = "x" * 500
    episodes = [_StubEpisode("X", False, long_err)] * 3
    hints = find_failing_tools(episodes, top_k=5)
    assert hints[0].recent_error.endswith("…")
    assert len(hints[0].recent_error) <= 80


def test_find_error_trim_preserves_first_79_chars() -> None:
    """Trim shape is exactly first 79 chars + ellipsis (Codex FLAG #3 pin)."""
    from core.self_improving_loop.tool_hints import find_failing_tools

    error = "abc" * 50  # 150 chars
    episodes = [_StubEpisode("X", False, error)] * 3
    hints = find_failing_tools(episodes, top_k=5)
    assert hints[0].recent_error == error[:79] + "…"
    assert len(hints[0].recent_error) == 80


def test_find_skips_non_bool_success() -> None:
    """Defensive: episode with non-bool ``success`` field → skipped
    (Codex FLAG #4 pin). Mirrors the non-str tool_name guard."""
    from core.self_improving_loop.tool_hints import find_failing_tools

    @dataclass
    class _BadEpisode:
        tool_name: str = "WeirdTool"
        success: object = None  # not a bool
        error: str | None = "e"

    good = [_StubEpisode("Good", False, "e")] * 3
    bad = [_BadEpisode()] * 3
    hints = find_failing_tools(good + bad, top_k=5)
    assert [h.tool_name for h in hints] == ["Good"]


# format_tool_hints_block ---------------------------------------------------


def test_format_empty_returns_empty_string() -> None:
    from core.self_improving_loop.tool_hints import format_tool_hints_block

    assert format_tool_hints_block([]) == ""


def test_format_renders_block_with_error() -> None:
    from core.self_improving_loop.tool_hints import ToolHint, format_tool_hints_block

    hints = [
        ToolHint(
            tool_name="Bash",
            fail_count=3,
            total=5,
            fail_rate=0.6,
            recent_error="permission denied",
        )
    ]
    block = format_tool_hints_block(hints)
    assert block.startswith("<tool-hints>")
    assert block.endswith("</tool-hints>")
    assert "[Bash] 3/5 failed" in block
    assert "permission denied" in block


def test_format_renders_block_without_error() -> None:
    """Tool with empty recent_error → shorter line (no 'recent error:' part)."""
    from core.self_improving_loop.tool_hints import ToolHint, format_tool_hints_block

    hints = [
        ToolHint(
            tool_name="X",
            fail_count=2,
            total=3,
            fail_rate=0.667,
            recent_error="",
        )
    ]
    block = format_tool_hints_block(hints)
    assert "[X] 2/3 failed" in block
    assert "recent error" not in block


# Orchestrator wiring -------------------------------------------------------


def test_orchestrator_prepends_tool_hints_block(monkeypatch: pytest.MonkeyPatch) -> None:
    """tool_hints slot active + failing tool in episodic ledger → block in system."""
    from core.self_improving_loop.in_context_slots import SLOT_TOOL_HINTS, InContextSlot
    from core.self_improving_loop.in_context_wiring import apply_in_context_slots

    monkeypatch.setattr(
        "core.self_improving_loop.in_context_slots._load_in_context_slots_override",
        lambda: {
            SLOT_TOOL_HINTS: InContextSlot(
                name=SLOT_TOOL_HINTS,
                max_entries=3,
                rank_by="success_rate",
                injection_point="system_prompt",
            )
        },
    )
    monkeypatch.setattr(
        "core.self_improving_loop.tool_hints.load_recent_episodes",
        lambda limit=200: [
            _StubEpisode("Bash", False, "cmd not found"),
            _StubEpisode("Bash", False, "cmd not found"),
            _StubEpisode("Bash", True),
        ],
    )
    _, new_sys = apply_in_context_slots([{"role": "user", "content": "go"}], system="ORIGINAL")
    assert "<tool-hints>" in new_sys
    assert "[Bash] 2/3 failed" in new_sys
    assert new_sys.endswith("ORIGINAL")


def test_orchestrator_no_op_when_no_failing_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    """tool_hints slot active but no tool meets threshold → system unchanged."""
    from core.self_improving_loop.in_context_slots import SLOT_TOOL_HINTS, InContextSlot
    from core.self_improving_loop.in_context_wiring import apply_in_context_slots

    monkeypatch.setattr(
        "core.self_improving_loop.in_context_slots._load_in_context_slots_override",
        lambda: {
            SLOT_TOOL_HINTS: InContextSlot(
                name=SLOT_TOOL_HINTS,
                max_entries=3,
                rank_by="success_rate",
                injection_point="system_prompt",
            )
        },
    )
    monkeypatch.setattr(
        "core.self_improving_loop.tool_hints.load_recent_episodes",
        lambda limit=200: [_StubEpisode("X", True)] * 5,  # all success
    )
    _, new_sys = apply_in_context_slots([{"role": "user", "content": "go"}], system="SYS")
    assert new_sys == "SYS"
