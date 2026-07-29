"""One K3-shaped message list over the agent trajectories on this machine.

Reading a session used to mean opening ``transcripts/`` for the dialogue and
``evidence/`` for the judgment rows and reconciling them by hand, because each
writer keeps its own row shape — and a Codex session was a third format again.
This module is the join: it replays either harness into the channel/tool-index
message list that Kimi K3's chat template uses (arXiv:2607.24653 Appendix F),
so a trajectory is one ordered object regardless of which agent produced it.

Two harnesses are read today, and they fail in opposite directions, which is
why the format has to carry both cases rather than assume the better one:

* ``geode`` — ``~/.geode/transcripts/``. No thinking event exists, so ``think``
  is always empty, and ``record_tool_result`` carries no call id, so calls and
  results are paired by order.
* ``codex`` — ``~/.codex/sessions/``. Emits ``reasoning`` items that fill
  ``think``, and every tool item carries ``call_id``, so pairing is exact.

Three roles, mirroring K3's channel split:

    {"role": "user",      "content": str}
    {"role": "assistant", "think": str, "response": str,
                          "tools": [{"tool": str, "index": int, "arguments": dict}]}
    {"role": "tool",      "results": [{"tool": str, "index": int,
                                       "status": str, "summary": str}]}

``index`` numbers the parallel calls *within one assistant message* and the
matching result repeats it, which is what makes a result attributable to its
call when several are in flight. ``think`` is always present even when empty,
because K3 keeps the channel so message structure stays constant across turns.

Read-only. It does not write, migrate, or alter the on-disk stores.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from core.paths import GEODE_HOME, GLOBAL_TRANSCRIPTS_DIR

__all__ = ["discover", "load", "merge", "resolve"]

_DIALOGUE_EVENTS = {"user_message", "assistant_message", "tool_call", "tool_result"}


CODEX_SESSIONS_DIR = Path.home() / ".codex" / "sessions"


def resolve(session: str | Path) -> Path:
    """Return the trajectory file for a session id, or the path itself."""
    p = Path(session)
    if p.is_file():
        return p
    hits = sorted(GLOBAL_TRANSCRIPTS_DIR.glob(f"*/{session}.jsonl"))
    if hits:
        return hits[0]
    hits = sorted(CODEX_SESSIONS_DIR.glob(f"**/*{session}*.jsonl"))
    if hits:
        return hits[0]
    raise FileNotFoundError(f"no trajectory for session {session!r}")


def discover(harness: str) -> list[Path]:
    """Every trajectory file for one harness, oldest first by mtime."""
    if harness == "geode":
        paths = GLOBAL_TRANSCRIPTS_DIR.glob("*/*.jsonl")
    elif harness == "codex":
        paths = CODEX_SESSIONS_DIR.glob("**/*.jsonl")
    else:
        raise ValueError(f"unknown harness {harness!r}")
    return sorted(paths, key=lambda p: p.stat().st_mtime)


def _arguments(raw: Any) -> dict[str, Any]:
    """Recover typed tool arguments from the transcript's serialized ``input``.

    ``record_tool_call`` stores ``json.dumps(...)`` truncated to 300 chars, so
    long arguments reach disk as a fragment that no longer parses. Restoring the
    dict when it does parse keeps K3's typed-argument property; flagging it when
    it does not stops a truncated blob from being read as real arguments.
    """
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {"_truncated": str(raw)}
    return parsed if isinstance(parsed, dict) else {"_value": parsed}


def _rows(path: Path) -> list[dict[str, Any]]:
    out = []
    for line in path.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # a truncated tail row must not sink the whole replay
    # ``seq`` restarts at 1 for every SessionTranscript instance, so a session id
    # reused across runs produces repeating and decreasing seq within one file
    # (189 of 14,970 decrease, 357 repeat). Ordering by seq alone interleaves
    # those runs; ``ts`` separates them and the stable sort keeps append order
    # for rows written inside the same clock tick.
    out.sort(key=lambda r: (r.get("ts", 0.0), r.get("seq", 0)))
    return out


def _messages(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    msgs: list[dict[str, Any]] = []
    asst: dict[str, Any] | None = None
    tool: dict[str, Any] | None = None
    pending: list[tuple[str, int]] = []  # (tool name, index) awaiting a result
    by_call_id: dict[str, int] = {}
    starts = 0
    ended = False

    def run() -> int:
        # dialogue after session_end with no new session_start belongs to its own
        # run, not to the one that already closed
        return max(0, starts - 1) + (1 if ended else 0)

    def open_asst() -> dict[str, Any]:
        nonlocal asst
        if asst is None:
            # turn_id stays empty: GEODE records no turn key, and dropping the
            # field would make the gap invisible once both harnesses are merged
            asst = {
                "role": "assistant",
                "run": run(),
                "turn_id": "",
                "think": "",
                "response": "",
                "tools": [],
            }
            msgs.append(asst)
        return asst

    for r in rows:
        event = r.get("event")

        if event in ("session_start", "session_end"):
            # One transcript file accumulates every run that reused this
            # session_id, so a flat message list would splice separate
            # conversations into one. Runs are numbered, not merged.
            # session_end closes the run too: 7 files continue emitting dialogue
            # after an end with no following start, and those 23 events would
            # otherwise be attributed to the run that already finished.
            starts += 1 if event == "session_start" else 0
            ended = event == "session_end"
            asst = tool = None
            pending.clear()
            by_call_id.clear()
            continue

        if event not in _DIALOGUE_EVENTS:
            continue

        if ended:
            starts += 1
            ended = False

        if event == "user_message":
            asst = tool = None
            msgs.append({"role": "user", "run": run(), "turn_id": "", "content": r.get("text", "")})

        elif event == "tool_call":
            tool = None
            m = open_asst()
            index = len(m["tools"])
            name = r.get("tool", "")
            call_id = r.get("call_id") or ""
            m["tools"].append(
                {
                    "tool": name,
                    "index": index,
                    "call_id": call_id,
                    "arguments": _arguments(r.get("input")),
                }
            )
            pending.append((name, index))
            if call_id:
                by_call_id[call_id] = index

        elif event == "tool_result":
            asst = None
            if tool is None:
                tool = {"role": "tool", "run": run(), "turn_id": "", "results": []}
                msgs.append(tool)
            name = r.get("tool", "")
            call_id = r.get("call_id") or ""
            if call_id and call_id in by_call_id:
                index = by_call_id.pop(call_id)
            else:
                # Rows written before call_id was threaded through carry no id, so
                # order is the only signal left. Two concurrent calls to the same
                # tool returning out of order will cross; ``pairing`` reports which
                # rule produced each index so a consumer can tell them apart.
                index = len(tool["results"])
                for i, (pname, pindex) in enumerate(pending):
                    if pname == name:
                        index = pindex
                        pending.pop(i)
                        break
            tool["results"].append(
                {
                    "tool": name,
                    "index": index,
                    "call_id": call_id,
                    "status": r.get("status", ""),
                    "summary": r.get("summary", ""),
                }
            )

        elif event == "assistant_message":
            tool = None
            open_asst()["response"] = r.get("text", "")
            asst = None  # a text response closes the message

    return msgs


_CODEX_CALLS = {"function_call", "custom_tool_call", "tool_search_call", "local_shell_call"}
_CODEX_OUTPUTS = {
    "function_call_output",
    "custom_tool_call_output",
    "tool_search_output",
    "local_shell_call_output",
}


def _codex_text(content: Any) -> str:
    """Flatten a Responses-API content list into plain text."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    return "".join(c.get("text", "") for c in content if isinstance(c, dict))


def _codex_call_args(payload: dict[str, Any]) -> dict[str, Any]:
    """Arguments for one Codex tool call, keeping free-form text unescaped.

    ``custom_tool_call`` carries its argument as raw text (an ``apply_patch``
    hunk, a shell script) rather than JSON. Running it through the JSON parser
    would flag valid input as malformed, so the raw form is kept under ``input``
    — which is also K3's stated reason for typing arguments instead of nesting
    an escaped JSON string.
    """
    if payload.get("type") == "custom_tool_call":
        return {"input": payload.get("input", "")}
    raw = payload.get("arguments")
    if isinstance(raw, dict):
        return raw
    return _arguments(raw)


def _turn(payload: dict[str, Any]) -> str:
    """Codex's turn key, the middle level of its session → turn → call hierarchy.

    GEODE has no equivalent: a transcript carries only a session id and a
    per-row ``seq``, so a group of rows cannot be attributed to one turn. Keeping
    the field here makes the gap visible rather than flattening both harnesses to
    the weaker key.
    """
    meta = payload.get("internal_chat_message_metadata_passthrough") or {}
    return meta.get("turn_id", "") if isinstance(meta, dict) else ""


def _codex_messages(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Project a Codex rollout onto the same message list as a GEODE session."""
    msgs: list[dict[str, Any]] = []
    asst: dict[str, Any] | None = None
    tool: dict[str, Any] | None = None
    think: list[str] = []
    index_of: dict[str, int] = {}  # call_id -> index within its assistant message
    name_of: dict[str, str] = {}
    turn = ""

    def open_asst() -> dict[str, Any]:
        nonlocal asst
        if asst is None:
            asst = {
                "role": "assistant",
                "run": 0,
                "turn_id": turn,
                "think": "",
                "response": "",
                "tools": [],
            }
            msgs.append(asst)
        if think:
            # append: several reasoning items can land in one assistant message
            # when parallel calls are interleaved, and assigning would drop all
            # but the last
            joined = "\n".join(think).strip()
            asst["think"] = f"{asst['think']}\n{joined}".strip() if asst["think"] else joined
            think.clear()
        return asst

    for r in rows:
        if r.get("type") != "response_item":
            continue
        p = r.get("payload") or {}
        kind = p.get("type")
        turn = _turn(p) or turn

        if kind == "reasoning":
            # encrypted_content is opaque to us; the summary is the readable trace
            think.extend(
                s.get("text", "")
                for s in (p.get("summary") or [])
                if isinstance(s, dict) and s.get("text")
            )

        elif kind == "message":
            role = p.get("role")
            text = _codex_text(p.get("content"))
            if role == "assistant":
                tool = None
                open_asst()["response"] = text
                asst = None
            else:
                asst = tool = None
                msgs.append(
                    {
                        "role": "system" if role == "developer" else "user",
                        "run": 0,
                        "turn_id": turn,
                        "content": text,
                    }
                )

        elif kind in _CODEX_CALLS:
            tool = None
            m = open_asst()
            index = len(m["tools"])
            name = p.get("name") or kind
            call_id = p.get("call_id") or ""
            m["tools"].append(
                {
                    "tool": name,
                    "index": index,
                    "arguments": _codex_call_args(p),
                    "call_id": call_id,
                }
            )
            index_of[call_id] = index
            name_of[call_id] = name

        elif kind in _CODEX_OUTPUTS:
            asst = None
            if tool is None:
                tool = {"role": "tool", "run": 0, "turn_id": turn, "results": []}
                msgs.append(tool)
            call_id = p.get("call_id") or ""
            output = p.get("output")
            if output is None and p.get("tools") is not None:
                output = json.dumps(p["tools"], ensure_ascii=False)
            tool["results"].append(
                {
                    "tool": name_of.get(call_id, kind),
                    "index": index_of.get(call_id, len(tool["results"])),
                    "status": p.get("status", "") or "",
                    "summary": output if isinstance(output, str) else "",
                    "call_id": call_id,
                }
            )

    return msgs


_MODELLED_EVENTS = _DIALOGUE_EVENTS | {"session_start", "session_end", "task_preflight"}


def _preflight(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per-run environment snapshot — GEODE's analogue of Codex ``turn_context``.

    ``task_preflight`` is 18.4% of all transcript rows (185,688 of 1,009,468) and
    records the capability graph and required evidence the run started under. It
    is not conversation, so it stays out of the message list, but dropping it
    loses the answer to "what was this run configured to do".
    """
    out = []
    run = 0
    for r in rows:
        event = r.get("event")
        if event == "session_start":
            run += 1
        elif event == "task_preflight":
            payload = r.get("payload")
            out.append({"run": max(0, run - 1), "payload": payload if payload else {}})
    return out


def _unmodelled(rows: list[dict[str, Any]]) -> dict[str, int]:
    """Events this projection drops, counted rather than silently discarded."""
    counts: dict[str, int] = {}
    for r in rows:
        event = r.get("event")
        if event and event not in _MODELLED_EVENTS:
            counts[str(event)] = counts.get(str(event), 0) + 1
    return counts


def _pairing(messages: list[dict[str, Any]]) -> dict[str, Any]:
    """How each tool result got its index — exactly, or by guessing at order.

    A consumer cannot otherwise tell the two apart: both produce the same
    ``index`` field, but only the id-matched one is a fact.
    """
    results = [r for m in messages if m["role"] == "tool" for r in m["results"]]
    exact = sum(1 for r in results if r.get("call_id"))
    return {
        "results": len(results),
        "by_call_id": exact,
        "positional": len(results) - exact,
        "mode": "call_id" if exact == len(results) and results else "positional",
    }


def _codex_meta(rows: list[dict[str, Any]]) -> dict[str, Any]:
    for r in rows:
        if r.get("type") == "session_meta":
            p = r.get("payload") or {}
            return {
                "session_id": p.get("session_id") or p.get("id") or "",
                "cwd": p.get("cwd", ""),
                "cli_version": p.get("cli_version", ""),
                "originator": p.get("originator", ""),
                "forked_from_id": p.get("forked_from_id") or "",
            }
    return {}


def _is_codex(rows: list[dict[str, Any]]) -> bool:
    return any(r.get("type") in {"session_meta", "response_item"} for r in rows[:20])


def load(session: str | Path, *, evidence: bool = True) -> dict[str, Any]:
    """Replay one session as a K3-shaped trajectory.

    ``evidence`` rows are returned alongside rather than interleaved: they are
    judgment records keyed by ``kind``, not conversation turns, and folding them
    into the message list would imply an ordering the writers never guaranteed.
    """
    path = resolve(session)
    rows = _rows(path)

    if _is_codex(rows):
        meta = _codex_meta(rows)
        codex_msgs = _codex_messages(rows)
        return {
            "harness": "codex",
            "session_id": meta.get("session_id") or path.stem,
            "source": str(path),
            "meta": meta,
            "pairing": _pairing(codex_msgs),
            "messages": codex_msgs,
        }

    session_id = path.stem
    messages = _messages(rows)
    out: dict[str, Any] = {
        "harness": "geode",
        "session_id": session_id,
        "source": str(path),
        "meta": {
            "runs": max((m["run"] for m in messages), default=-1) + 1,
            "preflight": _preflight(rows),
            "unmodelled_events": _unmodelled(rows),
        },
        "pairing": _pairing(messages),
        "messages": messages,
    }
    if evidence:
        ev = GEODE_HOME / "evidence" / f"{session_id}.jsonl"
        out["evidence"] = _rows(ev) if ev.is_file() else []
        out["hooks"] = _hooks(session_id)
    return out


def _hooks(session_id: str) -> list[dict[str, Any]]:
    """Hook events for one session, joined on the trajectory's own key.

    ``hook_events`` names the column ``session_key`` while the transcript calls
    the same value ``session_id``; the delegate writer fills both from one
    source, so this is a real join rather than a guess. The orchestrator lane
    (``subject:*``) uses ``session_key`` for a different thing and simply misses,
    which is the correct outcome — it has no transcript to attach to.
    """
    try:
        from core.memory.session_manager import _get_default_db_path

        db = _get_default_db_path()
        if not db.exists():
            return []
        # read-only: this database is live, and a reader must never lock it
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            cur = con.execute(
                "SELECT occurred_at, event, action, entity_type, entity_id, status, "
                "level, blocked, block_reason, run_id FROM hook_events "
                "WHERE session_key = ? ORDER BY occurred_at, id",
                (session_id,),
            )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]
        finally:
            con.close()
    except sqlite3.Error:
        return []


def merge(
    limit: int | None = None, harnesses: tuple[str, ...] = ("geode", "codex")
) -> dict[str, Any]:
    """Every discoverable trajectory in one object, newest ``limit`` per harness.

    ``coverage`` reports how many files each harness has and how many were read,
    so a bounded export never reads as a complete one. Files that fail to parse
    are counted in ``failed`` rather than dropped silently.
    """
    out: list[dict[str, Any]] = []
    coverage: dict[str, Any] = {}
    for harness in harnesses:
        found = discover(harness)
        picked = found[-limit:] if limit else found
        failed = 0
        for path in picked:
            try:
                out.append(load(path))
            except Exception:
                failed += 1
        coverage[harness] = {
            "available": len(found),
            "read": len(picked) - failed,
            "skipped_by_limit": len(found) - len(picked),
            "failed": failed,
        }
    msgs = sum(len(t["messages"]) for t in out)
    calls = sum(len(m["tools"]) for t in out for m in t["messages"] if m["role"] == "assistant")
    return {
        "schema": "k3-shaped/1",
        "coverage": coverage,
        "totals": {"trajectories": len(out), "messages": msgs, "tool_calls": calls},
        "trajectories": out,
    }


def _self_check() -> None:
    # one transcript file, two runs that reused the session id
    two_runs = _messages(
        [
            {"seq": 1, "event": "session_start"},
            {"seq": 2, "event": "tool_call", "tool": "Read", "input": "{}"},
            {"seq": 3, "event": "tool_result", "tool": "Read", "status": "ok"},
            {"seq": 4, "event": "session_end"},
            {"seq": 5, "event": "session_start"},
            {"seq": 6, "event": "tool_call", "tool": "Read", "input": "{}"},
        ]
    )
    assert [m["run"] for m in two_runs] == [0, 0, 1], two_runs
    # a call left open by run 0 must not absorb run 1's result
    assert two_runs[0]["tools"][0]["index"] == 0 and two_runs[2]["tools"][0]["index"] == 0

    # call_id, once written, outranks order even when results come back swapped
    paired = _messages(
        [
            {"seq": 1, "event": "tool_call", "tool": "Bash", "input": "{}", "call_id": "a"},
            {"seq": 2, "event": "tool_call", "tool": "Bash", "input": "{}", "call_id": "b"},
            {"seq": 3, "event": "tool_result", "tool": "Bash", "status": "ok", "call_id": "b"},
            {"seq": 4, "event": "tool_result", "tool": "Bash", "status": "ok", "call_id": "a"},
        ]
    )
    assert [r["index"] for r in paired[1]["results"]] == [1, 0], paired[1]
    assert _pairing(paired)["mode"] == "call_id"
    assert _pairing(two_runs)["positional"] == 1

    rows = [
        {"seq": 1, "event": "user_message", "text": "hi"},
        {"seq": 2, "event": "tool_call", "tool": "Read", "input": '{"p": "a"}'},
        {"seq": 3, "event": "tool_call", "tool": "Grep", "input": '{"q": "x"'},
        {"seq": 4, "event": "tool_result", "tool": "Grep", "status": "ok", "summary": "g"},
        {"seq": 5, "event": "tool_result", "tool": "Read", "status": "ok", "summary": "r"},
        {"seq": 6, "event": "assistant_message", "text": "done"},
    ]
    m = _messages(rows)
    assert [x["role"] for x in m] == ["user", "assistant", "tool", "assistant"], m
    assert m[1]["tools"] == [
        {"tool": "Read", "index": 0, "call_id": "", "arguments": {"p": "a"}},
        # truncated on write, so it is flagged rather than passed off as arguments
        {"tool": "Grep", "index": 1, "call_id": "", "arguments": {"_truncated": '{"q": "x"'}},
    ]
    # out-of-order results keep their call's index, not their arrival position
    assert [(r["tool"], r["index"]) for r in m[2]["results"]] == [("Grep", 1), ("Read", 0)]
    assert m[3]["response"] == "done" and m[3]["think"] == ""

    def item(payload: dict[str, Any]) -> dict[str, Any]:
        return {"type": "response_item", "payload": payload}

    def reasoning(text: str) -> dict[str, Any]:
        return item({"type": "reasoning", "summary": [{"type": "summary_text", "text": text}]})

    c = _codex_messages(
        [
            item({"type": "message", "role": "user", "content": [{"text": "go"}]}),
            reasoning("first"),
            item(
                {
                    "type": "function_call",
                    "name": "shell",
                    "call_id": "c1",
                    "arguments": '{"cmd": "ls"}',
                }
            ),
            reasoning("second"),
            item(
                {
                    "type": "custom_tool_call",
                    "name": "apply_patch",
                    "call_id": "c2",
                    "input": "*** Begin Patch",
                }
            ),
            item({"type": "function_call_output", "call_id": "c2", "output": "patched"}),
            item({"type": "function_call_output", "call_id": "c1", "output": "a\nb"}),
            item({"type": "message", "role": "assistant", "content": [{"text": "ok"}]}),
        ]
    )
    assert [x["role"] for x in c] == ["user", "assistant", "tool", "assistant"], c
    # both reasoning blocks survive; assigning instead of appending dropped "first"
    assert c[1]["think"] == "first\nsecond", c[1]["think"]
    assert [(t["tool"], t["index"]) for t in c[1]["tools"]] == [("shell", 0), ("apply_patch", 1)]
    # a patch hunk is raw text, not JSON, and must not be flagged as malformed
    assert c[1]["tools"][1]["arguments"] == {"input": "*** Begin Patch"}
    # call_id pairing survives out-of-order returns
    assert [(r["tool"], r["index"]) for r in c[2]["results"]] == [("apply_patch", 1), ("shell", 0)]
    assert c[3]["response"] == "ok"

    # every message carries turn_id in both harnesses, empty where GEODE has none
    assert all("turn_id" in x for x in m + c)
    t = _codex_messages(
        [
            item(
                {
                    "type": "message",
                    "role": "user",
                    "content": [{"text": "go"}],
                    "internal_chat_message_metadata_passthrough": {"turn_id": "t1"},
                }
            ),
            item({"type": "function_call", "name": "shell", "call_id": "c1", "arguments": "{}"}),
        ]
    )
    # the turn key carries forward to rows that omit it
    assert [x["turn_id"] for x in t] == ["t1", "t1"], t
    print("ok")


if __name__ == "__main__":
    import sys

    args = sys.argv[1:]
    if "--self-check" in args:
        _self_check()
    elif "--merge" in args:
        rest = [a for a in args if a != "--merge"]
        limit = int(rest[0]) if rest else None
        print(json.dumps(merge(limit), ensure_ascii=False, indent=2))
    elif args:
        print(json.dumps(load(args[0]), ensure_ascii=False, indent=2))
    else:
        print(__doc__)
