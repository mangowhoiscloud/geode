"""Structured scoring axes — domain-data sourced from active plugin.

For backwards compatibility, module-level constants ANALYST_SPECIFIC,
EVALUATOR_AXES, PROSPECT_EVALUATOR_AXES, VALID_AXES_MAP, AXES_VERSIONS
remain importable. They are populated at import time by reading from
``plugins.game_ip.axes`` if installed, or set to empty defaults so that
``core/`` can be imported in non-game_ip contexts (e.g. REODE forks).

For domain-aware lookups at runtime, prefer ``get_valid_axes_map()`` —
it delegates to the active ``DomainPort`` and works for any domain.

Step 1 of the domain-free-core refactor:
  see docs/architecture/domain-free-core-audit.md (§4, §6).
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

log = logging.getLogger(__name__)

ANALYST_SPECIFIC: dict[str, str]
EVALUATOR_AXES: dict[str, dict[str, Any]]
PROSPECT_EVALUATOR_AXES: dict[str, dict[str, Any]]
VALID_AXES_MAP: dict[str, set[str]]

try:
    from plugins.game_ip.axes import (
        ANALYST_SPECIFIC as _PLUGIN_ANALYST_SPECIFIC,
    )
    from plugins.game_ip.axes import (
        EVALUATOR_AXES as _PLUGIN_EVALUATOR_AXES,
    )
    from plugins.game_ip.axes import (
        PROSPECT_EVALUATOR_AXES as _PLUGIN_PROSPECT_EVALUATOR_AXES,
    )
    from plugins.game_ip.axes import (
        VALID_AXES_MAP as _PLUGIN_VALID_AXES_MAP,
    )

    ANALYST_SPECIFIC = _PLUGIN_ANALYST_SPECIFIC
    EVALUATOR_AXES = _PLUGIN_EVALUATOR_AXES
    PROSPECT_EVALUATOR_AXES = _PLUGIN_PROSPECT_EVALUATOR_AXES
    VALID_AXES_MAP = _PLUGIN_VALID_AXES_MAP
except ImportError:
    log.debug("game_ip plugin axes not present; axes constants set to empty defaults")
    ANALYST_SPECIFIC = {}
    EVALUATOR_AXES = {}
    PROSPECT_EVALUATOR_AXES = {}
    VALID_AXES_MAP = {}


def get_valid_axes_map() -> dict[str, set[str]]:
    """Get valid axes map from active domain adapter, else module-level fallback."""
    from core.domains.port import get_domain_or_none

    domain = get_domain_or_none()
    if domain is not None:
        return domain.get_valid_axes_map()
    return VALID_AXES_MAP


# ---------------------------------------------------------------------------
# Axes version hashing (Karpathy P4 — structured data drift detection)
# ---------------------------------------------------------------------------


def _hash_axes(data: Any) -> str:
    """SHA-256[:12] of JSON-serialized axes data for drift detection."""
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:12]


AXES_VERSIONS: dict[str, str] = {
    "EVALUATOR_AXES": _hash_axes(EVALUATOR_AXES),
    "PROSPECT_EVALUATOR_AXES": _hash_axes(PROSPECT_EVALUATOR_AXES),
    "ANALYST_SPECIFIC": _hash_axes(ANALYST_SPECIFIC),
}
