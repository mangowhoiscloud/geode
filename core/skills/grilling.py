"""Grilling skill invocation and session control-state composition."""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.memory.grills import GrillStore
from core.observability.session_timeline import SessionEventKind
from core.skills.skills import SkillRegistry, build_skill_prompt

if TYPE_CHECKING:
    from core.agent.loop import AgenticLoop


def build_grilling_prompt(
    arg: str, *, skill_registry: SkillRegistry | None, agentic_ref: AgenticLoop | None
) -> str:
    """Build the `/grill` prompt without adding a second execution engine."""
    loop = agentic_ref
    if loop is None or not getattr(loop, "_session_id", ""):
        raise ValueError("/grill requires an active AgenticLoop session")
    db_path = getattr(getattr(loop, "_timeline", None), "db_path", None)
    store = GrillStore(db_path)
    before = store.get(loop._session_id)
    subject = arg.strip() or (before.subject if before is not None else "")
    grill = store.start(loop._session_id, subject)
    controls = getattr(loop, "_control_state_renderers", None)
    if not isinstance(controls, dict):
        controls = {}
        loop._control_state_renderers = controls
    controls["grill"] = store
    if before is None or before.grill_id != grill.grill_id:
        timeline = getattr(loop, "_timeline", None)
        if timeline is not None:
            timeline.begin_control_turn()
            timeline.record_control_state(
                SessionEventKind.GRILL_STARTED,
                grill,
                trigger="slash_grill",
            )
    loop._prompt_dirty = True
    return build_skill_prompt(skill_registry, "grilling", subject)
