"""A.5 (2026-05-25) — meta-judge invocation invariants (PR-13).

Scope:
- build_meta_judge_prompt: empty records → ValueError, N records → 2-tuple,
  serialised JSONL per row, no PII leaks
- parse_meta_judge_response: strict JSON / fence-wrapped JSON / regex fallback
  / total-failure → (0.0, "") / clamp [0, 1] / truncate 500
- invoke_meta_judge: empty file → None / mock llm_call DI / score in
  expected range / evaluated_count == records read
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from core.self_improving.loop.meta_judge import (
    MetaJudgeResult,
    build_meta_judge_prompt,
    invoke_meta_judge,
    parse_meta_judge_response,
)


def _attribution_row(mid: str, score: float = 0.3) -> dict:
    return {
        "ts": time.time(),
        "kind": "attribution",
        "mutation_id": mid,
        "observed_dim": {"safety": 0.1},
        "ci95": {"safety": 0.05},
        "significant": {"safety": True},
        "attribution_score": score,
        "missing_baseline": False,
        "fitness_delta": 0.02,
    }


def _write_attribution_jsonl(path: Path, n: int) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for i in range(n):
            fh.write(json.dumps(_attribution_row(f"m{i}", 0.1 * (i + 1))) + "\n")


# ---------------------------------------------------------------------------
# 1. build_meta_judge_prompt — empty + happy path
# ---------------------------------------------------------------------------


def test_build_prompt_empty_records_raises() -> None:
    with pytest.raises(ValueError, match="empty records"):
        build_meta_judge_prompt([])


def test_build_prompt_includes_count_in_user_prompt(tmp_path: Path) -> None:
    """User prompt should mention the actual record count."""
    log = tmp_path / "mutations.jsonl"
    _write_attribution_jsonl(log, 3)
    from core.self_improving.loop.mutations_reader import read_recent_attributions

    records = read_recent_attributions(3, log)
    _system, user_prompt = build_meta_judge_prompt(records)
    assert "3 attribution rows" in user_prompt


def test_build_prompt_serialises_each_record_as_jsonl(tmp_path: Path) -> None:
    """Each record should appear as one JSONL line in the user prompt body."""
    log = tmp_path / "mutations.jsonl"
    _write_attribution_jsonl(log, 2)
    from core.self_improving.loop.mutations_reader import read_recent_attributions

    records = read_recent_attributions(2, log)
    _system, user_prompt = build_meta_judge_prompt(records)
    # Each record's mutation_id should appear; JSON shape preserved
    assert "m0" in user_prompt
    assert "m1" in user_prompt
    assert "observed_dim" in user_prompt


def test_build_prompt_system_demands_json_only() -> None:
    """System prompt should constrain output to JSON (no prose)."""
    records = [
        type(
            "R",
            (),
            {
                "mutation_id": "x",
                "observed_dim": {},
                "ci95": {},
                "significant": {},
                "attribution_score": 0.0,
                "fitness_delta": None,
            },
        )()
    ]
    system_prompt, _user = build_meta_judge_prompt(records)
    assert "JSON" in system_prompt
    assert "ONLY" in system_prompt or "only" in system_prompt


# ---------------------------------------------------------------------------
# 2. parse_meta_judge_response — strict JSON path
# ---------------------------------------------------------------------------


def test_parse_strict_json() -> None:
    raw = '{"drift_score": 0.42, "drift_summary": "scores drifted upward"}'
    score, summary = parse_meta_judge_response(raw)
    assert score == pytest.approx(0.42)
    assert summary == "scores drifted upward"


def test_parse_fence_wrapped_json() -> None:
    raw = '```json\n{"drift_score": 0.7, "drift_summary": "high"}\n```'
    score, summary = parse_meta_judge_response(raw)
    assert score == pytest.approx(0.7)
    assert summary == "high"


def test_parse_fence_wrapped_no_lang_marker() -> None:
    raw = '```\n{"drift_score": 0.3, "drift_summary": "ok"}\n```'
    score, summary = parse_meta_judge_response(raw)
    assert score == pytest.approx(0.3)
    assert summary == "ok"


def test_parse_clamps_out_of_range_score() -> None:
    """drift_score > 1 or < 0 → clamped to [0, 1]."""
    score_high, _ = parse_meta_judge_response('{"drift_score": 1.5, "drift_summary": "x"}')
    assert score_high == 1.0
    score_low, _ = parse_meta_judge_response('{"drift_score": -0.4, "drift_summary": "x"}')
    assert score_low == 0.0


def test_parse_truncates_summary_to_500() -> None:
    long_summary = "x" * 1000
    raw = json.dumps({"drift_score": 0.1, "drift_summary": long_summary})
    _score, summary = parse_meta_judge_response(raw)
    assert len(summary) == 500


# ---------------------------------------------------------------------------
# 3. parse_meta_judge_response — regex fallback + failure
# ---------------------------------------------------------------------------


def test_parse_regex_fallback_key_value_style() -> None:
    """Low-capability model that doesn't return JSON → regex extracts."""
    raw = 'Based on the attributions, drift_score: 0.55, drift_summary: "moderate".'
    score, summary = parse_meta_judge_response(raw)
    assert score == pytest.approx(0.55)
    assert summary == "moderate"


def test_parse_total_failure_returns_zero_and_empty() -> None:
    """Completely unparseable output → (0.0, "") so caller can detect."""
    score, summary = parse_meta_judge_response("This is not a meta-judge response at all.")
    assert score == 0.0
    assert summary == ""


def test_parse_non_numeric_score_falls_through() -> None:
    """JSON loads succeeds but ``drift_score`` is non-numeric → regex
    fallback tries to find numeric pattern → fails → returns (0.0, "").

    Codex MCP WARN #3 tighten — earlier wording allowed `summary == "x"`
    via regex even when JSON path rejected score; actual behaviour is
    score_match=None → entire return is (0.0, ""). Pin the exact tuple.
    """
    raw = '{"drift_score": "high", "drift_summary": "x"}'
    score, summary = parse_meta_judge_response(raw)
    assert score == 0.0
    assert summary == ""


def test_parse_negative_score_in_json_clamped_not_regex_fallback() -> None:
    """Codex MCP WARN #4 — regex 가 negative number 매칭 안 함 (-? 미포함).
    JSON 경로에서 negative 는 ``_clamp_score`` 가 0.0 으로 clamp. 본 test 가
    JSON 경로 lower-bound clamp 의 정확한 동작 pin — regex fallback 로
    falling through 하지 않음을 보장.
    """
    raw = '{"drift_score": -0.4, "drift_summary": "neg"}'
    score, summary = parse_meta_judge_response(raw)
    assert score == 0.0  # clamped from -0.4
    assert summary == "neg"  # summary 보존 — regex 로 fall through 하지 않음


# ---------------------------------------------------------------------------
# 4. invoke_meta_judge — DI + skip + result shape
# ---------------------------------------------------------------------------


def test_invoke_returns_none_when_no_attributions(tmp_path: Path) -> None:
    log = tmp_path / "mutations.jsonl"
    # File 부재 → reader 가 빈 list → invoke 가 None
    result = invoke_meta_judge(5, llm_call=lambda _s, _u: "", path=log)
    assert result is None


def test_invoke_calls_llm_with_built_prompts(tmp_path: Path) -> None:
    log = tmp_path / "mutations.jsonl"
    _write_attribution_jsonl(log, 2)
    captured: dict[str, str] = {}

    def fake_llm(system_prompt: str, user_prompt: str) -> str:
        captured["system"] = system_prompt
        captured["user"] = user_prompt
        return '{"drift_score": 0.25, "drift_summary": "low"}'

    result = invoke_meta_judge(2, llm_call=fake_llm, path=log)
    assert result is not None
    assert isinstance(result, MetaJudgeResult)
    assert result.drift_score == pytest.approx(0.25)
    assert result.drift_summary == "low"
    assert result.evaluated_count == 2
    assert "2 attribution rows" in captured["user"]
    assert "meta-judge" in captured["system"]


def test_invoke_clamps_score_via_parser(tmp_path: Path) -> None:
    """End-to-end clamp via parse_meta_judge_response."""
    log = tmp_path / "mutations.jsonl"
    _write_attribution_jsonl(log, 1)
    result = invoke_meta_judge(
        1, llm_call=lambda _s, _u: '{"drift_score": 2.0, "drift_summary": "x"}', path=log
    )
    assert result is not None
    assert result.drift_score == 1.0


def test_invoke_records_raw_llm_text(tmp_path: Path) -> None:
    """llm_raw should be retained for audit (truncated to 2000)."""
    log = tmp_path / "mutations.jsonl"
    _write_attribution_jsonl(log, 1)
    raw_text = '{"drift_score": 0.5, "drift_summary": "x"}'
    result = invoke_meta_judge(1, llm_call=lambda _s, _u: raw_text, path=log)
    assert result is not None
    assert result.llm_raw == raw_text


def test_invoke_truncates_huge_raw(tmp_path: Path) -> None:
    log = tmp_path / "mutations.jsonl"
    _write_attribution_jsonl(log, 1)
    huge = "x" * 5000
    result = invoke_meta_judge(1, llm_call=lambda _s, _u: huge, path=log)
    assert result is not None
    assert len(result.llm_raw) == 2000


def test_invoke_negative_n_raises(tmp_path: Path) -> None:
    log = tmp_path / "mutations.jsonl"
    _write_attribution_jsonl(log, 1)
    with pytest.raises(ValueError, match=r"n must be >= 1"):
        invoke_meta_judge(0, llm_call=lambda _s, _u: "", path=log)


def test_invoke_total_parse_failure_yields_zero_score(tmp_path: Path) -> None:
    """LLM returns garbage → MetaJudgeResult with drift_score=0.0 + empty summary.

    Caller can detect "no signal" via empty summary (vs LLM saying score=0.0
    means truly low drift). Score alone is ambiguous; pair with summary
    emptiness check.
    """
    log = tmp_path / "mutations.jsonl"
    _write_attribution_jsonl(log, 1)
    result = invoke_meta_judge(1, llm_call=lambda _s, _u: "this is garbage output", path=log)
    assert result is not None
    assert result.drift_score == 0.0
    assert result.drift_summary == ""
