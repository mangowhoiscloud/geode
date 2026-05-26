"""CL-A2 — in-context slot wiring invariants for ``tool_ranking``.

Pins the schema registration (5th canonical slot), the orchestrator
firing under SoT-active config, the shared-read optimisation when
both episodic slots are enabled, and the graceful no-op when no SoT
is configured.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest
from core.self_improving_loop.in_context_slots import (
    CANONICAL_SLOTS,
    SLOT_TOOL_HINTS,
    SLOT_TOOL_RANKING,
    InContextSlot,
)

from core.self_improving_loop import in_context_slots, in_context_wiring


@dataclass
class _FakeEpisode:
    tool_name: str
    success: bool
    error: str | None = None


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEODE_IN_CONTEXT_SLOTS_OVERRIDE", raising=False)


def test_tool_ranking_in_canonical_slots():
    assert SLOT_TOOL_RANKING == "tool_ranking"
    assert SLOT_TOOL_RANKING in CANONICAL_SLOTS
    assert SLOT_TOOL_HINTS in CANONICAL_SLOTS, "tool_hints should stay in the set"
    assert len(CANONICAL_SLOTS) == 5, "5 canonical slots after CL-A2"


def test_tool_ranking_exported():
    assert "SLOT_TOOL_RANKING" in in_context_slots.__all__


def test_schema_coerce_accepts_tool_ranking_entry(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """SoT JSON with a ``tool_ranking`` entry coerces to an InContextSlot."""
    sot = tmp_path / "in-context-slots.json"
    sot.write_text(
        json.dumps(
            {
                "tool_ranking": {
                    "max_entries": 4,
                    "rank_by": "wilson_lb",
                    "injection_point": "system_prompt",
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("GEODE_IN_CONTEXT_SLOTS_OVERRIDE", str(sot))
    monkeypatch.setenv("GEODE_IN_CONTEXT_SLOTS_STRICT", "1")
    slots = in_context_slots._load_in_context_slots_override()
    assert slots is not None
    cfg = slots.get(SLOT_TOOL_RANKING)
    assert isinstance(cfg, InContextSlot)
    assert cfg.max_entries == 4
    assert cfg.rank_by == "wilson_lb"


def test_wiring_no_sot_returns_input_identity(monkeypatch: pytest.MonkeyPatch):
    """No SoT loaded → fast path returns same objects, no allocation."""
    monkeypatch.setattr(
        in_context_wiring,
        "log",
        in_context_wiring.log,  # keep logger stable
    )
    messages = [{"role": "user", "content": "x"}]
    system = "base"
    new_messages, new_system = in_context_wiring.apply_in_context_slots(messages, system=system)
    assert new_messages is messages
    assert new_system is system


def test_wiring_emits_ranking_block_when_episodes_qualify(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """SoT has tool_ranking → orchestrator reads ledger → block appears."""
    sot = tmp_path / "in-context-slots.json"
    sot.write_text(
        json.dumps(
            {
                "tool_ranking": {
                    "max_entries": 3,
                    "rank_by": "wilson_lb",
                    "injection_point": "system_prompt",
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("GEODE_IN_CONTEXT_SLOTS_OVERRIDE", str(sot))

    def _fake_loader(limit: int = 200) -> list[object]:
        # 50 successes out of 50 → Wilson LB ~0.929 → comfortably above 0.5.
        return [_FakeEpisode("read", True) for _ in range(50)]

    monkeypatch.setattr(
        "core.self_improving_loop.tool_hints.load_recent_episodes",
        _fake_loader,
    )

    _messages, new_system = in_context_wiring.apply_in_context_slots(
        [{"role": "user", "content": "x"}], system="BASE"
    )
    assert "<tool-ranking>" in new_system
    assert "- [read] 50/50 succeeded" in new_system
    assert "BASE" in new_system, "system suffix preserved"


def test_wiring_emits_both_blocks_under_dual_slot_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """Both tool_hints + tool_ranking enabled → both blocks prepend.

    The orchestrator must NOT read the ledger twice — verified by
    counting ``load_recent_episodes`` calls.
    """
    sot = tmp_path / "in-context-slots.json"
    sot.write_text(
        json.dumps(
            {
                "tool_hints": {
                    "max_entries": 3,
                    "rank_by": "fail_rate",
                    "injection_point": "system_prompt",
                },
                "tool_ranking": {
                    "max_entries": 3,
                    "rank_by": "wilson_lb",
                    "injection_point": "system_prompt",
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("GEODE_IN_CONTEXT_SLOTS_OVERRIDE", str(sot))

    call_count = {"n": 0}

    def _fake_loader(limit: int = 200) -> list[object]:
        call_count["n"] += 1
        return [
            *[_FakeEpisode("ok_tool", True) for _ in range(20)],
            *[_FakeEpisode("bad_tool", False, "boom") for _ in range(10)],
        ]

    monkeypatch.setattr(
        "core.self_improving_loop.tool_hints.load_recent_episodes",
        _fake_loader,
    )

    _messages, new_system = in_context_wiring.apply_in_context_slots(
        [{"role": "user", "content": "x"}], system="BASE"
    )
    assert "<tool-hints>" in new_system
    assert "<tool-ranking>" in new_system
    assert "ok_tool" in new_system
    assert "bad_tool" in new_system
    assert call_count["n"] == 1, "ledger must be read once even with both slots"

    # Order invariant — both readers prepend to ``new_system``. Because
    # tool_hints runs first then tool_ranking second, the final layered
    # result is ``[tool-ranking][tool-hints][BASE]`` (newest prepend
    # appears first). Pinned so a future re-shuffle of the orchestrator
    # block surfaces in tests, not silently in production prompts.
    ranking_idx = new_system.index("<tool-ranking>")
    hints_idx = new_system.index("<tool-hints>")
    base_idx = new_system.index("BASE")
    assert ranking_idx < hints_idx < base_idx, (
        f"expected [ranking][hints][BASE], got "
        f"ranking@{ranking_idx} hints@{hints_idx} base@{base_idx}"
    )


def test_wiring_graceful_when_ledger_read_fails(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """A loader exception → both slots silently no-op, system prompt intact."""
    sot = tmp_path / "in-context-slots.json"
    sot.write_text(
        json.dumps(
            {
                "tool_ranking": {
                    "max_entries": 3,
                    "rank_by": "wilson_lb",
                    "injection_point": "system_prompt",
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("GEODE_IN_CONTEXT_SLOTS_OVERRIDE", str(sot))

    def _exploding_loader(limit: int = 200) -> list[object]:
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(
        "core.self_improving_loop.tool_hints.load_recent_episodes",
        _exploding_loader,
    )

    _messages, new_system = in_context_wiring.apply_in_context_slots(
        [{"role": "user", "content": "x"}], system="BASE"
    )
    assert "<tool-ranking>" not in new_system
    assert new_system == "BASE"
