"""Tests for P2 Multi-LLM Ensemble mode.

Covers:
- Single mode uses primary LLM only
- Cross mode alternates analysts between primary/secondary
- Fallback to primary when secondary unavailable
- model_provider tracking on AnalysisResult
- Agreement score calculation between models
"""

from __future__ import annotations

from typing import Any, TypeVar
from unittest.mock import patch

import pytest
from pydantic import BaseModel

from geode.config import Settings
from geode.infrastructure.ports.llm_port import (
    get_secondary_llm_json,
    get_secondary_llm_parsed,
    set_llm_callable,
)
from geode.nodes.analysts import (
    _PRIMARY_ANALYSTS,
    _SECONDARY_ANALYSTS,
    _run_analyst,
    _should_use_secondary,
)
from geode.state import AnalysisResult, GeodeState

T = TypeVar("T", bound=BaseModel)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_state(ip_name: str = "berserk", dry_run: bool = False) -> GeodeState:
    """Build a minimal GeodeState for analyst tests."""
    return GeodeState(
        ip_name=ip_name,
        ip_info={
            "ip_name": "Berserk",
            "media_type": "manga",
            "release_year": 1989,
            "studio": "Hakusensha",
            "genre": ["Dark Fantasy", "Action"],
            "synopsis": "A dark fantasy manga about Guts",
        },
        monolake={
            "dau_current": 0,
            "revenue_ltm": 0,
            "active_game_count": 0,
            "last_game_year": 2016,
        },
        signals={
            "youtube_views": 25_000_000,
            "reddit_subscribers": 520_000,
            "fan_art_yoy_pct": 65,
            "google_trends_index": 72,
            "twitter_mentions_monthly": 85_000,
        },
        dry_run=dry_run,
        verbose=False,
        analyses=[],
        errors=[],
    )


def _mock_primary_parsed(
    system: str,
    user: str,
    *,
    output_model: type[Any] = AnalysisResult,
    model: str | None = None,
    max_tokens: int = 4096,
    temperature: float = 0.3,
) -> Any:
    """Primary LLM mock — returns result with model_provider=None (set by _run_analyst)."""
    return AnalysisResult(
        analyst_type="game_mechanics",
        score=4.5,
        key_finding="Primary model finding",
        reasoning="Primary reasoning",
        evidence=["primary_evidence"],
        confidence=90.0,
    )


def _mock_secondary_parsed(
    system: str,
    user: str,
    *,
    output_model: type[Any] = AnalysisResult,
    model: str | None = None,
    max_tokens: int = 4096,
    temperature: float = 0.3,
) -> Any:
    """Secondary LLM mock — returns result with different score."""
    return AnalysisResult(
        analyst_type="player_experience",
        score=3.8,
        key_finding="Secondary model finding",
        reasoning="Secondary reasoning",
        evidence=["secondary_evidence"],
        confidence=85.0,
    )


def _mock_primary_json(
    system: str,
    user: str,
    *,
    model: str | None = None,
    max_tokens: int = 4096,
    temperature: float = 0.3,
) -> dict[str, Any]:
    return {
        "analyst_type": "game_mechanics",
        "score": 4.5,
        "key_finding": "Primary JSON finding",
        "reasoning": "Primary JSON reasoning",
        "evidence": ["primary_json"],
        "confidence": 90.0,
    }


def _mock_secondary_json(
    system: str,
    user: str,
    *,
    model: str | None = None,
    max_tokens: int = 4096,
    temperature: float = 0.3,
) -> dict[str, Any]:
    return {
        "analyst_type": "player_experience",
        "score": 3.8,
        "key_finding": "Secondary JSON finding",
        "reasoning": "Secondary JSON reasoning",
        "evidence": ["secondary_json"],
        "confidence": 85.0,
    }


def _mock_text(
    system: str,
    user: str,
    *,
    model: str | None = None,
    max_tokens: int = 4096,
    temperature: float = 0.3,
) -> str:
    return "mock text"


# ---------------------------------------------------------------------------
# Tests: ensemble_mode config
# ---------------------------------------------------------------------------


class TestEnsembleConfig:
    """Test ensemble_mode configuration."""

    def test_default_ensemble_mode_is_single(self) -> None:
        s = Settings(anthropic_api_key="test", openai_api_key="")
        assert s.ensemble_mode == "single"

    def test_ensemble_mode_cross(self) -> None:
        s = Settings(anthropic_api_key="test", openai_api_key="test", ensemble_mode="cross")
        assert s.ensemble_mode == "cross"


# ---------------------------------------------------------------------------
# Tests: _should_use_secondary routing
# ---------------------------------------------------------------------------


class TestShouldUseSecondary:
    """Test analyst-to-LLM routing logic."""

    def test_single_mode_never_secondary(self) -> None:
        with patch("geode.nodes.analysts.settings") as mock_settings:
            mock_settings.ensemble_mode = "single"
            for atype in ["game_mechanics", "player_experience", "growth_potential", "discovery"]:
                assert _should_use_secondary(atype) is False

    def test_cross_mode_primary_analysts(self) -> None:
        with patch("geode.nodes.analysts.settings") as mock_settings:
            mock_settings.ensemble_mode = "cross"
            for atype in _PRIMARY_ANALYSTS:
                assert _should_use_secondary(atype) is False

    def test_cross_mode_secondary_analysts(self) -> None:
        with patch("geode.nodes.analysts.settings") as mock_settings:
            mock_settings.ensemble_mode = "cross"
            for atype in _SECONDARY_ANALYSTS:
                assert _should_use_secondary(atype) is True


# ---------------------------------------------------------------------------
# Tests: single mode uses primary only
# ---------------------------------------------------------------------------


class TestSingleMode:
    """In single mode, all analysts use the primary LLM."""

    def test_single_mode_uses_primary(self) -> None:
        set_llm_callable(
            _mock_primary_json,
            _mock_text,
            parsed_fn=_mock_primary_parsed,
            secondary_json_fn=_mock_secondary_json,
            secondary_parsed_fn=_mock_secondary_parsed,
        )

        state = _make_state(dry_run=False)
        with patch("geode.nodes.analysts.settings") as mock_settings:
            mock_settings.ensemble_mode = "single"
            result = _run_analyst("game_mechanics", state)

        assert result.model_provider == "primary"
        assert result.key_finding == "Primary model finding"


# ---------------------------------------------------------------------------
# Tests: cross mode alternates correctly
# ---------------------------------------------------------------------------


class TestCrossMode:
    """In cross mode, analysts alternate between primary and secondary."""

    def test_cross_mode_primary_analyst(self) -> None:
        set_llm_callable(
            _mock_primary_json,
            _mock_text,
            parsed_fn=_mock_primary_parsed,
            secondary_json_fn=_mock_secondary_json,
            secondary_parsed_fn=_mock_secondary_parsed,
        )

        state = _make_state(dry_run=False)
        with patch("geode.nodes.analysts.settings") as mock_settings:
            mock_settings.ensemble_mode = "cross"
            result = _run_analyst("game_mechanics", state)

        assert result.model_provider == "primary"

    def test_cross_mode_secondary_analyst(self) -> None:
        set_llm_callable(
            _mock_primary_json,
            _mock_text,
            parsed_fn=_mock_primary_parsed,
            secondary_json_fn=_mock_secondary_json,
            secondary_parsed_fn=_mock_secondary_parsed,
        )

        state = _make_state(dry_run=False)
        with patch("geode.nodes.analysts.settings") as mock_settings:
            mock_settings.ensemble_mode = "cross"
            result = _run_analyst("player_experience", state)

        assert result.model_provider == "secondary"


# ---------------------------------------------------------------------------
# Tests: fallback to primary when secondary unavailable
# ---------------------------------------------------------------------------


class TestFallbackToPrimary:
    """When secondary is not configured, cross mode falls back to primary."""

    def test_fallback_when_no_secondary(self) -> None:
        # Only set primary — no secondary
        set_llm_callable(
            _mock_primary_json,
            _mock_text,
            parsed_fn=_mock_primary_parsed,
        )

        state = _make_state(dry_run=False)
        with patch("geode.nodes.analysts.settings") as mock_settings:
            mock_settings.ensemble_mode = "cross"
            result = _run_analyst("player_experience", state)

        # Should fall back to primary since secondary is None
        assert result.model_provider == "primary"
        assert result.key_finding == "Primary model finding"


# ---------------------------------------------------------------------------
# Tests: secondary contextvar getters
# ---------------------------------------------------------------------------


class TestSecondaryGetters:
    """Test secondary LLM contextvar access."""

    def test_secondary_json_none_when_not_set(self) -> None:
        set_llm_callable(_mock_primary_json, _mock_text)
        # secondary not set — getter should return None
        assert get_secondary_llm_json() is None

    def test_secondary_parsed_none_when_not_set(self) -> None:
        set_llm_callable(_mock_primary_json, _mock_text)
        assert get_secondary_llm_parsed() is None

    def test_secondary_json_set(self) -> None:
        set_llm_callable(
            _mock_primary_json,
            _mock_text,
            secondary_json_fn=_mock_secondary_json,
        )
        fn = get_secondary_llm_json()
        assert fn is not None
        result = fn("sys", "user")
        assert result["key_finding"] == "Secondary JSON finding"

    def test_secondary_parsed_set(self) -> None:
        set_llm_callable(
            _mock_primary_json,
            _mock_text,
            secondary_parsed_fn=_mock_secondary_parsed,
        )
        fn = get_secondary_llm_parsed()
        assert fn is not None
        result = fn("sys", "user", output_model=AnalysisResult)
        assert result.key_finding == "Secondary model finding"


# ---------------------------------------------------------------------------
# Tests: model_provider field on AnalysisResult
# ---------------------------------------------------------------------------


class TestModelProviderField:
    """Test that model_provider is properly tracked on AnalysisResult."""

    def test_default_model_provider_is_none(self) -> None:
        r = AnalysisResult(
            analyst_type="test",
            score=3.0,
            key_finding="test",
            reasoning="test",
        )
        assert r.model_provider is None

    def test_model_provider_set(self) -> None:
        r = AnalysisResult(
            analyst_type="test",
            score=3.0,
            key_finding="test",
            reasoning="test",
            model_provider="anthropic",
        )
        assert r.model_provider == "anthropic"

    def test_model_copy_preserves_provider(self) -> None:
        r = AnalysisResult(
            analyst_type="test",
            score=3.0,
            key_finding="test",
            reasoning="test",
            model_provider="openai",
        )
        r2 = r.model_copy(update={"score": 4.0})
        assert r2.model_provider == "openai"


# ---------------------------------------------------------------------------
# Tests: agreement score calculation
# ---------------------------------------------------------------------------


def compute_agreement_score(analyses: list[AnalysisResult]) -> float:
    """Compute inter-model agreement as 1 - normalized score variance.

    Returns a value in [0, 1] where 1.0 = perfect agreement.
    When all analyses come from the same model (single mode), returns 1.0.
    """
    providers = {a.model_provider for a in analyses if a.model_provider is not None}
    if len(providers) <= 1:
        return 1.0  # Single model — no cross-model disagreement

    # Group scores by provider
    by_provider: dict[str, list[float]] = {}
    for a in analyses:
        p = a.model_provider or "primary"
        by_provider.setdefault(p, []).append(a.score)

    # Compute mean score per provider
    means = [sum(scores) / len(scores) for scores in by_provider.values()]
    if len(means) < 2:
        return 1.0

    # Agreement = 1 - (max_diff / max_possible_diff)
    # Scores range [1, 5] so max possible diff = 4
    max_diff = max(means) - min(means)
    return max(0.0, 1.0 - max_diff / 4.0)


class TestAgreementScore:
    """Test inter-model agreement calculation."""

    def test_single_model_perfect_agreement(self) -> None:
        analyses = [
            AnalysisResult(
                analyst_type="game_mechanics",
                score=4.0,
                key_finding="f1",
                reasoning="r1",
                model_provider="primary",
            ),
            AnalysisResult(
                analyst_type="growth_potential",
                score=3.5,
                key_finding="f2",
                reasoning="r2",
                model_provider="primary",
            ),
        ]
        assert compute_agreement_score(analyses) == 1.0

    def test_cross_model_perfect_agreement(self) -> None:
        analyses = [
            AnalysisResult(
                analyst_type="game_mechanics",
                score=4.0,
                key_finding="f1",
                reasoning="r1",
                model_provider="primary",
            ),
            AnalysisResult(
                analyst_type="player_experience",
                score=4.0,
                key_finding="f2",
                reasoning="r2",
                model_provider="secondary",
            ),
        ]
        assert compute_agreement_score(analyses) == 1.0

    def test_cross_model_disagreement(self) -> None:
        analyses = [
            AnalysisResult(
                analyst_type="game_mechanics",
                score=5.0,
                key_finding="f1",
                reasoning="r1",
                model_provider="primary",
            ),
            AnalysisResult(
                analyst_type="player_experience",
                score=1.0,
                key_finding="f2",
                reasoning="r2",
                model_provider="secondary",
            ),
        ]
        # max_diff=4.0, agreement = 1 - 4/4 = 0.0
        assert compute_agreement_score(analyses) == pytest.approx(0.0)

    def test_cross_model_partial_agreement(self) -> None:
        analyses = [
            AnalysisResult(
                analyst_type="game_mechanics",
                score=4.0,
                key_finding="f1",
                reasoning="r1",
                model_provider="primary",
            ),
            AnalysisResult(
                analyst_type="growth_potential",
                score=4.0,
                key_finding="f2",
                reasoning="r2",
                model_provider="primary",
            ),
            AnalysisResult(
                analyst_type="player_experience",
                score=3.0,
                key_finding="f3",
                reasoning="r3",
                model_provider="secondary",
            ),
            AnalysisResult(
                analyst_type="discovery",
                score=3.0,
                key_finding="f4",
                reasoning="r4",
                model_provider="secondary",
            ),
        ]
        # Primary mean=4.0, Secondary mean=3.0, diff=1.0
        # agreement = 1 - 1/4 = 0.75
        assert compute_agreement_score(analyses) == pytest.approx(0.75)

    def test_no_provider_info(self) -> None:
        analyses = [
            AnalysisResult(
                analyst_type="game_mechanics",
                score=4.0,
                key_finding="f1",
                reasoning="r1",
            ),
        ]
        assert compute_agreement_score(analyses) == 1.0
