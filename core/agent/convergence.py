"""Convergence detection — extracted from AgenticLoop for SRP.

Tracks tool errors and detects stuck loop patterns (repeated identical failures).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

log = logging.getLogger(__name__)


class ConvergenceDetector:
    """Detects stuck loops and tracks tool error patterns.

    Extracted from AgenticLoop to isolate error tracking concerns.
    Uses composition: AgenticLoop creates and owns this instance.
    """

    def __init__(self, *, escalation_fn: Callable[[], bool] | None = None) -> None:
        self.total_consecutive_tool_errors: int = 0
        self.recent_errors: list[str] = []
        self.convergence_escalated: bool = False
        self._escalation_fn = escalation_fn

    def update_tool_error_tracking(
        self, tool_results: list[dict[str, Any]], tool_log: list[dict[str, Any]]
    ) -> None:
        """Update consecutive tool error tracking and recent error history.

        Processes a batch of tool results from the current round.
        Resets the consecutive counter on any success, increments on all-error rounds.
        Appends normalized error keys to recent_errors for convergence detection.
        """
        has_success = False
        has_error = False

        for tr in tool_results:
            content = tr.get("content", "")
            if isinstance(content, str):
                try:
                    parsed = json.loads(content)
                except (json.JSONDecodeError, ValueError):
                    parsed = {}
            else:
                parsed = content if isinstance(content, dict) else {}

            if isinstance(parsed, dict) and parsed.get("error"):
                has_error = True
                tool_use_id = tr.get("tool_use_id", "")
                error_str = str(parsed.get("error", ""))[:50]
                tool_name = "unknown"
                for entry in reversed(tool_log):
                    if tool_use_id and entry.get("tool") and isinstance(entry.get("result"), dict):
                        tool_name = entry["tool"]
                        break
                error_key = f"{tool_name}:{error_str}"
                self.recent_errors.append(error_key)
                # Keep last 6 entries max
                if len(self.recent_errors) > 6:
                    self.recent_errors = self.recent_errors[-6:]
            else:
                has_success = True

        if has_success:
            self.total_consecutive_tool_errors = 0
        elif has_error:
            self.total_consecutive_tool_errors += 1

    def check_convergence_break(self) -> bool:
        """Check if the loop is stuck in a repeating failure pattern.

        On first detection of 3 identical errors, attempts model escalation
        (runtime ratchet — Karpathy P4) instead of breaking immediately.
        Only breaks after escalation has been tried and errors persist.
        """
        if len(self.recent_errors) < 3:
            return False

        # Check last 3 entries for identical pattern
        last_3 = self.recent_errors[-3:]
        if last_3[0] == last_3[1] == last_3[2]:
            # Runtime ratchet: try model escalation before giving up
            if not self.convergence_escalated:
                self.convergence_escalated = True
                log.warning(
                    "Convergence detected (%s x3) — escalating model",
                    last_3[0],
                )
                if self._escalation_fn:
                    escalated = self._escalation_fn()
                    if escalated:
                        self.recent_errors.clear()
                        return False  # Give escalated model a chance
                # Escalation failed (no fallback) — fall through to break check

            # Already escalated and still stuck — check for 4+ identical
            if len(self.recent_errors) >= 4:
                last_4 = self.recent_errors[-4:]
                if last_4[0] == last_4[1] == last_4[2] == last_4[3]:
                    log.warning(
                        "Convergence detected after escalation: 4+ identical errors '%s'",
                        last_4[0],
                    )
                    return True
            # 3 identical post-escalation — log warning, don't break yet
            log.warning(
                "Convergence warning (post-escalation): 3 identical errors '%s'",
                last_3[0],
            )
        return False
