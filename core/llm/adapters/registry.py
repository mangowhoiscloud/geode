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

from core.llm.adapters.base import (
    CONCRETE_SOURCES,
    SOURCE_AUTO,
    EnvironmentReport,
    LLMAdapter,
)

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


def adapter_health(name: str) -> EnvironmentReport:
    """Probe ``adapter.test_environment`` by registry name.

    Step I.c (2026-05-23) — thin one-call accessor over the existing
    :meth:`LLMAdapter.test_environment` probe so picker UIs / readiness
    audits / external consumers (petri_audit's ``credential_source``
    cascade, the ``/auth`` slash, the routing-recovery loop) don't have
    to ``get_adapter(name).test_environment()`` themselves and don't
    need to know which exception ``get_adapter`` raises on a typo.

    Raises :class:`KeyError` when no adapter is registered under
    ``name`` (delegates to :func:`get_adapter`); the underlying
    ``test_environment`` call NEVER raises — adapters return an
    :class:`EnvironmentReport` with ``ok=False`` and operator-facing
    ``hints`` on credential failures by design (paperclip mirror).
    """
    return get_adapter(name).test_environment()


# PR-DRIFT-ANCHORS (2026-06-10) — single SoT for the legacy→registry
# provider-key translation. ``core.config._resolve_provider`` returns the
# broader vocabulary (``openai-codex`` for gpt-5.x, ``zhipuai`` for GLM);
# this registry keys adapters on the narrower ``openai`` / ``glm`` (the
# Codex distinction rides the ``source`` axis as ``subscription``).
# Previously FOUR independent copies of this map existed
# (agent_loop.__init__, _model_switching._resolve_path_b_adapter,
# runner._normalize_provider_for_registry,
# _reflection._normalize_provider_for_registry — the last two only
# carried the openai half), with a comment admitting they were not
# sync'd. Add new aliases HERE only.
PROVIDER_REGISTRY_NORMALIZATION: dict[str, str] = {
    "openai-codex": "openai",
    "glm-coding": "glm",
    "zhipuai": "glm",
}


def normalize_registry_provider(provider: str) -> str:
    """Translate a legacy ``_resolve_provider`` key to this registry's
    provider vocabulary (identity for already-narrow keys)."""
    return PROVIDER_REGISTRY_NORMALIZATION.get(provider, provider)


def resolve_for(provider: str, source: str) -> LLMAdapter:
    """Find the unique adapter matching ``(provider, source)``.

    ``provider`` accepts BOTH vocabularies — the registry's family names
    (``openai`` / ``glm``) and the routing layer's variant ids
    (``openai-codex`` / ``glm-coding`` / ``zhipuai``) — normalized here at
    the boundary. Callers used to be responsible for calling
    :func:`normalize_registry_provider` themselves; the fast-chat incident
    (2026-07-06 — ``loop._provider='openai-codex'`` passed through
    unnormalized, every codex-subscription fast-chat turn failed with
    AdapterUnavailableError) showed convention-enforced translation does
    not survive new callers. Normalizing at the lookup entry kills the
    bug class.

    ``source`` MUST be a concrete value (one of
    ``core.llm.adapters.base.CONCRETE_SOURCES``). The picker collapses
    ``"auto"`` → concrete before calling. Passing ``"auto"`` here raises
    :class:`ValueError` — failing loudly is the same anti-leak posture
    paperclip's registry takes on duplicate type registration.

    Raises :class:`AdapterNotFoundError` when no adapter matches.
    """
    provider = normalize_registry_provider(provider)
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
    "adapter_health",
    "bootstrap_builtins",
    "get_adapter",
    "list_adapters",
    "register_adapter",
    "resolve_for",
    "unregister_adapter",
]
