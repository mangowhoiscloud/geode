"""New-first event-file resolution and legacy row normalization."""

from __future__ import annotations

import json
from pathlib import Path

from core.observability.record_paths import read_event_stream, resolve_event_stream_path


def test_events_file_wins_over_legacy_names(tmp_path: Path) -> None:
    (tmp_path / "transcript.jsonl").write_text('{"event":"legacy"}\n')
    (tmp_path / "events.jsonl").write_text('{"event":"current"}\n')

    assert resolve_event_stream_path(tmp_path) == tmp_path / "events.jsonl"
    assert [row["event"] for row in read_event_stream(tmp_path)] == ["current"]


def test_session_event_normalizes_for_legacy_readers_without_rewriting(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    source = {
        "schema_id": "geode.session-event@1",
        "schema_version": 1,
        "ordinal": 7,
        "occurred_at": 10.0,
        "kind": "tool.called",
        "session_id": "s-1",
        "turn_id": "t-1",
        "call_id": "c-1",
        "payload": {"tool": "read", "arguments": {"path": "README.md"}},
    }
    original = json.dumps(source) + "\n"
    path.write_text(original)

    [row] = read_event_stream(tmp_path)
    assert row["event"] == "tool_call"
    assert row["seq"] == 7
    assert row["tool"] == "read"
    assert row["input"] == {"path": "README.md"}
    assert path.read_text() == original
