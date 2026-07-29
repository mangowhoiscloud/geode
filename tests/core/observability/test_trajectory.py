from core.observability.trajectory import _messages, _self_check


def test_projection_invariants():
    _self_check()


def test_result_without_a_call_still_lands():
    """An orphaned result must not vanish — a dropped call row is the common
    cause, and silently discarding its result would hide the gap."""
    m = _messages([{"seq": 1, "event": "tool_result", "tool": "Bash", "status": "ok"}])
    assert m == [
        {
            "role": "tool",
            "run": 0,
            "turn_id": "",
            "results": [{"tool": "Bash", "index": 0, "call_id": "", "status": "ok", "summary": ""}],
        }
    ]
