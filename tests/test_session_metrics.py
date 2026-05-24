"""PR-SESSION-METRICS — central session-scoped state aggregator tests.

Replaces the ``_LAST_LLM_CALL_USAGE`` module-level sidecar from PR-SIL-5THEME
C4 with a ``SessionMetrics`` ContextVar that mirrors claude-code
``AgentLoopState.totalUsage`` + hermes ``sessions`` table column shape.
"""

from __future__ import annotations

import time
from typing import Any

from core.observability import (
    SessionMetrics,
    current_session_metrics,
    session_metrics_scope,
    set_current_session_metrics,
)

# ---------------------------------------------------------------------------
# 1. SessionMetrics dataclass defaults
# ---------------------------------------------------------------------------


def test_session_metrics_defaults_zero_or_empty() -> None:
    """Fresh ``SessionMetrics()`` 가 모든 numeric field 0, string field ""."""
    m = SessionMetrics()
    assert m.session_id == ""
    assert m.input_tokens == 0
    assert m.output_tokens == 0
    assert m.cache_creation_tokens == 0
    assert m.cache_read_tokens == 0
    assert m.thinking_tokens == 0
    assert m.estimated_cost_usd == 0.0
    assert m.elapsed_seconds == 0.0
    assert m.model_used == ""
    assert m.api_call_count == 0
    assert m.tool_call_count == 0
    assert m.message_count == 0
    assert m.mutation_count == 0
    assert m.audit_call_count == 0
    assert m.billing_provider == ""
    assert m.billing_mode == ""
    assert m.retry_count == 0
    assert m.circuit_breaker_trips == {}
    assert m.error_count_by_type == {}
    assert m.rollback_count == 0
    assert m.fitness_before is None
    assert m.fitness_after is None
    assert m.last_call_input_tokens == 0
    assert m.missing_dims_total == 0
    assert m.missing_benches_total == 0
    assert m.cross_validation_conflict_count == 0


# ---------------------------------------------------------------------------
# 2. accumulate_llm_call — additive + last-call snapshot
# ---------------------------------------------------------------------------


def test_accumulate_llm_call_additive() -> None:
    """N 번의 call 이 cumulative field 에 + 누적."""
    m = SessionMetrics()
    m.accumulate_llm_call(input_tokens=100, output_tokens=50, elapsed_seconds=1.0)
    m.accumulate_llm_call(input_tokens=200, output_tokens=80, elapsed_seconds=2.5)
    assert m.input_tokens == 300
    assert m.output_tokens == 130
    assert m.elapsed_seconds == 3.5
    assert m.api_call_count == 2


def test_accumulate_llm_call_last_call_snapshot_overwrites() -> None:
    """``last_call_*`` field 는 매 call 마다 *덮어쓰기* (cumulative 아님)."""
    m = SessionMetrics()
    m.accumulate_llm_call(input_tokens=100, output_tokens=50, model="a")
    m.accumulate_llm_call(input_tokens=200, output_tokens=80, model="b")
    # 마지막 call 값만 last_call_* 에 남음
    assert m.last_call_input_tokens == 200
    assert m.last_call_output_tokens == 80
    assert m.last_call_model == "b"


def test_reset_last_call_preserves_cumulative() -> None:
    """``reset_last_call()`` 는 last_call_* 만 비우고 cumulative 보존."""
    m = SessionMetrics()
    m.accumulate_llm_call(input_tokens=100, output_tokens=50, model="a")
    m.reset_last_call()
    assert m.last_call_input_tokens == 0
    assert m.last_call_model == ""
    # cumulative untouched
    assert m.input_tokens == 100
    assert m.output_tokens == 50
    assert m.api_call_count == 1


# ---------------------------------------------------------------------------
# 3. Counter / accumulator API
# ---------------------------------------------------------------------------


def test_increment_apis() -> None:
    m = SessionMetrics()
    m.increment_tool_call()
    m.increment_tool_call(3)
    m.increment_message(5)
    m.increment_mutation()
    m.increment_audit_call(2)
    assert m.tool_call_count == 4
    assert m.message_count == 5
    assert m.mutation_count == 1
    assert m.audit_call_count == 2


def test_record_retry_and_circuit_breaker() -> None:
    m = SessionMetrics()
    m.record_retry()
    m.record_retry("anthropic")
    m.record_circuit_breaker_trip("anthropic")
    m.record_circuit_breaker_trip("anthropic")
    m.record_circuit_breaker_trip("openai")
    assert m.retry_count == 2
    assert m.circuit_breaker_trips == {"anthropic": 2, "openai": 1}


def test_record_error_by_type() -> None:
    m = SessionMetrics()
    m.record_error("RateLimitError")
    m.record_error("RateLimitError")
    m.record_error("OverloadedError")
    assert m.error_count_by_type == {"RateLimitError": 2, "OverloadedError": 1}


def test_record_goodhart() -> None:
    m = SessionMetrics()
    m.record_goodhart(missing_dims=3, missing_benches=2, cross_validation_conflict=True)
    m.record_goodhart(missing_dims=1, cross_validation_conflict=False)
    assert m.missing_dims_total == 4
    assert m.missing_benches_total == 2
    assert m.cross_validation_conflict_count == 1


# ---------------------------------------------------------------------------
# 4. to_session_row — persistence shape (hermes / paperclip parity)
# ---------------------------------------------------------------------------


def test_to_session_row_has_all_expected_keys() -> None:
    """Hermes sessions 테이블 column 패리티 — 핵심 field 모두 row 에 emit."""
    m = SessionMetrics(session_id="s1", gen_tag="g1", component="autoresearch", started_at=1.0)
    row = m.to_session_row()
    expected = {
        "session_id",
        "gen_tag",
        "component",
        "started_at",
        "input_tokens",
        "output_tokens",
        "cache_creation_tokens",
        "cache_read_tokens",
        "thinking_tokens",
        "estimated_cost_usd",
        "elapsed_seconds",
        "model_used",
        "api_call_count",
        "tool_call_count",
        "message_count",
        "mutation_count",
        "audit_call_count",
        "billing_provider",
        "billing_mode",
        "retry_count",
        "circuit_breaker_trips",
        "error_count_by_type",
        "rollback_count",
        "fitness_before",
        "fitness_after",
        "cohort_tag",
        "missing_dims_total",
        "missing_benches_total",
        "cross_validation_conflict_count",
    }
    assert expected.issubset(set(row.keys()))


def test_to_session_row_rounds_cost_and_elapsed() -> None:
    """Float field 는 round (6 / 4 자리) — JSONL serialization noise 차단."""
    m = SessionMetrics()
    m.estimated_cost_usd = 0.123456789
    m.elapsed_seconds = 1.23456789
    row = m.to_session_row()
    assert row["estimated_cost_usd"] == 0.123457
    assert row["elapsed_seconds"] == 1.2346


# ---------------------------------------------------------------------------
# 5. ContextVar lifecycle — session_metrics_scope
# ---------------------------------------------------------------------------


def test_current_session_metrics_lazy_init_when_unscoped() -> None:
    """Scope 밖에서 ``current_session_metrics()`` 호출 → 빈 SessionMetrics() 반환
    (RunTranscript 의 no-op fallback 패턴 일치)."""
    set_current_session_metrics(None)
    m = current_session_metrics()
    assert isinstance(m, SessionMetrics)


def test_session_metrics_scope_isolates_nested() -> None:
    """``session_metrics_scope`` 가 inner / outer scope 격리. exit 시 outer 복원."""
    set_current_session_metrics(None)
    with session_metrics_scope(session_id="outer"):
        outer = current_session_metrics()
        outer.input_tokens = 100
        with session_metrics_scope(session_id="inner"):
            inner = current_session_metrics()
            assert inner.session_id == "inner"
            assert inner.input_tokens == 0  # fresh
            inner.input_tokens = 200
        # outer 복원, inner mutation 무영향
        assert current_session_metrics().session_id == "outer"
        assert current_session_metrics().input_tokens == 100


def test_session_metrics_scope_started_at_set() -> None:
    """``session_metrics_scope`` 가 started_at 을 자동 stamp."""
    before = time.time()
    with session_metrics_scope(session_id="s") as m:
        after = time.time()
        assert before <= m.started_at <= after


def test_session_metrics_scope_restores_on_exception() -> None:
    """Exception 이 propagate 해도 outer ContextVar 복원."""
    set_current_session_metrics(None)
    outer_metrics = SessionMetrics(session_id="outer")
    set_current_session_metrics(outer_metrics)
    try:
        with session_metrics_scope(session_id="inner"):
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert current_session_metrics() is outer_metrics


# ---------------------------------------------------------------------------
# 6. Integration with _default_llm_call / propose() (C4 absorption)
# ---------------------------------------------------------------------------


def test_session_metrics_accumulates_through_propose_helper_api(monkeypatch: Any) -> None:
    """C4 의 ``_reset_last_llm_call_usage`` / ``_consume_last_llm_call_usage``
    가 SessionMetrics 와 정확히 sync — backward-compat path 검증."""
    from core.self_improving_loop.runner import (
        _consume_last_llm_call_usage,
        _reset_last_llm_call_usage,
    )

    with session_metrics_scope(session_id="test"):
        m = current_session_metrics()
        # production _default_llm_call 시뮬레이션
        m.accumulate_llm_call(
            input_tokens=500,
            output_tokens=200,
            elapsed_seconds=2.0,
            model="claude-opus-4-7",
        )
        # propose() 가 _consume 으로 회수
        snapshot = _consume_last_llm_call_usage()
        assert snapshot["input_tokens"] == 500
        assert snapshot["output_tokens"] == 200
        # cumulative 보존
        assert m.input_tokens == 500
        # 다음 propose() 전 _reset
        _reset_last_llm_call_usage()
        assert m.last_call_input_tokens == 0
        # 두 번째 LLM call 시뮬레이션
        m.accumulate_llm_call(input_tokens=300, output_tokens=100, model="claude-sonnet-4-6")
        # cumulative = 첫 call (500) + 두 번째 call (300) = 800
        assert m.input_tokens == 800
        assert m.api_call_count == 2
