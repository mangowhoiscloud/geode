"""Scoring formula constants — Python fallbacks for scoring_weights.yaml.

Single source of truth for hardcoded game-IP scoring defaults.
DomainPort adapters load from YAML at runtime; these constants are
the fallback when no domain or YAML is available.
"""

from __future__ import annotations

# --- Tier thresholds (descending order) ---
TIER_S_THRESHOLD = 80.0
TIER_A_THRESHOLD = 60.0
TIER_B_THRESHOLD = 40.0
TIER_FALLBACK = "C"

TIER_THRESHOLDS: list[tuple[float, str]] = [
    (TIER_S_THRESHOLD, "S"),
    (TIER_A_THRESHOLD, "A"),
    (TIER_B_THRESHOLD, "B"),
]

# --- Subscore weights (must sum to 1.0) ---
DEFAULT_WEIGHTS: dict[str, float] = {
    "exposure_lift": 0.25,
    "quality": 0.20,
    "recovery": 0.18,
    "growth": 0.12,
    "momentum": 0.20,
    "developer": 0.05,
}

# For report formatting (key names differ slightly: "psm" instead of "exposure_lift")
REPORT_WEIGHTS: list[tuple[str, float]] = [
    ("psm", 0.25),
    ("quality", 0.20),
    ("recovery", 0.18),
    ("growth", 0.12),
    ("momentum", 0.20),
    ("dev", 0.05),
]

# --- Confidence multiplier ---
CONFIDENCE_BASE_FACTOR = 0.7
CONFIDENCE_SCALE_FACTOR = 0.3


def classify_tier(score: float) -> str:
    """Classify a final score into a tier label (S/A/B/C)."""
    for threshold, label in TIER_THRESHOLDS:
        if score >= threshold:
            return label
    return TIER_FALLBACK


def score_style(score: float) -> str:
    """Return a Rich style string for a score value."""
    if score >= TIER_S_THRESHOLD:
        return "bold green"
    if score >= TIER_A_THRESHOLD:
        return "yellow"
    return "red"


def score_ansi_color(score: float) -> str:
    """Return ANSI color code for a score value (32=green, 33=yellow, 31=red)."""
    if score >= TIER_S_THRESHOLD:
        return "32"
    if score >= TIER_A_THRESHOLD:
        return "33"
    return "31"
