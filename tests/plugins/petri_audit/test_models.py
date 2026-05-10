"""Model-id mapping tests for petri_audit (no [audit] extra needed)."""

from __future__ import annotations

import pytest
from plugins.petri_audit.models import (
    AuditModelMappingError,
    list_audit_models,
    to_inspect_model,
    to_inspect_target,
)

# ---------------------------------------------------------------------------
# to_inspect_model — auditor / judge alias
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "geode_id, expected",
    [
        ("claude-opus-4-7", "anthropic/claude-opus-4-7"),
        ("claude-sonnet-4-6", "anthropic/claude-sonnet-4-6"),
        ("claude-haiku-4-5-20251001", "anthropic/claude-haiku-4-5-20251001"),
        ("gpt-5.5", "openai/gpt-5.5"),
        ("gpt-5.4-mini", "openai/gpt-5.4-mini"),
        ("o3", "openai/o3"),
        ("o4-mini", "openai/o4-mini"),
        ("glm-5", "geode/glm-5"),
        ("glm-4.7-flash", "geode/glm-4.7-flash"),
    ],
)
def test_to_inspect_model_known_families(geode_id: str, expected: str) -> None:
    assert to_inspect_model(geode_id) == expected


def test_to_inspect_model_raw_passthrough() -> None:
    raw = "openai-api/glm/glm-5.1"
    assert to_inspect_model(raw) == raw
    assert to_inspect_model("anthropic/claude-haiku-4-5-20251001") == (
        "anthropic/claude-haiku-4-5-20251001"
    )


def test_to_inspect_model_unknown_raises() -> None:
    with pytest.raises(AuditModelMappingError, match="Unknown model id"):
        to_inspect_model("mystery-model")


def test_to_inspect_model_empty_raises() -> None:
    with pytest.raises(AuditModelMappingError, match="Empty model id"):
        to_inspect_model("")


# ---------------------------------------------------------------------------
# to_inspect_target — always geode/<base>
# ---------------------------------------------------------------------------


def test_to_inspect_target_auto_prefixes() -> None:
    assert to_inspect_target("claude-opus-4-7") == "geode/claude-opus-4-7"
    assert to_inspect_target("gpt-5.5") == "geode/gpt-5.5"
    assert to_inspect_target("glm-5") == "geode/glm-5"


def test_to_inspect_target_raw_passthrough() -> None:
    assert to_inspect_target("geode/claude-opus-4-7") == "geode/claude-opus-4-7"
    assert to_inspect_target("anthropic/claude-opus-4-7") == "anthropic/claude-opus-4-7"


def test_to_inspect_target_none_returns_default_sentinel() -> None:
    """N6-followup: None / empty → ``geode/default`` sentinel."""
    assert to_inspect_target(None) == "geode/default"
    assert to_inspect_target("") == "geode/default"


# ---------------------------------------------------------------------------
# list_audit_models — catalog enumeration
# ---------------------------------------------------------------------------


def test_list_audit_models_includes_each_family() -> None:
    pairs = list_audit_models()
    inspect_ids = {inspect for _, inspect in pairs}
    assert any(i.startswith("anthropic/claude-") for i in inspect_ids)
    assert any(i.startswith("openai/gpt-") for i in inspect_ids)
    assert any(i.startswith("geode/glm-") for i in inspect_ids)


def test_list_audit_models_pairs_with_pricing_keys() -> None:
    """Every pair's geode_id is a MODEL_PRICING key (catalog SOT)."""
    from core.llm.token_tracker import MODEL_PRICING

    for geode_id, _ in list_audit_models():
        assert geode_id in MODEL_PRICING
