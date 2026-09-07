"""Bounded same-tool retry for tool failures.

Category and price do not establish semantic equivalence. After a failed
retry, return the failure so the caller can choose a different approach.
Existing safety exclusions and executor admission gates remain in force.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.agent.tool_executor import ToolExecutor

log = logging.getLogger(__name__)

# Tools that must NEVER be auto-recovered (safety gate preservation)
_EXCLUDED_TOOLS: frozenset[str] = frozenset(
    {
        "run_bash",
        "computer",
        "computer_use",
        "memory_save",
        "note_save",
        "set_api_key",
        "manage_auth",
        "manage_login",
    }
)


class RecoveryStrategy(StrEnum):
    """Recovery strategy types, in escalation order."""

    RETRY = "retry"
    # Retained for reading historical recovery records, never selected for new calls.
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


class ErrorRecoveryStrategy:
    """Adaptive error recovery with strategy chain.

    Strategies are tried in order: same-tool retry → escalate.
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

    def is_recoverable(self, tool_name: str) -> bool:
        """Check if a tool failure can be recovered.

        DANGEROUS and WRITE tools are excluded to preserve safety gates.
        """
        return tool_name not in _EXCLUDED_TOOLS

    async def arecover(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        failure_count: int,
        *,
        context_factory: Callable[[str, int], Any] | None = None,
        on_execution_started: Callable[[int, str, dict[str, Any]], None] | None = None,
    ) -> RecoveryResult:
        """Execute the recovery chain through the async tool executor path."""
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

        for attempt_index, strategy in enumerate(strategies, start=1):
            if len(attempts) >= self._max_recovery_attempts:
                break

            attempt = await self._aexecute_strategy(
                strategy,
                tool_name,
                tool_input,
                attempt_index=attempt_index,
                context_factory=context_factory,
                on_execution_started=on_execution_started,
            )
            attempts.append(attempt)

            if attempt.success:
                return RecoveryResult(
                    recovered=True,
                    final_result=attempt.result,
                    attempts=attempts,
                    strategy_used=strategy,
                )

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
        Second+ failure: retry → escalate; never substitute unrelated tools.
        """
        strategies: list[RecoveryStrategy] = [RecoveryStrategy.RETRY]

        if failure_count >= 2:
            strategies.append(RecoveryStrategy.ESCALATE)

        return strategies

    async def _aexecute_strategy(
        self,
        strategy: RecoveryStrategy,
        tool_name: str,
        tool_input: dict[str, Any],
        *,
        attempt_index: int,
        context_factory: Callable[[str, int], Any] | None,
        on_execution_started: Callable[[int, str, dict[str, Any]], None] | None,
    ) -> RecoveryAttempt:
        """Execute a single recovery strategy through async tool dispatch."""
        start = time.monotonic()

        if strategy == RecoveryStrategy.RETRY:
            return await self._atry_retry(
                tool_name,
                tool_input,
                start,
                attempt_index=attempt_index,
                context_factory=context_factory,
                on_execution_started=on_execution_started,
            )
        return self._try_escalate(tool_name, tool_input, start)

    async def _atry_retry(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        start: float,
        *,
        attempt_index: int,
        context_factory: Callable[[str, int], Any] | None,
        on_execution_started: Callable[[int, str, dict[str, Any]], None] | None,
    ) -> RecoveryAttempt:
        """Retry the same tool once with an async delay."""
        delay = self._retry_base_delay
        log.info(
            "Recovery[retry]: retrying '%s' after %.1fs delay",
            tool_name,
            delay,
        )
        if delay > 0:
            await asyncio.sleep(delay)

        result = await self._execute_recovery_tool(
            tool_name,
            tool_input,
            attempt_index=attempt_index,
            context_factory=context_factory,
            on_execution_started=on_execution_started,
        )
        elapsed = (time.monotonic() - start) * 1000
        success = not (result.get("error") or result.get("error_type"))

        return RecoveryAttempt(
            strategy=RecoveryStrategy.RETRY,
            tool_name=tool_name,
            success=success,
            result=result,
            duration_ms=elapsed,
        )

    async def _execute_recovery_tool(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        *,
        attempt_index: int,
        context_factory: Callable[[str, int], Any] | None,
        on_execution_started: Callable[[int, str, dict[str, Any]], None] | None,
    ) -> dict[str, Any]:
        context = context_factory(tool_name, attempt_index) if context_factory is not None else None

        def started(effective_name: str, arguments: dict[str, Any]) -> None:
            if on_execution_started is not None:
                on_execution_started(
                    attempt_index,
                    effective_name,
                    arguments,
                )

        return await self._executor.aexecute(
            tool_name,
            tool_input,
            context=context,
            on_execution_started=started,
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
