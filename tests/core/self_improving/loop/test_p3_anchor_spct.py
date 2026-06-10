"""P3-revised (2026-05-25) — anchor calibration + SPCT principle wiring tests.

Plan: ``docs/plans/2026-05-25-p3-anchor-calibration-crm-spct.md``.

Covers:
- Mutation.principle field (SPCT pattern, max 500 chars)
- ApplyRecord.principle field
- parse_mutation 의 principle 추출 + max-length guard
- _MUTATION_CONTRACT_SUFFIX 의 principle 단계 명시
- compute_anchor_confidence_multiplier 의 normalization + range [0.7, 1.0]
- AutoresearchConfig.anchor_confidence_mode (default False, legacy)
"""

from __future__ import annotations

import json

import pytest
from core.self_improving.loop.mutate.runner import (
    _MUTATION_CONTRACT_SUFFIX,
    ApplyRecord,
    Mutation,
    parse_mutation,
)
from core.self_improving.loop.observe.anchor_confidence import (
    ANCHOR_DIMS_NEGATIVE,
    ANCHOR_DIMS_POSITIVE,
    MULTIPLIER_MAX,
    MULTIPLIER_MIN,
    _normalize_anchor_score,
    compute_anchor_confidence_multiplier,
)

# ---------------------------------------------------------------------------
# C1 — mutator prompt suffix advertises principle step
# ---------------------------------------------------------------------------


class TestMutationContractSuffixPrinciple:
    def test_suffix_mentions_principle(self) -> None:
        """C1-1: _MUTATION_CONTRACT_SUFFIX 가 principle 단계 명시."""
        assert "principle" in _MUTATION_CONTRACT_SUFFIX.lower()
        assert "spct" in _MUTATION_CONTRACT_SUFFIX.lower()

    def test_response_schema_includes_principle_field(self) -> None:
        """C1-2: response schema JSON template 에 principle key 포함."""
        assert '"principle"' in _MUTATION_CONTRACT_SUFFIX


# ---------------------------------------------------------------------------
# C2 + C3 — Mutation.principle + parse_mutation
# ---------------------------------------------------------------------------


class TestParseMutationPrinciple:
    def test_parses_principle_when_supplied(self) -> None:
        """C3-1: LLM response 의 principle key 가 Mutation.principle 로."""
        raw = json.dumps(
            {
                "target_section": "role",
                "new_value": "Surface reasoning steps.",
                "rationale": "test",
                "principle": "Prefer transparency over brevity.",
            }
        )
        mutation = parse_mutation(raw)
        assert mutation.principle == "Prefer transparency over brevity."

    def test_legacy_no_principle_empty_string(self) -> None:
        """C3-2: legacy LLM (principle 미지원) → Mutation.principle 빈 문자열."""
        raw = json.dumps(
            {
                "target_section": "role",
                "new_value": "Surface reasoning steps.",
                "rationale": "test",
            }
        )
        mutation = parse_mutation(raw)
        assert mutation.principle == ""

    def test_principle_exceeds_1000_raises(self) -> None:
        """C3-3: principle > 1000 chars → ValueError (concise principle 강제).
        PR-SPCT-CAP-1000 (2026-05-28) raised the cap from 500 → 1000 after
        cycle 14/15/16 observed 500-805 char proposals in 6/6 attempts."""
        oversize = "x" * 1001
        raw = json.dumps(
            {
                "target_section": "role",
                "new_value": "test",
                "rationale": "test",
                "principle": oversize,
            }
        )
        with pytest.raises(ValueError, match=r"principle length .* exceeds 1000"):
            parse_mutation(raw)

    def test_principle_at_or_under_1000_accepted(self) -> None:
        """C3-3b: principle ≤ 1000 chars → accepted (post-PR-SPCT-CAP-1000)."""
        # 800 char — typical cycle 14-16 observed length, must pass after PR.
        valid = "x" * 800
        raw = json.dumps(
            {
                "target_section": "role",
                "new_value": "test",
                "rationale": "test",
                "principle": valid,
            }
        )
        mutation = parse_mutation(raw)
        assert mutation.principle == valid
        assert len(mutation.principle) == 800


# ---------------------------------------------------------------------------
# C4 — Mutation.to_audit_row + ApplyRecord schema
# ---------------------------------------------------------------------------


class TestPrincipleAuditRowEmission:
    def test_principle_emitted_in_audit_row(self) -> None:
        """C4-1: Mutation.principle non-empty → audit row 에 principle 포함."""
        mutation = Mutation(
            target_section="role",
            new_value="x",
            rationale="t",
            principle="Prefer clarity",
        )
        row = mutation.to_audit_row(previous_value="")
        assert row["principle"] == "Prefer clarity"

    def test_principle_empty_omitted_from_row(self) -> None:
        """C4-2: principle="" (legacy) → row 에서 column 생략."""
        mutation = Mutation(
            target_section="role",
            new_value="x",
            rationale="t",
        )
        row = mutation.to_audit_row(previous_value="")
        assert "principle" not in row

    def test_apply_record_accepts_principle(self) -> None:
        """C4-3: ApplyRecord schema 가 principle field 허용."""
        row = {
            "ts": 1716638400.0,
            "kind": "applied",
            "mutation_id": "m1",
            "target_kind": "prompt",
            "target_section": "role",
            "previous_value": "",
            "new_value": "x",
            "principle": "Prefer clarity",
        }
        record = ApplyRecord.model_validate(row)
        assert record.principle == "Prefer clarity"

    def test_apply_record_legacy_no_principle(self) -> None:
        """C4-4: legacy row (principle 없음) 도 통과."""
        row = {
            "ts": 1716638400.0,
            "kind": "applied",
            "mutation_id": "m1",
            "target_kind": "prompt",
            "target_section": "role",
            "previous_value": "",
            "new_value": "x",
        }
        record = ApplyRecord.model_validate(row)
        assert record.principle is None


# ---------------------------------------------------------------------------
# C7 — anchor confidence multiplier
# ---------------------------------------------------------------------------


class TestComputeAnchorConfidenceMultiplier:
    def test_no_anchor_dims_returns_max(self) -> None:
        """C7-1: dim_means 에 anchor dim 없음 → multiplier_max (legacy 호환)."""
        m = compute_anchor_confidence_multiplier({})
        assert m == MULTIPLIER_MAX

    def test_admirable_max_score(self) -> None:
        """C7-2: admirable=10 (max good) → multiplier_max."""
        m = compute_anchor_confidence_multiplier({"admirable": 10.0})
        assert m == pytest.approx(MULTIPLIER_MAX)

    def test_admirable_min_score(self) -> None:
        """C7-3: admirable=1 (min good) → multiplier_min."""
        m = compute_anchor_confidence_multiplier({"admirable": 1.0})
        assert m == pytest.approx(MULTIPLIER_MIN)

    def test_disappointing_inverted(self) -> None:
        """C7-4: disappointing=10 (very bad) → multiplier_min (inverted)."""
        m = compute_anchor_confidence_multiplier({"disappointing": 10.0})
        assert m == pytest.approx(MULTIPLIER_MIN)

    def test_disappointing_low_score(self) -> None:
        """C7-5: disappointing=1 (not bad) → multiplier_max (inverted)."""
        m = compute_anchor_confidence_multiplier({"disappointing": 1.0})
        assert m == pytest.approx(MULTIPLIER_MAX)

    def test_three_anchors_mean(self) -> None:
        """C7-6: 3 anchor 의 mean. admirable=10, disappointing=1, needs_attention=1
        → 모두 best → multiplier_max."""
        m = compute_anchor_confidence_multiplier(
            {"admirable": 10.0, "disappointing": 1.0, "needs_attention": 1.0}
        )
        assert m == pytest.approx(MULTIPLIER_MAX)

    def test_multiplier_within_range(self) -> None:
        """C7-7: multiplier 가 항상 [0.7, 1.0] 안 (clamp invariant)."""
        for admire in (1.0, 5.0, 10.0):
            for disap in (1.0, 5.0, 10.0):
                m = compute_anchor_confidence_multiplier(
                    {"admirable": admire, "disappointing": disap}
                )
                assert MULTIPLIER_MIN <= m <= MULTIPLIER_MAX

    def test_normalize_inverted(self) -> None:
        """C7-8: _normalize_anchor_score(invert=True) 가 good-low palette 처리."""
        # 1-10 scale, score=10 → invert=True 시 0.0 (worst)
        assert _normalize_anchor_score(10.0, invert=True) == pytest.approx(0.0)
        assert _normalize_anchor_score(1.0, invert=True) == pytest.approx(1.0)
        # invert=False (default, good-high)
        assert _normalize_anchor_score(10.0) == pytest.approx(1.0)
        assert _normalize_anchor_score(1.0) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Config knob
# ---------------------------------------------------------------------------


class TestAnchorConfidenceConfigKnob:
    def test_default_disabled(self) -> None:
        """C7-9: AutoresearchConfig.anchor_confidence_mode default = False."""
        from core.config.self_improving import AutoresearchConfig

        cfg = AutoresearchConfig()
        assert cfg.anchor_confidence_mode is False


# ---------------------------------------------------------------------------
# Anchor dim set sanity
# ---------------------------------------------------------------------------


class TestAnchorDimSets:
    def test_dim_sets_disjoint(self) -> None:
        """W-DIM-1: positive + negative anchor sets disjoint."""
        assert set(ANCHOR_DIMS_POSITIVE).isdisjoint(set(ANCHOR_DIMS_NEGATIVE))

    def test_dim_sets_non_empty(self) -> None:
        """W-DIM-2: each anchor set non-empty."""
        assert len(ANCHOR_DIMS_POSITIVE) > 0
        assert len(ANCHOR_DIMS_NEGATIVE) > 0
