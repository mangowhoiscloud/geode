"""Serve delegates the borrowed scheduler to runtime and closes sibling owners."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock, PropertyMock

import pytest
import typer
from core.cli import typer_serve
from core.config import settings
from core.runtime import GeodeRuntime


@pytest.mark.parametrize(
    "failed_owner",
    ["scheduler_save", "scheduler_stop", "poller", "runtime", "gateway", "admission"],
)
@pytest.mark.parametrize("host_exit", ["normal", "error", "cancel", "startup"])
def test_serve_failure_cleanup_preserves_primary_and_closes_each_owner(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    failed_owner: str,
    host_exit: str,
) -> None:
    runtime = MagicMock()
    runtime._shutdown = False
    # Keep the actual runtime teardown; isolate resources and the host loop.
    runtime.shutdown.side_effect = lambda: GeodeRuntime.shutdown(runtime)
    runtime.scheduler_service.recover_missed_tasks.return_value = []
    runtime.scheduler_service.job_count = 0
    gateway, poller, webhook, services = (MagicMock() for _ in range(4))
    lane = MagicMock()
    type(lane).active_count = PropertyMock(side_effect=[1, 1, 0, 0])
    services.lane_queue.session_lane = lane
    gateway.gateway_max_turns = 0
    gateway.gateway_time_budget_s = 1.0
    primary = (
        asyncio.CancelledError("host cancelled")
        if host_exit == "cancel"
        else RuntimeError("host failed")
        if host_exit in {"error", "startup"}
        else None
    )
    if host_exit == "startup":
        gateway.start.side_effect = primary
    secondary = OSError("cleanup failed")
    if failed_owner == "scheduler_save":
        runtime.scheduler_service.save.side_effect = secondary
    elif failed_owner == "scheduler_stop":
        runtime.scheduler_service.stop.side_effect = secondary
    elif failed_owner == "poller":
        poller.stop.side_effect = secondary
    elif failed_owner == "gateway":
        gateway.stop.side_effect = secondary
    elif failed_owner == "admission":
        poller.stop_accepting.side_effect = secondary
    else:
        runtime.dreaming_service.close.side_effect = (
            KeyboardInterrupt("secondary interruption")
            if primary is not None
            else TimeoutError("join failed")
        )

    def run(coroutine: Any) -> None:
        coroutine.close()
        assert host_exit != "startup"
        if primary is not None:
            raise primary

    monkeypatch.setattr(settings, "gateway_enabled", True)
    monkeypatch.setattr(settings, "webhook_enabled", True)
    monkeypatch.setattr("core.observability.logging_config.configure_logging", lambda *_: None)
    monkeypatch.setattr("core.cli.bootstrap.setup_contextvars", lambda **_: None)
    monkeypatch.setattr(typer_serve, "check_readiness", MagicMock())
    monkeypatch.setattr("core.memory.session_checkpoint.SessionCheckpoint", MagicMock())
    monkeypatch.setattr("core.wiring.adapters.get_gateway_manager", lambda: gateway)
    monkeypatch.setattr("core.wiring.adapters.build_cli_poller", lambda *_, **__: poller)
    monkeypatch.setattr("core.wiring.adapters.start_gateway_webhook", lambda *_, **__: webhook)
    monkeypatch.setattr("signal.signal", lambda *_: None)
    monkeypatch.setattr(typer_serve, "run_process_coroutine", run)

    with pytest.raises(type(primary) if primary is not None else typer.Exit) as caught:
        typer_serve.run_serve(
            0.1, runtime_builder=lambda: runtime, services_builder=lambda **_: services
        )
    if primary is not None:
        assert caught.value is primary
    else:
        assert caught.value.exit_code == 1
    output = capsys.readouterr().out
    assert "GEODE daemon shutdown incomplete" in output
    assert "Draining 1 active session" in output
    assert "GEODE daemon stopped." not in output
    poller.stop.assert_called_once()
    webhook.shutdown.assert_called_once()
    runtime.shutdown.assert_called_once()
    runtime.scheduler_service.save.assert_called_once()
    runtime.scheduler_service.stop.assert_called_once()
    runtime.mcp_manager.shutdown.assert_called_once()
    runtime.hooks.close.assert_called_once()
    assert runtime._shutdown is (failed_owner in {"poller", "gateway", "admission"})


@pytest.mark.parametrize("cleanup_failed", [False, True])
def test_cli_startup_failure_requires_cleanup_before_gateway_fallback(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    cleanup_failed: bool,
) -> None:
    runtime, gateway, poller, webhook, services = (MagicMock() for _ in range(5))
    runtime.scheduler_service.recover_missed_tasks.return_value = []
    runtime.scheduler_service.job_count = 0
    runtime.shutdown.return_value = True
    services.lane_queue.session_lane.active_count = 0
    gateway.gateway_max_turns = 0
    gateway.gateway_time_budget_s = 1.0
    primary = RuntimeError("CLI readiness timed out")
    poller.start.side_effect = primary
    if cleanup_failed:
        poller.stop.side_effect = TimeoutError("CLI worker is still stopping")
    run = MagicMock(side_effect=lambda coroutine: coroutine.close())

    monkeypatch.setattr(settings, "gateway_enabled", True)
    monkeypatch.setattr(settings, "webhook_enabled", True)
    monkeypatch.setattr("core.observability.logging_config.configure_logging", lambda *_: None)
    monkeypatch.setattr("core.cli.bootstrap.setup_contextvars", lambda **_: None)
    monkeypatch.setattr(typer_serve, "check_readiness", MagicMock())
    monkeypatch.setattr("core.memory.session_checkpoint.SessionCheckpoint", MagicMock())
    monkeypatch.setattr("core.wiring.adapters.get_gateway_manager", lambda: gateway)
    monkeypatch.setattr("core.wiring.adapters.build_cli_poller", lambda *_, **__: poller)
    monkeypatch.setattr("core.wiring.adapters.start_gateway_webhook", lambda *_, **__: webhook)
    monkeypatch.setattr("signal.signal", lambda *_: None)
    monkeypatch.setattr(typer_serve, "run_process_coroutine", run)

    if cleanup_failed:
        with pytest.raises(typer.Exit) as caught:
            typer_serve.run_serve(
                0.1, runtime_builder=lambda: runtime, services_builder=lambda **_: services
            )
        assert caught.value.exit_code == 1
        assert caught.value.__cause__ is primary
        gateway.start.assert_not_called()
        run.assert_not_called()
        assert "GEODE daemon stopped." not in capsys.readouterr().out
    else:
        typer_serve.run_serve(
            0.1, runtime_builder=lambda: runtime, services_builder=lambda **_: services
        )
        gateway.start.assert_called_once()
        run.assert_called_once()
        assert "GEODE daemon stopped." in capsys.readouterr().out
    poller.stop.assert_called_once()
    webhook.shutdown.assert_called_once()
    runtime.shutdown.assert_called_once()
