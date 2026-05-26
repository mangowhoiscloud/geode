"""PR-CODEX-GPT55-OUTPUT-EMIT — voter ``effort="low"`` wiring invariants.

Pins the fix for the smoke 20 defect: gpt-5.5 voter calls running at the
silent ``effort="medium"`` default returned ``output_text=""`` 100% of
the time, burning the entire output token budget (109-254 tokens per
call across 36 dumps) on encrypted reasoning items and emitting ZERO
message text — collapsing the ranker phase.

Root cause (ctx7-grounded): the vote task is a 3-way A/B/tie
classification + ≤ 200-token rationale, but the SubTask had no per-task
``effort`` override so it fell through to the ``_DIFFICULTY_TO_EFFORT``
default ("medium"). For a reasoning model, "medium" allocates enough
reasoning headroom that the entire ``output_tokens`` quota gets
consumed before the model emits the visible message block — the OpenAI
Responses API failure mode the docs call "Ran out of tokens during
reasoning" (ctx7 ``/websites/developers_openai_api`` → "Allocating
space for reasoning").

``max_output_tokens`` is NOT a fix here — the Codex OAuth backend
rejects the field with 400 ``Unsupported parameter`` (pinned by
``test_codex_kwargs_does_not_send_max_output_tokens`` and the comment
at ``core/llm/providers/codex.py:325``). The only available knob is
``reasoning.effort``.

Per ctx7 OpenAI Responses API docs the canonical low-effort example
uses gpt-5.5 with ``reasoning: {"effort": "low"}`` for a single
bash-script generation task; the voter A/B/tie call is a comparable
single-shot output (one verdict + one ≤ 200-token rationale). The
"Reasoning effort" section explicitly says: "Reducing reasoning effort
can result in faster responses and fewer tokens used on reasoning in a
response."

These tests pin:

1. ``SubTask.effort`` field exists with empty-string default
   (back-compat — preserves the legacy difficulty path).
2. ``_build_worker_request`` honours ``SubTask.effort`` when set,
   overriding both ``task.difficulty`` and ``settings.agentic_effort``.
3. The ranker's voter SubTasks set ``effort="low"`` so the codex-oauth
   adapter forwards ``reasoning.effort="low"`` to the gpt-5.5 backend.
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


def test_subtask_effort_field_accepts_low() -> None:
    """The ranker's voter SubTasks pin ``effort="low"`` per ctx7 guidance."""
    task = SubTask(task_id="t1", description="x", task_type="analyze", effort="low")
    assert task.effort == "low"


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
        effort="low",
    )
    req = mgr._build_worker_request(task)
    assert req.effort == "low", (
        "WorkerRequest must inherit SubTask.effort='low' — otherwise the "
        "codex-oauth adapter forwards reasoning.effort=medium and gpt-5.5 "
        "reproduces the smoke 20 empty-text failure mode."
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
        f"If this changed, the ranker voter pathway's effort='low' "
        f"override may also have drifted."
    )


def test_ranker_voter_subtasks_pin_effort_low() -> None:
    """Ranker SubTask construction pins ``effort="low"`` on EVERY voter task.

    This is the wire-through the smoke 20 fix depends on. Without it,
    the SubTask carries empty ``effort`` and falls through to the
    medium-default that produced 36 empty-text dumps. ctx7 OpenAI
    Responses API docs (``/websites/developers_openai_api`` →
    "Reasoning effort"): "Reducing reasoning effort can result in
    faster responses and fewer tokens used on reasoning in a
    response". The canonical low-effort example uses gpt-5.5 with
    ``effort="low"`` for a single bash-script generation task; the
    voter A/B/tie call is a comparable single-shot output (one
    verdict + one ≤ 200-token rationale).
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
        assert task.effort == "low", (
            f"Voter SubTask {task.task_id} must pin effort='low' to keep "
            f"gpt-5.5 from burning the output budget on encrypted reasoning. "
            f"Got effort={task.effort!r}. ctx7 reference: OpenAI Responses "
            f"API 'Reasoning effort' section + the canonical low-effort "
            f"bash-script example in the docs."
        )


def test_ranker_voter_subtasks_still_pin_response_schema() -> None:
    """Defence-in-depth: ``effort="low"`` does not regress the JSON schema wire.

    The smoke 20 failure was a 2-gap defect (insufficient effort +
    insufficient schema enforcement). Both knobs must remain pinned;
    removing either re-opens the empty-text path. ctx7-grounded note:
    on the codex-oauth backend the schema rides through
    ``text.format = {type: "json_schema", ...}``; strict mode is
    auto-detected (VOTE_SCHEMA lacks ``additionalProperties: false``
    so strict=False).
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
    assert tasks[0].effort == "low"
