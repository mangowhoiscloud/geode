"""Adaptive Error Recovery — strategy-based recovery for tool failures.

Replaces the simple 2-consecutive-failure auto-skip with a recovery chain
that progressively tries alternative strategies before giving up:

    retry (exponential backoff) → alternative tool (same category)
    → fallback (cheaper cost tier) → escalate (HITL)

Safety: DANGEROUS and WRITE tools are excluded from recovery attempts
to preserve the existing HITL safety gates.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.agent.tool_executor import ToolExecutor

log = logging.getLogger(__name__)

# Load tool definitions for category/cost_tier lookup
_TOOLS_JSON_PATH = Path(__file__).resolve().parent.parent / "tools" / "definitions.json"

# Tools that must NEVER be auto-recovered (safety gate preservation)
_EXCLUDED_TOOLS: frozenset[str] = frozenset(
    {
        "run_bash",
        "memory_save",
        "note_save",
        "set_api_key",
        "manage_auth",
    }
)

# Cost tier ordering: cheaper is better for fallback
_COST_TIER_ORDER: dict[str, int] = {
    "free": 0,
    "cheap": 1,
    "expensive": 2,
}


class RecoveryStrategy(StrEnum):
    """Recovery strategy types, in escalation order."""

    RETRY = "retry"
    ALTERNATIVE = "alternative"
    FALLBACK = "fallback"
    ESCALATE = "escalate"


@dataclass
class RecoveryAttempt:
    """Record of a single recovery attempt."""

    strategy: RecoveryStrategy
    tool_name: str
    success: bool
    result: dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0.0


@dataclass
class RecoveryResult:
    """Outcome of the full recovery chain."""

    recovered: bool
    final_result: dict[str, Any]
    attempts: list[RecoveryAttempt] = field(default_factory=list)
    strategy_used: RecoveryStrategy | None = None

    def to_summary(self) -> str:
        """Human-readable summary for LLM context."""
        if self.recovered:
            return (
                f"Recovery succeeded via {self.strategy_used} strategy "
                f"after {len(self.attempts)} attempt(s)."
            )
        strategies = [a.strategy.value for a in self.attempts]
        return (
            f"Recovery failed after {len(self.attempts)} attempt(s) "
            f"(tried: {', '.join(strategies)}). Please use a different approach."
        )


def _load_tool_definitions() -> list[dict[str, Any]]:
    """Load tool definitions from centralized JSON."""
    try:
        return json.loads(_TOOLS_JSON_PATH.read_text(encoding="utf-8"))  # type: ignore[no-any-return]
    except (OSError, json.JSONDecodeError):
        log.warning("Failed to load tool definitions for error recovery")
        return []


def _build_category_map(
    tool_defs: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Build category → [tool_def] mapping."""
    category_map: dict[str, list[dict[str, Any]]] = {}
    for tool_def in tool_defs:
        category = tool_def.get("category", "")
        if category:
            category_map.setdefault(category, []).append(tool_def)
    return category_map


def _build_cost_tier_map(
    tool_defs: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Build cost_tier → [tool_def] mapping."""
    tier_map: dict[str, list[dict[str, Any]]] = {}
    for tool_def in tool_defs:
        tier = tool_def.get("cost_tier", "")
        if tier:
            tier_map.setdefault(tier, []).append(tool_def)
    return tier_map


class ErrorRecoveryStrategy:
    """Adaptive error recovery with strategy chain.

    Strategies are tried in order: retry → alternative → fallback → escalate.
    Each strategy gets one chance. The chain stops on first success or
    after max_recovery_attempts total attempts.

    Safety invariant: DANGEROUS and WRITE tools are never auto-recovered.
    """

    def __init__(
        self,
        executor: ToolExecutor,
        *,
        max_recovery_attempts: int = 3,
        retry_base_delay: float = 1.0,
    ) -> None:
        self._executor = executor
        self._max_recovery_attempts = max_recovery_attempts
        self._retry_base_delay = retry_base_delay
        self._tool_defs = _load_tool_definitions()
        self._category_map = _build_category_map(self._tool_defs)
        self._cost_tier_map = _build_cost_tier_map(self._tool_defs)
        # Map tool_name → tool_def for quick lookup
        self._tool_lookup: dict[str, dict[str, Any]] = {t["name"]: t for t in self._tool_defs}

    def is_recoverable(self, tool_name: str) -> bool:
        """Check if a tool failure can be recovered.

        DANGEROUS and WRITE tools are excluded to preserve safety gates.
        """
        return tool_name not in _EXCLUDED_TOOLS

    def recover(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        failure_count: int,
    ) -> RecoveryResult:
        """Execute recovery chain for a failed tool.

        Args:
            tool_name: The tool that failed.
            tool_input: Original tool input parameters.
            failure_count: How many times this tool has failed consecutively.

        Returns:
            RecoveryResult with success/failure and all attempts.
        """
        if not self.is_recoverable(tool_name):
            return RecoveryResult(
                recovered=False,
                final_result={
                    "error": (
                        f"Tool '{tool_name}' is not eligible for automatic recovery "
                        "(safety-gated tool). Please try manually."
                    ),
                    "recovery_skipped": True,
                },
            )

        attempts: list[RecoveryAttempt] = []
        strategies = self._select_strategies(tool_name, failure_count)

        for strategy in strategies:
            if len(attempts) >= self._max_recovery_attempts:
                break

            attempt = self._execute_strategy(strategy, tool_name, tool_input)
            attempts.append(attempt)

            if attempt.success:
                return RecoveryResult(
                    recovered=True,
                    final_result=attempt.result,
                    attempts=attempts,
                    strategy_used=strategy,
                )

        # All strategies exhausted
        return RecoveryResult(
            recovered=False,
            final_result={
                "error": (
                    f"Tool '{tool_name}' recovery exhausted after "
                    f"{len(attempts)} attempt(s). "
                    "Try a different tool, or tell the user what failed. "
                    "Do NOT answer from training data without marking it as [Unverified]."
                ),
                "recovery_exhausted": True,
                "strategies_tried": [a.strategy.value for a in attempts],
            },
            attempts=attempts,
        )

    def _select_strategies(
        self,
        tool_name: str,
        failure_count: int,
    ) -> list[RecoveryStrategy]:
        """Determine which strategies to try based on failure context.

        First failure: retry only.
        Second+ failure: retry → alternative → fallback → escalate.
        """
        strategies: list[RecoveryStrategy] = [RecoveryStrategy.RETRY]

        if failure_count >= 2:
            # After 2+ failures, try progressively more aggressive strategies
            if self._has_alternatives(tool_name):
                strategies.append(RecoveryStrategy.ALTERNATIVE)
            if self._has_fallback(tool_name):
                strategies.append(RecoveryStrategy.FALLBACK)
            strategies.append(RecoveryStrategy.ESCALATE)

        return strategies

    def _execute_strategy(
        self,
        strategy: RecoveryStrategy,
        tool_name: str,
        tool_input: dict[str, Any],
    ) -> RecoveryAttempt:
        """Execute a single recovery strategy."""
        start = time.monotonic()

        if strategy == RecoveryStrategy.RETRY:
            return self._try_retry(tool_name, tool_input, start)
        if strategy == RecoveryStrategy.ALTERNATIVE:
            return self._try_alternative(tool_name, tool_input, start)
        if strategy == RecoveryStrategy.FALLBACK:
            return self._try_fallback(tool_name, tool_input, start)
        # ESCALATE
        return self._try_escalate(tool_name, tool_input, start)

    def _try_retry(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        start: float,
    ) -> RecoveryAttempt:
        """Retry the same tool once with a brief delay."""
        delay = self._retry_base_delay
        log.info(
            "Recovery[retry]: retrying '%s' after %.1fs delay",
            tool_name,
            delay,
        )
        time.sleep(delay)

        result = self._executor.execute(tool_name, tool_input)
        elapsed = (time.monotonic() - start) * 1000
        success = not (isinstance(result, dict) and result.get("error"))

        return RecoveryAttempt(
            strategy=RecoveryStrategy.RETRY,
            tool_name=tool_name,
            success=success,
            result=result,
            duration_ms=elapsed,
        )

    def _try_alternative(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        start: float,
    ) -> RecoveryAttempt:
        """Try a different tool from the same category."""
        alt_name = self._find_alternative(tool_name)
        if alt_name is None:
            return RecoveryAttempt(
                strategy=RecoveryStrategy.ALTERNATIVE,
                tool_name=tool_name,
                success=False,
                result={"error": f"No alternative tool found for '{tool_name}'"},
                duration_ms=(time.monotonic() - start) * 1000,
            )

        log.info(
            "Recovery[alternative]: trying '%s' instead of '%s'",
            alt_name,
            tool_name,
        )
        result = self._executor.execute(alt_name, tool_input)
        elapsed = (time.monotonic() - start) * 1000
        success = not (isinstance(result, dict) and result.get("error"))

        return RecoveryAttempt(
            strategy=RecoveryStrategy.ALTERNATIVE,
            tool_name=alt_name,
            success=success,
            result=result,
            duration_ms=elapsed,
        )

    def _try_fallback(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        start: float,
    ) -> RecoveryAttempt:
        """Try a cheaper tool from any category."""
        fallback_name = self._find_fallback(tool_name)
        if fallback_name is None:
            return RecoveryAttempt(
                strategy=RecoveryStrategy.FALLBACK,
                tool_name=tool_name,
                success=False,
                result={"error": f"No cheaper fallback found for '{tool_name}'"},
                duration_ms=(time.monotonic() - start) * 1000,
            )

        log.info(
            "Recovery[fallback]: trying cheaper '%s' instead of '%s'",
            fallback_name,
            tool_name,
        )
        result = self._executor.execute(fallback_name, tool_input)
        elapsed = (time.monotonic() - start) * 1000
        success = not (isinstance(result, dict) and result.get("error"))

        return RecoveryAttempt(
            strategy=RecoveryStrategy.FALLBACK,
            tool_name=fallback_name,
            success=success,
            result=result,
            duration_ms=elapsed,
        )

    def _try_escalate(
        self,
        tool_name: str,
        _tool_input: dict[str, Any],
        start: float,
    ) -> RecoveryAttempt:
        """Escalate to user — always returns failure to signal HITL needed."""
        log.info("Recovery[escalate]: escalating '%s' to user", tool_name)
        return RecoveryAttempt(
            strategy=RecoveryStrategy.ESCALATE,
            tool_name=tool_name,
            success=False,
            result={
                "error": (
                    f"Tool '{tool_name}' requires manual intervention. "
                    "All automatic recovery strategies have been exhausted."
                ),
                "escalated": True,
            },
            duration_ms=(time.monotonic() - start) * 1000,
        )

    # ------------------------------------------------------------------
    # Alternative / Fallback lookup
    # ------------------------------------------------------------------

    def _has_alternatives(self, tool_name: str) -> bool:
        """Check if there are alternative tools in the same category."""
        return self._find_alternative(tool_name) is not None

    def _has_fallback(self, tool_name: str) -> bool:
        """Check if there's a cheaper fallback tool."""
        return self._find_fallback(tool_name) is not None

    def _find_alternative(self, tool_name: str) -> str | None:
        """Find an alternative tool in the same category.

        Returns the first tool in the same category that:
        - Is not the failed tool itself
        - Is not excluded (DANGEROUS/WRITE)
        - Has a registered handler in the executor
        """
        tool_def = self._tool_lookup.get(tool_name)
        if tool_def is None:
            return None

        category = tool_def.get("category", "")
        if not category:
            return None

        candidates = self._category_map.get(category, [])
        registered = set(self._executor.registered_tools)

        for candidate in candidates:
            cand_name: str = str(candidate["name"])
            if cand_name == tool_name:
                continue
            if cand_name in _EXCLUDED_TOOLS:
                continue
            if cand_name in registered:
                return cand_name
        return None

    def _find_fallback(self, tool_name: str) -> str | None:
        """Find a cheaper tool that could serve as fallback.

        Looks for tools in cheaper cost tiers (within the same category
        first, then across all categories) that have a registered handler.
        """
        tool_def = self._tool_lookup.get(tool_name)
        if tool_def is None:
            return None

        current_tier = tool_def.get("cost_tier", "")
        current_order = _COST_TIER_ORDER.get(current_tier, 0)
        category = tool_def.get("category", "")
        registered = set(self._executor.registered_tools)

        # First: same category, cheaper tier
        if category:
            candidates = self._category_map.get(category, [])
            for candidate in candidates:
                cand_name: str = str(candidate["name"])
                cand_tier = candidate.get("cost_tier", "")
                cand_order = _COST_TIER_ORDER.get(cand_tier, 0)
                if cand_name == tool_name:
                    continue
                if cand_name in _EXCLUDED_TOOLS:
                    continue
                if cand_order < current_order and cand_name in registered:
                    return cand_name

        # Then: any category, cheaper tier
        for tier_name in ("free", "cheap"):
            tier_order = _COST_TIER_ORDER[tier_name]
            if tier_order >= current_order:
                continue
            for candidate in self._cost_tier_map.get(tier_name, []):
                cand_name = str(candidate["name"])
                if cand_name == tool_name:
                    continue
                if cand_name in _EXCLUDED_TOOLS:
                    continue
                if cand_name in registered:
                    return cand_name

        return None
