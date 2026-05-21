"""ADR-013 T5 — Cache breakpoint policy JSON mutation surface invariants.

5-element 패턴:
- SoT: cache-policy.json
- Path: GLOBAL_CACHE_POLICY_PATH + OPERATOR_LOCAL_CACHE_POLICY_PATH
- Reader: core/llm/cache_policy.py
- Entry: core/llm/providers/anthropic.py (apply_messages_cache_control 호출 직전)
- Env: GEODE_CACHE_POLICY_OVERRIDE + GEODE_CACHE_POLICY_STRICT
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from core.llm import cache_policy
from core.llm.cache_policy import (
    _load_cache_policy_override,
    apply_cache_policy_breakpoints,
)


@pytest.fixture
def isolated_sot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    sot = tmp_path / "cache-policy.json"
    operator_local = tmp_path / "operator-local-cache-policy.json"
    monkeypatch.setattr(cache_policy, "_CACHE_POLICY_SOT_PATH", sot)
    monkeypatch.setattr(cache_policy, "_OPERATOR_LOCAL_CACHE_POLICY_PATH", operator_local)
    monkeypatch.delenv("GEODE_CACHE_POLICY_OVERRIDE", raising=False)
    monkeypatch.delenv("GEODE_CACHE_POLICY_STRICT", raising=False)
    yield sot


def _write(sot: Path, payload: dict[str, Any]) -> None:
    sot.write_text(json.dumps(payload), encoding="utf-8")


# Reader ----------------------------------------------------------------------


def test_load_returns_none_when_sot_missing(isolated_sot: Path) -> None:
    assert _load_cache_policy_override() is None


def test_load_returns_none_when_unreadable(isolated_sot: Path) -> None:
    isolated_sot.write_text("bad json {", encoding="utf-8")
    assert _load_cache_policy_override() is None


def test_load_returns_none_when_value_not_int(isolated_sot: Path) -> None:
    _write(isolated_sot, {"messages_breakpoints": "three"})
    assert _load_cache_policy_override() is None


def test_load_rejects_bool_as_int(isolated_sot: Path) -> None:
    """Python bool is int subclass — _validate_schema rejects bool explicitly."""
    _write(isolated_sot, {"messages_breakpoints": True})
    assert _load_cache_policy_override() is None


def test_load_valid_payload_each_value(isolated_sot: Path) -> None:
    for n in (0, 1, 2, 3):
        _write(isolated_sot, {"messages_breakpoints": n})
        assert _load_cache_policy_override() == {"messages_breakpoints": n}


def test_load_out_of_range_value_dropped(isolated_sot: Path) -> None:
    """Out-of-range (4, -1) → per-axis graceful drop (returns empty dict)."""
    _write(isolated_sot, {"messages_breakpoints": 4})
    assert _load_cache_policy_override() == {}
    _write(isolated_sot, {"messages_breakpoints": -1})
    assert _load_cache_policy_override() == {}


def test_load_unknown_field_dropped(isolated_sot: Path) -> None:
    """Forward-compat — unknown field 자동 drop."""
    _write(isolated_sot, {"messages_breakpoints": 2, "future_field": "x"})
    assert _load_cache_policy_override() == {"messages_breakpoints": 2}


def test_strict_env_var_raises_on_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEODE_CACHE_POLICY_OVERRIDE", str(tmp_path / "nope.json"))
    monkeypatch.setenv("GEODE_CACHE_POLICY_STRICT", "1")
    with pytest.raises(RuntimeError, match="GEODE_CACHE_POLICY_OVERRIDE"):
        _load_cache_policy_override()


def test_env_var_without_strict_is_graceful(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GEODE_CACHE_POLICY_OVERRIDE", str(tmp_path / "nope.json"))
    monkeypatch.delenv("GEODE_CACHE_POLICY_STRICT", raising=False)
    assert _load_cache_policy_override() is None


def test_operator_local_layer_priority(isolated_sot: Path) -> None:
    operator_local = isolated_sot.parent / "operator-local-cache-policy.json"
    operator_local.write_text(json.dumps({"messages_breakpoints": 1}), encoding="utf-8")
    _write(isolated_sot, {"messages_breakpoints": 3})
    assert _load_cache_policy_override() == {"messages_breakpoints": 1}


# Apply -----------------------------------------------------------------------


def test_apply_none_returns_default() -> None:
    assert apply_cache_policy_breakpoints(3, None) == 3


def test_apply_empty_dict_returns_default() -> None:
    assert apply_cache_policy_breakpoints(3, {}) == 3


def test_apply_override_returns_policy_value() -> None:
    assert apply_cache_policy_breakpoints(3, {"messages_breakpoints": 1}) == 1


def test_apply_override_zero_returns_zero() -> None:
    """0 is a valid override (disables messages caching entirely)."""
    assert apply_cache_policy_breakpoints(3, {"messages_breakpoints": 0}) == 0


def test_apply_with_different_defaults() -> None:
    assert apply_cache_policy_breakpoints(0, None) == 0
    assert apply_cache_policy_breakpoints(2, None) == 2


# Wiring ----------------------------------------------------------------------


def test_anthropic_provider_imports_reader_and_apply() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    src = (repo_root / "core/llm/providers/anthropic.py").read_text(encoding="utf-8")
    assert "_load_cache_policy_override" in src
    assert "apply_cache_policy_breakpoints" in src


def test_anthropic_provider_uses_apply_before_cache_control() -> None:
    """`n_breakpoints = apply_cache_policy_breakpoints(...)` must precede
    the actual `apply_messages_cache_control(...)` call where the override
    flows into ``n_breakpoints=`` kwarg."""
    repo_root = Path(__file__).resolve().parent.parent
    src = (repo_root / "core/llm/providers/anthropic.py").read_text(encoding="utf-8")
    apply_idx = src.find("apply_cache_policy_breakpoints(")
    # Find apply_messages_cache_control that uses our n_breakpoints variable.
    call_idx = src.find("n_breakpoints=n_breakpoints")
    assert apply_idx > 0, "apply_cache_policy_breakpoints must be invoked"
    assert call_idx > 0, "apply_messages_cache_control must use n_breakpoints kwarg"
    assert apply_idx < call_idx, "apply_cache_policy_breakpoints must precede its consumer"


# Path constants --------------------------------------------------------------


def test_path_constants_present() -> None:
    from core.paths import GLOBAL_CACHE_POLICY_PATH, OPERATOR_LOCAL_CACHE_POLICY_PATH

    assert GLOBAL_CACHE_POLICY_PATH.name == "cache-policy.json"
    assert OPERATOR_LOCAL_CACHE_POLICY_PATH.name == "cache-policy.json"
    assert "policies" in str(GLOBAL_CACHE_POLICY_PATH)
    assert "self-improving-loop" in str(OPERATOR_LOCAL_CACHE_POLICY_PATH)


# Env wiring in train.py ------------------------------------------------------


def test_train_py_sets_cache_policy_env_pair() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    src = (repo_root / "autoresearch/train.py").read_text(encoding="utf-8")
    assert "GEODE_CACHE_POLICY_OVERRIDE" in src
    assert "GEODE_CACHE_POLICY_STRICT" in src
    assert "GLOBAL_CACHE_POLICY_PATH" in src


# ALIVE marker ----------------------------------------------------------------


def test_cache_policy_json_referenced_in_inference_path() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    hits: list[str] = []
    for path in (repo_root / "core").rglob("*.py"):
        if "test_" in path.name:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if "cache-policy.json" in content:
            hits.append(str(path.relative_to(repo_root)))
    assert any("cache_policy.py" in h for h in hits), (
        f"cache-policy.json must appear in core/llm/cache_policy.py. hits={hits}"
    )
