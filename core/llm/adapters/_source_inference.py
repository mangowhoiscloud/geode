"""Source inference for AgenticLoop adapter dispatch.

Bridges the operator-facing credential layer (``settings.openai_credential_source``
+ :class:`ProfileStore` OAuth registrations) to the adapter-registry source axis
(``payg`` / ``subscription`` / ``adapter``). The legacy
``_resolve_provider(model)`` returns only the provider key; the AgenticLoop
main path then defaulted ``source`` to ``"payg"``, so a freshly-completed
``/login openai`` (which writes the
``openai-codex-geode:user`` OAuth profile) had no path to surface as a
subscription dispatch — every gpt-5.x call collapsed to
``resolve_for("openai", "payg")`` → ``openai-payg`` → ``api.openai.com``,
returning ``insufficient_quota`` whenever the PAYG bucket was depleted while
the subscription bucket sat unused.

Resolution order (highest precedence first):

1. Explicit operator pin via ``/login source <provider> <type>`` — OpenAI's
   legacy ``"oauth"`` alias selects its subscription adapter, ``"api_key"``
   selects PAYG, and ``"none"`` disables the provider. Retired Anthropic
   ``"oauth"`` / ``"claude-cli"`` inputs fail before dispatch.
2. ``"auto"`` probes :class:`ProfileStore` for OpenAI and uses PAYG for
   Anthropic.
3. ``"payg"`` fallback so the registry resolution never raises on a missing
   credential source — :func:`resolve_for` will still surface the PAYG
   adapter's own credential miss with its operator-grade hint.

Built-in settings/account selection comes from the immutable
``CredentialRoute`` records. External adapters without an explicit selection
route keep the historical PAYG fallback.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from core.llm.adapters.base import SOURCE_PAYG

if TYPE_CHECKING:
    from core.auth.profiles import ProfileStore

log = logging.getLogger(__name__)


def infer_source(provider: str) -> str:
    """Pick the adapter-registry source for *provider* based on operator state.

    Returns one of the three concrete adapter sources. Falls back to PAYG for
    providers without a declared built-in route.
    """
    from core.llm.adapters.registry import normalize_registry_provider
    from core.llm.registry import provider_specs_for

    canonical = normalize_registry_provider(provider)
    specs = provider_specs_for(canonical)
    if not specs:
        return SOURCE_PAYG

    fields = {spec.credential.settings_field for spec in specs if spec.credential.settings_field}
    if len(fields) > 1:
        raise RuntimeError(f"provider {canonical!r} declares multiple credential setting fields")
    field = next(iter(fields), "")
    if not field:
        defaults = [spec.credential.source for spec in specs if spec.credential.default]
        return defaults[0] if len(defaults) == 1 else SOURCE_PAYG

    raw = _read_setting(field)
    if raw == "none":
        raise RuntimeError(
            f"provider {provider!r} is disabled by {field}='none'; "
            "select another credential source with /login source"
        )
    if raw == "claude-cli" or (canonical == "anthropic" and raw == "oauth"):
        from core.config.credential_source import CLAUDE_CLI_RETIRED_MESSAGE

        raise RuntimeError(CLAUDE_CLI_RETIRED_MESSAGE)
    if canonical == "anthropic" and raw == "openai-codex":
        raise RuntimeError("openai-codex is not a credential source for provider 'anthropic'")
    for spec in specs:
        if raw in spec.credential.settings_values:
            return spec.credential.source
    if raw == "auto":
        for spec in specs:
            route = spec.credential
            if route.auto_select and _has_oauth_profile(route.account_provider):
                return route.source
    defaults = [spec.credential.source for spec in specs if spec.credential.default]
    return defaults[0] if len(defaults) == 1 else SOURCE_PAYG


def _read_setting(field: str) -> str:
    try:
        from core.config import settings
    except Exception:
        log.debug("source-inference: settings import failed; defaulting to auto", exc_info=True)
        return "auto"
    raw = getattr(settings, field, "auto")
    return str(raw or "auto").lower()


def _has_oauth_profile(account_provider: str) -> bool:
    store = _load_profile_store()
    if store is None:
        return False
    from core.auth.profiles import CredentialType

    for profile in store.list_by_provider(account_provider):
        if profile.credential_type == CredentialType.OAUTH:
            return True
    return False


def _load_profile_store() -> ProfileStore | None:
    try:
        from core.wiring.container import ensure_profile_store
    except Exception:
        log.debug("source-inference: profile store import failed", exc_info=True)
        return None
    try:
        return ensure_profile_store()
    except Exception:
        log.debug("source-inference: ensure_profile_store raised", exc_info=True)
        return None
