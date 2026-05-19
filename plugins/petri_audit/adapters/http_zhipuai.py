"""HTTP API-key adapter for Zhipu (GLM provider) — routes via GeodeModelAPI.

Maps the manifest binding ``[petri.adapter.zhipuai.api_key]`` to
inspect_ai's ``geode/<model>`` provider (registered by
:mod:`plugins.petri_audit.targets.geode_target`). inspect_ai has no
native GLM provider, so GLM provider ids are routed through the GEODE
wrapper that the full agentic stack uses anyway — the same path
production code takes.

Registration is shared with the target adapter; this module just
exposes the readiness probe + inspect_prefix metadata so the registry
has a uniform import target.
"""

from __future__ import annotations

import os

from plugins.petri_audit.targets.geode_target import register as _register_geode

__all__ = ["INSPECT_PREFIX", "is_available", "register"]

INSPECT_PREFIX = "geode"


def register() -> None:
    """Register the ``geode`` ``ModelAPI`` (shared with the target adapter)."""
    _register_geode()


def is_available() -> bool:
    """True when ``ZHIPUAI_API_KEY`` is set in the environment."""
    return bool(os.environ.get("ZHIPUAI_API_KEY"))
