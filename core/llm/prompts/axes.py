"""Structured scoring axes.

For backwards compatibility, module-level constants ANALYST_SPECIFIC,
EVALUATOR_AXES, PROSPECT_EVALUATOR_AXES, VALID_AXES_MAP, AXES_VERSIONS
remain importable. GEODE core ships no built-in scoring axes, so these
constants default to empty mappings.
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
    """Return the core scoring axes map."""
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
