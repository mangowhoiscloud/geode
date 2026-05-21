"""ADR-012 S5 — in-context slot schema invariants.

5-element 패턴 (schema-only, no inference wiring yet — M4.4 deferred):
- SoT: in-context-slots.json
- Path: GLOBAL_IN_CONTEXT_SLOTS_PATH + OPERATOR_LOCAL_IN_CONTEXT_SLOTS_PATH
- Reader: core/self_improving_loop/in_context_slots.py
- Entry: deferred (M4.4 후속 PR)
- Env: GEODE_IN_CONTEXT_SLOTS_OVERRIDE + _STRICT=1 (train.py audit)
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from core.self_improving_loop.in_context_slots import (
    CANONICAL_SLOTS,
    INJECTION_SYSTEM_PROMPT,
    INJECTION_TOOL_DESCRIPTIONS,
    SLOT_EXEMPLARS,
    SLOT_MEMORY_RECALL,
    SLOT_RUBRIC_EXCERPTS,
    SLOT_TOOL_HINTS,
    VALID_INJECTION_POINTS,
    InContextSlot,
    _load_in_context_slots_override,
)

from core.self_improving_loop import in_context_slots


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


def test_canonical_slots_has_exactly_4_entries() -> None:
    assert CANONICAL_SLOTS == (
        "exemplars",
        "memory_recall",
        "rubric_excerpts",
        "tool_hints",
    )
    assert len(CANONICAL_SLOTS) == 4


def test_slot_identifier_constants_match_canonical() -> None:
    assert SLOT_EXEMPLARS == "exemplars"
    assert SLOT_MEMORY_RECALL == "memory_recall"
    assert SLOT_RUBRIC_EXCERPTS == "rubric_excerpts"
    assert SLOT_TOOL_HINTS == "tool_hints"


def test_valid_injection_points_has_two_namespaces() -> None:
    assert {"system_prompt", "tool_descriptions"} == VALID_INJECTION_POINTS
    assert INJECTION_SYSTEM_PROMPT == "system_prompt"
    assert INJECTION_TOOL_DESCRIPTIONS == "tool_descriptions"


def test_in_context_slot_dataclass_is_frozen() -> None:
    slot = InContextSlot(
        name="exemplars",
        max_entries=3,
        rank_by="elo_rating",
        injection_point="system_prompt",
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


def test_load_returns_none_when_max_entries_negative(isolated_sot: Path) -> None:
    _write(isolated_sot, {"exemplars": {"max_entries": -1}})
    assert _load_in_context_slots_override() is None


def test_load_rejects_bool_as_max_entries(isolated_sot: Path) -> None:
    """bool subclass int trap — schema must reject explicitly."""
    _write(isolated_sot, {"exemplars": {"max_entries": True}})
    assert _load_in_context_slots_override() is None


def test_load_valid_payload_all_4_slots(isolated_sot: Path) -> None:
    payload = {
        "exemplars": {
            "max_entries": 3,
            "rank_by": "elo_rating",
            "injection_point": "system_prompt",
        },
        "memory_recall": {
            "max_entries": 5,
            "rank_by": "recency",
            "injection_point": "system_prompt",
        },
        "rubric_excerpts": {
            "max_entries": 3,
            "rank_by": "regression_severity",
            "injection_point": "system_prompt",
        },
        "tool_hints": {
            "max_entries": 5,
            "rank_by": "success_rate",
            "injection_point": "tool_descriptions",
        },
    }
    _write(isolated_sot, payload)
    result = _load_in_context_slots_override()
    assert result is not None
    assert set(result.keys()) == set(CANONICAL_SLOTS)
    assert result["exemplars"].max_entries == 3
    assert result["tool_hints"].injection_point == "tool_descriptions"


def test_load_partial_slots(isolated_sot: Path) -> None:
    """Subset of slots → only that subset returned."""
    _write(
        isolated_sot,
        {"exemplars": {"max_entries": 3, "rank_by": "elo", "injection_point": "system_prompt"}},
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
                "rank_by": "elo",
                "injection_point": "system_prompt",
            },
            "future_slot": {"max_entries": 99, "injection_point": "system_prompt"},
        },
    )
    result = _load_in_context_slots_override()
    assert result is not None
    assert "future_slot" not in result
    assert "exemplars" in result


def test_load_unknown_injection_point_drops_slot(isolated_sot: Path) -> None:
    """Slot with `injection_point` outside VALID_INJECTION_POINTS → drop slot
    (per-axis graceful; other slots stay valid)."""
    _write(
        isolated_sot,
        {
            "exemplars": {
                "max_entries": 3,
                "rank_by": "elo",
                "injection_point": "badness",
            },
            "memory_recall": {
                "max_entries": 5,
                "rank_by": "recency",
                "injection_point": "system_prompt",
            },
        },
    )
    result = _load_in_context_slots_override()
    assert result is not None
    assert "exemplars" not in result
    assert "memory_recall" in result


def test_load_default_injection_point_is_system_prompt(isolated_sot: Path) -> None:
    """`injection_point` 누락 시 default = 'system_prompt'."""
    _write(isolated_sot, {"exemplars": {"max_entries": 3, "rank_by": "elo"}})
    result = _load_in_context_slots_override()
    assert result is not None
    assert result["exemplars"].injection_point == "system_prompt"


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
                    "rank_by": "from-ops",
                    "injection_point": "system_prompt",
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
                "rank_by": "from-repo",
                "injection_point": "system_prompt",
            }
        },
    )
    result = _load_in_context_slots_override()
    assert result is not None
    assert result["exemplars"].rank_by == "from-ops"
    assert result["exemplars"].max_entries == 99


# Path constants --------------------------------------------------------------


def test_path_constants_present() -> None:
    from core.paths import (
        GLOBAL_IN_CONTEXT_SLOTS_PATH,
        OPERATOR_LOCAL_IN_CONTEXT_SLOTS_PATH,
    )

    assert GLOBAL_IN_CONTEXT_SLOTS_PATH.name == "in-context-slots.json"
    assert OPERATOR_LOCAL_IN_CONTEXT_SLOTS_PATH.name == "in-context-slots.json"


# Env wiring in train.py ------------------------------------------------------


def test_train_py_sets_in_context_slots_env_pair() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    src = (repo_root / "autoresearch/train.py").read_text(encoding="utf-8")
    assert "GEODE_IN_CONTEXT_SLOTS_OVERRIDE" in src
    assert "GEODE_IN_CONTEXT_SLOTS_STRICT" in src
    assert "GLOBAL_IN_CONTEXT_SLOTS_PATH" in src


# ALIVE marker ----------------------------------------------------------------


def test_in_context_slots_json_referenced_in_inference_path() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    hits: list[str] = []
    for path in (repo_root / "core").rglob("*.py"):
        if "test_" in path.name:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if "in-context-slots.json" in content:
            hits.append(str(path.relative_to(repo_root)))
    assert any("in_context_slots.py" in h for h in hits)
