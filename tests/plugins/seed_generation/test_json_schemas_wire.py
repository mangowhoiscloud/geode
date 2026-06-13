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


# ────────────────────── PR-STRICT-COMPATIBLE-SCHEMAS invariants ──────────────


# PR-STRICT-COMPATIBLE-SCHEMAS (2026-05-26) — the codex_oauth adapter
# auto-detects strict-mode for ``text.format`` via
# ``_is_openai_strict_compatible``. Pre-fix every seed-gen schema
# used the permissive ``_additive()`` helper, so codex always landed
# on ``strict: False`` → text.format became a *hint*, not a
# *constraint* → gpt-5.5 reasoning models could burn the output
# budget on encrypted reasoning items and return empty
# ``output_text`` (smoke 18: vote-m000-openai.openai-codex turn 1
# cost $0.0358 with 0 assistant_message).
#
# The schemas listed in _STRICT_ROLES below were converted to
# ``_strict_additive`` (additionalProperties:false + every property
# in required). The remaining two (META_REVIEW, LITERATURE_REVIEW)
# cannot be strict because they use typed-additional maps (per-dim
# coverage / arxiv-id keyed snapshots) the schema can't enumerate at
# compile time. (The Pilot role lost its schema in
# PR-PILOT-UNIFY-DIM-EXTRACT 2026-06-04 — it no longer spawns an LLM.)


_STRICT_ROLES = {
    "PROXIMITY_SCHEMA": PROXIMITY_SCHEMA,
    "CRITIQUE_SCHEMA": CRITIQUE_SCHEMA,
    "VOTE_SCHEMA": VOTE_SCHEMA,
    "EVOLVE_SCHEMA": EVOLVE_SCHEMA,
    "SUPERVISOR_SCHEMA": SUPERVISOR_SCHEMA,
}

_NON_STRICT_ROLES = {
    "META_REVIEW_SCHEMA": META_REVIEW_SCHEMA,
    "LITERATURE_REVIEW_SCHEMA": LITERATURE_REVIEW_SCHEMA,
}


@pytest.mark.parametrize("name,schema", list(_STRICT_ROLES.items()))
def test_strict_role_schemas_pass_openai_strict_check(name: str, schema: dict) -> None:
    """Every converted schema satisfies OpenAI's strict-mode subset.

    Asserts ``_is_openai_strict_compatible`` returns True so the codex
    backend wires ``strict: True`` into ``text.format`` — the
    constraint that prevents gpt-5.5's reasoning budget from consuming
    the entire output budget on empty responses.
    """
    from core.llm.adapters._openai_common import _is_openai_strict_compatible

    assert _is_openai_strict_compatible(schema), (
        f"{name} declared strict-compatible but failed the codex adapter's "
        "strict-detector check. Verify every nested object uses "
        "_strict_additive (additionalProperties:false + required = "
        "list(properties.keys())) and every array items entry is strict-compatible."
    )


@pytest.mark.parametrize("name,schema", list(_NON_STRICT_ROLES.items()))
def test_non_strict_role_schemas_documented_reason(name: str, schema: dict) -> None:
    """The roles flagged non-strict-compatible by design must FAIL the
    strict-detector check.

    If a future PR accidentally tightens these (e.g. enumerates the
    Petri dim catalog into properties), this test catches the
    silent strict-mode flip — operators reading the
    ``additionalProperties: typed`` would expect the schema to remain
    permissive, but the detector would now return True and codex
    would start enforcing strict on a schema the role doesn't
    actually conform to.
    """
    from core.llm.adapters._openai_common import _is_openai_strict_compatible

    assert not _is_openai_strict_compatible(schema), (
        f"{name} is documented as non-strict-compatible "
        "(typed-additionalProperties for per-dim or per-arxiv-id maps) "
        "but now passes the strict-detector check. Either the schema "
        "actually became strict-compatible (update the docstring + "
        "move it to _STRICT_ROLES) or a property accidentally lost "
        "its typed-additional escape (regression — restore it)."
    )


def test_strict_helper_derives_required_from_properties_keys() -> None:
    """``_strict_additive`` must list every property in required;
    this is what makes the schema strict-compatible.
    """
    from plugins.seed_generation.json_schemas import _strict_additive

    schema = _strict_additive(
        properties={
            "a": {"type": "string"},
            "b": {"type": "number"},
        }
    )
    assert schema["required"] == ["a", "b"]
    assert schema["additionalProperties"] is False


# ──────────────────── PR-SCHEMA-TYPE-DRIFT-INVARIANT ───────────────────────
#
# Codex MCP retro-audit catch (post-PR-1 #1698, deferred to backlog item
# #99). The existing 7 Loop-1 SoT drift tests above only compare
# ``required`` key SETS — not property TYPES. A future schema-vs-parser
# type drift (like the pre-PR-2 LITERATURE_REVIEW_SCHEMA pre-fix
# ``articles_with_reasoning: array`` vs parser ``str(parsed.get(...))``,
# or ``snapshots: array`` vs parser ``isinstance(snapshots_raw, dict)``)
# would slip past the existing tests — the keys agree, the TYPES drift.
#
# This section pins each Loop-1 role's per-property JSON-Schema ``type``
# against the type the parser / downstream consumer actually expects.
# A future schema-tightening that changes ``"string"`` → ``"object"`` for
# a parser that still does ``str(parsed.get(...))`` trips here, forcing
# a conscious schema-OR-parser update.
#
# Convention: ``EXPECTED_TYPES[ROLE][prop]`` is either a JSON-Schema
# primitive (``"string"``, ``"number"``, ``"boolean"``, ``"array"``,
# ``"object"``) OR a tuple of primitives for nullable / union types
# (e.g. CRITIQUE.rewrite_section accepts ``["string", "null"]``).


def _schema_property_type(schema: dict, prop: str) -> str | tuple[str, ...]:
    """Extract the ``type`` of a JSON-Schema property as a normalised
    form: ``str`` for single-type, ``tuple[str, ...]`` for unions."""
    spec = schema["properties"][prop]
    decl = spec["type"]
    if isinstance(decl, list):
        return tuple(decl)
    return decl


_EXPECTED_TYPES: dict[str, dict[str, str | tuple[str, ...]]] = {
    "PROXIMITY": {
        "similarity_clusters": "array",
    },
    "CRITIQUE": {
        "candidate_id": "string",
        "target_dims_actual": "array",
        "intended_dim_match": "boolean",
        "strengths": "array",
        "weaknesses": "array",
        "judge_risk": "string",
        "discrimination_estimate": "number",
        "rewrite_section": ("string", "null"),
    },
    "VOTE": {
        "match_id": "string",
        "winner": "string",
        "rationale": "string",
    },
    "EVOLVE": {
        "parent_id": "string",
        "evolved_id": "string",
        "evolved_path": "string",
        "rewrite_section": "string",
        "verdict": "string",
        "notes": "string",
    },
    "META_REVIEW": {
        "coverage": "object",
        "underrepresented_dims": "array",
        "overrepresented_dims": "array",
        "next_gen_priors": "object",
        "elo_distribution": "object",
        "evolution_yield": "object",
        "session_summary": "string",
    },
    # LITERATURE_REVIEW — pre-PR-STRICT-COMPATIBLE-SCHEMAS the schema
    # declared both ``articles_with_reasoning`` and ``snapshots`` as
    # ``"array"`` while ``literature_review.py:164-166`` did
    # ``str(parsed.get(...))`` + ``isinstance(snapshots_raw, dict)``.
    # That bug is exactly what this whole section pins against.
    "LITERATURE_REVIEW": {
        "articles_with_reasoning": "string",
        "snapshots": "object",
    },
    "SUPERVISOR": {
        "research_goal_analysis": "object",
        "phase_guidance": "object",
        "session_summary": "string",
    },
}


_SCHEMA_BY_ROLE: dict[str, dict] = {
    "PROXIMITY": PROXIMITY_SCHEMA,
    "CRITIQUE": CRITIQUE_SCHEMA,
    "VOTE": VOTE_SCHEMA,
    "EVOLVE": EVOLVE_SCHEMA,
    "META_REVIEW": META_REVIEW_SCHEMA,
    "LITERATURE_REVIEW": LITERATURE_REVIEW_SCHEMA,
    "SUPERVISOR": SUPERVISOR_SCHEMA,
}


@pytest.mark.parametrize(
    "role,prop,expected",
    [
        (role, prop, expected)
        for role, props in _EXPECTED_TYPES.items()
        for prop, expected in props.items()
    ],
)
def test_schema_property_type_matches_parser_expectation(
    role: str, prop: str, expected: str | tuple[str, ...]
) -> None:
    """Per-property JSON-Schema ``type`` must match what the role's
    parser actually does with the value. If this fails, schema-vs-parser
    type drift is real — restore the parser-aligned type OR update
    ``_EXPECTED_TYPES`` in lockstep with the parser change."""
    schema = _SCHEMA_BY_ROLE[role]
    actual = _schema_property_type(schema, prop)
    assert actual == expected, (
        f"{role}.{prop}: schema declares type={actual!r} but parser / "
        f"downstream consumer expects {expected!r}. Either:\n"
        "  (a) the schema regressed (restore the parser-aligned type), or\n"
        "  (b) the parser contract intentionally changed (update "
        "_EXPECTED_TYPES here in lockstep with the parser change).\n"
        "``required``-only drift tests cannot catch type drift."
    )


def test_expected_types_covers_every_required_property() -> None:
    """Every ``required`` key for each Loop-1 role must have an
    ``_EXPECTED_TYPES`` entry. A new required field added to a schema
    without a corresponding expected-type entry would silently slip
    past the drift invariant above (no parametrize case → no failure).
    """
    for role, schema in _SCHEMA_BY_ROLE.items():
        required = set(schema["required"])
        covered = set(_EXPECTED_TYPES.get(role, {}).keys())
        missing = required - covered
        assert not missing, (
            f"{role}: ``required`` keys {sorted(missing)} not covered by "
            "_EXPECTED_TYPES. Add the expected JSON-Schema type for each "
            "(based on what the role's parser does with the value) so the "
            "drift invariant test covers the new fields."
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
