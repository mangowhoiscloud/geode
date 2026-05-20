"""Tests for the active AgenticLoop wrapper-override path."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from core.agent.system_prompt import WRAPPER_OVERRIDE_HOOK_READY, build_system_prompt


@pytest.fixture(autouse=True)
def clear_prompt_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEODE_WRAPPER_OVERRIDE", raising=False)
    monkeypatch.delenv("GEODE_AUDIT_UNRESTRICTED", raising=False)
    monkeypatch.delenv("GEODE_PERSONA", raising=False)


def _write_override(tmp_path: Path, payload: object) -> Path:
    path = tmp_path / "wrapper-override.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_wrapper_override_hook_ready_sentinel() -> None:
    assert WRAPPER_OVERRIDE_HOOK_READY is True


def test_unset_wrapper_override_keeps_default_wrapper() -> None:
    prompt = build_system_prompt()

    assert "You are an autonomous execution agent" in prompt
    assert "AUTORESEARCH_MUTATED_WRAPPER" not in prompt
    assert "<math_formatting>" in prompt


def test_valid_wrapper_override_replaces_default_wrapper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    override_path = _write_override(
        tmp_path,
        {
            "role": "AUTORESEARCH_MUTATED_WRAPPER",
            "tools": "Preserve tool-call discipline under mutation.",
        },
    )
    monkeypatch.setenv("GEODE_WRAPPER_OVERRIDE", str(override_path))

    prompt = build_system_prompt()

    assert "You are an autonomous execution agent" not in prompt
    assert "AUTORESEARCH_MUTATED_WRAPPER" in prompt
    assert "Preserve tool-call discipline under mutation." in prompt
    assert "<math_formatting>" in prompt
    assert "<dynamic_context>" in prompt


def test_valid_wrapper_override_reaches_unrestricted_audit_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    override_path = _write_override(tmp_path, {"role": "AUDIT_MODE_MUTATED_WRAPPER"})
    monkeypatch.setenv("GEODE_WRAPPER_OVERRIDE", str(override_path))
    monkeypatch.setenv("GEODE_AUDIT_UNRESTRICTED", "1")

    prompt = build_system_prompt()

    assert "AUDIT_MODE_MUTATED_WRAPPER" in prompt
    assert "You are an autonomous execution agent" not in prompt
    assert "<dynamic_context>" in prompt


def test_missing_wrapper_override_file_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GEODE_WRAPPER_OVERRIDE", str(tmp_path / "missing.json"))

    with pytest.raises(RuntimeError, match="file not found"):
        build_system_prompt()


def test_invalid_wrapper_override_schema_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    override_path = _write_override(tmp_path, ["not", "a", "dict"])
    monkeypatch.setenv("GEODE_WRAPPER_OVERRIDE", str(override_path))

    with pytest.raises(RuntimeError, match=r"non-empty dict\[str, str\]"):
        build_system_prompt()


# ---------------------------------------------------------------------------
# G5a — env-less SoT fallback (~/.geode/self-improving-loop/wrapper-sections.json)
# ---------------------------------------------------------------------------


def test_sot_fallback_default_when_no_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No SoT file + no env → default wrapper (router-style baseline)."""
    sot_path = tmp_path / "wrapper-sections.json"  # never created
    monkeypatch.setattr("core.agent.system_prompt._WRAPPER_SECTIONS_SOT_PATH", sot_path)
    prompt = build_system_prompt()
    assert "You are an autonomous execution agent" in prompt


def test_sot_fallback_loaded_when_file_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SoT file present + no env → SoT replaces default wrapper."""
    sot_path = tmp_path / "wrapper-sections.json"
    sot_path.write_text(
        json.dumps({"role": "G5A_SOT_LOADED_WRAPPER", "extra": "second section"}),
        encoding="utf-8",
    )
    monkeypatch.setattr("core.agent.system_prompt._WRAPPER_SECTIONS_SOT_PATH", sot_path)
    prompt = build_system_prompt()
    assert "G5A_SOT_LOADED_WRAPPER" in prompt
    assert "second section" in prompt
    assert "You are an autonomous execution agent" not in prompt


def test_env_override_wins_over_sot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """GEODE_WRAPPER_OVERRIDE env beats the SoT fallback."""
    sot_path = tmp_path / "wrapper-sections.json"
    sot_path.write_text(json.dumps({"role": "G5A_SOT_LOADED_WRAPPER"}), encoding="utf-8")
    monkeypatch.setattr("core.agent.system_prompt._WRAPPER_SECTIONS_SOT_PATH", sot_path)
    override_path = _write_override(tmp_path, {"role": "ENV_OVERRIDE_WINS"})
    monkeypatch.setenv("GEODE_WRAPPER_OVERRIDE", str(override_path))
    prompt = build_system_prompt()
    assert "ENV_OVERRIDE_WINS" in prompt
    assert "G5A_SOT_LOADED_WRAPPER" not in prompt


def test_sot_fallback_unparseable_uses_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Corrupted SoT → graceful degrade to default, no RuntimeError."""
    sot_path = tmp_path / "wrapper-sections.json"
    sot_path.write_text("{ not valid json", encoding="utf-8")
    monkeypatch.setattr("core.agent.system_prompt._WRAPPER_SECTIONS_SOT_PATH", sot_path)
    prompt = build_system_prompt()
    assert "You are an autonomous execution agent" in prompt
    assert "G5A_SOT" not in prompt


def test_sot_fallback_empty_dict_uses_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Empty dict SoT → graceful degrade."""
    sot_path = tmp_path / "wrapper-sections.json"
    sot_path.write_text(json.dumps({}), encoding="utf-8")
    monkeypatch.setattr("core.agent.system_prompt._WRAPPER_SECTIONS_SOT_PATH", sot_path)
    prompt = build_system_prompt()
    assert "You are an autonomous execution agent" in prompt


def test_sot_fallback_non_string_values_uses_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Non-string value in SoT → graceful degrade."""
    sot_path = tmp_path / "wrapper-sections.json"
    sot_path.write_text(json.dumps({"role": 42}), encoding="utf-8")
    monkeypatch.setattr("core.agent.system_prompt._WRAPPER_SECTIONS_SOT_PATH", sot_path)
    prompt = build_system_prompt()
    assert "You are an autonomous execution agent" in prompt


def test_sot_path_parity_with_autoresearch() -> None:
    """G5a — autoresearch.train.WRAPPER_SECTIONS_SOT_PATH ===
    core.agent.system_prompt._WRAPPER_SECTIONS_SOT_PATH.

    The two SoT path constants are deliberately *duplicated* (not
    imported) to keep the import-linter "Agent stays pure" contract
    intact, so the parity must be pinned by a test instead.
    """
    from autoresearch import train as auto_train

    from core.agent import system_prompt

    assert auto_train.WRAPPER_SECTIONS_SOT_PATH == system_prompt._WRAPPER_SECTIONS_SOT_PATH
