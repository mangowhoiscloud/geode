"""An install update must respect other workspaces and its prior service mode."""

from __future__ import annotations

import fcntl
from pathlib import Path
from unittest.mock import Mock

import pytest
from core.cli.commands import lifecycle
from core.cli.update_provenance import UpdateKind, UpdateTarget


def test_update_refuses_another_live_workspace_before_install(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner_path = tmp_path / "run" / "other" / "cli.serve.lock"
    owner_path.parent.mkdir(parents=True)
    monkeypatch.setattr(lifecycle, "GEODE_HOME", tmp_path)
    monkeypatch.setattr(lifecycle, "_serve_is_present", lambda: False)
    monkeypatch.setattr(lifecycle, "_serve_gateway_mode", lambda: None)
    monkeypatch.setattr("core.cli.ipc_client.is_serve_running", lambda *a: False)
    monkeypatch.setattr(
        lifecycle,
        "detect_update_target",
        lambda: UpdateTarget(
            UpdateKind.UV_TOOL,
            uv_tool_dir=tmp_path / "tools",
            uv_tool_bin_dir=tmp_path / "bin",
        ),
    )
    install = Mock()
    monkeypatch.setattr(lifecycle, "_run_lifecycle_step", install)
    with owner_path.open("w") as owner:
        fcntl.flock(owner, fcntl.LOCK_EX)
        assert not lifecycle.do_update()
    install.assert_not_called()


@pytest.mark.parametrize("mode", [False, True])
def test_restart_preserves_the_owned_daemon_gateway_mode(
    mode: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spawn = Mock()
    monkeypatch.setattr(lifecycle.subprocess, "Popen", spawn)
    monkeypatch.setattr("core.cli.ipc_client.is_serve_running", lambda: True)
    monkeypatch.setattr(lifecycle, "_serve_matches_cli", lambda executable: True)
    monkeypatch.setenv("GEODE_GATEWAY_ENABLED", str(not mode).lower())
    assert lifecycle._start_serve_background(executable="/tool/bin/geode", gateway_enabled=mode)
    assert spawn.call_args.args[0] == ["/tool/bin/geode", "serve"]
    assert spawn.call_args.kwargs["env"]["GEODE_GATEWAY_ENABLED"] == str(mode).lower()
