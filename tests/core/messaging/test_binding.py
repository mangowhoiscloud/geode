"""Gateway binding publication and owned-resource shutdown boundaries."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from core.messaging.binding import ChannelManager
from core.messaging.models import ChannelBinding
from core.messaging.poller import BasePoller
from core.orchestration.hot_reload import ConfigWatcher


def test_late_invalid_rule_preserves_bindings_and_defaults() -> None:
    manager = ChannelManager()
    manager.add_binding(ChannelBinding(channel="slack", channel_id="OLD"))
    original = manager.list_bindings()
    with pytest.raises(ValueError):
        manager.load_bindings_from_config(
            {
                "gateway": {
                    "max_turns": 9,
                    "time_budget_s": 40,
                    "bindings": {
                        "rules": [
                            {"channel": "slack", "channel_id": "NEW"},
                            {"channel": "slack", "channel_id": "BAD", "time_budget_s": "bad"},
                        ]
                    },
                }
            }
        )
    assert manager.list_bindings() == original
    assert manager.gateway_max_turns == 0
    assert manager.gateway_time_budget_s == 120


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("time_budget_s", float("nan")),
        ("time_budget_s", float("inf")),
        ("time_budget_s", -1),
        ("time_budget_s", True),
        ("max_rounds", True),
        ("max_rounds", -1),
        ("max_turns", True),
        ("max_turns", -1),
        ("max_turns", 1.5),
    ],
)
def test_invalid_gateway_numbers_preserve_candidate(field: str, value: Any) -> None:
    manager = ChannelManager()
    manager.add_binding(ChannelBinding(channel="slack", channel_id="OLD"))
    with pytest.raises(ValueError):
        manager.load_bindings_from_config({"gateway": {field: value, "bindings": {"rules": []}}})
    assert [binding["channel_id"] for binding in manager.list_bindings()] == ["OLD"]
    assert manager.gateway_time_budget_s == 120
    assert manager.gateway_max_turns == 0


@pytest.mark.parametrize(
    ("field", "value"),
    [("time_budget_s", float("nan")), ("time_budget_s", -1), ("max_rounds", True)],
)
def test_invalid_binding_budget_preserves_candidate(field: str, value: Any) -> None:
    manager = ChannelManager()
    manager.add_binding(ChannelBinding(channel="slack", channel_id="OLD"))
    with pytest.raises(ValueError):
        manager.load_bindings_from_config(
            {
                "gateway": {
                    "time_budget_s": 20,
                    "bindings": {
                        "rules": [{"channel": "slack", "channel_id": "NEW", field: value}]
                    },
                }
            }
        )
    assert [binding["channel_id"] for binding in manager.list_bindings()] == ["OLD"]
    assert manager.gateway_time_budget_s == 120


@pytest.mark.parametrize("field", ["time_budget_s", "max_rounds"])
def test_zero_budget_and_count_keep_unlimited_compatibility(field: str) -> None:
    manager = ChannelManager()
    assert (
        manager.load_bindings_from_config(
            {
                "gateway": {
                    field: 0,
                    "max_turns": 0,
                    "bindings": {"rules": [{"channel": "slack", "channel_id": "NEW", field: 0}]},
                }
            }
        )
        == 1
    )
    assert manager.gateway_time_budget_s == 0
    assert manager.gateway_max_turns == 0
    assert manager.list_bindings()[0]["time_budget_s"] == 0


@pytest.mark.parametrize("config", [{}, {"gateway": {}}, {"gateway": {"bindings": {}}}])
def test_absent_rules_do_not_revoke_existing_bindings(config: dict[str, Any]) -> None:
    manager = ChannelManager()
    manager.add_binding(ChannelBinding(channel="slack", channel_id="OLD"))
    assert manager.load_bindings_from_config(config) == 0
    assert [binding["channel_id"] for binding in manager.list_bindings()] == ["OLD"]


def test_explicit_empty_rules_revoke_bindings() -> None:
    manager = ChannelManager()
    manager.add_binding(ChannelBinding(channel="slack", channel_id="OLD"))
    assert manager.load_bindings_from_config({"gateway": {"bindings": {"rules": []}}}) == 0
    assert manager.list_bindings() == []


@pytest.mark.parametrize(
    "bindings",
    [
        [],
        {"rules": {}},
        {"rules": ["slack"]},
        {"rules": [{"channel_id": "NEW"}]},
        {"rules": [{"channel": "slack"}]},
        {"rules": [{"channel": "slack", "channel_id": 123}]},
        {"rules": [{"channel": "slack", "channel_id": "NEW", "auto_respond": "false"}]},
        {"rules": [{"channel": "slack", "channel_id": "NEW", "allowed_tools": "all"}]},
    ],
)
def test_malformed_candidates_do_not_revoke_bindings(bindings: Any) -> None:
    manager = ChannelManager()
    manager.add_binding(ChannelBinding(channel="slack", channel_id="OLD"))
    with pytest.raises(ValueError):
        manager.load_bindings_from_config({"gateway": {"bindings": bindings}})
    assert [binding["channel_id"] for binding in manager.list_bindings()] == ["OLD"]


def test_stop_closes_watcher_and_remaining_pollers_after_poller_failure() -> None:
    watcher = ConfigWatcher(poll_interval_s=0.01)
    manager = ChannelManager(binding_watcher=watcher)
    failed_poller = MagicMock(spec=BasePoller)
    primary_error = RuntimeError("poller stop failed")
    failed_poller.stop.side_effect = primary_error
    remaining_poller = MagicMock(spec=BasePoller)
    manager.register_poller(failed_poller)
    manager.register_poller(remaining_poller)
    watcher.start()
    thread = watcher._thread
    assert thread is not None
    try:
        with pytest.raises(RuntimeError) as caught:
            manager.stop()
        assert caught.value is primary_error
        remaining_poller.stop.assert_called_once()
        assert not watcher.is_running
        assert not thread.is_alive()
    finally:
        watcher.stop()


def test_secondary_cleanup_error_does_not_replace_primary_error() -> None:
    watcher = MagicMock(spec=ConfigWatcher)
    watcher.stop.side_effect = ValueError("watcher stop failed")
    poller = MagicMock(spec=BasePoller)
    primary_error = RuntimeError("poller stop failed")
    poller.stop.side_effect = primary_error
    manager = ChannelManager(binding_watcher=watcher)
    manager.register_poller(poller)
    with pytest.raises(RuntimeError) as caught:
        manager.stop()
    assert caught.value is primary_error
    watcher.stop.assert_called_once()
