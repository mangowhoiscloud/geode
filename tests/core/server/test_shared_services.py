"""Tests for core.server.supervised.services — SharedServices + SessionMode."""

from __future__ import annotations

import asyncio
from types import MappingProxyType
from unittest.mock import MagicMock, patch

import pytest
from core.server.supervised.services import (
    _MODE_DEFAULTS,
    SessionMode,
    SharedServices,
    _headless_denied_tools_for_mode,
    build_shared_services,
)
from core.tools.plan import ExecutionBinding, ToolSpec, bind_tool_plan, compile_tool_plan


def _bound_plan(*names: str):
    plan = compile_tool_plan(
        tuple(
            (
                ToolSpec(name=name, description=name, input_schema={"type": "object"}),
                f"test[{index}]",
            )
            for index, name in enumerate(names)
        ),
        tuple(ExecutionBinding(name=name, origin="test") for name in names),
    )
    return bind_tool_plan(plan, {name: MagicMock(return_value={"ok": True}) for name in names})


def _bound_builder(**_kwargs):
    return _bound_plan("test_tool"), {}


_TEST_WORKER_MODULE = "geode_product.worker"


class TestSessionMode:
    """SessionMode enum values and completeness."""

    def test_four_modes_exist(self) -> None:
        assert set(SessionMode) == {"repl", "ipc", "daemon", "scheduler"}

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

    def test_no_mode_uses_nonzero_max_rounds(self) -> None:
        """All modes use time-based constraints, not round limits."""
        for mode, defaults in _MODE_DEFAULTS.items():
            assert defaults["max_rounds"] == 0, f"{mode} has max_rounds={defaults['max_rounds']}"


class TestSharedServicesCreateSession:
    """SharedServices.create_session() wiring guarantees."""

    @pytest.fixture()
    def services(self) -> SharedServices:
        """Minimal SharedServices with mocked hook_system.

        v0.82.0 — `_model` / `_provider` fields removed; `create_session()`
        reads ``settings.model`` directly so a long-running daemon
        honours ``/model`` switches across IPC sessions.
        """
        return SharedServices(
            mcp_manager=MagicMock(),
            skill_registry=MagicMock(),
            hook_system=MagicMock(),
            tool_handlers={"test_tool": lambda **kw: {"ok": True}},
            _cost_budget=5.0,
        )

    def test_hooks_always_non_none(self, services: SharedServices) -> None:
        """Every mode receives hook_system — never None."""
        for mode in SessionMode:
            executor, loop = services.create_session(mode)
            assert loop._hooks is not None
            assert loop._hooks is services.hook_system

    def test_public_and_middleware_registries_are_process_owned(
        self, services: SharedServices
    ) -> None:
        executor_a, loop_a = services.create_session(SessionMode.REPL)
        executor_b, loop_b = services.create_session(SessionMode.DAEMON)

        assert executor_a.hook_registry is services.hook_registry
        assert executor_b.hook_registry is services.hook_registry
        assert loop_a._hook_registry is services.hook_registry
        assert loop_b._hook_registry is services.hook_registry
        assert executor_a.middleware_registry is services.middleware_registry
        assert executor_b.middleware_registry is services.middleware_registry
        assert loop_a._middleware_registry is services.middleware_registry
        assert loop_b._middleware_registry is services.middleware_registry

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

    def test_daemon_computer_use_is_fail_closed_by_default(self) -> None:
        denied = _headless_denied_tools_for_mode(
            SessionMode.DAEMON,
            gateway_allow_computer_use=False,
        )
        assert {"computer", "computer_use", "run_bash", "delegate_task"} <= denied

    def test_daemon_computer_use_opt_in_preserves_other_denials(self) -> None:
        from core.agent.safety import SENSITIVE_TOOLS

        denied = _headless_denied_tools_for_mode(
            SessionMode.DAEMON,
            gateway_allow_computer_use=True,
        )
        assert "computer" not in denied
        assert "computer_use" not in denied
        assert {"run_bash", "delegate_task"} <= denied
        assert denied >= SENSITIVE_TOOLS

    def test_daemon_non_boolean_opt_in_stays_fail_closed(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Defense in depth for legacy/mutated settings that skipped schema validation."""
        from core.config import settings

        computer = MagicMock(return_value={"result": "unexpected"})
        services = SharedServices(
            hook_system=MagicMock(),
            tool_handlers={"computer": computer, "computer_use": MagicMock()},
        )
        monkeypatch.setattr(settings, "gateway_allow_computer_use", "false")
        with patch("core.config.reload_settings_from_disk"):
            executor, _ = services.create_session(SessionMode.DAEMON)

        assert {"computer", "computer_use"} <= executor._denied_tools
        result = asyncio.run(executor.aexecute("computer", {}))
        assert result["denied"] is True
        computer.assert_not_called()

    def test_daemon_quoted_toml_false_is_denied_end_to_end(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from core import config

        monkeypatch.delenv("GEODE_GATEWAY_ALLOW_COMPUTER_USE", raising=False)
        monkeypatch.setattr(
            config,
            "_load_toml_config",
            lambda **_kw: {"gateway_allow_computer_use": "false"},
        )
        services = SharedServices(
            hook_system=MagicMock(),
            tool_handlers={"computer": MagicMock(), "computer_use": MagicMock()},
        )

        executor, _ = services.create_session(SessionMode.DAEMON)

        assert config.settings.gateway_allow_computer_use is False
        assert {"computer", "computer_use"} <= executor._denied_tools

    def test_daemon_env_true_outranks_toml_false_end_to_end(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from core import config

        monkeypatch.setenv("GEODE_GATEWAY_ALLOW_COMPUTER_USE", "true")
        monkeypatch.setattr(
            config,
            "_load_toml_config",
            lambda **_kw: {"gateway_allow_computer_use": False},
        )
        services = SharedServices(
            hook_system=MagicMock(),
            tool_handlers={"computer": MagicMock(), "computer_use": MagicMock()},
        )

        executor, _ = services.create_session(SessionMode.DAEMON)

        assert config.settings.gateway_allow_computer_use is True
        assert {"computer", "computer_use"}.isdisjoint(executor._denied_tools)

    def test_scheduler_ignores_gateway_computer_use_opt_in(self) -> None:
        denied = _headless_denied_tools_for_mode(
            SessionMode.SCHEDULER,
            gateway_allow_computer_use=True,
        )
        assert {"computer", "computer_use", "run_bash", "delegate_task"} <= denied

    def test_non_headless_modes_ignore_gateway_computer_use_policy(self) -> None:
        for mode in (SessionMode.REPL, SessionMode.IPC):
            assert not _headless_denied_tools_for_mode(
                mode,
                gateway_allow_computer_use=False,
            )

    def test_daemon_opt_in_wires_only_computer_handlers(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from core.config import settings

        services = SharedServices(
            hook_system=MagicMock(),
            tool_handlers={
                "computer": MagicMock(),
                "computer_use": MagicMock(),
                "run_bash": MagicMock(),
                "gmail_send": MagicMock(),
            },
        )
        monkeypatch.setattr(settings, "gateway_allow_computer_use", True)
        with patch("core.config.reload_settings_from_disk"):
            executor, _ = services.create_session(SessionMode.DAEMON)

        assert {"computer", "computer_use"} <= executor._handlers.keys()
        assert "run_bash" not in executor._handlers
        assert "gmail_send" not in executor._handlers
        assert {"computer", "computer_use"}.isdisjoint(executor._denied_tools)
        assert {"run_bash", "gmail_send"} <= executor._denied_tools

    def test_scheduler_time_budget(self, services: SharedServices) -> None:
        _, loop = services.create_session(SessionMode.SCHEDULER)
        assert loop._time_budget_s == 300.0

    def test_time_budget_override(self, services: SharedServices) -> None:
        _, loop = services.create_session(SessionMode.DAEMON, time_budget_override=120.0)
        assert loop._time_budget_s == 120.0

    def test_allowed_tools_reach_model_and_executor_rails(self, services: SharedServices) -> None:
        executor, loop = services.create_session(
            SessionMode.REPL,
            allowed_tool_names={"calculate"},
        )

        assert loop._allowed_tool_names == {"calculate"}
        assert {tool["name"] for tool in loop._tools} == {"calculate"}
        assert executor._allowed_tools == frozenset({"calculate"})

    def test_bound_plan_is_filtered_once_and_shared_by_identity(self) -> None:
        parent = _bound_plan("keep", "drop")
        services = SharedServices(hook_system=MagicMock(), bound_tool_plan=parent)

        executor, loop = services.create_session(
            SessionMode.REPL,
            allowed_tool_names={"keep"},
        )

        assert services.bound_tool_plan is parent
        assert executor._bound_tool_plan is loop._bound_tool_plan
        assert executor._bound_tool_plan is not parent
        assert executor._bound_tool_plan.tool_names == ("keep",)
        assert parent.tool_names == ("keep", "drop")
        assert tuple(executor._handlers) == ("keep",)
        snapshot_plan, snapshot_transient = loop.bound_tool_plan_snapshot()
        assert snapshot_plan is executor._bound_tool_plan
        assert snapshot_transient is executor._transient_handlers

    def test_policy_projected_special_route_is_denied_before_side_effect(
        self,
        tmp_path,
    ) -> None:
        import json
        from unittest.mock import AsyncMock

        from core.config.policy_source import PolicySourcePaths

        policy_path = tmp_path / "tool-policy.json"
        policy_path.write_text(
            json.dumps({"forbidden_tools": ["run_bash"]}),
            encoding="utf-8",
        )
        plan = compile_tool_plan(
            (
                (ToolSpec("memory_search", "Search memory", {}), "test"),
                (ToolSpec("run_bash", "Run command", {}), "test"),
            ),
            (
                ExecutionBinding("memory_search", "test"),
                ExecutionBinding("run_bash", "test", route="special"),
            ),
        )
        services = SharedServices(
            hook_system=MagicMock(),
            bound_tool_plan=bind_tool_plan(
                plan,
                {"memory_search": MagicMock(return_value={"ok": True})},
            ),
            policy_sources={
                "tool_policy": PolicySourcePaths(
                    "GEODE_TOOL_POLICY_OVERRIDE",
                    packaged_default=policy_path,
                )
            },
        )
        run_bash = AsyncMock(side_effect=AssertionError("run_bash side effect reached"))

        with (
            patch("core.config.reload_settings_from_disk"),
            patch(
                "core.agent.tool_executor.executor.ToolExecutor._run_bash_exec_async",
                run_bash,
            ),
        ):
            executor, loop = services.create_session(SessionMode.REPL)
            denied = asyncio.run(executor.aexecute("run_bash", {"command": "touch must-not-run"}))

        assert "run_bash" not in loop._bound_tool_plan.tool_names
        assert denied["denied"] is True
        run_bash.assert_not_awaited()

    def test_bound_session_executes_mcp_tool_added_after_start(self) -> None:
        from unittest.mock import AsyncMock

        mcp_manager = MagicMock(connection_epoch=0)
        mcp_manager.get_all_tools.return_value = []
        mcp_manager.find_server_for_tool.return_value = "dynamic"
        mcp_manager.acall_tool = AsyncMock(return_value={"ok": True})
        services = SharedServices(
            hook_system=MagicMock(),
            mcp_manager=mcp_manager,
            bound_tool_plan=_bound_plan("keep"),
        )
        executor, loop = services.create_session(SessionMode.REPL)
        added = {
            "name": "mcp_added_after_start",
            "description": "Added later",
            "input_schema": {"type": "object"},
        }

        mcp_manager.get_all_tools.return_value = [added]
        loop.refresh_tools()
        executor._mcp_approved_servers.add("dynamic")
        result = asyncio.run(executor.aexecute("mcp_added_after_start", {}))

        assert executor._allowed_tools is None
        assert "mcp_added_after_start" in executor._bound_allowed_tools
        assert result["ok"] is True
        mcp_manager.acall_tool.assert_awaited_once_with(
            "dynamic",
            "mcp_added_after_start",
            {},
        )

    @pytest.mark.parametrize(
        ("mode", "computer_visible"),
        [(SessionMode.DAEMON, False), (SessionMode.REPL, True)],
    )
    def test_session_denial_reaches_native_computer_wire(
        self,
        mode: SessionMode,
        computer_visible: bool,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from core.config import settings
        from core.llm.adapters import _anthropic_common
        from core.llm.adapters.base import AdapterCallResult, UsageSummary

        captured: dict[str, object] = {}

        class CaptureAdapter:
            name = "capture-anthropic"
            provider = "anthropic"

            async def acomplete(self, request):
                captured.update(_anthropic_common.build_create_kwargs(request))
                return AdapterCallResult(
                    text="ok",
                    usage=UsageSummary(),
                    stop_reason="completed",
                )

        monkeypatch.setattr(settings, "gateway_allow_computer_use", False)
        services = SharedServices(
            bound_tool_plan=_bound_plan("keep"),
            transient_tool_handlers={"computer": lambda **_kwargs: {"ok": True}},
        )
        with patch("core.config.reload_settings_from_disk"):
            _executor, loop = services.create_session(mode)
        loop._new_adapter = CaptureAdapter()

        with patch(
            "core.llm.providers.anthropic.is_computer_use_enabled",
            return_value=True,
        ):
            asyncio.run(
                loop._call_llm(
                    "Computer wire",
                    [{"role": "user", "content": "Continue."}],
                )
            )

        tools = captured.get("tools", [])
        assert isinstance(tools, list)
        assert any(tool.get("name") == "computer" for tool in tools) is computer_visible

    def test_session_without_computer_handler_never_advertises_native_computer(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from core.config import settings
        from core.llm.adapters import _anthropic_common
        from core.llm.adapters.base import AdapterCallResult, UsageSummary

        captured: dict[str, object] = {}

        class CaptureAdapter:
            name = "capture-anthropic"
            provider = "anthropic"

            async def acomplete(self, request):
                captured.update(_anthropic_common.build_create_kwargs(request))
                return AdapterCallResult(
                    text="ok",
                    usage=UsageSummary(),
                    stop_reason="completed",
                )

        monkeypatch.setattr(settings, "gateway_allow_computer_use", False)
        services = SharedServices(bound_tool_plan=_bound_plan("keep"))
        with patch("core.config.reload_settings_from_disk"):
            _executor, loop = services.create_session(SessionMode.REPL)
        loop._new_adapter = CaptureAdapter()

        with patch(
            "core.llm.providers.anthropic.is_computer_use_enabled",
            return_value=True,
        ):
            asyncio.run(
                loop._call_llm(
                    "Computer wire",
                    [{"role": "user", "content": "Continue."}],
                )
            )

        tools = captured.get("tools", [])
        assert isinstance(tools, list)
        assert not any(tool.get("name") == "computer" for tool in tools)

    def test_system_suffix_passed(self, services: SharedServices) -> None:
        _, loop = services.create_session(SessionMode.DAEMON, system_suffix="gateway instructions")
        assert "gateway instructions" in loop._system_suffix

    def test_current_loop_ctx_set(self, services: SharedServices) -> None:
        """create_session sets _current_loop_ctx ContextVar."""
        from core.cli.session_state import get_current_loop

        _, loop = services.create_session(SessionMode.REPL)
        assert get_current_loop() is loop

    def test_conversation_injected(self, services: SharedServices) -> None:
        from core.agent.conversation import ConversationContext

        ctx = ConversationContext()
        _, loop = services.create_session(SessionMode.REPL, conversation=ctx)
        assert loop.context is ctx

    def test_sessions_own_independent_metrics(self, services: SharedServices) -> None:
        from core.observability.session_metrics import set_current_session_metrics

        set_current_session_metrics(None)
        _, loop_a = services.create_session(SessionMode.IPC, session_id="session-a")
        _, loop_b = services.create_session(SessionMode.IPC, session_id="session-b")

        assert loop_a._session_metrics is not loop_b._session_metrics
        assert loop_a._session_metrics.session_id == "session-a"
        assert loop_b._session_metrics.session_id == "session-b"

    def test_autoresearch_scope_intentionally_aggregates_metrics(
        self,
        services: SharedServices,
    ) -> None:
        from core.observability.session_metrics import session_metrics_scope

        with session_metrics_scope(session_id="campaign", gen_tag="generation-1") as campaign:
            _, loop_a = services.create_session(SessionMode.IPC, session_id="session-a")
            _, loop_b = services.create_session(SessionMode.IPC, session_id="session-b")

        assert loop_a._session_metrics is campaign
        assert loop_b._session_metrics is campaign

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
        services = build_shared_services(
            tool_plan_builder=_bound_builder,
            worker_module=_TEST_WORKER_MODULE,
        )
        assert isinstance(services, SharedServices)

    def test_hook_system_auto_created(self) -> None:
        services = build_shared_services(
            tool_plan_builder=_bound_builder,
            worker_module=_TEST_WORKER_MODULE,
        )
        assert services.hook_system is not None

    def test_tool_handlers_populated(self) -> None:
        services = build_shared_services(
            tool_plan_builder=_bound_builder,
            worker_module=_TEST_WORKER_MODULE,
        )
        assert len(services.tool_handlers) > 0

    def test_tool_plan_builder_keeps_plan_and_handlers_together(self) -> None:
        bound = _bound_plan("test_tool")
        internal = {"internal": MagicMock()}
        builder = MagicMock(return_value=(bound, internal))

        services = build_shared_services(
            hook_system=MagicMock(),
            lane_queue=MagicMock(),
            tool_plan_builder=builder,
            worker_module=_TEST_WORKER_MODULE,
        )

        assert services.bound_tool_plan is bound
        assert services.tool_plan is bound.plan
        assert services.tool_handlers == {**bound.handlers, **internal}
        assert services.transient_tool_handlers == internal
        with pytest.raises(TypeError):
            services.tool_handlers["mutable"] = MagicMock()
        builder.assert_called_once_with(
            verbose=False,
            mcp_manager=None,
            skill_registry=None,
        )

    def test_tool_composition_has_one_authority(self) -> None:
        with pytest.raises(RuntimeError, match="injected bound tool-plan builder"):
            build_shared_services()

    def test_worker_composition_has_one_authority(self) -> None:
        with pytest.raises(RuntimeError, match="injected product worker module"):
            build_shared_services(tool_plan_builder=_bound_builder)

    def test_tool_plan_failure_precedes_process_side_effects(self) -> None:
        builder = MagicMock(side_effect=ValueError("invalid plan"))

        with (
            patch("core.wiring.bootstrap.build_hooks") as build_hooks,
            patch("core.wiring.bootstrap.build_tool_offload") as build_tool_offload,
            pytest.raises(ValueError, match="invalid plan"),
        ):
            build_shared_services(
                tool_plan_builder=builder,
                worker_module=_TEST_WORKER_MODULE,
            )

        build_hooks.assert_not_called()
        build_tool_offload.assert_not_called()

    def test_explicit_composition_reaches_every_session_owner(self) -> None:
        from core.hooks import MiddlewareRegistry

        policy_sources = MappingProxyType({"test": MagicMock()})
        activity_sink_provider = MagicMock(return_value=None)
        middleware_registry = MiddlewareRegistry()
        services = build_shared_services(
            policy_sources=policy_sources,
            activity_sink_provider=activity_sink_provider,
            middleware_registry=middleware_registry,
            tool_plan_builder=_bound_builder,
            worker_module=_TEST_WORKER_MODULE,
        )

        executor, loop = services.create_session(SessionMode.REPL)
        subagents = services._build_sub_agent_manager()

        assert services.policy_sources is policy_sources
        assert services.activity_sink_provider is activity_sink_provider
        assert executor.middleware_registry is middleware_registry
        assert loop._policy_sources is policy_sources
        assert loop._activity_sink_provider is activity_sink_provider
        assert subagents._policy_sources is policy_sources
        assert subagents._activity_sink_provider is activity_sink_provider

    def test_model_resolved_per_session(self) -> None:
        """v0.82.0 — `SharedServices` no longer freezes `_model` at boot.

        `create_session()` reads ``settings.model`` directly so a
        long-running daemon honours user-driven `/model` switches.
        Verify that the freshly constructed AgenticLoop carries the
        live ``settings.model`` rather than a stale boot-time value.
        """
        from core.config import settings
        from core.server.supervised.services import SessionMode

        services = build_shared_services(
            tool_plan_builder=_bound_builder,
            worker_module=_TEST_WORKER_MODULE,
        )
        _, loop = services.create_session(SessionMode.DAEMON)
        assert loop.model == settings.model

    def test_model_switch_propagates_across_sessions(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """v0.82.0 + PR-R6 staleness regression — disk-side ``GEODE_MODEL``
        mutation must reach the next session.

        Initial single-session check (``test_model_resolved_per_session``)
        only proves boot-time consistency. The v0.82.0 bug survived that
        check because the cached ``_model`` field happened to match
        ``settings.model`` at boot — divergence only emerged after
        ``cmd_model`` mutated state mid-flight.

        PR-R6 (2026-05-24) — rewritten to mutate ``GEODE_MODEL`` (the disk
        surface ``_apply_model`` actually writes) rather than an in-process
        ``settings.model`` attribute. The previous test mutated the
        in-process attribute directly, which silently reverts now that
        ``services.create_session`` calls
        ``reload_settings_from_disk()`` first (the env-var mutation is the
        whole point — that's how operator ``/model`` reaches the daemon).
        """
        from core.config import ANTHROPIC_PRIMARY, OPENAI_PRIMARY
        from core.server.supervised.services import SessionMode

        services = build_shared_services(
            tool_plan_builder=_bound_builder,
            worker_module=_TEST_WORKER_MODULE,
        )
        monkeypatch.setenv("GEODE_MODEL", ANTHROPIC_PRIMARY)
        _, loop_a = services.create_session(SessionMode.DAEMON)
        assert loop_a.model == ANTHROPIC_PRIMARY

        monkeypatch.setenv("GEODE_MODEL", OPENAI_PRIMARY)
        _, loop_b = services.create_session(SessionMode.DAEMON)
        assert loop_b.model == OPENAI_PRIMARY
        # ``loop_a`` is a separate AgenticLoop instance constructed before
        # the env flip — its captured ``model`` field stays at the value
        # it was built with (no auto-revert).
        assert loop_a.model == ANTHROPIC_PRIMARY

    def test_no_agentic_ref_attribute(self) -> None:
        """SharedServices should not have agentic_ref (removed in system-hardening)."""
        services = build_shared_services(
            tool_plan_builder=_bound_builder,
            worker_module=_TEST_WORKER_MODULE,
        )
        assert not hasattr(services, "agentic_ref")


class TestSchedulerREPLIsolation:
    """Verify scheduler sessions don't corrupt REPL state."""

    @pytest.fixture()
    def services(self) -> SharedServices:
        return SharedServices(
            mcp_manager=MagicMock(),
            skill_registry=MagicMock(),
            hook_system=MagicMock(),
            tool_handlers={"test_tool": lambda **kw: {"ok": True}},
            _cost_budget=5.0,
        )

    def test_scheduler_does_not_corrupt_repl_loop(self, services: SharedServices) -> None:
        """Scheduler create_session sets ContextVar per-thread, not shared ref."""
        import threading

        from core.cli.session_state import get_current_loop

        # REPL session in main thread
        _, repl_loop = services.create_session(SessionMode.REPL)
        assert get_current_loop() is repl_loop

        # Scheduler session in background thread
        sched_loops: list = []
        errors: list = []

        def sched_worker() -> None:
            try:
                _, sched_loop = services.create_session(
                    SessionMode.SCHEDULER, propagate_context=False
                )
                sched_loops.append(sched_loop)
            except Exception as exc:
                errors.append(exc)

        t = threading.Thread(target=sched_worker)
        t.start()
        t.join(timeout=5)

        assert not errors, f"Scheduler thread error: {errors}"
        assert len(sched_loops) == 1

        # REPL's ContextVar should still point to repl_loop (not scheduler's)
        assert get_current_loop() is repl_loop
        assert sched_loops[0] is not repl_loop

    def test_explicit_hook_system_used(self) -> None:
        mock_hooks = MagicMock()
        services = build_shared_services(
            hook_system=mock_hooks,
            tool_plan_builder=_bound_builder,
            worker_module=_TEST_WORKER_MODULE,
        )
        assert services.hook_system is mock_hooks
