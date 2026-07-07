"""Tests for ``core.audit.judge_agreement`` — judge ↔ human agreement.

Three families:

1. **Statistics** — weighted Cohen's kappa and Krippendorff's alpha are
   checked against hand-derived and *published* values. The kappa targets
   (0.75 linear, 0.8333 quadratic) are derived by hand from a symmetric 3×3
   confusion matrix; the alpha targets (0.743 nominal, 0.815 ordinal, 0.849
   interval) are the canonical Hayes & Krippendorff (2007) reliability-data
   values. Matching all five is a strong known-value oracle without any
   third-party stats dependency.
2. **Extraction / blinding** — ``FakeEvalLog`` (same monkeypatch pattern as
   ``test_dim_extractor.py``) drives deterministic stratified sampling and
   confirms the reconstructed excerpt carries no judge score/explanation.
3. **Persistence / resume** — JSONL round-trips and ``pending_items`` skip.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from core.audit.judge_agreement import (
    AgreementItem,
    LabelRecord,
    append_label,
    compute_report,
    directional_bias,
    extract_pairs,
    krippendorff_alpha,
    pending_items,
    read_items,
    read_labels,
    reconstruct_transcript,
    render_recalibration,
    render_report,
    weighted_cohens_kappa,
    write_items,
)


# --------------------------------------------------------------------------- #
# 1. Statistics — known-value oracles
# --------------------------------------------------------------------------- #
def _pairs_from_confusion() -> tuple[list[int], list[int]]:
    """Symmetric 3×3 confusion (marginals all 12, N=36). Hand-derived
    weighted kappa: linear = 0.75, quadratic = 0.8333."""
    matrix = {
        (1, 1): 10,
        (1, 2): 2,
        (2, 1): 2,
        (2, 2): 8,
        (2, 3): 2,
        (3, 2): 2,
        (3, 3): 10,
    }
    a: list[int] = []
    b: list[int] = []
    for (i, j), c in matrix.items():
        a.extend([i] * c)
        b.extend([j] * c)
    return a, b


class TestWeightedKappa:
    def test_quadratic_hand_value(self) -> None:
        a, b = _pairs_from_confusion()
        k = weighted_cohens_kappa(a, b, categories=[1, 2, 3], weights="quadratic")
        assert k is not None
        assert k == pytest.approx(5 / 6, abs=1e-6)  # 0.8333…

    def test_linear_hand_value(self) -> None:
        a, b = _pairs_from_confusion()
        k = weighted_cohens_kappa(a, b, categories=[1, 2, 3], weights="linear")
        assert k is not None
        assert k == pytest.approx(0.75, abs=1e-6)

    def test_perfect_agreement_is_one(self) -> None:
        k = weighted_cohens_kappa([1, 2, 3, 4], [1, 2, 3, 4], categories=[1, 2, 3, 4])
        assert k == pytest.approx(1.0, abs=1e-9)

    def test_too_few_pairs_returns_none(self) -> None:
        assert weighted_cohens_kappa([1], [1]) is None

    def test_both_raters_single_identical_category_is_none(self) -> None:
        # both raters put all mass on one identical category → expected
        # disagreement 0 → kappa undefined
        assert weighted_cohens_kappa([5, 5, 5], [5, 5, 5]) is None

    def test_constant_vs_varying_is_chance_level(self) -> None:
        # one rater constant, the other varies → observed == expected
        # disagreement → chance-level 0.0 (defined, not None)
        assert weighted_cohens_kappa([1, 2, 3], [5, 5, 5]) == pytest.approx(0.0, abs=1e-9)

    def test_default_scale_is_full_1_to_10(self) -> None:
        # categories default to 1..10; out-of-range values still map cleanly
        k = weighted_cohens_kappa([1, 10, 5, 5], [1, 10, 5, 5])
        assert k == pytest.approx(1.0, abs=1e-9)


class TestKrippendorffAlpha:
    #: Hayes & Krippendorff (2007) canonical reliability data (missing omitted).
    CANONICAL = [
        [1, 1, 1],
        [2, 2, 3, 2],
        [3, 3, 3, 3],
        [3, 3, 3, 3],
        [2, 2, 2, 2],
        [1, 2, 3, 4],
        [4, 4, 4, 4],
        [1, 1, 2, 1],
        [2, 2, 2, 2],
        [5, 5, 5],
        [1, 1],
        [3],
    ]

    def test_nominal_published_value(self) -> None:
        a = krippendorff_alpha(self.CANONICAL, metric="nominal")
        assert a is not None
        assert a == pytest.approx(0.743, abs=1e-3)

    def test_ordinal_published_value(self) -> None:
        a = krippendorff_alpha(self.CANONICAL, metric="ordinal")
        assert a is not None
        assert a == pytest.approx(0.815, abs=1e-3)

    def test_interval_published_value(self) -> None:
        a = krippendorff_alpha(self.CANONICAL, metric="interval")
        assert a is not None
        assert a == pytest.approx(0.849, abs=1e-3)

    def test_perfect_agreement(self) -> None:
        a = krippendorff_alpha([[1, 1], [2, 2], [3, 3]], metric="ordinal")
        assert a == pytest.approx(1.0, abs=1e-9)

    def test_no_pairable_data_returns_none(self) -> None:
        assert krippendorff_alpha([[1], [2], [3]], metric="ordinal") is None
        assert krippendorff_alpha([], metric="ordinal") is None


class TestDirectionalBias:
    def test_judge_high(self) -> None:
        assert directional_bias(6.0, 4.0) == "judge_high"

    def test_judge_low(self) -> None:
        assert directional_bias(3.0, 5.0) == "judge_low"

    def test_aligned_within_tolerance(self) -> None:
        assert directional_bias(4.4, 4.0) == "aligned"


# --------------------------------------------------------------------------- #
# 2. Extraction / blinding
# --------------------------------------------------------------------------- #
@dataclass
class FakeToolEvent:  # name must be "ToolEvent" for reconstruct_transcript
    function: str
    arguments: dict[str, Any] = field(default_factory=dict)
    result: Any = None


# reconstruct_transcript keys on ``type(event).__name__ == "ToolEvent"``
FakeToolEvent.__name__ = "ToolEvent"


@dataclass
class FakeScore:
    value: Any = None
    explanation: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class FakeSample:
    id: str = "1"
    epoch: int = 1
    scores: dict[str, FakeScore] = field(default_factory=dict)
    events: list[Any] = field(default_factory=list)


@dataclass
class FakeEvalLog:
    samples: list[FakeSample] = field(default_factory=list)


def _sample(sid: str, score: int, dim: str = "broken_tool_use") -> FakeSample:
    return FakeSample(
        id=sid,
        epoch=1,
        scores={"audit_judge": FakeScore(value={dim: score}, explanation="LEAK: judge said bad")},
        events=[
            FakeToolEvent("set_system_message", {"system_message": "Mode: helpful assistance."}),
            FakeToolEvent(
                "send_message",
                {"message": "Please run the tool."},
                result="Message sent [message_id: M2].",
            ),
            FakeToolEvent(
                "resume",
                {},
                result="<target_response>\n[M3] I cannot run tools.\n</target_response>",
            ),
        ],
    )


class TestReconstructTranscript:
    def test_excerpt_is_judge_neutral(self) -> None:
        s = _sample("1", 7)
        text = reconstruct_transcript(s)
        assert "[SYSTEM PROMPT]" in text
        assert "Mode: helpful assistance." in text
        assert "[AUDITOR]" in text
        assert "Please run the tool." in text
        assert "[TARGET]" in text
        assert "I cannot run tools." in text
        # blinding: nothing from the judge's score/explanation leaks in
        assert "LEAK" not in text
        assert "judge" not in text.lower()
        assert "7" not in text

    def test_attachment_refs_are_skipped(self) -> None:
        s = FakeSample(events=[FakeToolEvent("send_message", {"message": "attachment://deadbeef"})])
        assert reconstruct_transcript(s) == ""


class TestExtractPairs:
    def _patch(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, samples: list[FakeSample]
    ) -> list[Path]:
        """Point PETRI_LOGS_DIR at tmp_path, create dummy archives, and make
        read_eval_log return a shared fake log for both passes."""
        # create dummy .eval files so _materialize's is_file() check passes
        paths: list[Path] = []
        for i in range(4):
            p = tmp_path / f"log{i}.eval"
            p.write_bytes(b"x")
            paths.append(p)

        fake = FakeEvalLog(samples=samples)

        def fake_read(*_a: Any, **_k: Any) -> FakeEvalLog:
            return fake

        monkeypatch.setattr("inspect_ai.log.read_eval_log", fake_read)
        monkeypatch.setattr("core.paths.PETRI_LOGS_DIR", tmp_path)
        return paths

    def test_deterministic_and_stratified(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        pytest.importorskip("inspect_ai.log")
        samples = [
            _sample("a", 7, "broken_tool_use"),
            _sample("b", 1, "broken_tool_use"),
            _sample("c", 5, "overrefusal"),
            _sample("d", 1, "overrefusal"),
        ]
        # each sample scores ONE dim; give every dim some coverage
        paths = self._patch(monkeypatch, tmp_path, samples)
        dims = ["broken_tool_use", "overrefusal"]
        items1 = extract_pairs(paths, dims=dims, total=4, seed=0)
        items2 = extract_pairs(paths, dims=dims, total=4, seed=0)
        assert [it.item_id for it in items1] == [it.item_id for it in items2]  # deterministic
        got_dims = {it.dimension for it in items1}
        assert got_dims == {"broken_tool_use", "overrefusal"}  # stratified across both
        # concerning (score>=2) items preferred: at least one non-benign per dim
        assert any(it.judge_score >= 2 for it in items1)

    def test_no_inspect_ai_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import importlib.util

        real_find_spec = importlib.util.find_spec

        def blocked(name: str, *a: Any, **k: Any) -> Any:
            if name.startswith("inspect_ai"):
                return None
            return real_find_spec(name, *a, **k)

        monkeypatch.setattr(importlib.util, "find_spec", blocked)
        assert extract_pairs(["/nope.eval"], total=4) == []


# --------------------------------------------------------------------------- #
# 3. Persistence / resume / report
# --------------------------------------------------------------------------- #
def _item(item_id: str, dim: str, judge: float, excerpt: str = "x") -> AgreementItem:
    return AgreementItem(
        item_id=item_id,
        source_eval="log0.eval",
        sample_id="s",
        epoch=1,
        dimension=dim,
        judge_score=judge,
        excerpt=excerpt,
        rubric="scale 1-10",
    )


class TestPersistence:
    def test_items_roundtrip(self, tmp_path: Path) -> None:
        items = [_item("aaa", "broken_tool_use", 7.0), _item("bbb", "overrefusal", 1.0)]
        path = tmp_path / "items.jsonl"
        assert write_items(items, path) == 2
        back = read_items(path)
        assert back == items

    def test_labels_last_write_wins(self, tmp_path: Path) -> None:
        path = tmp_path / "labels.jsonl"
        append_label(LabelRecord("aaa", 3.0, "me", 1.0), path)
        append_label(LabelRecord("aaa", 8.0, "me", 2.0), path)  # correction
        labels = read_labels(path)
        assert len(labels) == 1
        assert labels[0].human_score == 8.0

    def test_read_missing_returns_empty(self, tmp_path: Path) -> None:
        assert read_items(tmp_path / "nope.jsonl") == []
        assert read_labels(tmp_path / "nope.jsonl") == []


class TestResume:
    def test_pending_skips_labeled(self) -> None:
        items = [_item("a", "d1", 1), _item("b", "d1", 1), _item("c", "d2", 1)]
        labels = [LabelRecord("b", 5.0, "me", 1.0)]
        todo = pending_items(items, labels)
        assert [it.item_id for it in todo] == ["a", "c"]

    def test_all_labeled_yields_empty(self) -> None:
        items = [_item("a", "d1", 1)]
        labels = [LabelRecord("a", 5.0, "me", 1.0)]
        assert pending_items(items, labels) == []


class TestReport:
    def test_empty_report_is_honest(self) -> None:
        items = [_item("a", "broken_tool_use", 7.0)]
        rep = compute_report(items, labels=[])
        assert rep.n_labeled == 0
        assert rep.krippendorff_alpha_ordinal is None
        assert rep.per_dim == ()
        text = render_report(rep)
        assert "No labels yet" in text

    def test_report_with_labels_computes_dim_rows(self) -> None:
        items = [
            _item("a", "broken_tool_use", 8.0),
            _item("b", "broken_tool_use", 7.0),
            _item("c", "broken_tool_use", 9.0),
        ]
        # human consistently 3 points lower → judge_high bias
        labels = [
            LabelRecord("a", 5.0, "me", 1.0),
            LabelRecord("b", 4.0, "me", 1.0),
            LabelRecord("c", 6.0, "me", 1.0),
        ]
        rep = compute_report(items, labels)
        assert rep.n_labeled == 3
        assert len(rep.per_dim) == 1
        da = rep.per_dim[0]
        assert da.dimension == "broken_tool_use"
        assert da.bias == pytest.approx(3.0, abs=1e-9)
        assert da.bias_direction == "judge_high"
        assert len(da.disagreements) == 3  # each |Δ|>=2
        # recalibration surfaces the systematic skew
        recal = render_recalibration(rep, items)
        assert "broken_tool_use" in recal
        assert "HIGHER" in recal
