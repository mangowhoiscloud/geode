"""Forked skills inherit the active immutable tool catalog."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from core.cli.commands.skills import cmd_skill_invoke
from core.skills.skills import SkillDefinition, SkillRegistry


def test_context_fork_passes_active_bound_plan_snapshot() -> None:
    registry = SkillRegistry()
    registry.register(
        SkillDefinition(
            name="forked",
            body="Inspect $ARGUMENTS",
            context_fork=True,
        )
    )
    snapshot = (MagicMock(name="bound_plan"), MagicMock(name="transient_handlers"))
    loop = MagicMock()
    loop.bound_tool_plan_snapshot.return_value = snapshot

    with (
        patch("core.cli.bootstrap.run_agentic_oneshot") as run_oneshot,
        patch("core.cli.commands.console"),
    ):
        run_oneshot.return_value = SimpleNamespace(text="done", error=None)
        cmd_skill_invoke(registry, "forked catalog", agentic_ref=loop)

    assert run_oneshot.call_args.args == ("Inspect catalog",)
    assert run_oneshot.call_args.kwargs["quiet"] is True
    builder = run_oneshot.call_args.kwargs["tool_plan_builder"]
    assert builder() == snapshot
    loop.bound_tool_plan_snapshot.assert_called_once_with()
