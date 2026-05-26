"""PR-GPT55-EMPTY-OUTPUT-EMIT (Sprint G) — voter ``effort="none"`` wiring invariants.

Supersedes PR-CODEX-GPT55-OUTPUT-EMIT's ``effort="low"`` which smoke 21
confirmed ineffective. Pins the Sprint G fix: gpt-5.5 voter calls now
run with ``reasoning.effort="none"`` so the model emits the A/B/tie
verdict directly without consuming any output budget on encrypted
reasoning items.

Root cause (ctx7-grounded): the vote task is a 3-way A/B/tie
classification + ≤ 200-token rationale — a single-step output that
doesn't benefit from any reasoning depth. Per ctx7 OpenAI Responses
API "Sampling Parameters", ``reasoning_effort`` enum includes
``none`` which disables reasoning entirely on reasoning-capable
models. The smoke 21 evidence showed ``effort="low"`` still produced
encrypted reasoning items consuming the full output budget with
``output_text=""`` — ``"none"`` is the documented mechanism to
prevent that consumption.

``max_output_tokens`` is NOT a fix here — the Codex OAuth backend
rejects the field with 400 ``Unsupported parameter`` (pinned by
``test_codex_kwargs_does_not_send_max_output_tokens`` and the comment
at ``core/llm/providers/codex.py:325``). ``reasoning.effort`` is the
only available knob, and ``"none"`` is the floor of that knob.

These tests pin:

1. ``SubTask.effort`` field exists with empty-string default
   (back-compat — preserves the legacy difficulty path).
2. ``_build_worker_request`` honours ``SubTask.effort`` when set,
   overriding both ``task.difficulty`` and ``settings.agentic_effort``.
3. The ranker's voter SubTasks set ``effort="none"`` so the codex-oauth
   adapter forwards ``reasoning.effort="none"`` to the gpt-5.5 backend
   and gpt-5.5 emits the verdict directly without encrypted reasoning.
4. Every gpt-5.x spec admits ``"none"`` in ``reasoning_effort_values``
   so the voter wire above remains valid for any operator-pinned
   gpt-5.x model. (The OpenAI generic enum admits ``"minimal"`` as
   well, but per-model docs for gpt-5.4 / gpt-5.5 do not — GEODE
   does NOT advertise ``"minimal"`` on those specs to avoid handing
   operators a value the server would reject at runtime.)
"""

from __future__ import annotations

from unittest.mock import MagicMock

from core.agent.sub_agent import SubAgentManager, SubTask
from plugins.seed_generation.agents.ranker import Ranker
from plugins.seed_generation.picker import VoterBinding
from plugins.seed_generation.tournament import MatchPlan


def test_subtask_has_effort_field_empty_default() -> None:
    """Back-compat: SubTask exposes ``effort`` and defaults to empty string.

    Empty string is the sentinel that means "fall back to the legacy
    ``task.difficulty`` → ``_DIFFICULTY_TO_EFFORT`` →
    ``settings.agentic_effort`` resolution chain". Callers that don't
    care about per-task reasoning depth still get the global default.
    """
    task = SubTask(task_id="t1", description="x", task_type="analyze")
    assert task.effort == ""


def test_subtask_effort_field_accepts_none() -> None:
    """The ranker's voter SubTasks pin ``effort="none"`` per Sprint G."""
    task = SubTask(task_id="t1", description="x", task_type="analyze", effort="none")
    assert task.effort == "none"


def test_build_worker_request_uses_task_effort_when_set() -> None:
    """``SubTask.effort`` wins over ``settings.agentic_effort``.

    Pre-fix the only effort knob was the global
    ``settings.agentic_effort`` (default ``"high"``) routed through
    ``_DIFFICULTY_TO_EFFORT["medium"]``. The ranker had no way to
    surface "this is a classification, run cheap" — so vote tasks
    inherited the global default and gpt-5.5 burned the entire
    output budget on reasoning.
    """
    mgr = SubAgentManager.__new__(SubAgentManager)
    mgr._denied_tools = set()  # type: ignore[attr-defined]
    mgr._agent_registry = None  # type: ignore[attr-defined]
    mgr._parent_session_key = ""  # type: ignore[attr-defined]
    mgr._timeout_s = 60  # type: ignore[attr-defined]
    mgr._time_budget_s = 0.0  # type: ignore[attr-defined]
    task = SubTask(
        task_id="vote-m000-openai.subscription",
        description="vote",
        task_type="vote",
        effort="none",
    )
    req = mgr._build_worker_request(task)
    assert req.effort == "none", (
        "WorkerRequest must inherit SubTask.effort='none' — otherwise the "
        "codex-oauth adapter forwards reasoning.effort=medium and gpt-5.5 "
        "reproduces the smoke 20/21 empty-text failure mode."
    )


def test_build_worker_request_falls_back_when_effort_empty() -> None:
    """Empty ``effort`` preserves the legacy difficulty/settings path.

    This is the back-compat guard — callers that don't care about
    per-task effort (the common case) still inherit
    ``settings.agentic_effort`` via ``_DIFFICULTY_TO_EFFORT``.
    """
    mgr = SubAgentManager.__new__(SubAgentManager)
    mgr._denied_tools = set()  # type: ignore[attr-defined]
    mgr._agent_registry = None  # type: ignore[attr-defined]
    mgr._parent_session_key = ""  # type: ignore[attr-defined]
    mgr._timeout_s = 60  # type: ignore[attr-defined]
    mgr._time_budget_s = 0.0  # type: ignore[attr-defined]
    task = SubTask(task_id="t1", description="x", task_type="analyze")
    req = mgr._build_worker_request(task)
    # Legacy path: ``difficulty`` defaults to "medium" via the
    # ``getattr(task, "difficulty", "medium")`` fallback at
    # ``core/agent/sub_agent.py:719``, so
    # ``_DIFFICULTY_TO_EFFORT["medium"]`` resolves to ``"medium"``.
    # PIN the exact value — a previous tautological form
    # (``req.effort != "low" or req.effort in {low,medium,high}``)
    # was True for any non-empty string and would not catch a
    # regression that changed default SubTask semantics.
    assert req.effort == "medium", (
        f"Default SubTask (no effort, no difficulty) must resolve to "
        f"_DIFFICULTY_TO_EFFORT['medium']='medium' — got {req.effort!r}. "
        f"If this changed, the ranker voter pathway's effort='none' "
        f"override (Sprint G) may also have drifted."
    )


def test_ranker_voter_subtasks_pin_effort_none() -> None:
    """Ranker SubTask construction pins ``effort="none"`` on EVERY voter task.

    Sprint G supersedes the prior ``effort="low"`` pin (which smoke
    21 confirmed ineffective — gpt-5.5 still produced 7+ empty-text
    dumps with 60-624 reasoning tokens consumed). ctx7 OpenAI
    Responses API "Sampling Parameters": ``reasoning_effort`` enum
    includes ``"none"`` to disable reasoning entirely so the model
    emits user-facing text directly. The voter A/B/tie + rationale
    task is single-step classification — no reasoning depth needed.
    """
    voters = [
        VoterBinding(
            provider="anthropic",
            source="subscription",
            model="claude-sonnet-4-5",
        ),
        VoterBinding(
            provider="openai",
            source="subscription",
            model="gpt-5.5",
        ),
    ]
    manager = MagicMock()
    ranker = Ranker(manager=manager, voters=voters)
    match = MatchPlan(match_id="m000", a="c_a", b="c_b")
    tasks = ranker._build_voter_tasks(
        match,
        pilot_means={
            "c_a": {"axis_1": 5.0},
            "c_b": {"axis_1": 6.0},
        },
        candidate_bodies={
            "c_a": "candidate a body text",
            "c_b": "candidate b body text",
        },
    )
    assert len(tasks) == len(voters), (
        f"Ranker must spawn one task per voter — got {len(tasks)} tasks for {len(voters)} voters."
    )
    for task in tasks:
        assert task.effort == "none", (
            f"Voter SubTask {task.task_id} must pin effort='none' to keep "
            f"gpt-5.5 from burning the output budget on encrypted reasoning. "
            f"Got effort={task.effort!r}. ctx7 reference: OpenAI Responses "
            f"API 'Sampling Parameters' — ``reasoning_effort`` enum supports "
            f"``none`` to disable reasoning entirely on reasoning-capable "
            f"models. Prior ``effort='low'`` (PR-CODEX-GPT55-OUTPUT-EMIT) "
            f"was ineffective per smoke 21 evidence."
        )


def test_ranker_voter_subtasks_still_pin_response_schema() -> None:
    """Defence-in-depth: ``effort="none"`` does not regress the JSON schema wire.

    The smoke 20 failure was a 2-gap defect (insufficient effort +
    insufficient schema enforcement). Both knobs must remain pinned;
    removing either re-opens the empty-text path. ctx7-grounded note:
    on the codex-oauth backend the schema rides through
    ``text.format = {type: "json_schema", ...}``; strict mode is
    auto-detected (VOTE_SCHEMA satisfies the OpenAI Structured
    Outputs subset since PR-STRICT-COMPATIBLE-SCHEMAS).
    """
    from plugins.seed_generation.json_schemas import VOTE_SCHEMA

    voters = [
        VoterBinding(
            provider="anthropic",
            source="subscription",
            model="claude-sonnet-4-5",
        ),
        VoterBinding(
            provider="openai",
            source="subscription",
            model="gpt-5.5",
        ),
    ]
    manager = MagicMock()
    ranker = Ranker(manager=manager, voters=voters)
    match = MatchPlan(match_id="m001", a="c_a", b="c_b")
    tasks = ranker._build_voter_tasks(
        match,
        pilot_means={},
        candidate_bodies={"c_a": "a", "c_b": "b"},
    )
    assert tasks[0].response_schema == VOTE_SCHEMA
    assert tasks[0].effort == "none"


def test_gpt5_family_spec_supports_none_effort() -> None:
    """Sprint G (2026-05-26) — every gpt-5.x spec must list ``"none"``
    in ``reasoning_effort_values`` so the voter pathway can disable
    reasoning entirely. The ``"minimal"`` value the OpenAI generic
    enum admits is intentionally NOT added across gpt-5.x — per-model
    docs for gpt-5.4 / gpt-5.5 list only (none, low, medium, high,
    xhigh) and adding ``"minimal"`` would let operators select an
    effort the server rejects at runtime. (Codex MCP catch, 2026-05-26.)
    """
    from core.llm.adapters._openai_common import get_openai_model_spec

    for model_id in ("gpt-5.3-codex", "gpt-5.4", "gpt-5.4-mini", "gpt-5.5"):
        spec = get_openai_model_spec(model_id)
        assert spec.reasoning_effort_values is not None, model_id
        assert "none" in spec.reasoning_effort_values, model_id
