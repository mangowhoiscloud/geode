"""Failure-atomicity tests for scheduler wiring."""

from unittest.mock import MagicMock, patch

import pytest
from core.wiring.scheduling import build_scheduling


def test_build_scheduling_stops_trigger_thread_when_service_creation_fails() -> None:
    trigger_manager = MagicMock()
    with (
        patch("core.wiring.scheduling.TriggerManager", return_value=trigger_manager),
        patch("core.scheduler.create_scheduler", side_effect=RuntimeError("service failed")),
        pytest.raises(RuntimeError, match="service failed"),
    ):
        build_scheduling(hooks=MagicMock())

    trigger_manager.start_scheduler.assert_called_once()
    trigger_manager.stop_scheduler.assert_called_once()


def test_build_scheduling_calls_only_the_explicit_feature_registrar() -> None:
    hooks = MagicMock()
    trigger_manager = MagicMock()
    scheduler_service = MagicMock()
    feature_registrar = MagicMock()
    with (
        patch("core.wiring.scheduling.TriggerManager", return_value=trigger_manager),
        patch("core.scheduler.create_scheduler", return_value=scheduler_service),
    ):
        build_scheduling(hooks=hooks, feature_registrar=feature_registrar)

    feature_registrar.assert_called_once_with(trigger_manager, hooks)
