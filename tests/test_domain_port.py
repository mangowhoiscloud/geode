"""Tests for DomainPort Protocol and GameIPDomain adapter."""

from __future__ import annotations

import pytest
from core.domains.game_ip.adapter import GameIPDomain
from core.domains.loader import list_domains, load_domain_adapter
from core.domains.port import (
    DomainPort,
    get_domain,
    get_domain_or_none,
    set_domain,
)

# ---------------------------------------------------------------------------
# DomainPort Protocol compliance
# ---------------------------------------------------------------------------


class TestDomainPortProtocol:
    def test_game_ip_is_domain_port(self):
        adapter = GameIPDomain()
        assert isinstance(adapter, DomainPort)

    def test_identity_properties(self):
        adapter = GameIPDomain()
        assert adapter.name == "game_ip"
        assert adapter.version == "1.0.0"
        assert len(adapter.description) > 0


# ---------------------------------------------------------------------------
# GameIPDomain — Analyst Configuration
# ---------------------------------------------------------------------------


class TestGameIPAnalysts:
    def test_analyst_types(self):
        adapter = GameIPDomain()
        types = adapter.get_analyst_types()
        assert isinstance(types, list)
        assert len(types) == 4
        assert "game_mechanics" in types
        assert "player_experience" in types
        assert "growth_potential" in types
        assert "discovery" in types

    def test_analyst_specific(self):
        adapter = GameIPDomain()
        specific = adapter.get_analyst_specific()
        assert isinstance(specific, dict)
        for t in adapter.get_analyst_types():
            assert t in specific
            assert len(specific[t]) > 0


# ---------------------------------------------------------------------------
# GameIPDomain — Evaluator Configuration
# ---------------------------------------------------------------------------


class TestGameIPEvaluators:
    def test_evaluator_types(self):
        adapter = GameIPDomain()
        types = adapter.get_evaluator_types()
        assert isinstance(types, list)
        assert len(types) == 3
        assert "quality_judge" in types
        assert "hidden_value" in types
        assert "community_momentum" in types

    def test_evaluator_axes(self):
        adapter = GameIPDomain()
        axes = adapter.get_evaluator_axes()
        for eval_type in adapter.get_evaluator_types():
            assert eval_type in axes
            assert "axes" in axes[eval_type]
            assert len(axes[eval_type]["axes"]) > 0

    def test_valid_axes_map(self):
        adapter = GameIPDomain()
        axes_map = adapter.get_valid_axes_map()
        assert "quality_judge" in axes_map
        assert "hidden_value" in axes_map
        assert "community_momentum" in axes_map
        for _eval_type, keys in axes_map.items():
            assert isinstance(keys, set)
            assert len(keys) > 0


# ---------------------------------------------------------------------------
# GameIPDomain — Scoring
# ---------------------------------------------------------------------------


class TestGameIPScoring:
    def test_scoring_weights(self):
        adapter = GameIPDomain()
        weights = adapter.get_scoring_weights()
        assert isinstance(weights, dict)
        assert len(weights) == 6
        total = sum(weights.values())
        assert abs(total - 1.0) < 1e-10, f"Weights must sum to 1.0, got {total}"

    def test_confidence_multiplier_params(self):
        adapter = GameIPDomain()
        base, scale = adapter.get_confidence_multiplier_params()
        assert base == 0.7
        assert scale == 0.3

    def test_tier_thresholds(self):
        adapter = GameIPDomain()
        thresholds = adapter.get_tier_thresholds()
        assert thresholds == [(80.0, "S"), (60.0, "A"), (40.0, "B")]
        assert adapter.get_tier_fallback() == "C"


# ---------------------------------------------------------------------------
# GameIPDomain — Classification
# ---------------------------------------------------------------------------


class TestGameIPClassification:
    def test_cause_values(self):
        adapter = GameIPDomain()
        causes = adapter.get_cause_values()
        assert len(causes) == 6
        assert "undermarketed" in causes
        assert "discovery_failure" in causes

    def test_action_values(self):
        adapter = GameIPDomain()
        actions = adapter.get_action_values()
        assert len(actions) == 5
        assert "marketing_boost" in actions

    def test_cause_to_action_mapping(self):
        adapter = GameIPDomain()
        mapping = adapter.get_cause_to_action()
        for cause in adapter.get_cause_values():
            assert cause in mapping
            assert mapping[cause] in adapter.get_action_values()

    def test_cause_descriptions(self):
        adapter = GameIPDomain()
        descs = adapter.get_cause_descriptions()
        for cause in adapter.get_cause_values():
            assert cause in descs
            assert len(descs[cause]) > 0

    def test_action_descriptions(self):
        adapter = GameIPDomain()
        descs = adapter.get_action_descriptions()
        for action in adapter.get_action_values():
            assert action in descs
            assert len(descs[action]) > 0


# ---------------------------------------------------------------------------
# GameIPDomain — Fixtures
# ---------------------------------------------------------------------------


class TestGameIPFixtures:
    def test_list_fixtures(self):
        adapter = GameIPDomain()
        fixtures = adapter.list_fixtures()
        assert isinstance(fixtures, list)
        assert len(fixtures) >= 3

    def test_fixture_path(self):
        adapter = GameIPDomain()
        path = adapter.get_fixture_path()
        assert path is not None


# ---------------------------------------------------------------------------
# contextvars injection
# ---------------------------------------------------------------------------


class TestDomainContextVars:
    def test_set_and_get(self):
        adapter = GameIPDomain()
        set_domain(adapter)
        retrieved = get_domain()
        assert retrieved is adapter
        assert retrieved.name == "game_ip"

    def test_get_domain_or_none(self):
        result = get_domain_or_none()
        assert result is None or isinstance(result, DomainPort)


# ---------------------------------------------------------------------------
# Domain loader
# ---------------------------------------------------------------------------


class TestDomainLoader:
    def test_list_domains(self):
        domains = list_domains()
        assert "game_ip" in domains

    def test_load_game_ip(self):
        adapter = load_domain_adapter("game_ip")
        assert isinstance(adapter, DomainPort)
        assert adapter.name == "game_ip"

    def test_load_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown domain"):
            load_domain_adapter("nonexistent_domain")
