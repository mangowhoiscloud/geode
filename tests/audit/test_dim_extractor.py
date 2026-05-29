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

from core.audit.dim_extractor import extract_dim_aggregates, extract_evidence


@dataclass
class FakeScore:
    value: Any = None
    explanation: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class FakeSample:
    scores: dict[str, FakeScore] = field(default_factory=dict)
    id: str = ""


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
        assert result == {
            "dim_means": {},
            "dim_stderr": {},
            "sample_count": {},
            "measurement_modality": {},
            "per_sample": [],
        }

    def test_empty_samples_returns_empty(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        path = tmp_path / "fake.eval"
        path.write_bytes(b"placeholder")
        _patch_read(monkeypatch, FakeEvalLog(samples=[]))

        result = extract_dim_aggregates(path)
        assert result == {
            "dim_means": {},
            "dim_stderr": {},
            "sample_count": {},
            "measurement_modality": {},
            "per_sample": [],
        }

    def test_read_failure_swallowed(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """A broken ``.eval`` must not propagate exceptions — the
        self-improving-loop is best-effort scaffolding, not a blocker."""
        path = tmp_path / "fake.eval"
        path.write_bytes(b"placeholder")

        def boom(*_args: Any, **_kwargs: Any) -> None:
            raise RuntimeError("synthetic read failure")

        monkeypatch.setattr("inspect_ai.log.read_eval_log", boom)

        result = extract_dim_aggregates(path)
        assert result == {
            "dim_means": {},
            "dim_stderr": {},
            "sample_count": {},
            "measurement_modality": {},
            "per_sample": [],
        }

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


# ---------------------------------------------------------------------------
# PR 0 — post-judge analytics dims (verbose_padding + redundant_tool_invocation)
# ---------------------------------------------------------------------------


def test_compute_verbose_padding_empty_returns_one() -> None:
    from core.audit.dim_extractor import compute_verbose_padding

    assert compute_verbose_padding([]) == 1.0


def test_compute_verbose_padding_no_reference_returns_one() -> None:
    from core.audit.dim_extractor import compute_verbose_padding

    # Without a reference there's nothing to compare to.
    assert compute_verbose_padding([100, 200, 300]) == 1.0


def test_compute_verbose_padding_ratio_one_returns_one() -> None:
    from core.audit.dim_extractor import compute_verbose_padding

    # Sample median = reference median → no padding
    assert compute_verbose_padding([100, 100], reference_median=100.0) == 1.0


def test_compute_verbose_padding_ratio_three_saturates_at_ten() -> None:
    from core.audit.dim_extractor import compute_verbose_padding

    assert compute_verbose_padding([300], reference_median=100.0) == 10.0


def test_compute_verbose_padding_ratio_two_intermediate() -> None:
    from core.audit.dim_extractor import compute_verbose_padding

    # Linear interp: ratio 2.0 → 1.0 + 1.0 * 4.5 = 5.5
    assert compute_verbose_padding([200], reference_median=100.0) == 5.5


def test_compute_redundant_tool_invocation_empty_returns_one() -> None:
    from core.audit.dim_extractor import compute_redundant_tool_invocation

    assert compute_redundant_tool_invocation([]) == 1.0


def test_compute_redundant_tool_invocation_no_duplicates() -> None:
    from core.audit.dim_extractor import compute_redundant_tool_invocation

    calls = [
        {"name": "read", "arguments": {"path": "a.py"}},
        {"name": "read", "arguments": {"path": "b.py"}},
        {"name": "write", "arguments": {"path": "a.py", "content": "x"}},
    ]
    assert compute_redundant_tool_invocation(calls) == 1.0


def test_compute_redundant_tool_invocation_one_duplicate() -> None:
    from core.audit.dim_extractor import compute_redundant_tool_invocation

    calls = [
        {"name": "read", "arguments": {"path": "a.py"}},
        {"name": "read", "arguments": {"path": "a.py"}},  # duplicate
    ]
    assert compute_redundant_tool_invocation(calls) == 4.0


def test_compute_redundant_tool_invocation_three_plus_saturates() -> None:
    from core.audit.dim_extractor import compute_redundant_tool_invocation

    calls = [{"name": "read", "arguments": {"path": "a.py"}}] * 5
    # 5 same calls → 4 duplicates → score 10.0
    assert compute_redundant_tool_invocation(calls) == 10.0


def test_compute_redundant_tool_invocation_args_order_insensitive() -> None:
    """JSON sort_keys=True means dict order doesn't fool the dedup."""
    from core.audit.dim_extractor import compute_redundant_tool_invocation

    calls = [
        {"name": "x", "arguments": {"a": 1, "b": 2}},
        {"name": "x", "arguments": {"b": 2, "a": 1}},  # same after sort
    ]
    assert compute_redundant_tool_invocation(calls) == 4.0


def test_compute_redundant_tool_invocation_handles_unserializable_args() -> None:
    """Args that aren't JSON-serializable fall back to repr — still dedupable."""
    from core.audit.dim_extractor import compute_redundant_tool_invocation

    class _Weird:
        def __repr__(self) -> str:
            return "weird"

    w = _Weird()
    calls = [
        {"name": "x", "arguments": {"obj": w}},
        {"name": "x", "arguments": {"obj": w}},
    ]
    # Falls back to repr; same repr → still detected as duplicate
    assert compute_redundant_tool_invocation(calls) >= 4.0


# ---------------------------------------------------------------------------
# PR-1 (2026-05-23) — sample_count + measurement_modality provenance
# ---------------------------------------------------------------------------


class TestProvenance:
    """PR-1 adds two provenance dicts so the baseline.json v2 schema can
    distinguish single-sample N=1 stderr=0 ("no signal") from
    multi-sample stderr=0 ("perfect stability"), and tell judge-LLM
    dims apart from post-judge analytics dims (token_count / tool_log).
    """

    def test_sample_count_matches_value_count(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """``sample_count[dim]`` must equal the number of numeric values
        that went into the aggregation for that dim."""
        path = tmp_path / "fake.eval"
        path.write_bytes(b"placeholder")
        fake_log = FakeEvalLog(
            samples=[
                FakeSample(scores={"judge": FakeScore(value={"dim_a": 2.0, "dim_b": 1.0})}),
                FakeSample(scores={"judge": FakeScore(value={"dim_a": 4.0, "dim_b": 5.0})}),
                FakeSample(scores={"judge": FakeScore(value={"dim_a": 6.0})}),
            ]
        )
        _patch_read(monkeypatch, fake_log)

        result = extract_dim_aggregates(path)
        assert result["sample_count"]["dim_a"] == 3
        assert result["sample_count"]["dim_b"] == 2

    def test_n1_sample_count_disambiguates_stderr_zero(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """N=1 stderr=0 must surface as ``sample_count=1`` so the
        autoresearch ``_should_promote`` rule can treat it as "no
        stability signal" rather than "perfect stability"."""
        path = tmp_path / "fake.eval"
        path.write_bytes(b"placeholder")
        fake_log = FakeEvalLog(
            samples=[FakeSample(scores={"judge": FakeScore(value={"dim_a": 3.0})})]
        )
        _patch_read(monkeypatch, fake_log)

        result = extract_dim_aggregates(path)
        assert result["sample_count"]["dim_a"] == 1
        assert result["dim_stderr"]["dim_a"] == 0.0  # invariant unchanged

    def test_judge_dim_modality_is_judge_llm(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """A rubric-scored dim must carry the ``judge_llm`` modality."""
        path = tmp_path / "fake.eval"
        path.write_bytes(b"placeholder")
        fake_log = FakeEvalLog(
            samples=[FakeSample(scores={"judge": FakeScore(value={"broken_tool_use": 4.0})})]
        )
        _patch_read(monkeypatch, fake_log)

        result = extract_dim_aggregates(path)
        assert result["measurement_modality"]["broken_tool_use"] == "judge_llm"

    def test_analytics_dim_modalities_tagged_distinctly(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """``verbose_padding`` → ``token_count``;
        ``redundant_tool_invocation`` → ``tool_log``. Both differ from
        the judge-LLM default so the autoresearch fitness aggregator
        can weight them differently if needed."""
        path = tmp_path / "fake.eval"
        path.write_bytes(b"placeholder")

        # Build a sample whose messages carry assistant-role usage +
        # duplicate tool calls so both analytics dims fire.
        class _Usage:
            output_tokens = 4000  # well above typical median

        class _Msg:
            role = "assistant"
            usage = _Usage()
            tool_calls = [
                {"function": {"name": "shell", "arguments": '{"cmd": "ls"}'}},
                {"function": {"name": "shell", "arguments": '{"cmd": "ls"}'}},
            ]

        class _SampleWithUsage:
            scores = {"judge": FakeScore(value={"input_hallucination": 2.0})}
            messages = [_Msg()]

        fake_log = FakeEvalLog(samples=[_SampleWithUsage()])
        _patch_read(monkeypatch, fake_log)

        result = extract_dim_aggregates(path)
        modality = result["measurement_modality"]
        assert modality.get("input_hallucination") == "judge_llm"
        assert modality.get("verbose_padding") == "token_count"
        assert modality.get("redundant_tool_invocation") == "tool_log"

    def test_n_gt_1_identical_values_stderr_zero(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """``stderr == 0.0`` also arises when ``N > 1`` and all sample
        values are identical (variance is genuinely zero, not
        "undefined"). ``sample_count > 1`` is the disambiguator from
        the ``N == 1`` case."""
        path = tmp_path / "fake.eval"
        path.write_bytes(b"placeholder")
        fake_log = FakeEvalLog(
            samples=[
                FakeSample(scores={"judge": FakeScore(value={"dim_a": 3.0})}),
                FakeSample(scores={"judge": FakeScore(value={"dim_a": 3.0})}),
                FakeSample(scores={"judge": FakeScore(value={"dim_a": 3.0})}),
            ]
        )
        _patch_read(monkeypatch, fake_log)

        result = extract_dim_aggregates(path)
        assert result["dim_stderr"]["dim_a"] == 0.0
        assert result["sample_count"]["dim_a"] == 3  # NOT 1 — perfect stability, not no-signal

    def test_all_four_dicts_share_key_set(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """``dim_means`` / ``dim_stderr`` / ``sample_count`` /
        ``measurement_modality`` must all carry the same key set —
        downstream baseline.json v2 build path zips them together
        and a key mismatch would silently drop dims."""
        path = tmp_path / "fake.eval"
        path.write_bytes(b"placeholder")
        fake_log = FakeEvalLog(
            samples=[
                FakeSample(scores={"judge": FakeScore(value={"dim_a": 2.0, "dim_b": 7.0})}),
                FakeSample(scores={"judge": FakeScore(value={"dim_a": 4.0, "dim_b": 5.0})}),
            ]
        )
        _patch_read(monkeypatch, fake_log)

        result = extract_dim_aggregates(path)
        means_keys = set(result["dim_means"])
        assert set(result["dim_stderr"]) == means_keys
        assert set(result["sample_count"]) == means_keys
        assert set(result["measurement_modality"]) == means_keys


# ---------------------------------------------------------------------------
# G2 — per-dim top-K evidence (2026-05-20 self-improving-loop wiring sprint)
# ---------------------------------------------------------------------------


class TestEvidence:
    """``extract_evidence`` — per-dim top-K worst-sample {sample_id, value,
    explanation, highlights} rows."""

    def test_ranks_dim_rows_by_value_descending(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Highest dim value = most concerning; top_k picks the worst K."""
        archive_path = tmp_path / "fake.eval"
        archive_path.write_bytes(b"placeholder")
        fake_log = FakeEvalLog(
            samples=[
                FakeSample(
                    id="seed-low",
                    scores={
                        "judge": FakeScore(
                            value={"broken_tool_use": 2},
                            explanation="low concern",
                            metadata={"highlights": "- [M1] low"},
                        )
                    },
                ),
                FakeSample(
                    id="seed-high",
                    scores={
                        "judge": FakeScore(
                            value={"broken_tool_use": 9},
                            explanation="severe hallucination",
                            metadata={"highlights": "- [M2] worst"},
                        )
                    },
                ),
                FakeSample(
                    id="seed-mid",
                    scores={
                        "judge": FakeScore(
                            value={"broken_tool_use": 5},
                            explanation="mid concern",
                            metadata={"highlights": "- [M3] mid"},
                        )
                    },
                ),
            ]
        )
        _patch_read(monkeypatch, fake_log)

        evidence_by_dim = extract_evidence(archive_path, top_k=2)
        rows = evidence_by_dim["broken_tool_use"]
        assert [r["sample_id"] for r in rows] == ["seed-high", "seed-mid"]
        assert rows[0]["value"] == 9.0
        assert "severe hallucination" in rows[0]["explanation"]
        assert "[M2]" in rows[0]["highlights"]

    def test_alphabetical_tiebreak_on_equal_value(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Equal values → sample_id alphabetical ascending. Stable diffs."""
        archive_path = tmp_path / "fake.eval"
        archive_path.write_bytes(b"placeholder")
        fake_log = FakeEvalLog(
            samples=[
                FakeSample(id="seed-z", scores={"j": FakeScore(value={"d": 7})}),
                FakeSample(id="seed-a", scores={"j": FakeScore(value={"d": 7})}),
                FakeSample(id="seed-m", scores={"j": FakeScore(value={"d": 7})}),
            ]
        )
        _patch_read(monkeypatch, fake_log)

        ranked_rows = extract_evidence(archive_path, top_k=3)["d"]
        assert [r["sample_id"] for r in ranked_rows] == ["seed-a", "seed-m", "seed-z"]

    def test_skips_scalar_valued_scores(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Scalar score.value can't be tied to a dim citation — silently skipped."""
        archive_path = tmp_path / "fake.eval"
        archive_path.write_bytes(b"placeholder")
        fake_log = FakeEvalLog(
            samples=[
                FakeSample(
                    id="seed-scalar",
                    scores={"scalar": FakeScore(value=8.0, explanation="ignored")},
                ),
                FakeSample(
                    id="seed-dict",
                    scores={"judge": FakeScore(value={"dim_x": 4}, explanation="kept")},
                ),
            ]
        )
        _patch_read(monkeypatch, fake_log)

        evidence_by_dim = extract_evidence(archive_path, top_k=5)
        assert "scalar" not in evidence_by_dim
        assert "dim_x" in evidence_by_dim
        assert evidence_by_dim["dim_x"][0]["explanation"] == "kept"

    def test_top_k_zero_returns_empty(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """top_k<1 short-circuits — caller treats as 'no evidence wanted'."""
        archive_path = tmp_path / "fake.eval"
        archive_path.write_bytes(b"placeholder")
        fake_log = FakeEvalLog(
            samples=[FakeSample(id="s", scores={"j": FakeScore(value={"d": 7})})]
        )
        _patch_read(monkeypatch, fake_log)

        assert extract_evidence(archive_path, top_k=0) == {}

    def test_missing_archive_returns_empty(self, tmp_path: Path) -> None:
        """Same graceful contract as extract_dim_aggregates."""
        missing_archive = tmp_path / "absent.eval"
        assert extract_evidence(missing_archive, top_k=3) == {}

    def test_read_failure_swallowed(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Broken archive → empty evidence, no exception bubbled up."""
        archive_path = tmp_path / "fake.eval"
        archive_path.write_bytes(b"placeholder")

        def boom(*_args: Any, **_kwargs: Any) -> None:
            raise RuntimeError("synthetic read failure")

        monkeypatch.setattr("inspect_ai.log.read_eval_log", boom)
        assert extract_evidence(archive_path, top_k=3) == {}

    def test_missing_explanation_and_highlights(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Sample without explanation/metadata → empty strings, not KeyError."""
        archive_path = tmp_path / "fake.eval"
        archive_path.write_bytes(b"placeholder")
        fake_log = FakeEvalLog(
            samples=[FakeSample(id="seed-bare", scores={"j": FakeScore(value={"d": 6})})]
        )
        _patch_read(monkeypatch, fake_log)

        rows = extract_evidence(archive_path, top_k=1)["d"]
        assert rows[0]["explanation"] == ""
        assert rows[0]["highlights"] == ""
