"""LLMAdapter registry — mutable global lookup.

Mirrors paperclip ``server/src/adapters/registry.ts``:

- ``registerServerAdapter(adapter)`` → :func:`register_adapter`
- ``unregisterServerAdapter(type)`` → :func:`unregister_adapter`
- ``requireServerAdapter(type)`` → :func:`get_adapter`

Built-in adapters register at runtime bootstrap (``core/runtime.py``).
External plugins call :func:`register_adapter` from their entry point.

The registry is process-global and module-level (matches paperclip's mutable
Map shape). Test fixtures can call :func:`_reset_for_test` to clear state
between tests.

See ``docs/plans/2026-05-23-llm-adapter-abstraction.md`` Layer 4 for the
``resolve_for(provider, source)`` contract — it raises on ``source="auto"``
because the picker is responsible for collapsing ``auto`` to a concrete value
before the adapter is selected.
"""

from __future__ import annotations

import logging

from core.llm.adapters.base import CONCRETE_SOURCES, SOURCE_AUTO, LLMAdapter

log = logging.getLogger(__name__)


_REGISTRY: dict[str, LLMAdapter] = {}


class AdapterAlreadyRegisteredError(RuntimeError):
    """Raised by :func:`register_adapter` when a name collides without ``replace=True``."""


class AdapterNotFoundError(KeyError):
    """Raised by :func:`get_adapter` and :func:`resolve_for` on lookup miss."""


def register_adapter(adapter: LLMAdapter, *, replace: bool = False) -> None:
    """Add ``adapter`` to the global registry.

    Re-registration with ``replace=False`` raises :class:`AdapterAlreadyRegisteredError`
    — same shape as paperclip's registry which throws on duplicate type. Tests
    use ``replace=True`` to swap in a mock without first calling
    :func:`unregister_adapter`.
    """
    name = adapter.name
    if not name:
        raise ValueError("register_adapter: adapter.name is empty")
    if adapter.source not in CONCRETE_SOURCES:
        raise ValueError(
            f"register_adapter: adapter.source={adapter.source!r} is not a concrete value "
            f"(must be one of {sorted(CONCRETE_SOURCES)})"
        )
    if name in _REGISTRY and not replace:
        raise AdapterAlreadyRegisteredError(
            f"adapter {name!r} already registered; pass replace=True to override"
        )
    _REGISTRY[name] = adapter
    log.debug(
        "adapter registered: %s (provider=%s source=%s)",
        name,
        adapter.provider,
        adapter.source,
    )


def unregister_adapter(name: str) -> None:
    """Remove ``name`` from the registry. No-op when absent."""
    _REGISTRY.pop(name, None)


def get_adapter(name: str) -> LLMAdapter:
    """Look up a registered adapter by its canonical ``name``.

    Raises :class:`AdapterNotFoundError` when missing.
    """
    try:
        return _REGISTRY[name]
    except KeyError as exc:
        raise AdapterNotFoundError(
            f"adapter {name!r} not registered. Known: {sorted(_REGISTRY)}"
        ) from exc


def list_adapters() -> list[LLMAdapter]:
    """All currently registered adapters in registration order."""
    return list(_REGISTRY.values())


def resolve_for(provider: str, source: str) -> LLMAdapter:
    """Find the unique adapter matching ``(provider, source)``.

    ``source`` MUST be a concrete value (one of
    ``core.llm.adapters.base.CONCRETE_SOURCES``). The picker collapses
    ``"auto"`` → concrete before calling. Passing ``"auto"`` here raises
    :class:`ValueError` — failing loudly is the same anti-leak posture
    paperclip's registry takes on duplicate type registration.

    Raises :class:`AdapterNotFoundError` when no adapter matches.
    """
    if source == SOURCE_AUTO:
        raise ValueError(
            "resolve_for: source='auto' is a picker sentinel — collapse it to a "
            "concrete value (payg / subscription / adapter) before resolving."
        )
    if source not in CONCRETE_SOURCES:
        raise ValueError(
            f"resolve_for: source={source!r} is not a concrete value "
            f"(must be one of {sorted(CONCRETE_SOURCES)})"
        )
    candidates = [a for a in _REGISTRY.values() if a.provider == provider and a.source == source]
    if not candidates:
        known = [(a.provider, a.source) for a in _REGISTRY.values()]
        raise AdapterNotFoundError(
            f"no adapter for provider={provider!r} source={source!r}. Known pairs: {known}"
        )
    if len(candidates) > 1:
        raise RuntimeError(
            f"resolve_for: multiple adapters match provider={provider!r} source={source!r}: "
            f"{[a.name for a in candidates]} — registry invariant violated"
        )
    return candidates[0]


def bootstrap_builtins() -> None:
    """Register the 8 built-in adapters.

    Called from ``core/runtime.py`` during process bootstrap. Idempotent —
    re-registration is a no-op (logs at debug level). Mirrors paperclip's
    ``initializeBuiltinAdapters`` startup hook.

    v0.99.44 — Follow-up F adds the two GLM adapters (PAYG /api/paas/v4
    + Coding Plan /api/coding/paas/v4 subscription endpoint).
    """
    from core.llm.adapters.anthropic_oauth import AnthropicOAuthAdapter
    from core.llm.adapters.anthropic_payg import AnthropicPaygAdapter
    from core.llm.adapters.claude_cli import ClaudeCliAdapter
    from core.llm.adapters.codex_cli import CodexCliAdapter
    from core.llm.adapters.codex_oauth import CodexOAuthAdapter
    from core.llm.adapters.glm_coding_plan import GlmCodingPlanAdapter
    from core.llm.adapters.glm_payg import GlmPaygAdapter
    from core.llm.adapters.openai_payg import OpenAIPaygAdapter

    for adapter_cls in (
        AnthropicPaygAdapter,
        AnthropicOAuthAdapter,
        ClaudeCliAdapter,
        OpenAIPaygAdapter,
        CodexOAuthAdapter,
        CodexCliAdapter,
        GlmPaygAdapter,
        GlmCodingPlanAdapter,
    ):
        instance = adapter_cls()
        if instance.name in _REGISTRY:
            log.debug("bootstrap_builtins: %s already registered, skipping", instance.name)
            continue
        register_adapter(instance)


def _reset_for_test() -> None:
    """Clear the registry. Test-only — production callers must not invoke."""
    _REGISTRY.clear()


__all__ = [
    "AdapterAlreadyRegisteredError",
    "AdapterNotFoundError",
    "bootstrap_builtins",
    "get_adapter",
    "list_adapters",
    "register_adapter",
    "resolve_for",
    "unregister_adapter",
]
