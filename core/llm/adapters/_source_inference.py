"""Source inference for AgenticLoop adapter dispatch.

Bridges the operator-facing credential layer (``settings.openai_credential_source``
+ :class:`ProfileStore` OAuth registrations) to the adapter-registry source axis
(``payg`` / ``subscription``). The legacy ``_resolve_provider(model)`` returns
only the provider key; the AgenticLoop main path then defaulted ``source`` to
``"payg"``, so a freshly-completed ``/login openai`` (which writes the
``openai-codex-geode:user`` OAuth profile) had no path to surface as a
subscription dispatch — every gpt-5.x call collapsed to
``resolve_for("openai", "payg")`` → ``openai-payg`` → ``api.openai.com``,
returning ``insufficient_quota`` whenever the PAYG bucket was depleted while
the subscription bucket sat unused.

Resolution order (highest precedence first):

1. Explicit operator pin via ``/login source <provider> <type>`` —
   ``settings.{provider}_credential_source`` of ``"oauth"`` → subscription,
   ``"api_key"`` → payg. ``"none"`` falls back to payg (the historical default
   so a disabled credential source still routes through the configured PAYG
   key rather than raising at the registry).
2. ``"auto"`` (the unconfigured default) probes :class:`ProfileStore` —
   any OAuth profile registered for the provider promotes to ``"subscription"``.
3. ``"payg"`` fallback so the registry resolution never raises on a missing
   credential source — :func:`resolve_for` will still surface the PAYG
   adapter's own credential miss with its operator-grade hint.

Only ``openai`` / ``openai-codex`` and ``anthropic`` participate; ``glm`` and
the local-CLI adapters route through their own picker paths and never reach
this helper.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from core.llm.adapters.base import SOURCE_PAYG, SOURCE_SUBSCRIPTION

if TYPE_CHECKING:
    from core.auth.profiles import ProfileStore

log = logging.getLogger(__name__)


_SETTINGS_FIELD: dict[str, str] = {
    "openai": "openai_credential_source",
    "openai-codex": "openai_credential_source",
    "anthropic": "anthropic_credential_source",
}

_OAUTH_PROVIDER_KEY: dict[str, str] = {
    "openai": "openai-codex",
    "openai-codex": "openai-codex",
    "anthropic": "anthropic",
}


def infer_source(provider: str) -> str:
    """Pick the adapter-registry source for *provider* based on operator state.

    Returns one of :data:`SOURCE_PAYG` / :data:`SOURCE_SUBSCRIPTION`. Falls back
    to :data:`SOURCE_PAYG` for any provider not in :data:`_SETTINGS_FIELD` so
    the AgenticLoop registry lookup stays consistent with the historical
    default (the loop's ``source or "payg"`` had no concept of inference).
    """
    field = _SETTINGS_FIELD.get(provider)
    if field is None:
        return SOURCE_PAYG

    raw = _read_setting(field)
    if raw == "oauth":
        return SOURCE_SUBSCRIPTION
    if raw in ("api_key", "none"):
        return SOURCE_PAYG
    if _has_oauth_profile(provider):
        return SOURCE_SUBSCRIPTION
    return SOURCE_PAYG


def _read_setting(field: str) -> str:
    try:
        from core.config import settings
    except Exception:
        log.debug("source-inference: settings import failed; defaulting to auto", exc_info=True)
        return "auto"
    raw = getattr(settings, field, "auto")
    return str(raw or "auto").lower()


def _has_oauth_profile(provider: str) -> bool:
    profile_key = _OAUTH_PROVIDER_KEY.get(provider)
    if profile_key is None:
        return False
    store = _load_profile_store()
    if store is None:
        return False
    from core.auth.profiles import CredentialType

    for profile in store.list_by_provider(profile_key):
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
