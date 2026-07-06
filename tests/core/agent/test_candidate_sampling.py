"""Best-of-N candidate sampling — lens forcing, judge selection, executor wiring.

GAP 2+4 (2026-07-06): same-task N-candidate sampling with diversity
lenses + judge selection, exposed as ``delegate_task``'s opt-in
``best_of`` parameter. Mocking mirrors ``test_reflection_node.py``
(module-attr monkeypatch on ``call_with_failover`` / ``resolve_for`` /
``_resolve_provider``).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from core.agent import candidate_sampling as cs
from core.agent.candidate_sampling import (
    DIVERSITY_LENSES,
    MAX_BEST_OF,
    CandidateVerdict,
    judge_candidates,
    lensed_description,
)

# ---------------------------------------------------------------------------
# Diversity lenses
# ---------------------------------------------------------------------------


def test_lensed_descriptions_are_distinct_and_carry_base() -> None:
    base = "Summarize the auth module's error handling."
    lensed = [lensed_description(base, i) for i in range(len(DIVERSITY_LENSES))]
    assert len(set(lensed)) == len(DIVERSITY_LENSES)
    assert all(base in text for text in lensed)


def test_lens_rotation_wraps_past_available_lenses() -> None:
    base = "task"
    assert lensed_description(base, len(DIVERSITY_LENSES)) == lensed_description(base, 0)


def test_max_best_of_within_lens_count() -> None:
    """Every candidate up to the cap gets a UNIQUE lens — the diversity
    guarantee breaks silently if the cap outgrows the lens pool."""
    assert len(DIVERSITY_LENSES) >= MAX_BEST_OF


# ---------------------------------------------------------------------------
# judge_candidates
# ---------------------------------------------------------------------------


def _judge_response(payload: dict[str, Any] | None) -> SimpleNamespace:
    tool_uses = () if payload is None else ({"name": "select_candidate", "input": payload},)
    return SimpleNamespace(tool_uses=tool_uses)


def _patch_judge_dispatch(monkeypatch: pytest.MonkeyPatch, response: SimpleNamespace) -> list[str]:
    """Patch the module-scope LLM plumbing; returns the called-models log."""
    called: list[str] = []

    async def _fake_call_with_failover(models: list[str], do_call: Any) -> tuple[Any, str]:
        called.append(models[0])
        return response, models[0]

    monkeypatch.setattr(cs, "call_with_failover", _fake_call_with_failover)
    monkeypatch.setattr(cs, "resolve_for", lambda _p, _s: SimpleNamespace())
    monkeypatch.setattr(cs, "_resolve_provider", lambda _m: "anthropic")
    return called


def test_judge_single_candidate_skips_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _explode(*_a: Any, **_k: Any) -> None:
        raise AssertionError("judge LLM must not be called for a single candidate")

    monkeypatch.setattr(cs, "call_with_failover", _explode)
    verdict = asyncio.run(judge_candidates("t", ["only one"], model="m"))
    assert verdict.winner_index == 0
    assert verdict.judge_error == ""


def test_judge_selects_winner(monkeypatch: pytest.MonkeyPatch) -> None:
    called = _patch_judge_dispatch(
        monkeypatch, _judge_response({"winner_index": 2, "reason": "most complete"})
    )
    verdict = asyncio.run(judge_candidates("t", ["a", "b", "c"], model="judge-model"))
    assert verdict == CandidateVerdict(2, "most complete")
    assert called == ["judge-model"]


def test_judge_decline_falls_back_observably(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_judge_dispatch(monkeypatch, _judge_response(None))
    verdict = asyncio.run(judge_candidates("t", ["a", "b"], model="m"))
    assert verdict.winner_index == 0
    assert "declined" in verdict.judge_error


def test_judge_out_of_range_index_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_judge_dispatch(monkeypatch, _judge_response({"winner_index": 9, "reason": "x"}))
    verdict = asyncio.run(judge_candidates("t", ["a", "b"], model="m"))
    assert verdict.winner_index == 0
    assert "out of range" in verdict.judge_error


def test_judge_bool_index_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    """bool is an int subclass — True must not select candidate 1."""
    _patch_judge_dispatch(monkeypatch, _judge_response({"winner_index": True, "reason": "x"}))
    verdict = asyncio.run(judge_candidates("t", ["a", "b"], model="m"))
    assert verdict.winner_index == 0
    assert "non-integer" in verdict.judge_error


def test_judge_llm_failure_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _boom(*_a: Any, **_k: Any) -> None:
        raise RuntimeError("adapter down")

    monkeypatch.setattr(cs, "call_with_failover", _boom)
    monkeypatch.setattr(cs, "resolve_for", lambda _p, _s: SimpleNamespace())
    monkeypatch.setattr(cs, "_resolve_provider", lambda _m: "anthropic")
    verdict = asyncio.run(judge_candidates("t", ["a", "b"], model="m"))
    assert verdict.winner_index == 0
    assert "judge call failed" in verdict.judge_error


# ---------------------------------------------------------------------------
# delegate_task wiring (schema + executor expansion + payload)
# ---------------------------------------------------------------------------


def test_definitions_json_carries_best_of() -> None:
    definitions = json.loads(
        (Path(__file__).parents[3] / "core" / "tools" / "definitions.json").read_text()
    )
    delegate = next(d for d in definitions if d.get("name") == "delegate_task")
    best_of_schema = delegate["input_schema"]["properties"]["best_of"]
    assert best_of_schema["type"] == "integer"
    assert best_of_schema["minimum"] == 2
    assert best_of_schema["maximum"] == MAX_BEST_OF


class _FakeSubAgentManager:
    """Captures dispatched SubTasks; returns one successful SubResult each."""

    def __init__(self) -> None:
        self.dispatched: list[Any] = []

    async def adelegate(self, tasks: list[Any], **_kwargs: Any) -> list[Any]:
        from core.agent.sub_agent import SubResult

        self.dispatched = list(tasks)
        return [
            SubResult(
                task_id=t.task_id,
                description=t.description,
                success=True,
                output={"text": f"answer from {t.task_id}"},
            )
            for t in tasks
        ]


def _make_executor(manager: _FakeSubAgentManager) -> Any:
    from core.agent.tool_executor import ToolExecutor

    return ToolExecutor(action_handlers={}, sub_agent_manager=manager)


def test_best_of_expands_single_task_with_distinct_lenses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _FakeSubAgentManager()
    executor = _make_executor(manager)

    async def _fake_judge(
        _desc: str, candidates: list[str], *, model: str, **_k: Any
    ) -> CandidateVerdict:
        assert len(candidates) == 3
        return CandidateVerdict(1, "middle one wins")

    monkeypatch.setattr(cs, "judge_candidates", _fake_judge)

    payload = asyncio.run(
        executor._aexecute_delegate({"task_description": "solve X", "best_of": 3}, context=None)
    )

    descriptions = [t.description for t in manager.dispatched]
    assert len(descriptions) == 3
    assert len(set(descriptions)) == 3, "each candidate must get a distinct lens"
    assert all("solve X" in d for d in descriptions)

    block = payload["best_of"]
    assert block["n"] == 3
    assert block["judged"] == 3
    assert block["reason"] == "middle one wins"
    assert block["winner_task_id"] == manager.dispatched[1].task_id
    assert payload["total"] == 3


def test_best_of_ignored_in_batch_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = _FakeSubAgentManager()
    executor = _make_executor(manager)

    async def _explode(*_a: Any, **_k: Any) -> None:
        raise AssertionError("judge must not run in batch mode")

    monkeypatch.setattr(cs, "judge_candidates", _explode)

    payload = asyncio.run(
        executor._aexecute_delegate(
            {
                "tasks": [
                    {"task_description": "a"},
                    {"task_description": "b"},
                ],
                "best_of": 3,
            },
            context=None,
        )
    )
    assert "best_of" not in payload
    assert payload["total"] == 2


def test_best_of_clamps_to_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = _FakeSubAgentManager()
    executor = _make_executor(manager)

    async def _fake_judge(
        _desc: str, candidates: list[str], *, model: str, **_k: Any
    ) -> CandidateVerdict:
        return CandidateVerdict(0, "first")

    monkeypatch.setattr(cs, "judge_candidates", _fake_judge)

    payload = asyncio.run(
        executor._aexecute_delegate({"task_description": "solve X", "best_of": 99}, context=None)
    )
    assert payload["total"] == MAX_BEST_OF


def test_best_of_all_failed_reports_observable_error() -> None:
    class _AllFailManager(_FakeSubAgentManager):
        async def adelegate(self, tasks: list[Any], **_kwargs: Any) -> list[Any]:
            from core.agent.sub_agent import SubResult

            self.dispatched = list(tasks)
            return [
                SubResult(task_id=t.task_id, description=t.description, success=False)
                for t in tasks
            ]

    executor = _make_executor(_AllFailManager())
    payload = asyncio.run(
        executor._aexecute_delegate({"task_description": "solve X", "best_of": 2}, context=None)
    )
    block = payload["best_of"]
    assert block["winner"] is None
    assert "no successful candidates" in block["judge_error"]


def test_best_of_ignored_for_one_item_batch(monkeypatch: pytest.MonkeyPatch) -> None:
    """A one-item ``tasks`` array is STILL batch mode — best_of must not
    multiply it (Codex MCP MED, 2026-07-06)."""
    manager = _FakeSubAgentManager()
    executor = _make_executor(manager)

    async def _explode(*_a: Any, **_k: Any) -> None:
        raise AssertionError("judge must not run in batch mode")

    monkeypatch.setattr(cs, "judge_candidates", _explode)

    payload = asyncio.run(
        executor._aexecute_delegate(
            {"tasks": [{"task_description": "a"}], "best_of": 4}, context=None
        )
    )
    assert "best_of" not in payload
    assert payload["total"] == 1


def test_best_of_bool_true_means_disabled() -> None:
    """``best_of: true`` (bool is an int subclass) must not expand."""
    manager = _FakeSubAgentManager()
    executor = _make_executor(manager)
    payload = asyncio.run(
        executor._aexecute_delegate({"task_description": "solve X", "best_of": True}, context=None)
    )
    assert "best_of" not in payload
    assert payload["total"] == 1


def test_best_of_winner_maps_through_failed_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Judge indexes the SUCCESSFUL subset — with candidate 0 failed,
    judged index 1 must map to the third dispatched task overall."""

    class _FirstFailsManager(_FakeSubAgentManager):
        async def adelegate(self, tasks: list[Any], **_kwargs: Any) -> list[Any]:
            from core.agent.sub_agent import SubResult

            self.dispatched = list(tasks)
            return [
                SubResult(
                    task_id=t.task_id,
                    description=t.description,
                    success=(i != 0),
                    output={"text": f"answer {i}"},
                )
                for i, t in enumerate(tasks)
            ]

    manager = _FirstFailsManager()
    executor = _make_executor(manager)

    async def _fake_judge(
        _desc: str, candidates: list[str], *, model: str, **_k: Any
    ) -> CandidateVerdict:
        assert candidates == ["answer 1", "answer 2"]
        return CandidateVerdict(1, "second of the successful")

    monkeypatch.setattr(cs, "judge_candidates", _fake_judge)

    payload = asyncio.run(
        executor._aexecute_delegate({"task_description": "solve X", "best_of": 3}, context=None)
    )
    block = payload["best_of"]
    assert block["judged"] == 2
    assert block["winner_task_id"] == manager.dispatched[2].task_id


def test_best_of_judge_inherits_tool_context_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When no judge_model is pinned, the judge call must carry the
    ToolContext's live model + provider + source (Codex MCP MED)."""
    from core.config import settings

    monkeypatch.setattr(settings, "judge_model", "", raising=False)
    manager = _FakeSubAgentManager()
    executor = _make_executor(manager)
    seen: dict[str, Any] = {}

    async def _fake_judge(
        _desc: str, candidates: list[str], *, model: str, **kwargs: Any
    ) -> CandidateVerdict:
        seen["model"] = model
        seen["provider"] = kwargs.get("provider")
        seen["source"] = kwargs.get("source")
        return CandidateVerdict(0, "ok")

    monkeypatch.setattr(cs, "judge_candidates", _fake_judge)

    live_route = SimpleNamespace(model="claude-opus-4-8", provider="anthropic", source="oauth")
    asyncio.run(
        executor._aexecute_delegate(
            {"task_description": "solve X", "best_of": 2}, context=live_route
        )
    )
    assert seen == {"model": "claude-opus-4-8", "provider": "anthropic", "source": "oauth"}


def test_candidate_text_prefers_text_keys_over_dict_repr() -> None:
    assert cs.candidate_text({"text": "the answer"}) == "the answer"
    assert cs.candidate_text({"summary": "s"}) == "s"
    as_json = cs.candidate_text({"count": 3})
    assert as_json == '{"count": 3}'
    assert cs.candidate_text(None) == ""
