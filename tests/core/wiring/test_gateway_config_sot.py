"""Gateway config root SoT — global authoritative, project overlay
(PR-SLACK-TRANSPORT). Pins the cwd-independence defect: bindings lived
only in the project ``.geode/config.toml``, so the daemon's Slack surface
silently depended on its launchd WorkingDirectory."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from core.messaging.binding import ChannelManager, get_gateway, set_gateway
from core.wiring.adapters import _load_gateway_config, build_gateway


@pytest.fixture()
def config_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Path]:
    global_toml = tmp_path / "global" / "config.toml"
    project_toml = tmp_path / "project" / "config.toml"
    global_toml.parent.mkdir()
    project_toml.parent.mkdir()
    monkeypatch.setenv("GEODE_CONFIG_TOML", str(global_toml))
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


def test_disabled_external_gateway_still_builds_local_cli_manager(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("core.config._settings_instance", SimpleNamespace(gateway_enabled=False))
    set_gateway(None)
    try:
        build_gateway()
        gateway = get_gateway()
        assert isinstance(gateway, ChannelManager)
        assert gateway._pollers == []
    finally:
        set_gateway(None)


def test_gateway_watches_redirected_config_and_reloads_it(
    config_files: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.orchestration import hot_reload

    config_files["global"].write_text("[gateway]\npollers = []\nmax_turns = 7\n")
    monkeypatch.setattr(
        "core.config._settings_instance",
        SimpleNamespace(gateway_enabled=True, gateway_poll_interval_s=1),
    )
    monkeypatch.setenv("SLACK_BOT_USER_ID", "test-bot")
    monkeypatch.setattr("core.wiring.container.build_default_lanes", lambda: None)
    monkeypatch.setattr(
        "core.mcp.manager.get_mcp_manager",
        lambda **kwargs: SimpleNamespace(connected_count=0, server_count=0),
    )
    watcher = Mock(spec=hot_reload.ConfigWatcher)
    monkeypatch.setattr(hot_reload, "ConfigWatcher", lambda: watcher)
    set_gateway(None)
    try:
        build_gateway()
        assert [call.args[0] for call in watcher.watch.call_args_list] == [
            config_files["global"],
            config_files["project"],
        ]
        watcher.start.assert_called_once_with()
        manager = get_gateway()
        assert manager is not None
        reload_config = Mock()
        monkeypatch.setattr(manager, "load_bindings_from_config", reload_config)
        config_files["global"].write_text("[gateway]\npollers = []\nmax_turns = 9\n")
        callback = watcher.watch.call_args_list[0].args[1]
        callback(config_files["global"], 1.0)
        assert reload_config.call_args.args[0]["gateway"]["max_turns"] == 9
    finally:
        set_gateway(None)
