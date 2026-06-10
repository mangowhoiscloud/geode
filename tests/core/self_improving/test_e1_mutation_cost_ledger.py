"""PR-SIL-5THEME C4 — E1 mutation cost ledger tests.

`mutations.jsonl` 가 git-tracked 으로 존재했으나 cost 컬럼이 0건이라
operator 가 mutation 의 ROI (cost vs fitness Δ) 볼 수 없었다. C4 가
3 step 으로 silent disconnect 닫음:

1. _default_llm_call 이 response.usage 를 sidecar dict 에 capture
2. propose() 가 sidecar 소비하여 Mutation 의 cost 4-field 채움
3. attribution row 에 fitness_before / fitness_after / fitness_delta 추가
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from core.observability import current_session_metrics, session_metrics_scope
from core.self_improving.loop.mutate.runner import (
    Mutation,
    _consume_last_llm_call_usage,
    _reset_last_llm_call_usage,
)
from core.self_improving.loop.observe.attribution import compute_attribution

# ---------------------------------------------------------------------------
# 1. Mutation cost fields
# ---------------------------------------------------------------------------


def test_mutation_default_cost_fields_zero_or_empty() -> None:
    """기본 Mutation 인스턴스의 cost 4 필드는 0 / "" (backward-compat).

    Legacy caller (test mock 등) 가 cost 미설정 시 default 유지 → audit row
    에 cost 컬럼 자체 미생성 (downstream parser 무영향).
    """
    m = Mutation(target_section="s", new_value="v", rationale="r")
    assert m.cost_input_tokens == 0
    assert m.cost_output_tokens == 0
    assert m.cost_elapsed_seconds == 0.0
    assert m.cost_model == ""


def test_mutation_to_audit_row_omits_cost_columns_when_zero() -> None:
    """Cost 0 / "" 일 때 row 에 cost_* 키 자체 미생성 (legacy reader 무영향)."""
    m = Mutation(target_section="s", new_value="v", rationale="r")
    row = m.to_audit_row(previous_value="prev")
    assert "cost_input_tokens" not in row
    assert "cost_output_tokens" not in row
    assert "cost_elapsed_seconds" not in row
    assert "cost_model" not in row


def test_mutation_to_audit_row_includes_cost_columns_when_set() -> None:
    """Cost 채워진 Mutation → row 가 cost 4 컬럼 emit (cost_input_tokens
    + cost_output_tokens 둘 다 양수일 때 함께 emit)."""
    m = Mutation(
        target_section="s",
        new_value="v",
        rationale="r",
        cost_input_tokens=1234,
        cost_output_tokens=567,
        cost_elapsed_seconds=12.345,
        cost_model="claude-opus-4-7",
    )
    row = m.to_audit_row(previous_value="prev")
    assert row["cost_input_tokens"] == 1234
    assert row["cost_output_tokens"] == 567
    assert row["cost_elapsed_seconds"] == 12.345
    assert row["cost_model"] == "claude-opus-4-7"


def test_mutation_to_audit_row_partial_cost_fields() -> None:
    """Cost 일부만 set 일 때 — input_tokens=0 + output_tokens=0 면 token 컬럼
    skip, elapsed_seconds 만 set 이면 그 컬럼만 emit. 명확히 separable."""
    m = Mutation(
        target_section="s",
        new_value="v",
        rationale="r",
        cost_elapsed_seconds=5.0,
    )
    row = m.to_audit_row(previous_value="prev")
    assert "cost_input_tokens" not in row
    assert "cost_output_tokens" not in row
    assert row["cost_elapsed_seconds"] == 5.0
    assert "cost_model" not in row


# ---------------------------------------------------------------------------
# 2. SessionMetrics last-call snapshot capture (PR-SESSION-METRICS)
# ---------------------------------------------------------------------------
#
# PR-SIL-5THEME C4 의 module-level ``_LAST_LLM_CALL_USAGE`` dict + PR-C4.fix-
# contextvar 의 ``_LAST_LLM_CALL_USAGE_VAR`` ContextVar + ``_UsageProxy`` shim
# 이 SessionMetrics 의 last-call 4-field snapshot 으로 흡수됨. Test 는
# ``current_session_metrics()`` ContextVar 를 통해 직접 mutate / read.


def test_reset_last_llm_call_usage_clears_session_metrics_last_call() -> None:
    """``_reset_last_llm_call_usage`` 는 SessionMetrics 의 last-call snapshot
    만 비움 (cumulative 보존). propose() 가 LLM call 직전 호출."""
    with session_metrics_scope(session_id="test"):
        m = current_session_metrics()
        m.last_call_input_tokens = 100
        m.last_call_model = "test-model"
        _reset_last_llm_call_usage()
        assert m.last_call_input_tokens == 0
        assert m.last_call_model == ""


def test_consume_last_llm_call_usage_returns_snapshot_and_clears() -> None:
    """``_consume_last_llm_call_usage`` 가 snapshot 반환 + SessionMetrics 의
    last-call 슬롯 비움. Race condition 없음 — 같은 ContextVar 안의 atomic
    read-and-clear."""
    with session_metrics_scope(session_id="test"):
        m = current_session_metrics()
        m.accumulate_llm_call(
            input_tokens=100,
            output_tokens=50,
            elapsed_seconds=1.23,
            model="claude-opus-4-7",
        )
        snapshot = _consume_last_llm_call_usage()
        assert snapshot == {
            "input_tokens": 100,
            "output_tokens": 50,
            "elapsed_seconds": 1.23,
            "model": "claude-opus-4-7",
        }
        # last-call 슬롯 비워짐, cumulative 는 보존
        assert m.last_call_input_tokens == 0
        assert m.input_tokens == 100  # cumulative untouched


def test_consume_last_llm_call_usage_empty_when_unset() -> None:
    """LLM call mock 이 accumulate 안 했으면 consume 은 빈 dict 반환."""
    with session_metrics_scope(session_id="test"):
        assert _consume_last_llm_call_usage() == {}


# ---------------------------------------------------------------------------
# 3. propose() — sidecar consumption + cost population
# ---------------------------------------------------------------------------


def _build_propose_runner(
    raw_response: str,
    monkeypatch: Any,
    tmp_path: Path,
) -> Any:
    """propose() 호출 가능한 minimal runner — mock llm_call + minimal context."""
    from core.self_improving.loop.mutate import runner as runner_mod

    # build_runner_context 가 baseline_reader 등 실제 SoT 를 읽으려 함 — mock.
    mock_ctx = MagicMock()
    mock_ctx.baseline_snapshot = None
    mock_ctx.current_sections = {"# Setup": "current setup content"}
    mock_ctx.current_policies = {"prompt": {"# Setup": "current setup content"}}
    mock_ctx.target_dim = ""
    # PR-FIX-DEVELOP-TEST-BREAKAGE (2026-05-27) — PR-MUTATOR-HISTORY-FEEDBACK
    # (#1779) added a new ``ctx.mutator_feedback_block`` block read in
    # ``_build_user_prompt``. Pre-PR the MagicMock auto-returned a
    # MagicMock for the missing attr → ``"\n\n".join(blocks)`` failed
    # with "expected str instance, MagicMock found". Set explicitly to
    # empty string so the falsy guard at
    # ``runner.py:_build_user_prompt`` skips appending.
    mock_ctx.mutator_feedback_block = ""
    # PR-MUTATOR-DEDUP-GUARD (#1779) — also reads
    # ``ctx.recent_applies_for_dedup`` to gate the dedup guard. Empty
    # tuple → guard skipped (legacy behaviour).
    mock_ctx.recent_applies_for_dedup = ()
    monkeypatch.setattr(runner_mod, "build_runner_context", lambda: mock_ctx)
    # apply 가 disk 안 건드리도록 path mock
    monkeypatch.setattr(runner_mod, "MUTATION_AUDIT_LOG_PATH", tmp_path / "mutations.jsonl")

    return runner_mod.SelfImprovingLoopRunner(
        llm_call=lambda _sys, _usr: raw_response,
        commit_enabled=False,
        rerun_enabled=False,
        audit_log_path=tmp_path / "mutations.jsonl",
    )


def test_propose_mock_llm_call_leaves_cost_default(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    """Test 가 inject 한 str-returning mock 은 sidecar 비움 → Mutation 의
    cost 4-field 가 default 유지. Backward-compat: 기존 mock-based test
    전체 영향 0.
    """
    response_json = json.dumps(
        {
            "target_section": "# Setup",
            "new_value": "new content",
            "rationale": "test",
        }
    )
    runner = _build_propose_runner(response_json, monkeypatch, tmp_path)

    proposal = runner.propose()
    m = proposal.mutation
    assert m.cost_input_tokens == 0
    assert m.cost_output_tokens == 0
    assert m.cost_elapsed_seconds == 0.0
    assert m.cost_model == ""


def test_propose_populates_cost_from_sidecar(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    """mock llm_call 안에서 sidecar 채워두면 propose() 가 그 값을 mutation
    에 forward. _default_llm_call 의 production path 시뮬레이션."""
    response_json = json.dumps(
        {
            "target_section": "# Setup",
            "new_value": "new content",
            "rationale": "test",
        }
    )

    def llm_call_with_usage(_sys: str, _usr: str) -> str:
        # production _default_llm_call 처럼 SessionMetrics accumulate
        current_session_metrics().accumulate_llm_call(
            input_tokens=2500,
            output_tokens=1200,
            elapsed_seconds=4.567,
            model="claude-opus-4-7",
        )
        return response_json

    from core.self_improving.loop.mutate import runner as runner_mod

    mock_ctx = MagicMock()
    mock_ctx.baseline_snapshot = None
    mock_ctx.current_sections = {"# Setup": "current setup content"}
    mock_ctx.current_policies = {"prompt": {"# Setup": "current setup content"}}
    mock_ctx.target_dim = ""
    mock_ctx.mutator_feedback_block = ""
    mock_ctx.recent_applies_for_dedup = ()
    monkeypatch.setattr(runner_mod, "build_runner_context", lambda: mock_ctx)
    monkeypatch.setattr(runner_mod, "MUTATION_AUDIT_LOG_PATH", tmp_path / "mutations.jsonl")

    runner = runner_mod.SelfImprovingLoopRunner(
        llm_call=llm_call_with_usage,
        commit_enabled=False,
        rerun_enabled=False,
        audit_log_path=tmp_path / "mutations.jsonl",
    )

    with session_metrics_scope(session_id="test"):
        proposal = runner.propose()
    m = proposal.mutation
    assert m.cost_input_tokens == 2500
    assert m.cost_output_tokens == 1200
    assert m.cost_elapsed_seconds == 4.567
    assert m.cost_model == "claude-opus-4-7"


def test_propose_clears_last_call_before_invocation(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    """이전 mutation 의 last-call snapshot 잔여 (e.g. 이전 propose() 가 실패한
    경우) 가 다음 propose() 의 mutation 에 끼지 못함. ``_reset_last_llm_call_usage``
    가 LLM call 직전 fire 해서 SessionMetrics 의 last-call 슬롯 비움."""

    response_json = json.dumps(
        {
            "target_section": "# Setup",
            "new_value": "new content",
            "rationale": "test",
        }
    )

    def mock_llm(_sys: str, _usr: str) -> str:
        # mock 는 SessionMetrics accumulate 안 함 → reset 후 0 유지
        return response_json

    from core.self_improving.loop.mutate import runner as runner_mod

    mock_ctx = MagicMock()
    mock_ctx.baseline_snapshot = None
    mock_ctx.current_sections = {"# Setup": "current setup content"}
    mock_ctx.current_policies = {"prompt": {"# Setup": "current setup content"}}
    mock_ctx.target_dim = ""
    mock_ctx.mutator_feedback_block = ""
    mock_ctx.recent_applies_for_dedup = ()
    monkeypatch.setattr(runner_mod, "build_runner_context", lambda: mock_ctx)
    monkeypatch.setattr(runner_mod, "MUTATION_AUDIT_LOG_PATH", tmp_path / "mutations.jsonl")

    runner = runner_mod.SelfImprovingLoopRunner(
        llm_call=mock_llm,
        commit_enabled=False,
        rerun_enabled=False,
        audit_log_path=tmp_path / "mutations.jsonl",
    )
    with session_metrics_scope(session_id="test") as m:
        # 이전 mutation 의 last-call 잔여 시뮬레이션
        m.last_call_input_tokens = 999
        m.last_call_model = "stale-model"
        proposal = runner.propose()
    # stale 999 가 안 새들어옴 — default 0
    assert proposal.mutation.cost_input_tokens == 0
    assert proposal.mutation.cost_model == ""


# ---------------------------------------------------------------------------
# 4. compute_attribution — fitness_before / fitness_after / fitness_delta
# ---------------------------------------------------------------------------


def test_compute_attribution_emits_fitness_delta_when_both_provided() -> None:
    """fitness_before + fitness_after 둘 다 명시 → payload 에 3 컬럼 emit."""
    payload = compute_attribution(
        mutation_id="mut1",
        expected_dim={},
        baseline_before=None,
        baseline_after=None,
        fitness_before=0.50,
        fitness_after=0.62,
    )
    assert payload["fitness_before"] == 0.50
    assert payload["fitness_after"] == 0.62
    # rounded to 6 decimals
    assert payload["fitness_delta"] == 0.12


def test_compute_attribution_omits_fitness_keys_when_unset() -> None:
    """fitness_before / after 미명시 → 키 자체 미생성 (legacy reader 무영향)."""
    payload = compute_attribution(
        mutation_id="mut1",
        expected_dim={},
        baseline_before=None,
        baseline_after=None,
    )
    assert "fitness_before" not in payload
    assert "fitness_after" not in payload
    assert "fitness_delta" not in payload


def test_compute_attribution_omits_fitness_when_only_before() -> None:
    """fitness_before 만 명시 (after 부재) → 키 미생성 (Δ 계산 불가)."""
    payload = compute_attribution(
        mutation_id="mut1",
        expected_dim={},
        baseline_before=None,
        baseline_after=None,
        fitness_before=0.5,
    )
    assert "fitness_before" not in payload
    assert "fitness_after" not in payload
    assert "fitness_delta" not in payload


def test_compute_attribution_fitness_delta_negative() -> None:
    """Regression scenario — after < before → fitness_delta 음수."""
    payload = compute_attribution(
        mutation_id="mut1",
        expected_dim={},
        baseline_before=None,
        baseline_after=None,
        fitness_before=0.70,
        fitness_after=0.55,
    )
    assert payload["fitness_delta"] == -0.15
