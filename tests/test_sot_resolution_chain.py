"""PR-BACKFILL-SOT — shared 3-layer SoT resolution invariants.

Pins the resolution order (env → operator-local → in-repo → None) and the
strict-flag opt-in semantics that the 4 mutation-surface readers depend on.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from core.self_improving_loop.sot_resolution import SoTSelection, resolve_sot

_ENV = "GEODE_FAKE_POLICY_OVERRIDE"
_STRICT_ENV = "GEODE_FAKE_POLICY_STRICT"


def _resolve(operator_local: Path, in_repo: Path) -> SoTSelection | None:
    return resolve_sot(env_var=_ENV, operator_local=operator_local, in_repo=in_repo)


def _clear(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(_ENV, raising=False)
    monkeypatch.delenv(_STRICT_ENV, raising=False)


# Empty chain -----------------------------------------------------------------


def test_returns_none_when_no_layer_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear(monkeypatch)
    assert _resolve(tmp_path / "ops.json", tmp_path / "repo.json") is None


# In-repo layer ---------------------------------------------------------------


def test_returns_in_repo_graceful_when_only_in_repo_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear(monkeypatch)
    in_repo = tmp_path / "repo.json"
    in_repo.write_text("{}", encoding="utf-8")
    result = _resolve(tmp_path / "ops.json", in_repo)
    assert result == SoTSelection(in_repo, strict=False)


# Operator-local layer --------------------------------------------------------


def test_returns_operator_local_graceful_when_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear(monkeypatch)
    operator_local = tmp_path / "ops.json"
    operator_local.write_text("{}", encoding="utf-8")
    in_repo = tmp_path / "repo.json"
    in_repo.write_text("{}", encoding="utf-8")
    result = _resolve(operator_local, in_repo)
    assert result == SoTSelection(operator_local, strict=False)


def test_operator_local_takes_priority_over_in_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """3-layer chain order — operator-local > in-repo when both exist."""
    _clear(monkeypatch)
    operator_local = tmp_path / "ops.json"
    operator_local.write_text("{}", encoding="utf-8")
    in_repo = tmp_path / "repo.json"
    in_repo.write_text("{}", encoding="utf-8")
    result = _resolve(operator_local, in_repo)
    assert result is not None
    assert result.path == operator_local


# Env layer -------------------------------------------------------------------


def test_env_var_alone_returns_graceful_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Operator daily — env path is selected but graceful (no strict flag)."""
    target = tmp_path / "env.json"
    target.write_text("{}", encoding="utf-8")
    monkeypatch.setenv(_ENV, str(target))
    monkeypatch.delenv(_STRICT_ENV, raising=False)
    result = _resolve(tmp_path / "ops.json", tmp_path / "repo.json")
    assert result == SoTSelection(target, strict=False)


def test_env_var_with_strict_flag_returns_strict_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Audit subprocess — both _OVERRIDE and _STRICT=1 set → strict=True."""
    target = tmp_path / "env.json"
    target.write_text("{}", encoding="utf-8")
    monkeypatch.setenv(_ENV, str(target))
    monkeypatch.setenv(_STRICT_ENV, "1")
    result = _resolve(tmp_path / "ops.json", tmp_path / "repo.json")
    assert result == SoTSelection(target, strict=True)


def test_strict_flag_value_other_than_one_is_graceful(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only literal ``"1"`` activates strict. ``"true"`` / ``"0"`` / ``""`` → graceful."""
    target = tmp_path / "env.json"
    target.write_text("{}", encoding="utf-8")
    monkeypatch.setenv(_ENV, str(target))
    for non_one in ("0", "true", "True", "yes", ""):
        monkeypatch.setenv(_STRICT_ENV, non_one)
        result = _resolve(tmp_path / "ops.json", tmp_path / "repo.json")
        assert result == SoTSelection(target, strict=False), (
            f"_STRICT={non_one!r} should be graceful, got strict=True"
        )


def test_env_var_overrides_lower_layers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Env layer takes priority — no fall-through even when env file is missing."""
    missing_env = tmp_path / "missing-env.json"
    operator_local = tmp_path / "ops.json"
    operator_local.write_text("{}", encoding="utf-8")
    in_repo = tmp_path / "repo.json"
    in_repo.write_text("{}", encoding="utf-8")
    monkeypatch.setenv(_ENV, str(missing_env))
    monkeypatch.delenv(_STRICT_ENV, raising=False)
    result = _resolve(operator_local, in_repo)
    assert result is not None
    # Env path selected as the authoritative SoT, not the operator-local/in-repo.
    assert result.path == missing_env
    assert result.strict is False


# Strict-suffix derivation ----------------------------------------------------


def test_strict_env_name_is_derived_from_override_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``GEODE_X_OVERRIDE`` → ``GEODE_X_STRICT`` automatic derivation —
    no per-reader registration required."""
    target = tmp_path / "env.json"
    target.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("GEODE_CUSTOM_OVERRIDE", str(target))
    monkeypatch.setenv("GEODE_CUSTOM_STRICT", "1")
    monkeypatch.delenv("GEODE_FAKE_POLICY_OVERRIDE", raising=False)
    monkeypatch.delenv("GEODE_FAKE_POLICY_STRICT", raising=False)
    result = resolve_sot(
        env_var="GEODE_CUSTOM_OVERRIDE",
        operator_local=tmp_path / "ops.json",
        in_repo=tmp_path / "repo.json",
    )
    assert result is not None
    assert result.strict is True
