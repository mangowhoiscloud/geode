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
   (inherits the caller's effort, then the configured default).
2. ``SubagentProtocol.build_worker_request`` honours ``SubTask.effort`` when set,
   overriding both caller effort and ``settings.agentic_effort``.
3. The ranker's voter SubTasks set ``effort="none"`` so the codex-oauth
   adapter forwards ``reasoning.effort="none"`` to the gpt-5.5 backend
   and gpt-5.5 emits the verdict directly without encrypted reasoning.
4. Models with documented disabled reasoning retain ``none``; the retired
   subscription GPT-5.3-Codex API model keeps its supported low-to-xhigh range.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from core.agent.sub_agent import SubAgentManager, SubTask
from core.orchestration.isolated_execution import IsolatedRunner
from evals.seed_generation.agents.ranker import Ranker
from evals.seed_generation.picker import VoterBinding
from evals.seed_generation.tournament import MatchPlan


def test_subtask_has_effort_field_empty_default() -> None:
    """Back-compat: SubTask exposes ``effort`` and defaults to empty string.

    Empty string means inherit the caller's effort, or the configured
    ``settings.agentic_effort`` when no caller effort is supplied.
    """
    task = SubTask(task_id="t1", description="x", task_type="analyze")
    assert task.effort == ""


def test_subtask_effort_field_accepts_none() -> None:
    """The ranker's voter SubTasks pin ``effort="none"`` per Sprint G."""
    task = SubTask(task_id="t1", description="x", task_type="analyze", effort="none")
    assert task.effort == "none"


def test_build_worker_request_uses_task_effort_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """The voter's explicit ``none`` wins over caller and configured effort."""
    from core.config import settings

    monkeypatch.setattr(settings, "agentic_effort", "high")
    mgr = SubAgentManager(IsolatedRunner(), timeout_s=60)
    task = SubTask(
        task_id="vote-m000-openai.subscription",
        description="vote",
        task_type="vote",
        effort="none",
    )
    req = mgr._protocol.build_worker_request(task, default_effort="max")
    assert req.effort == "none", (
        "WorkerRequest must inherit SubTask.effort='none' — otherwise the "
        "codex-oauth adapter inherits caller/configured effort and gpt-5.5 "
        "reproduces the smoke 20/21 empty-text failure mode."
    )


@pytest.mark.parametrize(
    "configured, caller, expected",
    [("high", "", "high"), ("low", "", "low"), ("low", "max", "max"), ("high", "none", "none")],
)
def test_build_worker_request_falls_back_when_effort_empty(
    monkeypatch: pytest.MonkeyPatch, configured: str, caller: str, expected: str
) -> None:
    """Empty task effort inherits its caller before the configured fallback."""
    from core.config import settings

    monkeypatch.setattr(settings, "agentic_effort", configured)
    mgr = SubAgentManager(IsolatedRunner(), timeout_s=60)
    task = SubTask(task_id="t1", description="x", task_type="analyze")
    req = mgr._protocol.build_worker_request(task, default_effort=caller)
    assert req.effort == expected


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
    from evals.seed_generation.json_schemas import VOTE_SCHEMA

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
    """Reasoning can be disabled only on models whose public contract allows it."""
    from core.llm.adapters._openai_common import get_openai_model_spec

    for model_id in ("gpt-5.4", "gpt-5.4-mini", "gpt-5.5"):
        spec = get_openai_model_spec(model_id)
        assert spec.reasoning_effort_values is not None, model_id
        assert "none" in spec.reasoning_effort_values, model_id
    assert get_openai_model_spec("gpt-5.3-codex").reasoning_effort_values == (
        "low",
        "medium",
        "high",
        "xhigh",
    )
