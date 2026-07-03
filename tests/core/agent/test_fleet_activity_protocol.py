"""Fleet-view Stage 1.5 — worker stdout activity protocol + child emit helper.

Covers the parent-side line protocol parser and the child-side emit helper in
isolation (no real subprocess spawned), per the design SOT
``docs/plans/2026-07-03-fleet-view.md``:

- (a) a legacy bare-result-only stdout still parses to a WorkerResult (compat);
- (b) activity-lines-then-result yields the activity updates + the final result;
- (c) a malformed activity line is skipped, not fatal;
- (d) the ``emit_activity=False`` path emits nothing (fail-safe gate);
- the child emit helper writes well-formed activity JSON and throttles
  consecutive duplicate tool names.
"""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout

from core.agent.worker import WorkerRequest, WorkerResult, _make_activity_sink
from core.orchestration.isolated_execution import (
    _classify_worker_line,
    parse_worker_stream,
)


class TestLineClassifier:
    def test_bare_legacy_result_classifies_as_result(self) -> None:
        """Backward compat: no `type` key → treated as the terminal result."""
        line = json.dumps({"task_id": "t1", "success": True, "output": "done"})
        kind, obj = _classify_worker_line(line)
        assert kind == "result"
        assert obj is not None and obj["task_id"] == "t1"

    def test_activity_line_classifies_as_activity(self) -> None:
        line = json.dumps({"type": "activity", "task_id": "t1", "tool": "grep_files"})
        kind, obj = _classify_worker_line(line)
        assert kind == "activity"
        assert obj is not None and obj["tool"] == "grep_files"

    def test_explicit_type_result_classifies_as_result(self) -> None:
        """A tagged {"type":"result"} line is also terminal (compat rule)."""
        line = json.dumps({"type": "result", "task_id": "t1", "success": True})
        kind, _obj = _classify_worker_line(line)
        assert kind == "result"

    def test_malformed_and_blank_lines_skip(self) -> None:
        assert _classify_worker_line("not json at all")[0] == "skip"
        assert _classify_worker_line("")[0] == "skip"
        assert _classify_worker_line("   ")[0] == "skip"
        # Valid JSON that is not an object is not a result either.
        assert _classify_worker_line("[1, 2, 3]")[0] == "skip"

    def test_stray_json_object_is_not_a_result(self) -> None:
        """Codex HIGH: a stray tool/library print of a JSON object that is NOT
        WorkerResult-shaped (missing task_id/success) must skip, not clobber
        the real result."""
        assert _classify_worker_line(json.dumps({"foo": "bar"}))[0] == "skip"
        assert _classify_worker_line(json.dumps({"success": True}))[0] == "skip"  # no task_id
        assert _classify_worker_line(json.dumps({"task_id": "t1"}))[0] == "skip"  # no success

    def test_stray_object_does_not_clobber_real_result(self) -> None:
        """A stray object printed AFTER the real result must not win."""
        lines = [
            json.dumps({"task_id": "t1", "success": True, "output": "real"}),
            json.dumps({"status": "ok", "note": "stray tool print"}),
        ]
        _activity, result = parse_worker_stream(lines)
        assert result is not None and result["output"] == "real"


class TestParseWorkerStream:
    def test_legacy_bare_result_only(self) -> None:
        """(a) A worker that emits ONLY a bare result line parses to that result."""
        result_line = json.dumps({"task_id": "t1", "success": True, "output": "ok"})
        activities, result = parse_worker_stream([result_line])
        assert activities == []
        assert result is not None
        restored = WorkerResult.from_dict(result)
        assert restored.task_id == "t1"
        assert restored.success is True

    def test_activity_lines_then_result(self) -> None:
        """(b) Activity lines are collected in order; the last line is the result."""
        lines = [
            json.dumps({"type": "activity", "task_id": "t1", "tool": "grep_files", "tokens": 10}),
            json.dumps(
                {"type": "activity", "task_id": "t1", "tool": "read_document", "tokens": 40}
            ),
            json.dumps({"task_id": "t1", "success": True, "output": "final", "prompt_tokens": 50}),
        ]
        activities, result = parse_worker_stream(lines)
        assert [a["tool"] for a in activities] == ["grep_files", "read_document"]
        assert result is not None and result["output"] == "final"
        assert WorkerResult.from_dict(result).prompt_tokens == 50

    def test_malformed_activity_line_is_skipped_not_fatal(self) -> None:
        """(c) A malformed line in the middle is dropped; parsing continues."""
        lines = [
            json.dumps({"type": "activity", "task_id": "t1", "tool": "grep_files"}),
            "{ this is not valid json",
            "",
            json.dumps({"task_id": "t1", "success": True}),
        ]
        activities, result = parse_worker_stream(lines)
        assert len(activities) == 1
        assert result is not None and result["success"] is True

    def test_no_result_line_returns_none(self) -> None:
        """A worker that emits only activity (crashed before result) → result None."""
        activities, result = parse_worker_stream(
            [json.dumps({"type": "activity", "task_id": "t1", "tool": "x"})]
        )
        assert len(activities) == 1
        assert result is None

    def test_last_result_line_wins(self) -> None:
        lines = [
            json.dumps({"task_id": "t1", "success": False, "output": "first"}),
            json.dumps({"task_id": "t1", "success": True, "output": "second"}),
        ]
        _activities, result = parse_worker_stream(lines)
        assert result is not None and result["output"] == "second"


class TestChildEmitHelper:
    def test_sink_writes_wellformed_activity_json(self) -> None:
        sink = _make_activity_sink("task-42")
        buf = io.StringIO()
        with redirect_stdout(buf):
            sink("grep_files", 128)
        lines = [ln for ln in buf.getvalue().splitlines() if ln.strip()]
        assert len(lines) == 1
        obj = json.loads(lines[0])
        assert obj["type"] == "activity"
        assert obj["task_id"] == "task-42"
        assert obj["tool"] == "grep_files"
        assert obj["tokens"] == 128
        assert "ts" in obj
        # The result line reader must classify this as activity, not result.
        assert _classify_worker_line(lines[0])[0] == "activity"

    def test_sink_throttles_consecutive_duplicate_tool(self) -> None:
        """Change-only throttle: same tool twice → one line; a change re-emits."""
        sink = _make_activity_sink("t1")
        buf = io.StringIO()
        with redirect_stdout(buf):
            sink("grep_files", 1)
            sink("grep_files", 2)  # duplicate — suppressed
            sink("read_document", 3)  # change — emitted
            sink("read_document", 4)  # duplicate — suppressed
        tools = [json.loads(ln)["tool"] for ln in buf.getvalue().splitlines() if ln.strip()]
        assert tools == ["grep_files", "read_document"]

    def test_sink_ignores_empty_tool_name(self) -> None:
        sink = _make_activity_sink("t1")
        buf = io.StringIO()
        with redirect_stdout(buf):
            sink("", 5)
        assert buf.getvalue().strip() == ""


class TestEmitActivityGate:
    def test_worker_request_roundtrip_carries_emit_activity(self) -> None:
        req = WorkerRequest(task_id="t1", description="x", emit_activity=True)
        restored = WorkerRequest.from_dict(req.to_dict())
        assert restored.emit_activity is True

    def test_emit_activity_defaults_false(self) -> None:
        """(d) Fail-safe: an un-flagged request keeps activity off."""
        assert WorkerRequest(task_id="t1").emit_activity is False
        assert WorkerRequest.from_dict({"task_id": "t1"}).emit_activity is False

    def test_activity_channel_noop_without_sink(self) -> None:
        """No sink installed (parent process / seed-gen) → emit is a no-op."""
        from core.agent import activity_channel

        activity_channel.clear_activity_sink()
        assert activity_channel.get_activity_sink() is None
        # Must not raise and must not write anything.
        buf = io.StringIO()
        with redirect_stdout(buf):
            activity_channel.emit_tool_activity("grep_files")
        assert buf.getvalue() == ""

    def test_activity_channel_forwards_to_installed_sink(self) -> None:
        from core.agent import activity_channel

        received: list[tuple[str, int]] = []
        try:
            activity_channel.set_activity_sink(lambda tool, tokens: received.append((tool, tokens)))
            activity_channel.emit_tool_activity("edit_file")
        finally:
            activity_channel.clear_activity_sink()
        assert len(received) == 1
        assert received[0][0] == "edit_file"
        # tokens is best-effort (0 for a fresh/absent tracker) — never negative.
        assert received[0][1] >= 0
