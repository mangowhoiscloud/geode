"""Agent Reflection -- auto-learn patterns from pipeline results.

Listens for PIPELINE_END hook events and extracts actionable patterns
to ``~/.geode/user_profile/learned.md`` via ``FileBasedUserProfile``.

Karpathy P4 Ratchet pattern: Tier regressions are flagged as warnings.
"""

from __future__ import annotations

import logging
from typing import Any

from core.orchestration.hooks import HookEvent

log = logging.getLogger(__name__)


def make_reflection_handler(
    user_profile: Any,
    result_cache: Any | None = None,
) -> tuple[str, Any]:
    """Create a PIPELINE_END hook handler that auto-learns patterns.

    Args:
        user_profile: FileBasedUserProfile instance for writing learned patterns.
        result_cache: Optional ResultCache for detecting tier changes (Ratchet).

    Returns:
        Tuple of (handler_name, handler_fn) for HookSystem.register().
    """

    def _on_pipeline_end(event: HookEvent, data: dict[str, Any]) -> None:
        """Extract patterns from pipeline completion data."""
        if event != HookEvent.PIPELINE_END:
            return

        ip_name = data.get("ip_name", "")
        tier = data.get("tier", "")
        score = data.get("score")
        cause = data.get("cause", "")
        status = data.get("status", "ok")

        if not ip_name:
            return

        # Rule 1: Record analysis completion with tier/score
        if tier and score is not None:
            pattern = f"[{ip_name}] Analyzed: Tier {tier} / {score:.1f} — cause: {cause}"
            user_profile.add_learned_pattern(pattern, "analysis")

        # Rule 2: Detect tier change (Karpathy P4 Ratchet)
        if result_cache is not None and tier:
            _check_tier_change(user_profile, result_cache, ip_name, tier, score)

        # Rule 3: Record failures
        if status == "error":
            error_msg = data.get("error", "unknown")
            pattern = f"[{ip_name}] Analysis failed: {error_msg}"
            user_profile.add_learned_pattern(pattern, "failure")

        # Rule 4: Record low confidence iterations
        iterations = data.get("iterations", 1)
        if iterations > 1:
            pattern = (
                f"[{ip_name}] Required {iterations} confidence iterations "
                f"(final: Tier {tier} / {score})"
            )
            user_profile.add_learned_pattern(pattern, "confidence")

    return "agent_reflection", _on_pipeline_end


def _check_tier_change(
    user_profile: Any,
    result_cache: Any,
    ip_name: str,
    current_tier: str,
    current_score: float | None,
) -> None:
    """Detect tier changes by comparing with cached results (Ratchet pattern)."""
    prev = result_cache.get(ip_name)
    if prev is None:
        return

    prev_tier = prev.get("tier", "")
    prev_score = prev.get("final_score")

    if not prev_tier or prev_tier == current_tier:
        return

    tier_order = {"S": 4, "A": 3, "B": 2, "C": 1}
    prev_rank = tier_order.get(prev_tier, 0)
    curr_rank = tier_order.get(current_tier, 0)

    direction = "upgraded" if curr_rank > prev_rank else "downgraded"
    score_info = ""
    if prev_score is not None and current_score is not None:
        score_info = f" (score: {prev_score:.1f} -> {current_score:.1f})"

    pattern = f"[{ip_name}] Tier {direction}: {prev_tier} -> {current_tier}{score_info}"
    category = "tier_upgrade" if direction == "upgraded" else "tier_regression"
    user_profile.add_learned_pattern(pattern, category)

    if direction == "downgraded":
        log.warning(
            "Ratchet warning: %s tier downgraded %s -> %s",
            ip_name,
            prev_tier,
            current_tier,
        )
