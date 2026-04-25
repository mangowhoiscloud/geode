"""Phase 3 — /login unified command UX tests.

Smoke-tests for the subcommand router and the side effects on
ProfileStore + PlanRegistry. UI rendering is covered by snapshot tests
of the dashboard string output.
"""

from __future__ import annotations

from unittest.mock import patch

from core.auth.plan_registry import (
    get_plan_registry,
    reset_plan_registry,
)
from core.auth.plans import GLM_CODING_TIERS, default_plan_for_payg
from core.cli.commands import cmd_login


def _reset_state() -> None:
    from core.lifecycle import container as infra

    infra._profile_store = None
    infra._profile_rotator = None
    reset_plan_registry()


class TestSubcommandRouter:
    def test_bare_login_renders_dashboard(self) -> None:
        _reset_state()
        with patch("core.cli.commands.console") as mock_console:
            cmd_login("")
            assert mock_console.print.called

    def test_help_subcommand(self) -> None:
        _reset_state()
        with patch("core.cli.commands.console") as mock_console:
            cmd_login("help")
            text = " ".join(
                str(call.args[0]) for call in mock_console.print.call_args_list if call.args
            )
            assert "/login add" in text
            assert "/login oauth" in text

    def test_unknown_subcommand_warns(self) -> None:
        _reset_state()
        with patch("core.cli.commands.console") as mock_console:
            cmd_login("nonsense")
            text = " ".join(
                str(call.args[0]) for call in mock_console.print.call_args_list if call.args
            )
            assert "Unknown" in text


class TestSetKeyAndUse:
    def test_set_key_updates_existing_plan(self) -> None:
        _reset_state()
        registry = get_plan_registry()
        plan = default_plan_for_payg("openai", "")
        registry.add(plan)
        cmd_login(f"set-key {plan.id} sk-fresh-key-1234567890")
        from core.lifecycle.container import ensure_profile_store

        store = ensure_profile_store()
        bound = [p for p in store.list_all() if p.plan_id == plan.id]
        assert bound and bound[0].key == "sk-fresh-key-1234567890"

    def test_set_key_unknown_plan_warns(self) -> None:
        _reset_state()
        with patch("core.cli.commands.console") as mock_console:
            cmd_login("set-key ghost sk-key")
            text = " ".join(
                str(call.args[0]) for call in mock_console.print.call_args_list if call.args
            )
            assert "Unknown plan" in text

    def test_use_pins_plan_for_provider(self) -> None:
        _reset_state()
        registry = get_plan_registry()
        plan = GLM_CODING_TIERS["lite"]
        registry.add(plan)
        cmd_login(f"use {plan.id}")
        chain = registry.get_routing("glm-5.1")
        assert chain[0] == plan.id


class TestRouteAndQuota:
    def test_route_requires_known_plan(self) -> None:
        _reset_state()
        with patch("core.cli.commands.console") as mock_console:
            cmd_login("route glm-5.1 ghost-plan")
            text = " ".join(
                str(call.args[0]) for call in mock_console.print.call_args_list if call.args
            )
            assert "Unknown plan" in text

    def test_route_records_chain(self) -> None:
        _reset_state()
        registry = get_plan_registry()
        a = default_plan_for_payg("glm", "")
        a.id = "glm-a"
        registry.add(a)
        b = GLM_CODING_TIERS["lite"]
        registry.add(b)
        cmd_login(f"route glm-5.1 {b.id} {a.id}")
        assert registry.get_routing("glm-5.1") == [b.id, a.id]

    def test_quota_shows_subscription_plans(self) -> None:
        _reset_state()
        registry = get_plan_registry()
        plan = GLM_CODING_TIERS["lite"]
        registry.add(plan)
        with patch("core.cli.commands.console") as mock_console:
            cmd_login("quota")
            text = " ".join(
                str(call.args[0]) for call in mock_console.print.call_args_list if call.args
            )
            assert plan.id in text
            assert "80" in text  # max_calls


class TestLegacyKeyAlias:
    def test_bare_key_redirects_to_login(self) -> None:
        _reset_state()
        from core.cli.commands import cmd_key

        with patch("core.cli.commands.console") as mock_console:
            cmd_key("")
            text = " ".join(
                str(call.args[0]) for call in mock_console.print.call_args_list if call.args
            )
            # Either the deprecation hint or the dashboard "Plans" header must show
            assert "Plans" in text or "redirects" in text
