from __future__ import annotations

from types import SimpleNamespace

from core.agent.loop._context import inject_runtime_hints, render_control_state_hints
from core.agent.plan import Plan, PlanStep, render_plan_for_prompt
from core.agent.system_prompt import PROMPT_CACHE_BOUNDARY, build_system_prompt
from core.llm.adapters._openai_common import _prompt_cache_key
from core.memory.goals import GoalStore
from core.memory.grills import GrillStore
from evals.geo import GeoStore


def test_slash_control_snapshots_stay_in_dynamic_zone_and_preserve_cache_key(tmp_path) -> None:
    db_path = tmp_path / "sessions.db"
    goal_store = GoalStore(db_path)
    grill_store = GrillStore(db_path)
    geo_store = GeoStore(db_path)
    goal_store.create("s-zone", "Persist safely")
    grill_store.start("s-zone", "Choose a boundary")
    geo_store.start("s-zone", "Audit example.test")
    loop = SimpleNamespace(
        _session_id="s-zone",
        _control_state_renderers={
            "goal": goal_store,
            "grill": grill_store,
            "geo": geo_store,
        },
    )
    plan = Plan(
        steps=(PlanStep("inspect", "Inspect evidence", "Gap is observed"),),
        reasoning="Prerequisite first.",
    )

    base = build_system_prompt(model="gpt-5.6-luna")
    enriched = inject_runtime_hints(
        base,
        render_plan_for_prompt(plan),
        render_control_state_hints(loop),
    )

    assert base.split(PROMPT_CACHE_BOUNDARY, 1)[0] == enriched.split(PROMPT_CACHE_BOUNDARY, 1)[0]
    assert _prompt_cache_key(base) == _prompt_cache_key(enriched)
    assert enriched.count("<dynamic_context>") == enriched.count("</dynamic_context>") == 1
    dynamic = enriched.split(PROMPT_CACHE_BOUNDARY, 1)[1]
    assert all(
        marker in dynamic for marker in ("<goal_state", "<plan>", "<grill_state", "<geo_state")
    )
    assert enriched.rstrip().endswith("</dynamic_context>")
