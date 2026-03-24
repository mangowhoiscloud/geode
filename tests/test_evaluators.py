"""Tests for evaluator node (dry-run mode + typed output models)."""

from __future__ import annotations

from core.domains.game_ip.nodes.evaluators import (
    _EVALUATOR_OUTPUT_MODELS,
    EVALUATOR_TYPES,
    CommunityMomentumAxes,
    HiddenValueAxes,
    ProspectJudgeAxes,
    QualityJudgeAxes,
    _CommunityMomentumOutput,
    _dry_run_result,
    _format_axes_schema,
    _HiddenValueOutput,
    _ProspectJudgeOutput,
    _QualityJudgeOutput,
)


class TestEvaluatorTypes:
    def test_three_evaluators(self):
        assert len(EVALUATOR_TYPES) == 3

    def test_expected_names(self):
        expected = {"quality_judge", "hidden_value", "community_momentum"}
        assert set(EVALUATOR_TYPES) == expected


class TestDryRunResult:
    def test_cowboy_bebop_quality(self):
        result = _dry_run_result("quality_judge", "Cowboy Bebop")
        assert result.evaluator_type == "quality_judge"
        assert result.composite_score == 76.56  # (32.5-8)/32*100
        assert "a_score" in result.axes
        assert len(result.axes) == 8  # Full 8-axis

    def test_cowboy_bebop_hidden(self):
        result = _dry_run_result("hidden_value", "Cowboy Bebop")
        assert result.axes["d_score"] == 5.0  # Extreme acquisition gap

    def test_berserk_quality_s_tier(self):
        result = _dry_run_result("quality_judge", "Berserk")
        assert result.composite_score == 75.31  # (32.1-8)/32*100
        assert len(result.axes) == 8

    def test_berserk_momentum(self):
        result = _dry_run_result("community_momentum", "Berserk")
        assert result.composite_score == 90.83  # (J+K+L-3)/12*100

    def test_ghost_quality_low(self):
        result = _dry_run_result("quality_judge", "Ghost in the Shell")
        assert result.composite_score == 61.56  # (27.7-8)/32*100

    def test_ghost_hidden_low(self):
        result = _dry_run_result("hidden_value", "Ghost in the Shell")
        assert result.composite_score == 25.0

    def test_all_ips_all_evaluators(self):
        ips = ["Cowboy Bebop", "Berserk", "Ghost in the Shell"]
        for ip in ips:
            for etype in EVALUATOR_TYPES:
                result = _dry_run_result(etype, ip)
                assert 0 <= result.composite_score <= 100
                for val in result.axes.values():
                    assert 1.0 <= val <= 5.0

    def test_unknown_ip_falls_back(self):
        result = _dry_run_result("quality_judge", "Unknown")
        assert result.composite_score == 76.56  # Cowboy Bebop default


class TestFormatAxesSchema:
    def test_quality_judge_schema(self):
        schema = _format_axes_schema("quality_judge")
        assert "a_score" in schema
        assert "float 1-5" in schema

    def test_hidden_value_schema(self):
        schema = _format_axes_schema("hidden_value")
        assert "d_score" in schema


class TestTypedAxesModels:
    """Typed axes models enforce required keys in structured output JSON schema."""

    def test_quality_judge_axes_requires_8_keys(self):
        axes = QualityJudgeAxes(
            a_score=4.0,
            b_score=3.5,
            c_score=4.0,
            b1_score=3.5,
            c1_score=3.8,
            c2_score=3.9,
            m_score=3.7,
            n_score=4.0,
        )
        assert axes.a_score == 4.0
        assert len(axes.model_dump()) == 8

    def test_quality_judge_axes_rejects_empty(self):
        import pytest

        with pytest.raises(Exception):
            QualityJudgeAxes()  # type: ignore[call-arg]

    def test_hidden_value_axes_requires_3_keys(self):
        axes = HiddenValueAxes(d_score=4.0, e_score=3.0, f_score=4.5)
        assert len(axes.model_dump()) == 3

    def test_community_momentum_axes_requires_3_keys(self):
        axes = CommunityMomentumAxes(j_score=4.0, k_score=3.5, l_score=3.8)
        assert len(axes.model_dump()) == 3

    def test_prospect_judge_axes_requires_9_keys(self):
        axes = ProspectJudgeAxes(
            g_score=4.0,
            h_score=3.5,
            i_score=4.0,
            o_score=3.8,
            p_score=3.5,
            q_score=3.0,
            r_score=4.5,
            s_score=3.5,
            t_score=3.0,
        )
        assert len(axes.model_dump()) == 9

    def test_axes_range_validation(self):
        import pytest

        with pytest.raises(Exception):
            QualityJudgeAxes(
                a_score=6.0,  # > 5 → invalid
                b_score=3.5,
                c_score=4.0,
                b1_score=3.5,
                c1_score=3.8,
                c2_score=3.9,
                m_score=3.7,
                n_score=4.0,
            )


class TestTypedOutputModels:
    """Typed output models map evaluator_type to correct Pydantic model."""

    def test_all_four_evaluator_types_mapped(self):
        assert len(_EVALUATOR_OUTPUT_MODELS) == 4
        assert "quality_judge" in _EVALUATOR_OUTPUT_MODELS
        assert "hidden_value" in _EVALUATOR_OUTPUT_MODELS
        assert "community_momentum" in _EVALUATOR_OUTPUT_MODELS
        assert "prospect_judge" in _EVALUATOR_OUTPUT_MODELS

    def test_quality_judge_output_model(self):
        result = _QualityJudgeOutput(
            evaluator_type="quality_judge",
            axes=QualityJudgeAxes(
                a_score=4.0,
                b_score=3.5,
                c_score=4.0,
                b1_score=3.5,
                c1_score=3.8,
                c2_score=3.9,
                m_score=3.7,
                n_score=4.0,
            ),
            composite_score=72.0,
            rationale="Strong core mechanics.",
        )
        axes_dict = result.axes.model_dump()
        assert len(axes_dict) == 8
        assert all(1.0 <= v <= 5.0 for v in axes_dict.values())

    def test_hidden_value_output_model(self):
        result = _HiddenValueOutput(
            evaluator_type="hidden_value",
            axes=HiddenValueAxes(d_score=5.0, e_score=2.0, f_score=4.0),
            composite_score=50.0,
            rationale="Acquisition gap.",
        )
        assert result.axes.d_score == 5.0

    def test_community_momentum_output_model(self):
        result = _CommunityMomentumOutput(
            evaluator_type="community_momentum",
            axes=CommunityMomentumAxes(j_score=4.3, k_score=4.1, l_score=3.9),
            composite_score=77.5,
            rationale="Active community.",
        )
        assert result.axes.j_score == 4.3

    def test_prospect_judge_output_model(self):
        result = _ProspectJudgeOutput(
            evaluator_type="prospect_judge",
            axes=ProspectJudgeAxes(
                g_score=4.5,
                h_score=3.8,
                i_score=4.2,
                o_score=4.0,
                p_score=3.5,
                q_score=3.0,
                r_score=4.5,
                s_score=3.5,
                t_score=3.5,
            ),
            composite_score=70.83,
            rationale="Strong world-building.",
        )
        assert len(result.axes.model_dump()) == 9

    def test_json_schema_has_required_fields(self):
        """Verify the JSON schema generated for structured output has required fields."""
        schema = _QualityJudgeOutput.model_json_schema()
        axes_ref = schema["$defs"]["QualityJudgeAxes"]
        assert "a_score" in axes_ref["properties"]
        assert "required" in axes_ref
        assert "a_score" in axes_ref["required"]
        assert len(axes_ref["required"]) == 8
