"""PR-JSON-WIRE (2026-05-25) — per-role JSON Schema wire-through tests.

Verifies each seed-generation role populates ``SubTask.response_schema``
with the schema declared in ``plugins.seed_generation.json_schemas``,
and that the schema's ``required`` list matches the role's
``_REQUIRED_*_FIELDS`` constant. Drift between the schema's
required-list and the parser's required-fields would let the LLM
emit valid-against-schema responses that the parser rejects (or
vice versa).

Why the cross-check matters: the schema is what the provider
enforces (claude-cli ``--json-schema``); the constants are what
the parser checks after the fact. They must agree, or the wire-
through gives false confidence.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from plugins.seed_generation.json_schemas import (
    CRITIQUE_SCHEMA,
    EVOLVE_SCHEMA,
    LITERATURE_REVIEW_SCHEMA,
    META_REVIEW_SCHEMA,
    PILOT_SCHEMA,
    PROXIMITY_SCHEMA,
    SUPERVISOR_SCHEMA,
    VOTE_SCHEMA,
)

# ────────────────────── Schema ↔ required-fields drift ────────────────────────


def test_proximity_schema_required_matches_parser_required() -> None:
    from plugins.seed_generation.agents.proximity import _REQUIRED_FIELDS

    assert set(PROXIMITY_SCHEMA["required"]) == set(_REQUIRED_FIELDS)


def test_critique_schema_required_matches_parser_required() -> None:
    from plugins.seed_generation.agents.critic import _REQUIRED_CRITIQUE_FIELDS

    # PR-SCHEMA-PARSER-DRIFT-CLOSE (2026-05-26) — tightened from
    # ``issubset`` to ``==``. Pre-fix the schema permissively allowed
    # ``discrimination_estimate`` to be missing while the parser still
    # rejected it (smoke 18: 4/12 critic sub-agents malformed_critique
    # for exactly this drift). The worker-side ``_needs_schema_retry``
    # only fires for schema ``required`` violations; keeping the
    # parser tuple stricter than the schema meant the retry path was
    # silently dead for the one field most likely to be dropped. Both
    # SoTs must now agree.
    assert set(CRITIQUE_SCHEMA["required"]) == set(_REQUIRED_CRITIQUE_FIELDS)


def test_pilot_schema_required_matches_parser_required() -> None:
    from plugins.seed_generation.agents.pilot import _REQUIRED_PILOT_FIELDS

    assert set(PILOT_SCHEMA["required"]) == set(_REQUIRED_PILOT_FIELDS)


def test_vote_schema_required_matches_parser_required() -> None:
    from plugins.seed_generation.agents.ranker import _REQUIRED_VOTE_FIELDS

    assert set(VOTE_SCHEMA["required"]) == set(_REQUIRED_VOTE_FIELDS)


def test_evolve_schema_required_matches_parser_required() -> None:
    from plugins.seed_generation.agents.evolver import _REQUIRED_EVOLVE_FIELDS

    assert set(EVOLVE_SCHEMA["required"]) == set(_REQUIRED_EVOLVE_FIELDS)


def test_meta_review_schema_required_matches_parser_required() -> None:
    from plugins.seed_generation.agents.meta_reviewer import _REQUIRED_META_FIELDS

    assert set(META_REVIEW_SCHEMA["required"]) == set(_REQUIRED_META_FIELDS)


def test_supervisor_schema_required_matches_parser_required() -> None:
    # PR-SCHEMA-PARSER-DRIFT-CLOSE (2026-05-26) — supervisor was the
    # only Loop-1 phase whose schema did not exist. The parser tuple
    # has been in supervisor.py since the role landed; the schema
    # was added in this PR.
    from plugins.seed_generation.agents.supervisor import _REQUIRED_SUPERVISOR_FIELDS

    assert set(SUPERVISOR_SCHEMA["required"]) == set(_REQUIRED_SUPERVISOR_FIELDS)


def test_literature_review_schema_required_matches_parser_call_site() -> None:
    # literature_review.py:144 passes ``required_fields`` inline to
    # ``parse_structured_output`` rather than declaring a
    # module-level constant. Pin the inline tuple ↔ schema equality
    # so a future caller-side edit can't drift from the schema.
    from plugins.seed_generation.agents import literature_review as litreview

    source = Path(litreview.__file__).read_text(encoding="utf-8")
    # The required_fields tuple is the only multi-string tuple in
    # the file's parse_structured_output call site (line ~144).
    assert 'required_fields=("articles_with_reasoning", "snapshots")' in source
    assert set(LITERATURE_REVIEW_SCHEMA["required"]) == {
        "articles_with_reasoning",
        "snapshots",
    }


# ────────────────────── SubTask carries response_schema ───────────────────────


def _pipeline_state_with_candidate() -> object:
    """Minimal PipelineState stub for _build_tasks tests."""
    from plugins.seed_generation.orchestrator import PipelineState

    state = PipelineState(
        run_id="run-x",
        target_dim="redundant_tool_invocation",
        gen_tag="gen1",
        candidates_requested=1,
    )
    state.candidates = [
        {
            "id": "gen1-000-aaaaaaaa",
            "path": "/tmp/gen1-000.md",  # noqa: S108
            "target_dim": "redundant_tool_invocation",
        }
    ]
    state.target_dim = "redundant_tool_invocation"
    return state


def test_proximity_build_tasks_carries_schema() -> None:
    from plugins.seed_generation.agents.proximity import Proximity

    state = _pipeline_state_with_candidate()
    agent = Proximity(MagicMock())
    task = agent._build_task(state)  # type: ignore[attr-defined]
    assert task.response_schema is PROXIMITY_SCHEMA


def test_critic_build_tasks_carries_schema() -> None:
    from plugins.seed_generation.agents.critic import Critic

    state = _pipeline_state_with_candidate()
    agent = Critic(MagicMock())
    tasks = agent._build_tasks(state)  # type: ignore[attr-defined]
    assert tasks
    for t in tasks:
        assert t.response_schema is CRITIQUE_SCHEMA


def test_pilot_build_tasks_carries_schema() -> None:
    from plugins.seed_generation.agents.pilot import Pilot

    state = _pipeline_state_with_candidate()
    agent = Pilot(MagicMock())
    tasks = agent._build_tasks(state)  # type: ignore[attr-defined]
    assert tasks
    for t in tasks:
        assert t.response_schema is PILOT_SCHEMA


def test_supervisor_build_task_carries_schema() -> None:
    # PR-SCHEMA-PARSER-DRIFT-CLOSE (2026-05-26) — supervisor's spawn
    # site previously omitted ``response_schema=`` entirely, so the
    # worker-side retry never fired and the supervisor.json checkpoint
    # regressed in smoke 18 vs smoke 17.
    from plugins.seed_generation.agents.supervisor import Supervisor

    state = _pipeline_state_with_candidate()
    agent = Supervisor(MagicMock())
    task = agent._build_task(state)  # type: ignore[attr-defined]
    assert task.response_schema is SUPERVISOR_SCHEMA


def test_literature_review_build_task_carries_schema() -> None:
    # PR-SCHEMA-PARSER-DRIFT-CLOSE (2026-05-26) — the schema has
    # existed since PR-JSON-WIRE (#79) but literature_review.py's
    # ``_build_task`` was the one spawn site that never wired it.
    from plugins.seed_generation.agents.literature_review import LiteratureReview

    state = _pipeline_state_with_candidate()
    agent = LiteratureReview(MagicMock())
    task = agent._build_task(state, max_papers=1)  # type: ignore[attr-defined]
    assert task.response_schema is LITERATURE_REVIEW_SCHEMA


# ────────────────────── End-to-end wire-through ───────────────────────────────


def test_subtask_response_schema_field_default_none() -> None:
    """Back-compat — SubTask without a schema keeps the legacy
    free-form-text contract."""
    from core.agent.sub_agent import SubTask

    task = SubTask(task_id="t1", description="desc", task_type="x")
    assert task.response_schema is None


def test_worker_request_round_trips_response_schema() -> None:
    """SubAgentManager → WorkerRequest → from_dict round-trip
    preserves the schema dict."""
    from core.agent.worker import WorkerRequest

    schema = {"type": "object", "properties": {"foo": {"type": "string"}}, "required": ["foo"]}
    req = WorkerRequest(task_id="t1", response_schema=schema)
    encoded = req.to_dict()
    assert encoded["response_schema"] == schema
    decoded = WorkerRequest.from_dict(encoded)
    assert decoded.response_schema == schema


def test_worker_request_from_dict_defaults_to_none() -> None:
    """Legacy payload (no response_schema key) deserialises to None
    so the worker keeps the free-form-text path."""
    from core.agent.worker import WorkerRequest

    decoded = WorkerRequest.from_dict({"task_id": "t1"})
    assert decoded.response_schema is None


def test_build_adapter_request_threads_response_schema() -> None:
    """``build_adapter_request`` forwards ``response_schema`` into
    ``AdapterCallRequest`` so the adapter call site gets the value
    AgenticLoop holds."""
    from core.llm.adapters.translation import build_adapter_request

    schema = {"type": "object", "required": ["x"]}
    req = build_adapter_request(
        model="claude-opus-4-7",
        system="",
        messages=[],
        tools=[],
        tool_choice="auto",
        max_tokens=100,
        temperature=0.0,
        thinking_budget=0,
        effort="high",
        response_schema=schema,
    )
    assert req.response_schema == schema


def test_build_adapter_request_default_response_schema_none() -> None:
    from core.llm.adapters.translation import build_adapter_request

    req = build_adapter_request(
        model="claude-opus-4-7",
        system="",
        messages=[],
        tools=[],
        tool_choice="auto",
        max_tokens=100,
        temperature=0.0,
        thinking_budget=0,
        effort="high",
    )
    assert req.response_schema is None


def test_subagent_manager_threads_schema_to_worker_request() -> None:
    """SubAgentManager._build_worker_request copies SubTask.response_schema
    into WorkerRequest.response_schema (the parent → child IPC SoT)."""
    from core.agent.sub_agent import SubAgentManager, SubTask
    from core.orchestration.isolated_execution import IsolatedRunner

    schema = {"type": "object", "required": ["foo"]}
    task = SubTask(
        task_id="t1",
        description="d",
        task_type="x",
        response_schema=schema,
    )
    manager = SubAgentManager(runner=IsolatedRunner(), action_handlers={})
    request = manager._build_worker_request(task)
    assert request.response_schema == schema


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
