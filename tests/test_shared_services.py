"""Tests for core.gateway.shared_services — SharedServices + SessionMode."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from core.gateway.shared_services import (
    _MODE_DEFAULTS,
    SessionMode,
    SharedServices,
    build_shared_services,
)


class TestSessionMode:
    """SessionMode enum values and completeness."""

    def test_four_modes_exist(self) -> None:
        assert set(SessionMode) == {"repl", "daemon", "scheduler", "fork"}

    def test_all_modes_have_defaults(self) -> None:
        for mode in SessionMode:
            assert mode in _MODE_DEFAULTS, f"Missing defaults for {mode}"

    def test_repl_is_interactive(self) -> None:
        d = _MODE_DEFAULTS[SessionMode.REPL]
        assert d["hitl_level"] == 2
        assert d["quiet"] is False

    def test_daemon_is_headless(self) -> None:
        d = _MODE_DEFAULTS[SessionMode.DAEMON]
        assert d["hitl_level"] == 0
        assert d["quiet"] is True

    def test_scheduler_has_time_cap(self) -> None:
        d = _MODE_DEFAULTS[SessionMode.SCHEDULER]
        assert d["time_budget_s"] == 300.0
        assert d["max_rounds"] == 0  # unlimited rounds, time-based only

    def test_fork_has_short_timeout(self) -> None:
        d = _MODE_DEFAULTS[SessionMode.FORK]
        assert d["time_budget_s"] == 60.0

    def test_no_mode_uses_nonzero_max_rounds(self) -> None:
        """All modes use time-based constraints, not round limits."""
        for mode, defaults in _MODE_DEFAULTS.items():
            assert defaults["max_rounds"] == 0, f"{mode} has max_rounds={defaults['max_rounds']}"


class TestSharedServicesCreateSession:
    """SharedServices.create_session() wiring guarantees."""

    @pytest.fixture()
    def services(self) -> SharedServices:
        """Minimal SharedServices with mocked hook_system."""
        return SharedServices(
            mcp_manager=MagicMock(),
            skill_registry=MagicMock(),
            hook_system=MagicMock(),
            tool_handlers={"test_tool": lambda **kw: {"ok": True}},
            agentic_ref=[None],
            _model="claude-sonnet-4-6",
            _provider="anthropic",
            _cost_budget=5.0,
        )

    def test_hooks_always_non_none(self, services: SharedServices) -> None:
        """Every mode receives hook_system — never None."""
        for mode in SessionMode:
            executor, loop = services.create_session(mode)
            assert loop._hooks is not None
            assert loop._hooks is services.hook_system

    def test_mcp_shared_across_modes(self, services: SharedServices) -> None:
        """All modes receive the same MCP manager instance."""
        _, loop_repl = services.create_session(SessionMode.REPL)
        _, loop_daemon = services.create_session(SessionMode.DAEMON)
        assert loop_repl._mcp_manager is loop_daemon._mcp_manager
        assert loop_repl._mcp_manager is services.mcp_manager

    def test_cost_budget_shared(self, services: SharedServices) -> None:
        """All modes receive the same cost budget."""
        _, loop = services.create_session(SessionMode.SCHEDULER)
        assert loop._cost_budget == 5.0

    def test_repl_hitl_2(self, services: SharedServices) -> None:
        executor, _ = services.create_session(SessionMode.REPL)
        assert executor._hitl_level == 2

    def test_daemon_hitl_0(self, services: SharedServices) -> None:
        executor, _ = services.create_session(SessionMode.DAEMON)
        assert executor._hitl_level == 0

    def test_scheduler_time_budget(self, services: SharedServices) -> None:
        _, loop = services.create_session(SessionMode.SCHEDULER)
        assert loop._time_budget_s == 300.0

    def test_fork_time_budget(self, services: SharedServices) -> None:
        _, loop = services.create_session(SessionMode.FORK)
        assert loop._time_budget_s == 60.0

    def test_time_budget_override(self, services: SharedServices) -> None:
        _, loop = services.create_session(
            SessionMode.DAEMON, time_budget_override=120.0
        )
        assert loop._time_budget_s == 120.0

    def test_system_suffix_passed(self, services: SharedServices) -> None:
        _, loop = services.create_session(
            SessionMode.DAEMON, system_suffix="gateway instructions"
        )
        assert "gateway instructions" in loop._system_suffix

    def test_agentic_ref_updated(self, services: SharedServices) -> None:
        """create_session updates the shared agentic_ref."""
        _, loop1 = services.create_session(SessionMode.REPL)
        assert services.agentic_ref[0] is loop1
        _, loop2 = services.create_session(SessionMode.DAEMON)
        assert services.agentic_ref[0] is loop2

    def test_conversation_injected(self, services: SharedServices) -> None:
        from core.agent.conversation import ConversationContext

        ctx = ConversationContext()
        _, loop = services.create_session(SessionMode.REPL, conversation=ctx)
        assert loop.context is ctx

    def test_fresh_conversation_when_none(self, services: SharedServices) -> None:
        _, loop = services.create_session(SessionMode.SCHEDULER)
        assert loop.context is not None

    def test_max_rounds_zero_for_all_modes(self, services: SharedServices) -> None:
        """No mode caps rounds — time is the only constraint."""
        for mode in SessionMode:
            _, loop = services.create_session(mode)
            assert loop.max_rounds == 0, f"{mode} has max_rounds={loop.max_rounds}"

    def test_propagate_context_calls_propagate(self, services: SharedServices) -> None:
        with patch.object(services, "_propagate_contextvars") as mock_prop:
            services.create_session(SessionMode.SCHEDULER, propagate_context=True)
            mock_prop.assert_called_once()

    def test_no_propagate_by_default(self, services: SharedServices) -> None:
        with patch.object(services, "_propagate_contextvars") as mock_prop:
            services.create_session(SessionMode.REPL)
            mock_prop.assert_not_called()


class TestBuildSharedServices:
    """build_shared_services() factory integration."""

    def test_returns_shared_services(self) -> None:
        services = build_shared_services()
        assert isinstance(services, SharedServices)

    def test_hook_system_auto_created(self) -> None:
        services = build_shared_services()
        assert services.hook_system is not None

    def test_tool_handlers_populated(self) -> None:
        services = build_shared_services()
        assert len(services.tool_handlers) > 0

    def test_model_resolved(self) -> None:
        services = build_shared_services()
        assert services._model != ""

    def test_explicit_hook_system_used(self) -> None:
        mock_hooks = MagicMock()
        services = build_shared_services(hook_system=mock_hooks)
        assert services.hook_system is mock_hooks
