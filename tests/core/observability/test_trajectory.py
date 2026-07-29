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
    discover,
    load,
    resolve,
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
