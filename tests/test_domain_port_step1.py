"""Step 1 of domain-free-core refactor: tests.

See docs/architecture/domain-free-core-audit.md (§6 step 1).

Verifies:
1. axes.py defusing — module-level constants populate from plugin (if present),
   default to empty dicts otherwise (REODE-fork compatibility).
2. Loader 2-pass discovery — empty `_BUILTIN_DOMAINS` is recovered by
   convention-fallback `import plugins.<name>` triggering self-registration.
3. New v2 method on DomainPort: `get_prospect_evaluator_axes()`.
"""

from __future__ import annotations

import sys

import pytest


def test_loader_loads_game_ip() -> None:
    """Game IP plugin loads via either pre-registration or convention fallback."""
    from core.domains.loader import load_domain_adapter

    adapter = load_domain_adapter("game_ip")
    assert adapter.name == "game_ip"
    assert adapter.version


def test_loader_unknown_domain_raises_value_error() -> None:
    """Unknown domain name surfaces a clear ValueError after both lookup passes."""
    from core.domains.loader import load_domain_adapter

    with pytest.raises(ValueError, match="Unknown domain: 'definitely_not_a_real_domain'"):
        load_domain_adapter("definitely_not_a_real_domain")


def test_loader_2pass_self_registration() -> None:
    """If `_BUILTIN_DOMAINS` is missing the entry, loader imports `plugins.<name>`,
    which triggers the plugin's `__init__.py` to call `register_domain(...)`,
    after which the registry has the entry."""
    from core.domains import loader

    # Simulate fresh state by clearing the registry entry. The plugin module
    # itself is still cached in sys.modules, so simulate reload by also
    # dropping that cache so the convention-fallback re-imports it.
    saved = loader._BUILTIN_DOMAINS.pop("game_ip", None)
    saved_module = sys.modules.pop("plugins.game_ip", None)
    try:
        adapter = loader.load_domain_adapter("game_ip")
        assert adapter.name == "game_ip"
        # Plugin self-registration should have re-populated the registry.
        assert "game_ip" in loader._BUILTIN_DOMAINS
    finally:
        # Restore whatever state existed before the test.
        if saved is not None:
            loader._BUILTIN_DOMAINS["game_ip"] = saved
        if saved_module is not None:
            sys.modules["plugins.game_ip"] = saved_module


def test_get_prospect_evaluator_axes_returns_axes() -> None:
    """GameIPDomain exposes the v2 `get_prospect_evaluator_axes` method,
    returning a non-empty mapping (game_ip has prospect_evaluator_axes in YAML)."""
    from plugins.game_ip.adapter import GameIPDomain

    domain = GameIPDomain()
    axes = domain.get_prospect_evaluator_axes()

    assert isinstance(axes, dict)
    assert len(axes) > 0  # game_ip ships with prospect axes
    # Each entry is itself a dict spec
    for spec in axes.values():
        assert isinstance(spec, dict)


def test_axes_module_constants_populated_with_plugin() -> None:
    """When plugins.game_ip is installed, core/llm/prompts/axes.py re-exports
    populated constants (current GEODE behavior preserved)."""
    from core.llm.prompts.axes import (
        ANALYST_SPECIFIC,
        AXES_VERSIONS,
        EVALUATOR_AXES,
        PROSPECT_EVALUATOR_AXES,
        VALID_AXES_MAP,
    )

    assert isinstance(ANALYST_SPECIFIC, dict) and len(ANALYST_SPECIFIC) > 0
    assert isinstance(EVALUATOR_AXES, dict) and len(EVALUATOR_AXES) > 0
    assert isinstance(PROSPECT_EVALUATOR_AXES, dict) and len(PROSPECT_EVALUATOR_AXES) > 0
    assert isinstance(VALID_AXES_MAP, dict) and len(VALID_AXES_MAP) > 0
    assert set(AXES_VERSIONS.keys()) == {
        "EVALUATOR_AXES",
        "PROSPECT_EVALUATOR_AXES",
        "ANALYST_SPECIFIC",
    }


def test_axes_data_matches_plugin_source() -> None:
    """`core.llm.prompts.axes` constants are the same objects (or equal data)
    as `plugins.game_ip.axes` — proves the data moved without duplication."""
    from core.llm.prompts.axes import EVALUATOR_AXES as CORE_EVAL
    from plugins.game_ip.axes import EVALUATOR_AXES as PLUGIN_EVAL

    assert CORE_EVAL == PLUGIN_EVAL
    # Same identity confirms the import re-export, not a deep copy
    assert CORE_EVAL is PLUGIN_EVAL
