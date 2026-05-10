"""Convergence detection — extracted from AgenticLoop for SRP.

Tracks tool errors and detects stuck loop patterns (repeated identical failures).

v0.90.0 — auto-escalation removed. Earlier revisions retried convergence
breaks by silently escalating to the next model in the fallback chain
(Karpathy P4 runtime ratchet); the consequent silent model swap
violated the v0.53.0 governance principle (no auto provider/model
swap). Convergence now breaks immediately and the loop surfaces a
``model_action_required`` diagnostic so the user picks the next model.
"""

from __future__ import annotations

import json
import logging
from typing import Any

log = logging.getLogger(__name__)


class ConvergenceDetector:
    """Detects stuck loops and tracks tool error patterns.

    Extracted from AgenticLoop to isolate error tracking concerns.
    Uses composition: AgenticLoop creates and owns this instance.
    """

    def __init__(self) -> None:
        self.total_consecutive_tool_errors: int = 0
        self.recent_errors: list[str] = []

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
        """Return True when 3 consecutive identical tool errors are observed.

        The caller (AgenticLoop) breaks the loop and surfaces a user-facing
        diagnostic; we no longer try to auto-swap models on stuck loops.
        """
        if len(self.recent_errors) < 3:
            return False
        last_3 = self.recent_errors[-3:]
        if last_3[0] == last_3[1] == last_3[2]:
            log.warning("Convergence detected: 3 identical errors '%s'", last_3[0])
            return True
        return False

    @property
    def last_error_key(self) -> str | None:
        """Most recent error key (for diagnostic surfacing). None if empty."""
        return self.recent_errors[-1] if self.recent_errors else None
