"""Gateway config root SoT — global authoritative, project overlay
(PR-SLACK-TRANSPORT). Pins the cwd-independence defect: bindings lived
only in the project ``.geode/config.toml``, so the daemon's Slack surface
silently depended on its launchd WorkingDirectory."""

from __future__ import annotations

from pathlib import Path

import pytest
from core.wiring.adapters import _load_gateway_config


@pytest.fixture()
def config_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Path]:
    global_toml = tmp_path / "global" / "config.toml"
    project_toml = tmp_path / "project" / "config.toml"
    global_toml.parent.mkdir()
    project_toml.parent.mkdir()
    monkeypatch.setattr("core.paths.GLOBAL_CONFIG_TOML", global_toml)
    monkeypatch.setattr("core.paths.PROJECT_CONFIG_TOML", project_toml)
    return {"global": global_toml, "project": project_toml}


def test_global_only(config_files: dict[str, Path]) -> None:
    config_files["global"].write_text(
        '[gateway]\nmax_turns = 7\n\n[[gateway.bindings.rules]]\nchannel = "slack"\n'
        'channel_id = "C_GLOBAL"\n'
    )
    merged, sources = _load_gateway_config()
    assert merged["gateway"]["max_turns"] == 7
    rules = merged["gateway"]["bindings"]["rules"]
    assert [r["channel_id"] for r in rules] == ["C_GLOBAL"]
    assert len(sources) == 1 and sources[0].startswith("global:")


def test_project_only_still_works(config_files: dict[str, Path]) -> None:
    config_files["project"].write_text(
        '[gateway]\n\n[[gateway.bindings.rules]]\nchannel = "slack"\nchannel_id = "C_PROJ"\n'
    )
    merged, sources = _load_gateway_config()
    assert [r["channel_id"] for r in merged["gateway"]["bindings"]["rules"]] == ["C_PROJ"]
    assert len(sources) == 1 and sources[0].startswith("project:")


def test_overlay_scalars_project_wins_rules_append(config_files: dict[str, Path]) -> None:
    config_files["global"].write_text(
        "[gateway]\nmax_turns = 7\ntime_budget_s = 100.0\n\n"
        '[[gateway.bindings.rules]]\nchannel = "slack"\nchannel_id = "C_GLOBAL"\n'
    )
    config_files["project"].write_text(
        "[gateway]\nmax_turns = 3\n\n"
        '[[gateway.bindings.rules]]\nchannel = "slack"\nchannel_id = "C_PROJ"\n'
    )
    merged, sources = _load_gateway_config()
    gw = merged["gateway"]
    assert gw["max_turns"] == 3  # project overrides scalar
    assert gw["time_budget_s"] == 100.0  # global fills gaps
    assert [r["channel_id"] for r in gw["bindings"]["rules"]] == ["C_GLOBAL", "C_PROJ"]
    assert len(sources) == 2


def test_both_absent(config_files: dict[str, Path]) -> None:
    merged, sources = _load_gateway_config()
    assert merged == {}
    assert sources == []


def test_unreadable_file_is_skipped(config_files: dict[str, Path]) -> None:
    config_files["global"].write_text("not [ valid toml ===")
    config_files["project"].write_text(
        '[gateway]\n\n[[gateway.bindings.rules]]\nchannel = "slack"\nchannel_id = "C_OK"\n'
    )
    merged, sources = _load_gateway_config()
    assert [r["channel_id"] for r in merged["gateway"]["bindings"]["rules"]] == ["C_OK"]
    assert len(sources) == 1
