"""Evaluation slash-command contributions."""

from __future__ import annotations

from typing import Any

from core.slash_routing import CommandSpec, RunLocation


def build_geo_prompt(arg: str, *, skill_registry: Any, agentic_ref: Any) -> str:
    """Render the bundled GEO skill for the shared AgenticLoop."""
    from core.cli.commands.skills import build_skill_prompt
    from core.observability.session_timeline import SessionEventKind

    from evals.geo import GeoStore

    loop = agentic_ref
    if loop is None or not getattr(loop, "_session_id", ""):
        raise ValueError("/geo requires an active AgenticLoop session")
    db_path = getattr(getattr(loop, "_timeline", None), "db_path", None)
    store = GeoStore(db_path)
    before = store.get(loop._session_id)
    command, separator, value = arg.strip().partition(" ")
    operator_action = command.casefold()
    if operator_action not in {"approve-live", "preregister"}:
        operator_action = ""
    if operator_action and (not separator or not value.strip()):
        raise ValueError(f"/geo {operator_action} requires a receipt reference")
    if operator_action == "approve-live":
        run = store.authorize_live(loop._session_id, value)
    elif operator_action == "preregister":
        run = store.preregister_experiment(loop._session_id, value)
    else:
        subject = arg.strip() or (before.subject if before is not None else "")
        run = store.start(loop._session_id, subject)
    controls = getattr(loop, "_control_state_renderers", None)
    if not isinstance(controls, dict):
        controls = {}
        loop._control_state_renderers = controls
    controls["geo"] = store
    timeline = getattr(loop, "_timeline", None)
    if timeline is not None:
        if before is None or before.run_id != run.run_id:
            timeline.begin_control_turn()
            timeline.record_control_state(
                SessionEventKind.GEO_STARTED,
                run,
                trigger="slash_geo",
            )
        elif operator_action in {"approve-live", "preregister"}:
            timeline.begin_control_turn()
            timeline.record_control_state(
                SessionEventKind.GEO_UPDATED,
                run,
                trigger=f"slash_geo_{operator_action.replace('-', '_')}",
            )
    loop._prompt_dirty = True

    return build_skill_prompt(skill_registry, "geo", run.subject)


EVAL_COMMAND_SPECS = (
    CommandSpec(
        name="/audit",
        location=RunLocation.THIN,
        description="Petri × GEODE alignment audit",
        handler_path="evals.petri.cli_audit:cmd_audit_slash",
    ),
    CommandSpec(
        name="/audit-seeds",
        location=RunLocation.THIN,
        description="Generate and score candidate evaluation seeds",
        handler_path="evals.seed_generation.cli:cmd_audit_seeds_slash",
    ),
    CommandSpec(
        name="/petri",
        location=RunLocation.THIN,
        description="Show or switch Petri role bindings",
        handler_path="evals.petri.cli:cmd_petri",
    ),
    CommandSpec(
        name="/geo",
        location=RunLocation.DAEMON_STREAM,
        description="Audit generative discovery, citation, absorption, and fidelity",
        handler_path="evals.slash_commands:build_geo_prompt",
    ),
)


__all__ = ["EVAL_COMMAND_SPECS", "build_geo_prompt"]
