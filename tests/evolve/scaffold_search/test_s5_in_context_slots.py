"""ADR-012 S5 — in-context slot schema invariants.

5-element 패턴 (schema-only, no inference wiring yet — M4.4 deferred):
- SoT: in-context-slots.json
- Path: AUTORESEARCH_IN_CONTEXT_SLOTS_PATH + OPERATOR_LOCAL_IN_CONTEXT_SLOTS_PATH
- Reader: core/agent/policy_injection/in_context_slots.py
- Entry: deferred (M4.4 후속 PR)
- Env: GEODE_IN_CONTEXT_SLOTS_OVERRIDE + _STRICT=1 (train.py audit)
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from dataclasses import fields
from pathlib import Path
from typing import Any

import pytest
from core.agent.policy_injection import in_context_slots
from core.agent.policy_injection.in_context_slots import (
    CANONICAL_SLOTS,
    SLOT_EXEMPLARS,
    SLOT_MEMORY_RECALL,
    SLOT_RUBRIC_EXCERPTS,
    SLOT_TOOL_HINTS,
    InContextSlot,
    _load_in_context_slots_override,
)


@pytest.fixture
def isolated_sot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    sot = tmp_path / "in-context-slots.json"
    operator_local = tmp_path / "operator-local-in-context-slots.json"
    monkeypatch.setattr(in_context_slots, "_IN_CONTEXT_SLOTS_SOT_PATH", sot)
    monkeypatch.setattr(in_context_slots, "_OPERATOR_LOCAL_IN_CONTEXT_SLOTS_PATH", operator_local)
    monkeypatch.delenv("GEODE_IN_CONTEXT_SLOTS_OVERRIDE", raising=False)
    monkeypatch.delenv("GEODE_IN_CONTEXT_SLOTS_STRICT", raising=False)
    yield sot


def _write(sot: Path, payload: dict[str, Any]) -> None:
    sot.write_text(json.dumps(payload), encoding="utf-8")


# Canonical schema ------------------------------------------------------------


def test_canonical_slots_has_exactly_5_entries() -> None:
    """CL-A2 (2026-05-26) added ``tool_ranking`` as the 5th canonical
    slot — the success-side counterpart of ``tool_hints``."""
    assert CANONICAL_SLOTS == (
        "exemplars",
        "memory_recall",
        "rubric_excerpts",
        "tool_hints",
        "tool_ranking",
    )
    assert len(CANONICAL_SLOTS) == 5


def test_slot_identifier_constants_match_canonical() -> None:
    from core.agent.policy_injection.in_context_slots import SLOT_TOOL_RANKING

    assert SLOT_EXEMPLARS == "exemplars"
    assert SLOT_MEMORY_RECALL == "memory_recall"
    assert SLOT_RUBRIC_EXCERPTS == "rubric_excerpts"
    assert SLOT_TOOL_HINTS == "tool_hints"
    assert SLOT_TOOL_RANKING == "tool_ranking"


def test_in_context_slot_exposes_only_consumed_controls() -> None:
    """Ranking and placement are fixed in the wiring; only the cap is a knob."""
    assert {field.name for field in fields(InContextSlot)} == {"name", "max_entries"}
    assert not hasattr(in_context_slots, "VALID_INJECTION_POINTS")


def test_in_context_slot_dataclass_is_frozen() -> None:
    slot = InContextSlot(
        name="exemplars",
        max_entries=3,
    )
    with pytest.raises(Exception):  # FrozenInstanceError or AttributeError
        slot.max_entries = 5  # type: ignore[misc]


# Loader ----------------------------------------------------------------------


def test_load_returns_none_when_sot_missing(isolated_sot: Path) -> None:
    assert _load_in_context_slots_override() is None


def test_load_returns_none_when_unreadable(isolated_sot: Path) -> None:
    isolated_sot.write_text("bad json {", encoding="utf-8")
    assert _load_in_context_slots_override() is None


def test_load_returns_none_when_max_entries_not_int(isolated_sot: Path) -> None:
    _write(isolated_sot, {"exemplars": {"max_entries": "three"}})
    assert _load_in_context_slots_override() is None


def test_load_drops_slot_when_max_entries_negative(isolated_sot: Path) -> None:
    """Per-axis graceful — negative max_entries drops THAT slot only,
    sibling slots stay valid (Codex MCP catch on PR #1425 FAIL #2)."""
    _write(
        isolated_sot,
        {
            "exemplars": {"max_entries": -1},
            "memory_recall": {
                "max_entries": 5,
            },
        },
    )
    result = _load_in_context_slots_override()
    assert result is not None
    assert "exemplars" not in result
    assert "memory_recall" in result


def test_load_single_negative_slot_returns_empty_dict(isolated_sot: Path) -> None:
    """Single slot with negative max_entries → empty dict (not None) —
    the SoT was parseable, just nothing qualified for inclusion."""
    _write(isolated_sot, {"exemplars": {"max_entries": -1}})
    assert _load_in_context_slots_override() == {}


def test_load_rejects_bool_as_max_entries(isolated_sot: Path) -> None:
    """bool subclass int trap — schema must reject explicitly."""
    _write(isolated_sot, {"exemplars": {"max_entries": True}})
    assert _load_in_context_slots_override() is None


def test_load_valid_payload_all_5_slots(isolated_sot: Path) -> None:
    payload = {
        "exemplars": {
            "max_entries": 3,
        },
        "memory_recall": {
            "max_entries": 5,
        },
        "rubric_excerpts": {
            "max_entries": 3,
        },
        "tool_hints": {
            "max_entries": 5,
        },
        "tool_ranking": {
            "max_entries": 5,
        },
    }
    _write(isolated_sot, payload)
    result = _load_in_context_slots_override()
    assert result is not None
    assert set(result.keys()) == set(CANONICAL_SLOTS)
    assert result["exemplars"].max_entries == 3
    assert result["tool_hints"].max_entries == 5


def test_load_partial_slots(isolated_sot: Path) -> None:
    """Subset of slots → only that subset returned."""
    _write(
        isolated_sot,
        {"exemplars": {"max_entries": 3}},
    )
    result = _load_in_context_slots_override()
    assert result is not None
    assert set(result.keys()) == {"exemplars"}


def test_load_unknown_slot_dropped(isolated_sot: Path) -> None:
    """Forward-compat — unknown slot name 자동 drop."""
    _write(
        isolated_sot,
        {
            "exemplars": {
                "max_entries": 3,
            },
            "future_slot": {"max_entries": 99},
        },
    )
    result = _load_in_context_slots_override()
    assert result is not None
    assert "future_slot" not in result
    assert "exemplars" in result


def test_load_unknown_injection_point_drops_slot(isolated_sot: Path) -> None:
    """Legacy `injection_point` outside the old enum still drops that slot
    (per-axis graceful; other slots stay valid) — retiring the knob must not
    activate a previously invalid policy."""
    _write(
        isolated_sot,
        {
            "exemplars": {"max_entries": 3, "rank_by": "elo", "injection_point": "badness"},
            "memory_recall": {"max_entries": 5, "rank_by": "recency"},
        },
    )
    result = _load_in_context_slots_override()
    assert result == {"memory_recall": InContextSlot(name="memory_recall", max_entries=5)}


def test_load_valid_legacy_keys_keep_slot_without_warning(
    isolated_sot: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Valid legacy strings still activate the slot by `max_entries`. The
    note is debug-level: the wiring reloads the policy on every call."""
    _write(
        isolated_sot,
        {
            "exemplars": {"max_entries": 3, "rank_by": "elo", "injection_point": "system_prompt"},
            "tool_hints": {"max_entries": 5, "injection_point": "tool_descriptions"},
            "memory_recall": {"max_entries": 2},
        },
    )
    with caplog.at_level("DEBUG", logger=in_context_slots.__name__):
        result = _load_in_context_slots_override()
    assert result == {
        "exemplars": InContextSlot(name="exemplars", max_entries=3),
        "tool_hints": InContextSlot(name="tool_hints", max_entries=5),
        "memory_recall": InContextSlot(name="memory_recall", max_entries=2),
    }
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len([r for r in caplog.records if "retired keys" in r.getMessage()]) == 2


@pytest.mark.parametrize("key", ["rank_by", "injection_point"])
def test_load_non_string_legacy_key_rejects_file(isolated_sot: Path, key: str) -> None:
    """Graceful source: a malformed legacy value still discards the file."""
    _write(
        isolated_sot, {"exemplars": {"max_entries": 3, key: 5}, "memory_recall": {"max_entries": 2}}
    )
    assert _load_in_context_slots_override() is None


@pytest.mark.parametrize("key", ["rank_by", "injection_point"])
def test_strict_override_non_string_legacy_key_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, key: str
) -> None:
    sot = tmp_path / "override.json"
    _write(sot, {"exemplars": {"max_entries": 3, key: ["system_prompt"]}})
    monkeypatch.setenv("GEODE_IN_CONTEXT_SLOTS_OVERRIDE", str(sot))
    monkeypatch.setenv("GEODE_IN_CONTEXT_SLOTS_STRICT", "1")
    with pytest.raises(RuntimeError, match=f"{key} must be str"):
        _load_in_context_slots_override()


def test_strict_env_var_raises_on_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEODE_IN_CONTEXT_SLOTS_OVERRIDE", str(tmp_path / "nope.json"))
    monkeypatch.setenv("GEODE_IN_CONTEXT_SLOTS_STRICT", "1")
    with pytest.raises(RuntimeError, match="GEODE_IN_CONTEXT_SLOTS_OVERRIDE"):
        _load_in_context_slots_override()


def test_env_var_without_strict_is_graceful(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GEODE_IN_CONTEXT_SLOTS_OVERRIDE", str(tmp_path / "nope.json"))
    monkeypatch.delenv("GEODE_IN_CONTEXT_SLOTS_STRICT", raising=False)
    assert _load_in_context_slots_override() is None


def test_operator_local_layer_priority(isolated_sot: Path) -> None:
    operator_local = isolated_sot.parent / "operator-local-in-context-slots.json"
    operator_local.write_text(
        json.dumps(
            {
                "exemplars": {
                    "max_entries": 99,
                }
            },
        ),
        encoding="utf-8",
    )
    _write(
        isolated_sot,
        {
            "exemplars": {
                "max_entries": 3,
            }
        },
    )
    result = _load_in_context_slots_override()
    assert result is not None
    assert result["exemplars"].max_entries == 99


# Path constants --------------------------------------------------------------


def test_path_constants_present() -> None:
    from core.paths import (
        AUTORESEARCH_IN_CONTEXT_SLOTS_PATH,
        OPERATOR_LOCAL_IN_CONTEXT_SLOTS_PATH,
    )

    assert AUTORESEARCH_IN_CONTEXT_SLOTS_PATH.name == "in-context-slots.json"
    assert OPERATOR_LOCAL_IN_CONTEXT_SLOTS_PATH.name == "in-context-slots.json"


# Env wiring in train.py ------------------------------------------------------


def test_train_py_sets_in_context_slots_env_pair() -> None:
    # S-5 (2026-06-11) — the audit-env assembly moved to measure.py
    # (train.py is restored to the autoresearch-원형 mutation surface).
    repo_root = Path(__file__).resolve().parents[3]
    src = (repo_root / "evolve/scaffold_search/measure.py").read_text(encoding="utf-8")
    assert "GEODE_IN_CONTEXT_SLOTS_OVERRIDE" in src
    assert "GEODE_IN_CONTEXT_SLOTS_STRICT" in src
    assert "AUTORESEARCH_IN_CONTEXT_SLOTS_PATH" in src


# ALIVE marker ----------------------------------------------------------------


def test_in_context_slots_json_referenced_in_inference_path() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    hits: list[str] = []
    for source_root in (repo_root / "core", repo_root / "evals", repo_root / "evolve"):
        for path in source_root.rglob("*.py"):
            try:
                content = path.read_text(encoding="utf-8")
            except OSError:
                continue
            if "in-context-slots.json" in content:
                hits.append(str(path.relative_to(repo_root)))
    assert any("in_context_slots.py" in h for h in hits)
