"""Regression pin for ``AgenticLoop``'s adapter-name + category dual lookup.

Before PR-AGENTIC-LOOP-ADAPTER-NAME-LOOKUP (2026-05-27), the loop's
adapter resolution was a single ``resolve_for(provider, source)`` call
that required ``source`` to be one of the three concrete categories
(``payg`` / ``subscription`` / ``adapter``). Callers that passed an
actual registered adapter name (``codex-oauth`` / ``claude-cli`` /
``openai-payg`` / ...) hit ``ValueError: source not concrete`` and the
exception was swallowed upstream — the audit subprocess silently fell
back to PAYG and emitted ``OPENAI_API_KEY not set`` for every target
call, masquerading as a credential problem.

The fix tries ``get_adapter(name)`` first (registry-name lookup) and
falls through to ``resolve_for(provider, source)`` (category lookup)
only when the direct lookup misses. The two-path resolution lets
callers pass either form interchangeably, which is what the audit
subprocess needs (``get_binding("target")`` returns adapter-name)
while preserving the legacy category-axis path for callers that
have not migrated.
"""

from __future__ import annotations

from pathlib import Path

import pytest


def test_agentic_loop_resolves_via_get_adapter_first() -> None:
    """Source-level pin: AgenticLoop tries ``get_adapter`` before ``resolve_for``.

    Greps ``core/agent/loop/agent_loop.py`` for the dual-lookup pattern
    so a future refactor that drops the adapter-name path fails this
    test before the audit-subprocess fake-success failure re-emerges.
    """
    loop_module = Path(__file__).resolve().parents[1] / "core" / "agent" / "loop" / "agent_loop.py"
    source = loop_module.read_text(encoding="utf-8")
    assert "get_adapter(self._source)" in source, (
        "agent_loop.py no longer calls get_adapter(self._source). The "
        "audit subprocess will silently fall back to PAYG when the "
        "operator's source is an adapter name (e.g. 'codex-oauth')."
    )
    assert "AdapterNotFoundError" in source, (
        "agent_loop.py does not handle AdapterNotFoundError; the "
        "category-axis fallback (resolve_for) is unreachable."
    )


@pytest.mark.parametrize(
    "adapter_name",
    [
        # Subscription OAuth — adapter names registered by
        # bootstrap_builtins. ``get_adapter`` resolves them directly;
        # ``resolve_for("openai", "codex-oauth")`` would raise because
        # codex-oauth is an adapter name, not a category.
        "codex-oauth",
        "claude-cli",
        "anthropic-oauth",
        # Local-CLI subprocess wrapper.
        "codex-cli",
        # PAYG adapters by name (rather than category) — also
        # resolvable via ``get_adapter`` so callers don't need to know
        # which form the source string takes.
        "openai-payg",
        "anthropic-payg",
        "glm-payg",
        "glm-coding-plan",
    ],
)
def test_agentic_loop_constructs_with_adapter_name_source(adapter_name: str) -> None:
    """All eight registered adapter names resolve through ``get_adapter``.

    The audit subprocess calls
    ``AgenticLoop(..., source=binding.source)`` where ``binding.source``
    is the registered adapter name (after the Petri-surface alias
    translation in geode_target.py). Each of the eight builtins must
    resolve cleanly — a regression that drops one (e.g. a refactor
    that removes ``codex-cli`` from the bootstrap list) surfaces here
    per-adapter rather than as a remote audit-subprocess WARNING.
    """
    from core.llm.adapters.registry import (
        _reset_for_test,
        bootstrap_builtins,
        get_adapter,
    )

    try:
        _reset_for_test()
        bootstrap_builtins()
        adapter = get_adapter(adapter_name)
        assert adapter is not None, (
            f"get_adapter({adapter_name!r}) returned None after bootstrap. "
            f"The audit subprocess will fall back to PAYG when the "
            f"operator configures this source."
        )
        assert adapter.name == adapter_name, (
            f"get_adapter({adapter_name!r}) returned adapter with name "
            f"{adapter.name!r} — namespace mismatch."
        )
    finally:
        _reset_for_test()
        bootstrap_builtins()


def test_geode_target_translates_petri_surface_alias() -> None:
    """Source-level pin: ``geode_target`` maps ``openai-codex`` → ``codex-oauth``.

    Petri's ``get_binding("target")`` returns the Petri-surface name
    (``openai-codex``) but the GEODE adapter registry uses
    ``codex-oauth``. Without the translation, AgenticLoop's
    ``get_adapter("openai-codex")`` misses (the name was never
    registered) and the fallback ``resolve_for`` raises on the
    non-concrete source — the audit then falls back to PAYG.
    """
    target_module = (
        Path(__file__).resolve().parents[1]
        / "plugins"
        / "petri_audit"
        / "targets"
        / "geode_target.py"
    )
    source = target_module.read_text(encoding="utf-8")
    assert '"openai-codex": "codex-oauth"' in source, (
        "geode_target.py no longer translates the Petri-surface "
        "'openai-codex' alias to the GEODE registry name "
        "'codex-oauth'. The audit subprocess will silently fall back "
        "to PAYG when the operator pins openai-codex as the source."
    )
    assert '"api_key": "payg"' in source, (
        "geode_target.py no longer translates the Petri-surface "
        "'api_key' alias to the GEODE registry category 'payg'. PAYG "
        "operators (anthropic/openai/glm) will fail because Petri's "
        "concrete PAYG source name is 'api_key' but the GEODE registry "
        "uses provider-specific '{provider}-payg' adapters; the 'payg' "
        "category lets resolve_for pick the right one."
    )


def test_petri_to_registry_map_covers_every_petri_concrete_source() -> None:
    """Map coverage — every Petri concrete source resolves on the GEODE side.

    ``plugins/petri_audit/petri.plugin.toml`` declares the concrete
    sources per provider:

    - anthropic: ``claude-cli``, ``api_key``
    - openai: ``openai-codex``, ``api_key``
    - zhipuai: ``api_key``

    Petri concrete sources that are NOT identical to a registered
    GEODE adapter name MUST appear in ``_PETRI_TO_REGISTRY`` so the
    AgenticLoop lookup (``get_adapter`` → ``resolve_for`` fallback)
    succeeds for every operator configuration.
    """
    from core.llm.adapters.registry import (
        _reset_for_test,
        bootstrap_builtins,
        list_adapters,
    )

    try:
        _reset_for_test()
        bootstrap_builtins()
        registry_names = {a.name for a in list_adapters()}
    finally:
        _reset_for_test()
        bootstrap_builtins()

    # Concrete sources Petri may emit through ``get_binding``.
    petri_concrete_sources = {"claude-cli", "openai-codex", "codex-cli", "api_key"}
    # Categorical fallback values resolve_for accepts.
    categories = {"payg", "subscription", "adapter"}

    target_module = (
        Path(__file__).resolve().parents[1]
        / "plugins"
        / "petri_audit"
        / "targets"
        / "geode_target.py"
    )
    geode_target_src = target_module.read_text(encoding="utf-8")

    # Build the actual translation map by importing the module's
    # source and evaluating the dict literal. This guards against
    # ``"api_key": "subscription"`` (a wrong mapping that would
    # category-resolve but to the wrong adapter category) — the
    # earlier presence check only verified the key existed.
    import re

    match = re.search(
        r"_PETRI_TO_REGISTRY\s*=\s*\{([^}]+)\}",
        geode_target_src,
        re.DOTALL,
    )
    assert match, "_PETRI_TO_REGISTRY literal not found in geode_target.py"
    translation_map: dict[str, str] = {}
    for entry in re.finditer(r'"([^"]+)"\s*:\s*"([^"]+)"', match.group(1)):
        translation_map[entry.group(1)] = entry.group(2)

    def _value_resolves_for_some_provider(value: str) -> bool:
        # Direct registry hit (e.g. ``codex-oauth``).
        if value in registry_names:
            return True
        # Category fallback (e.g. ``payg``). ``resolve_for`` raises if
        # the category is wrong for every provider, so try each one.
        if value not in categories:
            return False
        from core.llm.adapters.registry import (
            AdapterNotFoundError,
            resolve_for,
        )

        for provider in ("openai", "anthropic", "glm"):
            try:
                resolve_for(provider, value)
                return True
            except (AdapterNotFoundError, ValueError):
                continue
        return False

    for petri_source in petri_concrete_sources:
        # Direct registry hit?
        if petri_source in registry_names:
            continue
        # Otherwise the translation entry must exist AND the translated
        # value must actually resolve (rejects ``"api_key": "subscription"``
        # which would be a syntactically valid but semantically wrong
        # mapping that category-resolves to the wrong adapter pool).
        translated = translation_map.get(petri_source)
        assert translated is not None, (
            f"Petri concrete source {petri_source!r} has no "
            f"_PETRI_TO_REGISTRY entry. Registered: {sorted(registry_names)}; "
            f"categories: {sorted(categories)}."
        )
        try:
            _reset_for_test()
            bootstrap_builtins()
            assert _value_resolves_for_some_provider(translated), (
                f"_PETRI_TO_REGISTRY[{petri_source!r}] = {translated!r} "
                f"does not resolve to any registered adapter nor to a "
                f"valid category that selects one. The mapping is "
                f"syntactically present but semantically wrong."
            )
        finally:
            _reset_for_test()
            bootstrap_builtins()


def test_negative_openai_codex_without_translation_misses_registry() -> None:
    """Without the geode_target translation, ``openai-codex`` would miss.

    Pins the *necessity* of the translation: if a future refactor drops
    ``_PETRI_TO_REGISTRY`` and passes the raw Petri-surface alias to
    AgenticLoop, ``get_adapter`` returns ``AdapterNotFoundError`` (the
    name is unregistered) and the fallback ``resolve_for`` raises
    ``ValueError`` (the name is not a category) — the audit subprocess
    silently falls back to PAYG.
    """
    from core.llm.adapters.registry import (
        AdapterNotFoundError,
        _reset_for_test,
        bootstrap_builtins,
        get_adapter,
        resolve_for,
    )

    try:
        _reset_for_test()
        bootstrap_builtins()
        # Direct registry lookup of the raw Petri-surface alias misses
        # because the registered name is ``codex-oauth``.
        with pytest.raises(AdapterNotFoundError):
            get_adapter("openai-codex")
        # Category fallback also misses — ``openai-codex`` is not a
        # category. ``resolve_for`` raises ValueError on this.
        with pytest.raises(ValueError, match="not a concrete value"):
            resolve_for("openai", "openai-codex")
    finally:
        _reset_for_test()
        bootstrap_builtins()


def test_category_axis_fallback_still_resolves_payg() -> None:
    """Legacy callers passing ``source="payg"`` (category) still resolve.

    The fallback ``resolve_for(provider, source)`` must remain
    reachable for the AgenticLoop sites that have not migrated (e.g.
    sub-agent worker, server-side loop, CLI bootstrap). A regression
    that drops the except branch would break every non-audit caller.
    """
    from core.llm.adapters.registry import (
        _reset_for_test,
        bootstrap_builtins,
        resolve_for,
    )

    try:
        _reset_for_test()
        bootstrap_builtins()
        # Each provider has a payg adapter; verify the category
        # resolution still finds it. This is what AgenticLoop falls
        # back to when source="payg" (the existing default behaviour).
        for provider in ("openai", "anthropic", "glm"):
            adapter = resolve_for(provider, "payg")
            assert adapter.source == "payg", (
                f"resolve_for({provider!r}, 'payg') returned adapter "
                f"with source={adapter.source!r} — category lookup broke."
            )
    finally:
        _reset_for_test()
        bootstrap_builtins()
