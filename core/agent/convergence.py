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

REPEATED_SUCCESS_THRESHOLD = 5


class ConvergenceDetector:
    """Detects stuck loops and tracks tool error patterns.

    Extracted from AgenticLoop to isolate error tracking concerns.
    Uses composition: AgenticLoop creates and owns this instance.
    """

    def __init__(self) -> None:
        self.total_consecutive_tool_errors: int = 0
        self.recent_errors: list[str] = []
        self.repeated_success_streak: int = 0
        self.last_success_fingerprint: str | None = None
        self.last_success_tool: str | None = None
        self.last_success_summary: str | None = None

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
        log_by_id = {
            str(entry.get("tool_use_id")): entry for entry in tool_log if entry.get("tool_use_id")
        }
        recent_log_entries = tool_log[-len(tool_results) :] if tool_results else []

        for idx, tr in enumerate(tool_results):
            parsed = self._parse_tool_content(tr.get("content", ""))
            tool_use_id = str(tr.get("tool_use_id", ""))
            log_entry = log_by_id.get(tool_use_id)
            if log_entry is None and idx < len(recent_log_entries):
                log_entry = recent_log_entries[idx]

            if isinstance(parsed, dict) and parsed.get("error"):
                has_error = True
                error_str = str(parsed.get("error", ""))[:50]
                tool_name = self._tool_name(log_entry)
                error_key = f"{tool_name}:{error_str}"
                self.recent_errors.append(error_key)
                # Keep last 6 entries max
                if len(self.recent_errors) > 6:
                    self.recent_errors = self.recent_errors[-6:]
                self._reset_success_streak()
            else:
                has_success = True
                self._update_success_streak(parsed, log_entry)

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

    def check_repeated_success_no_progress(self) -> bool:
        """Return True when identical successful observations repeat too often.

        This is intentionally separate from round limits: GEODE can keep the
        default loop unbounded, while still breaking when the model keeps
        asking the same tool with the same input and receives the same success.
        """
        if self.repeated_success_streak < REPEATED_SUCCESS_THRESHOLD:
            return False
        log.warning(
            "No-progress success detected: %s repeated %d times",
            self.last_success_tool or "unknown",
            self.repeated_success_streak,
        )
        return True

    @property
    def last_error_key(self) -> str | None:
        """Most recent error key (for diagnostic surfacing). None if empty."""
        return self.recent_errors[-1] if self.recent_errors else None

    @staticmethod
    def _parse_tool_content(content: Any) -> Any:
        if isinstance(content, str):
            try:
                return json.loads(content)
            except (json.JSONDecodeError, ValueError):
                return content
        if isinstance(content, list):
            text_parts = [
                str(block.get("text"))
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            ]
            if len(text_parts) == 1:
                return ConvergenceDetector._parse_tool_content(text_parts[0])
            return content
        return content

    @staticmethod
    def _tool_name(log_entry: dict[str, Any] | None) -> str:
        if log_entry and log_entry.get("tool"):
            return str(log_entry["tool"])
        return "unknown"

    @staticmethod
    def _stable_json(value: Any) -> str:
        try:
            return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            return str(value)

    def _success_fingerprint(self, parsed: Any, log_entry: dict[str, Any] | None) -> str:
        tool_name = self._tool_name(log_entry)
        tool_input = log_entry.get("input", {}) if log_entry else {}
        payload = {
            "tool": tool_name,
            "input": tool_input,
            "result": parsed,
        }
        return self._stable_json(payload)[:4000]

    def _success_summary(self, parsed: Any) -> str:
        summary = self._stable_json(parsed)
        if len(summary) > 240:
            summary = summary[:237] + "..."
        return summary

    def _update_success_streak(self, parsed: Any, log_entry: dict[str, Any] | None) -> None:
        fingerprint = self._success_fingerprint(parsed, log_entry)
        if fingerprint == self.last_success_fingerprint:
            self.repeated_success_streak += 1
        else:
            self.last_success_fingerprint = fingerprint
            self.repeated_success_streak = 1
        self.last_success_tool = self._tool_name(log_entry)
        self.last_success_summary = self._success_summary(parsed)

    def _reset_success_streak(self) -> None:
        self.repeated_success_streak = 0
        self.last_success_fingerprint = None
        self.last_success_tool = None
        self.last_success_summary = None
