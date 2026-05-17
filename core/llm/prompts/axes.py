"""Structured scoring axes — domain-data sourced from active domain.

For backwards compatibility, module-level constants ANALYST_SPECIFIC,
EVALUATOR_AXES, PROSPECT_EVALUATOR_AXES, VALID_AXES_MAP, AXES_VERSIONS
remain importable. GEODE core ships no built-in domain axes as of v1.0.0,
so these constants default to empty mappings.

For domain-aware lookups at runtime, prefer ``get_valid_axes_map()`` —
it delegates to the active ``DomainPort`` and works for any domain.

Step 1 of the domain-free-core refactor:
  see docs/architecture/domain-free-core-audit.md (§4, §6).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

ANALYST_SPECIFIC: dict[str, str] = {}
EVALUATOR_AXES: dict[str, dict[str, Any]] = {}
PROSPECT_EVALUATOR_AXES: dict[str, dict[str, Any]] = {}
VALID_AXES_MAP: dict[str, set[str]] = {}


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
