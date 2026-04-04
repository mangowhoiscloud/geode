"""Tool approval history tracker — JSONL-based HITL pattern learning.

Records approval/denial decisions and suggests auto-approve candidates
based on consecutive approval streaks.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from core.hooks.system import HookEvent

log = logging.getLogger(__name__)

_DEFAULT_HISTORY_PATH: Path | None = None


def _get_history_path() -> Path:
    global _DEFAULT_HISTORY_PATH
    if _DEFAULT_HISTORY_PATH is None:
        from core.paths import GEODE_HOME

        _DEFAULT_HISTORY_PATH = GEODE_HOME / "approval_history.jsonl"
    return _DEFAULT_HISTORY_PATH


class ApprovalTracker:
    """Tracks HITL tool approval decisions to ~/.geode/approval_history.jsonl."""

    CONSECUTIVE_THRESHOLD = 5
    LOOKBACK_DAYS = 30

    def __init__(self, history_path: Path | None = None) -> None:
        self._path = history_path or _get_history_path()

    def record(self, data: dict[str, Any]) -> None:
        """Append a decision record to the JSONL file."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "ts": time.time(),
            "tool_name": data.get("tool_name", ""),
            "permission_level": data.get("permission_level", ""),
            "decision": data.get("decision", ""),
            "response_type": data.get("response_type", ""),
            "latency_ms": data.get("latency_ms", 0),
            "session_key": data.get("session_key", ""),
        }
        try:
            with open(self._path, "a") as f:
                f.write(json.dumps(record) + "\n")
        except OSError:
            log.debug("Failed to write approval record", exc_info=True)

    def suggest_auto_approve(self, tool_name: str) -> bool:
        """Return True if tool has N+ consecutive approvals with no denials in lookback."""
        if not self._path.exists():
            return False

        cutoff = time.time() - self.LOOKBACK_DAYS * 86400
        consecutive = 0

        try:
            with open(self._path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if rec.get("tool_name") != tool_name:
                        continue
                    if rec.get("ts", 0) < cutoff:
                        continue
                    if rec.get("decision") == "approved":
                        consecutive += 1
                    else:
                        consecutive = 0
        except OSError:
            return False

        return consecutive >= self.CONSECUTIVE_THRESHOLD

    def make_hook_handler(self, session_key: str = "") -> tuple[str, Any]:
        """Return (handler_name, handler_fn) for HookSystem registration."""

        def _on_approval(event: HookEvent, data: dict[str, Any]) -> None:
            data.setdefault("session_key", session_key)
            decision = "approved" if event == HookEvent.TOOL_APPROVAL_GRANTED else "denied"
            data.setdefault("decision", decision)
            self.record(data)

        return "approval_tracker", _on_approval
