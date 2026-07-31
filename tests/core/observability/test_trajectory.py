"""Boundary coverage for the K3-shaped trajectory projection.

Each case pins a defect that real transcripts actually produce, so the
docstrings name the population rather than restating the assertion.
"""

import json

import pytest
from core.observability.trajectory import (
    _arguments,
    _messages,
    _pairing,
    _preflight,
    _rows,
    _self_check,
    _unmodelled,
    build_trajectory,
    discover,
    load,
    normalize_trajectory_artifact,
    resolve,
    to_k3,
    trajectory_from_session,
    trajectory_from_sessions,
    verify_trajectory_integrity,
)


def ev(seq: float, event: str, **kw):
    return {"ts": seq, "seq": int(seq), "event": event, **kw}


def test_projection_invariants():
    _self_check()


def test_result_without_a_call_still_lands():
    """An orphaned result must not vanish — a dropped call row is the common
    cause, and silently discarding its result would hide the gap."""
    m = _messages([ev(1, "tool_result", tool="Bash", status="ok")])
    assert m == [
        {
            "role": "tool",
            "run": 0,
            "turn_id": "",
            "results": [{"tool": "Bash", "index": 0, "call_id": "", "status": "ok", "summary": ""}],
        }
    ]


def test_seq_restart_across_runs_does_not_interleave(tmp_path):
    """``seq`` restarts at 1 per SessionTranscript instance, so 189 of 14,970
    real files carry decreasing seq. Ordering by seq alone spliced those runs
    into one conversation and dropped the earlier ones."""
    path = tmp_path / "s-multi.jsonl"
    path.write_text(
        "\n".join(
            json.dumps(r)
            for r in [
                {"ts": 10.0, "seq": 1, "event": "session_start"},
                {"ts": 11.0, "seq": 2, "event": "user_message", "text": "first"},
                {"ts": 12.0, "seq": 3, "event": "session_end"},
                {"ts": 20.0, "seq": 1, "event": "session_start"},
                {"ts": 21.0, "seq": 2, "event": "user_message", "text": "second"},
            ]
        )
    )
    msgs = _messages(_rows(path))
    assert [(m["run"], m["content"]) for m in msgs] == [(0, "first"), (1, "second")]


def test_dialogue_after_session_end_opens_a_new_run():
    """7 real files keep emitting dialogue after session_end with no following
    start; those 23 events used to be credited to the run that already closed."""
    msgs = _messages(
        [
            ev(1, "session_start"),
            ev(2, "user_message", text="a"),
            ev(3, "session_end"),
            ev(4, "user_message", text="b"),
        ]
    )
    assert [(m["run"], m["content"]) for m in msgs] == [(0, "a"), (1, "b")]


def test_file_with_no_session_start_is_one_run():
    msgs = _messages([ev(1, "user_message", text="a"), ev(2, "assistant_message", text="b")])
    assert {m["run"] for m in msgs} == {0}


def test_call_id_beats_order_and_pairing_reports_the_rule():
    """Two concurrent calls to the same tool returning out of order cross under
    FIFO-by-name; the id decides, and ``pairing`` states which rule was used."""
    msgs = _messages(
        [
            ev(1, "tool_call", tool="Bash", input="{}", call_id="a"),
            ev(2, "tool_call", tool="Bash", input="{}", call_id="b"),
            ev(3, "tool_result", tool="Bash", status="ok", call_id="b"),
            ev(4, "tool_result", tool="Bash", status="ok", call_id="a"),
        ]
    )
    assert [r["index"] for r in msgs[1]["results"]] == [1, 0]
    assert _pairing(msgs) == {
        "results": 2,
        "by_call_id": 2,
        "positional": 0,
        "mode": "call_id",
    }


def test_mixed_call_id_falls_back_per_result():
    """Rows written before the id was threaded through sit next to rows written
    after it, so the rule is chosen per result, not per file."""
    msgs = _messages(
        [
            ev(1, "tool_call", tool="Read", input="{}", call_id="x"),
            ev(2, "tool_call", tool="Grep", input="{}"),
            ev(3, "tool_result", tool="Grep", status="ok"),
            ev(4, "tool_result", tool="Read", status="ok", call_id="x"),
        ]
    )
    p = _pairing(msgs)
    assert (p["by_call_id"], p["positional"], p["mode"]) == (1, 1, "positional")


def test_stale_pending_does_not_leak_across_runs():
    """A call left unanswered when a run ends must not absorb the next run's
    result — the pending table is cleared at the boundary."""
    msgs = _messages(
        [
            ev(1, "session_start"),
            ev(2, "tool_call", tool="Read", input="{}"),
            ev(3, "session_start"),
            ev(4, "tool_call", tool="Read", input="{}"),
            ev(5, "tool_result", tool="Read", status="ok"),
        ]
    )
    tool_msgs = [m for m in msgs if m["role"] == "tool"]
    assert len(tool_msgs) == 1
    assert tool_msgs[0]["run"] == 1
    assert tool_msgs[0]["results"][0]["index"] == 0


def test_rows_survives_blank_and_malformed_lines(tmp_path):
    path = tmp_path / "s-bad.jsonl"
    path.write_text('{"ts": 1, "seq": 1, "event": "user_message", "text": "ok"}\n\n{ broken\n')
    assert [r["text"] for r in _rows(path)] == ["ok"]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('{"a": 1}', {"a": 1}),
        ("", {}),
        ({"a": 1}, {"a": 1}),
        ('{"a": ', {"_truncated": '{"a": '}),
        ("[1, 2]", {"_value": [1, 2]}),
    ],
)
def test_arguments_recovers_or_flags(raw, expected):
    """1,598 of 23,072 real tool_call rows were truncated mid-JSON on write; a
    fragment must be flagged rather than passed off as arguments."""
    assert _arguments(raw) == expected


def test_preflight_and_unmodelled_are_reported_not_dropped():
    """task_preflight is 18.4% of transcript rows and gui_step carries real
    screen trajectory; neither belongs in the message list, and neither may
    disappear without a count."""
    rows = [
        ev(1, "session_start"),
        {"ts": 1.5, "seq": 2, "event": "task_preflight", "payload": {"model": "m"}},
        ev(2, "gui_step", tool="computer"),
        ev(3, "handoff_triggered"),
    ]
    assert _preflight(rows) == [{"run": 0, "payload": {"model": "m"}}]
    assert _unmodelled(rows) == {"gui_step": 1, "handoff_triggered": 1}


def test_capability_graph_digest_resolves_against_the_first_emission():
    """The writer emits the graph once per run and then references its digest —
    43.4 MB across only 19 distinct values before. A later row carrying only the
    hash must still read back the full graph."""
    graph = {"provider": "anthropic", "tools": ["Read"]}
    rows = [
        ev(1, "session_start"),
        {
            "ts": 1.1,
            "seq": 2,
            "event": "task_preflight",
            "payload": {
                "capability_graph_sha256": "d1",
                "capability_graph": graph,
                "preflight": {"turn": 1},
            },
        },
        {
            "ts": 1.2,
            "seq": 3,
            "event": "task_preflight",
            "payload": {"capability_graph_sha256": "d1", "preflight": {"turn": 2}},
        },
    ]
    out = _preflight(rows)
    assert [e["payload"]["capability_graph"] for e in out] == [graph, graph]
    assert [e["payload"]["preflight"]["turn"] for e in out] == [1, 2]


def test_unknown_capability_graph_digest_is_left_unresolved():
    """A digest whose full emission was rotated away must not silently resolve
    to some other run's graph."""
    rows = [
        ev(1, "session_start"),
        {
            "ts": 1.1,
            "seq": 2,
            "event": "task_preflight",
            "payload": {"capability_graph_sha256": "gone", "preflight": {}},
        },
    ]
    assert "capability_graph" not in _preflight(rows)[0]["payload"]


def test_resolve_rejects_unknown_session():
    with pytest.raises(FileNotFoundError):
        resolve("no-such-session-id-exists")


def test_discover_rejects_unknown_harness():
    with pytest.raises(ValueError, match="unknown harness"):
        discover("hermes")


def test_load_reads_a_geode_file_end_to_end(tmp_path):
    path = tmp_path / "s-e2e.jsonl"
    path.write_text(
        "\n".join(
            json.dumps(r)
            for r in [
                {"ts": 1, "seq": 1, "event": "session_start"},
                {"ts": 2, "seq": 2, "event": "user_message", "text": "hi"},
                {"ts": 3, "seq": 3, "event": "tool_call", "tool": "Read", "input": "{}"},
                {"ts": 4, "seq": 4, "event": "tool_result", "tool": "Read", "status": "ok"},
                {"ts": 5, "seq": 5, "event": "assistant_message", "text": "done"},
            ]
        )
    )
    out = load(path, evidence=False)
    assert out["harness"] == "geode"
    assert out["meta"]["runs"] == 1
    assert [m["role"] for m in out["messages"]] == ["user", "assistant", "tool", "assistant"]
    assert out["pairing"]["results"] == 1


def test_versioned_trajectory_builder_validates_and_adapts_to_k3():
    trajectory = build_trajectory(
        trajectory_id="traj-1",
        captured_at="2026-07-31T00:00:00Z",
        source={"harness": "test", "session": "s-1", "run": "r-1", "parents": None},
        events=[
            {"kind": "message.user", "actor": "user", "payload": {"content": "go"}},
            {
                "kind": "tool.called",
                "actor": "assistant",
                "call_id": "c-1",
                "payload": {"tool": "read", "arguments": {"path": "README.md"}},
            },
            {
                "kind": "tool.completed",
                "actor": "tool",
                "call_id": "c-1",
                "payload": {"tool": "read", "summary": "ok"},
            },
            {
                "kind": "message.assistant",
                "actor": "assistant",
                "payload": {"content": "done"},
            },
        ],
        outcome={"result": "pass"},
        provenance={"store": "test"},
        privacy={"review_state": "local"},
        trajectory_class=("dialogue", "tool"),
    )

    assert trajectory["schema_id"] == "geode.trajectory@1"
    assert [event["ordinal"] for event in trajectory["events"]] == [1, 2, 3, 4]
    assert trajectory["integrity"]["record_count"] == 4
    assert trajectory["integrity"]["quality"]["tool_pairing"] == {
        "calls": 1,
        "results": 1,
        "paired": 1,
        "orphan_calls": 0,
        "orphan_results": 0,
        "missing_call_ids": 0,
    }
    k3 = to_k3(trajectory)
    assert k3["source_schema"] == "geode.trajectory@1"
    assert k3["pairing"]["mode"] == "call_id"
    assert [message["role"] for message in k3["messages"]] == [
        "user",
        "assistant",
        "tool",
        "assistant",
    ]


def test_trajectory_builds_from_canonical_sqlite_history(tmp_path):
    from core.observability.session_timeline import SessionTimeline

    db = tmp_path / "sessions.db"
    timeline = SessionTimeline("s-sql", db_path=db)
    timeline.bind_turn("t-1")
    timeline.record_session_start()
    timeline.record_user_message("hello")
    timeline.record_assistant_message("done")
    timeline.record_session_end()

    trajectory = trajectory_from_session("s-sql", db_path=db)
    assert trajectory["source"]["session"] == "s-sql"
    assert [event["turn_id"] for event in trajectory["events"]] == ["t-1"] * 4
    assert trajectory["integrity"]["complete"] is True


def test_trajectory_marks_orphaned_tool_event_incomplete():
    trajectory = build_trajectory(
        trajectory_id="traj-orphan",
        captured_at="2026-07-31T00:00:00Z",
        source={"harness": "test", "session": "s-1"},
        events=[
            {
                "event_id": "call-without-result",
                "kind": "tool.called",
                "actor": "assistant",
                "call_id": "c-1",
                "payload": {"tool": "read"},
            }
        ],
        outcome={},
        provenance={},
        privacy={},
    )

    assert trajectory["integrity"]["complete"] is False
    assert trajectory["integrity"]["quality"]["tool_pairing"]["orphan_calls"] == 1


def test_turn_scoped_event_without_turn_id_is_scope_incomplete():
    trajectory = build_trajectory(
        trajectory_id="traj-missing-turn",
        captured_at="2026-07-31T00:00:00Z",
        source={"harness": "test", "session": "s-1"},
        events=[
            {
                "kind": "message.user",
                "actor": "user",
                "payload": {"content": "hello"},
            }
        ],
        outcome={},
        provenance={},
        privacy={},
    )

    correlation = trajectory["integrity"]["quality"]["correlation"]
    assert correlation["turn_id_required"] == 1
    assert correlation["turn_id_missing"] == 1
    assert trajectory["integrity"]["scope_complete"] is False


def test_trajectory_rejects_duplicate_event_ids():
    with pytest.raises(ValueError, match="event_id values must be unique"):
        build_trajectory(
            trajectory_id="traj-duplicate",
            captured_at="2026-07-31T00:00:00Z",
            source={"harness": "test", "session": "s-1"},
            events=[
                {"event_id": "same", "kind": "a", "actor": "agent", "payload": {}},
                {"event_id": "same", "kind": "b", "actor": "agent", "payload": {}},
            ],
            outcome={},
            provenance={},
            privacy={},
        )


def test_trajectory_integrity_rejects_false_producer_claims():
    trajectory = build_trajectory(
        trajectory_id="traj-integrity",
        captured_at="2026-07-31T00:00:00Z",
        source={"harness": "test", "session": "s-1"},
        events=[{"kind": "message.user", "actor": "user", "payload": {}}],
        outcome={},
        provenance={},
        privacy={},
    )
    trajectory["integrity"]["quality"]["payload_issue_events"] = 7

    with pytest.raises(ValueError, match="quality does not match"):
        verify_trajectory_integrity(trajectory)


def test_dated_publication_trajectory_normalizes_without_rewrite():
    legacy = {
        "schema_id": "geode.trajectory@2026-07-31",
        "trajectory_id": "published-tau2",
        "captured_at": "2026-07-31T12:00:00",
        "published_at": "2026-07-31T03:00:00Z",
        "observed_on": "2026-07-31",
        "trajectory_class": ["dialogue", "tool"],
        "source": {"harness": "tau2", "run": "run-1", "session": None},
        "events": [
            {
                "sequence": 1,
                "timestamp": "2026-07-31T12:00:01",
                "actor": "assistant",
                "kind": "tool_call",
                "payload": {"call_id": "c-1", "tool": "read"},
            },
            {
                "sequence": 2,
                "timestamp": "2026-07-31T12:00:02",
                "actor": "environment",
                "kind": "tool_result",
                "payload": {"call_id": "c-1", "result": "ok"},
            },
        ],
        "outcome": {"result": "pass"},
        "integrity": {"record_count": 2},
        "privacy": {"review_state": "reviewed"},
        "provenance": {"adapter": "legacy"},
    }

    normalized = normalize_trajectory_artifact(legacy)

    assert legacy["schema_id"] == "geode.trajectory@2026-07-31"
    assert normalized["schema_id"] == "geode.trajectory@1"
    assert normalized["source"]["session"] == "run-1"
    assert normalized["integrity"]["quality"]["tool_pairing"]["paired"] == 1
    assert normalized["provenance"]["migrated_from_schema_id"] == legacy["schema_id"]


def test_dated_publication_preserves_ts_and_defaults_to_incomplete_replay():
    legacy = {
        "schema_id": "geode.trajectory@2026-07-31",
        "trajectory_id": "published-hook",
        "captured_at": "2026-07-30T23:49:51Z",
        "source": {"harness": "hook-e2e", "run": "run-1", "session": None},
        "events": [
            {
                "sequence": 1,
                "ts": "2026-07-30T23:49:52Z",
                "actor": "extension",
                "kind": "public_hook",
                "payload": {},
            }
        ],
        "integrity": {
            "record_count": 1,
            "fidelity": "raw prompts and tool bodies remain unpublished",
        },
        "privacy": {
            "review_state": "reviewed",
            "redactions": [{"type": "content_reduction"}],
        },
    }

    first = normalize_trajectory_artifact(legacy)
    second = normalize_trajectory_artifact(legacy)

    assert first["events"][0]["occurred_at"] == "2026-07-30T23:49:52Z"
    assert first["events"][0]["event_id"] == second["events"][0]["event_id"]
    assert first["integrity"]["complete"] is False
    assert any("replay completeness" in reason for reason in first["integrity"]["incompleteness"])


def test_tool_pairing_is_ordered_and_scoped_by_session_and_turn():
    trajectory = build_trajectory(
        trajectory_id="traj-scoped-pairing",
        captured_at="2026-07-31T00:00:00Z",
        source={"harness": "test", "session": "s-1"},
        events=[
            {
                "kind": "tool.completed",
                "session_id": "s-1",
                "turn_id": "t-1",
                "call_id": "same",
                "payload": {},
            },
            {
                "kind": "tool.called",
                "session_id": "s-2",
                "turn_id": "t-2",
                "call_id": "same",
                "payload": {},
            },
        ],
        outcome={},
        provenance={},
        privacy={},
    )

    pairing = trajectory["integrity"]["quality"]["tool_pairing"]
    assert pairing["paired"] == 0
    assert pairing["orphan_calls"] == 1
    assert pairing["orphan_results"] == 1
    assert trajectory["integrity"]["complete"] is False


def test_trajectory_aggregates_sessions_in_database_order(tmp_path):
    from core.observability.session_timeline import SessionTimeline

    db = tmp_path / "sessions.db"
    first = SessionTimeline("s-first", db_path=db)
    second = SessionTimeline("s-second", db_path=db)
    first.record_user_message("one")
    second.record_user_message("two")
    first.record_assistant_message("three")

    trajectory = trajectory_from_sessions(
        ("s-second", "s-first", "s-second"),
        trajectory_id="benchmark-run",
        source={
            "harness": "test",
            "run": "run-1",
            "session": "run-1",
            "parents": ["s-second", "s-first"],
        },
        db_path=db,
    )

    assert [event["payload"]["content"] for event in trajectory["events"]] == [
        "one",
        "two",
        "three",
    ]
    assert trajectory["integrity"]["record_count"] == 3
