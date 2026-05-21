"""ADR-013 T3 — Response style guide JSON mutation surface invariants.

5-element 패턴:
- SoT: style-guide.json (in-repo + operator-local)
- Path: GLOBAL_STYLE_GUIDE_PATH + OPERATOR_LOCAL_STYLE_GUIDE_PATH
- Reader: core/agent/style_guide_policy.py
- Entry: core/agent/system_prompt.py:build_system_prompt
- Env: GEODE_STYLE_GUIDE_OVERRIDE + GEODE_STYLE_GUIDE_STRICT
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from core.agent.style_guide_policy import (
    _load_style_guide_override,
    apply_style_guide_policy,
)

from core.agent import style_guide_policy


@pytest.fixture
def isolated_sot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    sot = tmp_path / "style-guide.json"
    operator_local = tmp_path / "operator-local-style-guide.json"
    monkeypatch.setattr(style_guide_policy, "_STYLE_GUIDE_SOT_PATH", sot)
    monkeypatch.setattr(style_guide_policy, "_OPERATOR_LOCAL_STYLE_GUIDE_PATH", operator_local)
    monkeypatch.delenv("GEODE_STYLE_GUIDE_OVERRIDE", raising=False)
    monkeypatch.delenv("GEODE_STYLE_GUIDE_STRICT", raising=False)
    yield sot


def _write(sot: Path, payload: dict[str, Any]) -> None:
    sot.write_text(json.dumps(payload), encoding="utf-8")


# Reader ----------------------------------------------------------------------


def test_load_returns_none_when_sot_missing(isolated_sot: Path) -> None:
    assert _load_style_guide_override() is None


def test_load_returns_none_when_unreadable(isolated_sot: Path) -> None:
    isolated_sot.write_text("bad json {", encoding="utf-8")
    assert _load_style_guide_override() is None


def test_load_returns_none_when_value_not_str(isolated_sot: Path) -> None:
    _write(isolated_sot, {"tone": 42})
    assert _load_style_guide_override() is None


def test_load_valid_payload_all_fields(isolated_sot: Path) -> None:
    payload = {
        "tone": "concise",
        "verbosity_level": "low",
        "response_format": "markdown",
        "code_style": "show-first",
    }
    _write(isolated_sot, payload)
    assert _load_style_guide_override() == payload


def test_load_partial_payload(isolated_sot: Path) -> None:
    """Field 일부만 set → 그 field 만 반환."""
    _write(isolated_sot, {"tone": "concise"})
    assert _load_style_guide_override() == {"tone": "concise"}


def test_load_unknown_enum_value_dropped_with_warning(
    isolated_sot: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Unknown enum value → axis drop (graceful), 다른 valid axis 는 유지."""
    _write(isolated_sot, {"tone": "savage", "verbosity_level": "low"})
    result = _load_style_guide_override()
    assert result == {"verbosity_level": "low"}


def test_load_unknown_field_dropped(isolated_sot: Path) -> None:
    """Forward-compat — `_coerce` 가 알려진 enum field 만 유지."""
    _write(isolated_sot, {"tone": "concise", "future_field": "x"})
    assert _load_style_guide_override() == {"tone": "concise"}


def test_strict_env_var_raises_on_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEODE_STYLE_GUIDE_OVERRIDE", str(tmp_path / "nope.json"))
    monkeypatch.setenv("GEODE_STYLE_GUIDE_STRICT", "1")
    with pytest.raises(RuntimeError, match="GEODE_STYLE_GUIDE_OVERRIDE"):
        _load_style_guide_override()


def test_env_var_without_strict_is_graceful(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GEODE_STYLE_GUIDE_OVERRIDE", str(tmp_path / "nope.json"))
    monkeypatch.delenv("GEODE_STYLE_GUIDE_STRICT", raising=False)
    assert _load_style_guide_override() is None


def test_operator_local_layer_priority(isolated_sot: Path) -> None:
    operator_local = isolated_sot.parent / "operator-local-style-guide.json"
    operator_local.write_text(json.dumps({"tone": "verbose"}), encoding="utf-8")
    _write(isolated_sot, {"tone": "concise"})
    assert _load_style_guide_override() == {"tone": "verbose"}


# Apply -----------------------------------------------------------------------


_BASE = "BASE PROMPT TEXT"


def test_apply_none_is_noop() -> None:
    assert apply_style_guide_policy(_BASE, None) == _BASE


def test_apply_empty_dict_is_noop() -> None:
    assert apply_style_guide_policy(_BASE, {}) == _BASE


def test_apply_single_field_appends_block() -> None:
    out = apply_style_guide_policy(_BASE, {"tone": "concise"})
    assert out.startswith(_BASE)
    assert "<response_style>" in out
    assert "tone: concise" in out
    assert "Keep responses brief" in out
    assert "</response_style>" in out


def test_apply_all_fields_renders_all_lines() -> None:
    out = apply_style_guide_policy(
        _BASE,
        {
            "tone": "verbose",
            "verbosity_level": "high",
            "response_format": "structured",
            "code_style": "explain-first",
        },
    )
    assert "tone: verbose" in out
    assert "verbosity_level: high" in out
    assert "response_format: structured" in out
    assert "code_style: explain-first" in out


def test_apply_unknown_enum_value_in_policy_is_skipped() -> None:
    """`_coerce` 가 unknown 값을 drop 했어야 하지만 직접 apply 호출 시도
    fallback — directive 가 None 이면 줄을 건너뜀."""
    out = apply_style_guide_policy(_BASE, {"tone": "savage"})
    # No valid directive → block empty → return base unchanged.
    assert out == _BASE


def test_apply_with_empty_base_prompt() -> None:
    out = apply_style_guide_policy("", {"tone": "concise"})
    assert out.startswith("<response_style>")


def test_apply_preserves_field_order() -> None:
    """Render order: tone → verbosity → format → code_style (declarative)."""
    out = apply_style_guide_policy(
        _BASE,
        {
            "code_style": "show-first",
            "tone": "concise",
            "verbosity_level": "low",
            "response_format": "plain",
        },
    )
    body = out.split("<response_style>")[1]
    idx_tone = body.find("tone:")
    idx_verb = body.find("verbosity_level:")
    idx_fmt = body.find("response_format:")
    idx_code = body.find("code_style:")
    assert 0 < idx_tone < idx_verb < idx_fmt < idx_code


# Wiring ----------------------------------------------------------------------


def test_system_prompt_imports_reader_and_apply() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    src = (repo_root / "core/agent/system_prompt.py").read_text(encoding="utf-8")
    assert "_load_style_guide_override" in src
    assert "apply_style_guide_policy" in src


def test_system_prompt_wires_apply_into_static() -> None:
    """`static = apply_style_guide_policy(static, _load_style_guide_override())`
    must appear in `core/agent/system_prompt.py`."""
    repo_root = Path(__file__).resolve().parent.parent
    src = (repo_root / "core/agent/system_prompt.py").read_text(encoding="utf-8")
    assert "static = apply_style_guide_policy(" in src


# Path constants --------------------------------------------------------------


def test_path_constants_present() -> None:
    from core.paths import GLOBAL_STYLE_GUIDE_PATH, OPERATOR_LOCAL_STYLE_GUIDE_PATH

    assert GLOBAL_STYLE_GUIDE_PATH.name == "style-guide.json"
    assert OPERATOR_LOCAL_STYLE_GUIDE_PATH.name == "style-guide.json"
    assert "policies" in str(GLOBAL_STYLE_GUIDE_PATH)
    assert "self-improving-loop" in str(OPERATOR_LOCAL_STYLE_GUIDE_PATH)


# Env wiring in train.py ------------------------------------------------------


def test_train_py_sets_style_guide_env_pair() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    src = (repo_root / "autoresearch/train.py").read_text(encoding="utf-8")
    assert "GEODE_STYLE_GUIDE_OVERRIDE" in src
    assert "GEODE_STYLE_GUIDE_STRICT" in src
    assert "GLOBAL_STYLE_GUIDE_PATH" in src


# ALIVE marker ----------------------------------------------------------------


def test_style_guide_json_referenced_in_inference_path() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    hits: list[str] = []
    for path in (repo_root / "core").rglob("*.py"):
        if "test_" in path.name:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if "style-guide.json" in content:
            hits.append(str(path.relative_to(repo_root)))
    assert any("style_guide_policy.py" in h for h in hits), (
        f"style-guide.json must appear in core/agent/style_guide_policy.py. hits={hits}"
    )
