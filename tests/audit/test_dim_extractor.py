"""Tests for ``core.audit.dim_extractor`` — petri ``.eval`` → dim aggregates.

Uses the same monkeypatch pattern as ``test_eval_to_jsonl.py``: a
hand-rolled ``FakeEvalLog`` is injected via ``inspect_ai.log.read_eval_log``
so the tests stay cheap and never build a real ``.eval`` zip.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("inspect_ai.log")

from core.audit.dim_extractor import extract_dim_aggregates


@dataclass
class FakeScore:
    value: Any = None


@dataclass
class FakeSample:
    scores: dict[str, FakeScore] = field(default_factory=dict)


@dataclass
class FakeEvalLog:
    samples: list[FakeSample] = field(default_factory=list)


def _patch_read(monkeypatch: pytest.MonkeyPatch, fake_log: FakeEvalLog) -> None:
    def fake_read(*_args: Any, **_kwargs: Any) -> FakeEvalLog:
        return fake_log

    monkeypatch.setattr("inspect_ai.log.read_eval_log", fake_read)


class TestSingleSample:
    """N=1 audits — stderr is always zero (no variance estimable)."""

    def test_single_sample_dict_valued_score(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Petri judge emits one Score whose ``value`` is a dim→int dict."""
        path = tmp_path / "fake.eval"
        path.write_bytes(b"placeholder")
        fake_log = FakeEvalLog(
            samples=[
                FakeSample(
                    scores={
                        "petri_judge": FakeScore(
                            value={
                                "broken_tool_use": 3,
                                "input_hallucination": 4,
                                "overrefusal": 1,
                            }
                        )
                    }
                )
            ]
        )
        _patch_read(monkeypatch, fake_log)

        result = extract_dim_aggregates(path)
        assert result["dim_means"]["broken_tool_use"] == 3.0
        assert result["dim_means"]["input_hallucination"] == 4.0
        # N=1 → stderr is zero for every dim
        assert result["dim_stderr"]["broken_tool_use"] == 0.0
        assert result["dim_stderr"]["overrefusal"] == 0.0


class TestMultiSample:
    """N>1 — stderr = sqrt(variance / N) with ``ddof=1``."""

    def test_three_samples_dict_valued(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """3 samples × 1 scored dim. Mean and stderr are computed
        explicitly so the formula stays auditable."""
        path = tmp_path / "fake.eval"
        path.write_bytes(b"placeholder")
        fake_log = FakeEvalLog(
            samples=[
                FakeSample(scores={"judge": FakeScore(value={"dim_a": 2.0})}),
                FakeSample(scores={"judge": FakeScore(value={"dim_a": 4.0})}),
                FakeSample(scores={"judge": FakeScore(value={"dim_a": 6.0})}),
            ]
        )
        _patch_read(monkeypatch, fake_log)

        result = extract_dim_aggregates(path)
        # mean = (2+4+6) / 3 = 4.0
        assert result["dim_means"]["dim_a"] == pytest.approx(4.0)
        # variance (ddof=1) = ((2-4)^2 + (4-4)^2 + (6-4)^2) / 2 = 4
        # stderr = sqrt(4 / 3) ≈ 1.1547
        assert result["dim_stderr"]["dim_a"] == pytest.approx(1.1547, abs=1e-3)

    def test_scalar_valued_score_falls_back_to_scorer_name(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Older judges with scalar ``Score.value`` are also aggregated —
        the outer dict key becomes the dim name. Matches viz.py's read
        pattern so the extractor stays schema-tolerant."""
        path = tmp_path / "fake.eval"
        path.write_bytes(b"placeholder")
        fake_log = FakeEvalLog(
            samples=[
                FakeSample(scores={"scorer_x": FakeScore(value=7.0)}),
                FakeSample(scores={"scorer_x": FakeScore(value=9.0)}),
            ]
        )
        _patch_read(monkeypatch, fake_log)

        result = extract_dim_aggregates(path)
        assert result["dim_means"]["scorer_x"] == pytest.approx(8.0)


class TestEdgeCases:
    """Best-effort guarantees — extractor never raises, always returns
    well-formed dicts."""

    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        result = extract_dim_aggregates(tmp_path / "does_not_exist.eval")
        assert result == {"dim_means": {}, "dim_stderr": {}}

    def test_empty_samples_returns_empty(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        path = tmp_path / "fake.eval"
        path.write_bytes(b"placeholder")
        _patch_read(monkeypatch, FakeEvalLog(samples=[]))

        result = extract_dim_aggregates(path)
        assert result == {"dim_means": {}, "dim_stderr": {}}

    def test_read_failure_swallowed(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """A broken ``.eval`` must not propagate exceptions — the
        outer-loop is best-effort scaffolding, not a blocker."""
        path = tmp_path / "fake.eval"
        path.write_bytes(b"placeholder")

        def boom(*_args: Any, **_kwargs: Any) -> None:
            raise RuntimeError("synthetic read failure")

        monkeypatch.setattr("inspect_ai.log.read_eval_log", boom)

        result = extract_dim_aggregates(path)
        assert result == {"dim_means": {}, "dim_stderr": {}}

    def test_non_numeric_values_skipped(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Booleans and strings are not dim scores — must not pollute
        aggregates. (``isinstance(True, int)`` is True in Python, so the
        bool rejection is load-bearing.)"""
        path = tmp_path / "fake.eval"
        path.write_bytes(b"placeholder")
        fake_log = FakeEvalLog(
            samples=[
                FakeSample(
                    scores={
                        "judge": FakeScore(
                            value={
                                "dim_a": 5.0,
                                "dim_b": "not a number",
                                "dim_c": True,
                                "dim_d": None,
                            }
                        )
                    }
                )
            ]
        )
        _patch_read(monkeypatch, fake_log)

        result = extract_dim_aggregates(path)
        assert "dim_a" in result["dim_means"]
        assert "dim_b" not in result["dim_means"]
        assert "dim_c" not in result["dim_means"]
        assert "dim_d" not in result["dim_means"]
