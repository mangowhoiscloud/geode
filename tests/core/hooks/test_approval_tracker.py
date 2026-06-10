"""Tests for core.hooks.approval_tracker."""

from __future__ import annotations

import json
import time

import pytest
from core.hooks.approval_tracker import ApprovalTracker
from core.hooks.system import HookEvent


@pytest.fixture()
def tracker(tmp_path):
    return ApprovalTracker(history_path=tmp_path / "history.jsonl")


class TestRecord:
    def test_creates_file(self, tracker):
        tracker.record({"tool_name": "run_bash", "decision": "approved"})
        assert tracker._path.exists()

    def test_appends_jsonl(self, tracker):
        tracker.record({"tool_name": "a", "decision": "approved"})
        tracker.record({"tool_name": "b", "decision": "denied"})
        lines = tracker._path.read_text().strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0])["tool_name"] == "a"
        assert json.loads(lines[1])["tool_name"] == "b"

    def test_record_has_timestamp(self, tracker):
        tracker.record({"tool_name": "x", "decision": "approved"})
        rec = json.loads(tracker._path.read_text().strip())
        assert "ts" in rec
        assert rec["ts"] > 0


class TestSuggestAutoApprove:
    def test_no_history_returns_false(self, tracker):
        assert tracker.suggest_auto_approve("run_bash") is False

    def test_below_threshold(self, tracker):
        for _ in range(4):
            tracker.record({"tool_name": "run_bash", "decision": "approved"})
        assert tracker.suggest_auto_approve("run_bash") is False

    def test_at_threshold(self, tracker):
        for _ in range(5):
            tracker.record({"tool_name": "run_bash", "decision": "approved"})
        assert tracker.suggest_auto_approve("run_bash") is True

    def test_denial_resets(self, tracker):
        for _ in range(4):
            tracker.record({"tool_name": "run_bash", "decision": "approved"})
        tracker.record({"tool_name": "run_bash", "decision": "denied"})
        for _ in range(3):
            tracker.record({"tool_name": "run_bash", "decision": "approved"})
        assert tracker.suggest_auto_approve("run_bash") is False

    def test_tool_isolation(self, tracker):
        for _ in range(5):
            tracker.record({"tool_name": "other_tool", "decision": "approved"})
        assert tracker.suggest_auto_approve("run_bash") is False

    def test_old_records_ignored(self, tracker):
        old_ts = time.time() - 40 * 86400
        for _ in range(5):
            tracker._path.parent.mkdir(parents=True, exist_ok=True)
            rec = json.dumps({"ts": old_ts, "tool_name": "run_bash", "decision": "approved"})
            with open(tracker._path, "a") as f:
                f.write(rec + "\n")
        assert tracker.suggest_auto_approve("run_bash") is False


class TestMakeHookHandler:
    def test_returns_handler(self, tracker):
        name, fn = tracker.make_hook_handler(session_key="test")
        assert name == "approval_tracker"
        assert callable(fn)

    def test_handler_records_granted(self, tracker):
        _, fn = tracker.make_hook_handler()
        fn(HookEvent.TOOL_APPROVAL_GRANTED, {"tool_name": "run_bash"})
        rec = json.loads(tracker._path.read_text().strip())
        assert rec["decision"] == "approved"

    def test_handler_records_denied(self, tracker):
        _, fn = tracker.make_hook_handler()
        fn(HookEvent.TOOL_APPROVAL_DENIED, {"tool_name": "run_bash"})
        rec = json.loads(tracker._path.read_text().strip())
        assert rec["decision"] == "denied"
