"""R6.9 COLLAB-005: persistent forks through SessionCheckpoint/SessionManager."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from core.agent.conversation import ConversationContext
from core.agent.loop._phases import _repair_incomplete_tool_round
from core.config.session import SessionModelConfig
from core.memory import session_checkpoint
from core.memory.collaboration import CollaborationStore
from core.memory.session_checkpoint import (
    SessionCheckpoint,
    SessionForkError,
    SessionState,
    SessionStatus,
    completed_turn_boundaries,
)
from core.memory.session_manager import SessionManager
from core.memory.session_peers import SessionPrincipal, fork_session
from core.observability.session_timeline import SessionTimeline

OPERATOR = SessionPrincipal(operator_intent=True)
SETTINGS = SessionModelConfig(model="gpt-test", effort="high", source="payg")


def _turn(n: int, *, tools: int = 0) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": f"task {n}", "metadata": {"origin": "user_input"}}
    ]
    for t in range(tools):
        call_id = f"call-{n}-{t}"
        messages.append(
            {
                "role": "assistant",
                "content": [{"type": "tool_use", "id": call_id, "name": "run_bash", "input": {}}],
                "metadata": {"effect_operations": {call_id: {"operation_id": f"op-{call_id}"}}},
            }
        )
        messages.append(
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": call_id}]}
        )
    messages.append({"role": "assistant", "content": f"done {n}"})
    return messages


def _save(base: Path, session_id: str, messages: list[dict[str, Any]], **fields: Any) -> None:
    SessionCheckpoint(base).save(
        SessionState(
            session_id=session_id,
            model="gpt-test",
            provider="openai",
            model_settings=SETTINGS,
            messages=messages,
            cognitive_state={"goal": "source-only"},
            loop_guards={"active_plan": {"steps": []}, "reflection_requires_redaction": True},
            **fields,
        )
    )


def _source_fingerprint(base: Path, session_id: str) -> tuple[Any, ...]:
    with sqlite3.connect(base / "sessions.db") as conn:
        rows = conn.execute(
            "SELECT seq, role, content, metadata FROM messages WHERE session_id = ? ORDER BY seq",
            (session_id,),
        ).fetchall()
        events = conn.execute(
            "SELECT * FROM session_events WHERE session_id = ? ORDER BY 1", (session_id,)
        ).fetchall()
    files = tuple((p.name, p.read_bytes()) for p in sorted((base / session_id).iterdir()))
    return rows, events, files


def _balanced(messages: list[dict[str, Any]]) -> bool:
    return bool(messages) and completed_turn_boundaries(messages)[-1] == len(messages)


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from core import paths

    monkeypatch.setattr(paths, "resolve_sessions_dir", lambda: tmp_path)
    return tmp_path


def test_operator_fork_copies_only_history_and_settings(project: Path) -> None:
    _save(project, "s-src", [*_turn(1, tools=2), *_turn(2)])
    timeline = SessionTimeline(
        "s-src", db_path=project / "sessions.db", projection_path=project / "e.jsonl"
    )
    timeline.record_user_message("task 1")
    before = _source_fingerprint(project, "s-src")

    receipt = fork_session(OPERATOR, "s-src")
    fork = SessionCheckpoint(project).load(receipt.session_id)

    assert fork is not None and receipt.session_id not in {"s-src", ""}
    assert receipt.to_dict()["turn_started"] is False and fork.status == "paused"
    assert fork.lineage["source_session_id"] == "s-src"
    assert fork.lineage["source_generation"] == 1
    assert fork.lineage["source_message_count"] == 8 == len(fork.messages)
    assert fork.lineage["forked_by"] == "operator" and len(fork.lineage["source_digest"]) == 64
    assert (fork.model, fork.provider, fork.model_settings) == ("gpt-test", "openai", SETTINGS)
    assert fork.round_idx == 0 and fork.cognitive_state == {} and fork.pending_verification == {}
    # Only the monotone redaction restriction survives; plans/approvals do not.
    assert fork.loop_guards == {"reflection_requires_redaction": True}
    assert all("effect_operations" not in m.get("metadata", {}) for m in fork.messages)
    assert _source_fingerprint(project, "s-src") == before

    meta = SessionManager(project / "sessions.db").get(receipt.session_id)
    assert meta is not None and (meta.source_session_id, meta.source_message_count) == ("s-src", 8)
    assert receipt.session_id in {s.session_id for s in SessionCheckpoint(project).list_resumable()}

    # Each side appends independently; later fork saves keep the lineage.
    _save(project, receipt.session_id, [*fork.messages, *_turn(3)])
    resumed = SessionCheckpoint(project).load(receipt.session_id)
    assert resumed is not None and resumed.lineage == fork.lineage
    assert _source_fingerprint(project, "s-src") == before


def test_bounded_truncation_keeps_balanced_groups_and_never_redispatches(project: Path) -> None:
    history = [message for n in range(12) for message in _turn(n, tools=n % 3)]
    _save(project, "s-long", history)
    state = SessionCheckpoint(project).fork_completed_turn(
        "s-long", forked_by="operator", max_messages=9
    )
    assert len(state.messages) <= 9 and state.messages[0]["content"].startswith("task ")
    assert _balanced(state.messages)
    assert state.lineage["source_window_start"] > 0

    recovered: list[Any] = []
    loop = SimpleNamespace(
        context=ConversationContext(messages=list(state.messages)),
        _session_id=state.session_id,
        _checkpoint=SessionCheckpoint(project),
        _tool_processor=SimpleNamespace(
            _executor=SimpleNamespace(
                _effect_receipts=SimpleNamespace(recover=lambda **kw: recovered.append(kw))
            )
        ),
        _save_checkpoint=lambda *_a, **_k: recovered.append("save"),
    )
    _repair_incomplete_tool_round(loop, "resume")
    assert recovered == [] and loop.context.messages == state.messages

    with pytest.raises(SessionForkError, match="bound"):
        SessionCheckpoint(project).fork_completed_turn(
            "s-long", forked_by="operator", max_messages=2
        )


@pytest.mark.parametrize(
    "tail",
    [
        [{"role": "user", "content": "new turn", "metadata": {"origin": "user_input"}}],
        [{"role": "assistant", "content": [{"type": "tool_use", "id": "x", "name": "n"}]}],
    ],
)
def test_busy_or_incomplete_source_is_rejected(project: Path, tail: list[dict[str, Any]]) -> None:
    _save(project, "s-busy", [*_turn(1), *tail])
    with pytest.raises(SessionForkError, match="in-flight"):
        fork_session(OPERATOR, "s-busy")
    _save(project, "s-pending", _turn(1), pending_verification={"candidate": "x"})
    with pytest.raises(SessionForkError, match="pending external verification"):
        fork_session(OPERATOR, "s-pending")
    assert sorted(p.name for p in project.iterdir() if p.is_dir()) == ["s-busy", "s-pending"]


def test_self_fork_from_inside_its_turn_cuts_at_the_last_completed_turn(project: Path) -> None:
    in_flight = {"role": "assistant", "content": [{"type": "tool_use", "id": "f", "name": "f"}]}
    _save(project, "s-self", [*_turn(1), *_turn(2, tools=1), _turn(3)[0], in_flight])
    receipt = fork_session(SessionPrincipal(session_id="s-self"), "")
    assert receipt.lineage["source_message_count"] == 6
    assert receipt.lineage["forked_by"] == "session:s-self"
    with pytest.raises(SessionForkError, match="in-flight"):
        fork_session(OPERATOR, "s-self")


def test_ownership_rules_for_roots_children_and_gateways(
    project: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    store = CollaborationStore(project / "sessions.db")
    for sid in ("s-a", "s-b", "s-gw-123", "agent_done", "agent_live"):
        _save(project, sid, _turn(1))
    store.begin_run(task_id="agent_done", parent_session_id="s-a", task_type="analyze")
    store.finish_run(parent_session_id="s-a", task_id="agent_done", generation=1, status="failed")
    store.begin_run(task_id="agent_live", parent_session_id="s-a", task_type="analyze")
    other = tmp_path_factory.mktemp("foreign")
    _save(other, "s-foreign", _turn(1))

    refused = [
        (SessionPrincipal(session_id="s-a"), "s-b", "only itself"),
        (SessionPrincipal(session_id="s-b"), "agent_done", "owning parent"),
        (SessionPrincipal(session_id="agent_done", parent_session_id="s-a"), "agent_done", "child"),
        (SessionPrincipal(session_id="agent_done"), "agent_done", "child session cannot"),
        (SessionPrincipal(session_id="s-a"), "agent_live", "still running"),
        (OPERATOR, "agent_live", "still running"),
        (OPERATOR, "s-gw-123", "gateway"),
        (OPERATOR, "s-foreign", "unknown source"),
        (SessionPrincipal(session_id="s-a"), "../s-b", "unknown source"),
        (SessionPrincipal(), "s-a", "no backend-bound session"),
    ]
    for principal, source, reason in refused:
        with pytest.raises(SessionForkError, match=reason):
            fork_session(principal, source)
    assert sorted(p.name for p in project.iterdir() if p.is_dir()) == [
        "agent_done",
        "agent_live",
        "s-a",
        "s-b",
        "s-gw-123",
    ]

    by_parent = fork_session(SessionPrincipal(session_id="s-a"), "agent_done")
    by_operator = fork_session(OPERATOR, "agent_done")
    root = fork_session(OPERATOR, "s-b")
    loaded = [SessionCheckpoint(project).load(r.session_id) for r in (by_parent, by_operator)]
    # A fork of a child is a new root session; it inherits no parent scope.
    assert all(state is not None and state.parent_session_id == "" for state in loaded)
    assert root.lineage["source_session_id"] == "s-b"
    assert not store.is_child_session(by_parent.session_id)


def test_symlinked_source_is_refused(project: Path, tmp_path_factory) -> None:
    outside = tmp_path_factory.mktemp("outside")
    _save(outside, "s-real", _turn(1))
    (project / "s-link").symlink_to(outside / "s-real")
    # The authority check never resolves a symlinked id; the owner refuses it too.
    with pytest.raises(SessionForkError, match="unknown source"):
        fork_session(OPERATOR, "s-link")
    with pytest.raises(SessionForkError, match="symlink"):
        SessionCheckpoint(project).fork_completed_turn("s-link", forked_by="operator")
    # The refusal happens under the status lock; no session directory appears.
    assert sorted(p.name for p in project.iterdir() if not p.name.startswith(".")) == ["s-link"]


def test_failed_publication_leaves_no_visible_partial_session(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _save(project, "s-src", _turn(1, tools=1))
    before = _source_fingerprint(project, "s-src")
    original = session_checkpoint.atomic_write_json

    def failing_write(path: Path, data: Any, **kwargs: Any) -> None:
        if path.name == "state.json" and path.parent.name != "s-src":
            raise OSError("disk full")
        original(path, data, **kwargs)

    monkeypatch.setattr(session_checkpoint, "atomic_write_json", failing_write)
    with pytest.raises(OSError, match="disk full"):
        fork_session(OPERATOR, "s-src")
    assert [p.name for p in project.iterdir() if p.is_dir()] == ["s-src"]
    with sqlite3.connect(project / "sessions.db") as conn:
        assert conn.execute("SELECT DISTINCT session_id FROM messages").fetchall() == [("s-src",)]
        assert conn.execute("SELECT session_id FROM sessions").fetchall() == [("s-src",)]
    assert _source_fingerprint(project, "s-src") == before


def test_crashed_publisher_orphan_is_removed_under_the_lock(project: Path) -> None:
    _save(project, "s-src", _turn(1))
    orphan = project / "s-orphan"
    orphan.mkdir()
    (orphan / ".fork-pending").write_text("s-src")
    SessionManager(project / "sessions.db").upsert_messages("s-orphan", _turn(9))
    _save(project, "s-committed", _turn(2))
    (project / "s-committed" / ".fork-pending").write_text("s-src")

    assert SessionCheckpoint(project).cleanup(max_age_hours=10_000) == 1
    assert not orphan.exists()
    assert SessionManager(project / "sessions.db").get_messages("s-orphan") == []
    assert not (project / "s-committed" / ".fork-pending").exists()
    assert SessionCheckpoint(project).load("s-committed") is not None


def test_cancelled_caller_observes_complete_publication(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _save(project, "s-src", _turn(1))
    entered = threading.Event()
    release = threading.Event()
    original = SessionCheckpoint._sync_messages_to_db

    def blocking_sync(
        self: SessionCheckpoint, state: SessionState, *, strict: bool = False
    ) -> None:
        if state.session_id != "s-src":
            entered.set()
            release.wait(5)
        original(self, state, strict=strict)

    monkeypatch.setattr(SessionCheckpoint, "_sync_messages_to_db", blocking_sync)

    async def scenario() -> Any:
        worker = asyncio.ensure_future(asyncio.to_thread(fork_session, OPERATOR, "s-src"))
        caller = asyncio.ensure_future(asyncio.shield(worker))
        await asyncio.to_thread(entered.wait, 5)
        caller.cancel()
        with pytest.raises(asyncio.CancelledError):
            await caller
        assert not worker.done()  # persistence is still running after the cancel
        release.set()
        return await worker

    receipt = asyncio.run(scenario())
    published = SessionCheckpoint(project).load(receipt.session_id)
    assert published is not None and not (project / receipt.session_id / ".fork-pending").exists()


def test_fork_racing_source_appends_always_takes_one_committed_cut(project: Path) -> None:
    history = _turn(0)
    _save(project, "s-race", history)
    stop = threading.Event()

    def append_turns() -> None:
        n = 1
        while not stop.is_set() and n < 40:
            # Mid-turn and completed-turn saves interleave as in a live loop.
            _save(project, "s-race", [*history, *_turn(n, tools=1)[:2]])
            history.extend(_turn(n, tools=1))
            _save(project, "s-race", list(history))
            n += 1

    writer = threading.Thread(target=append_turns)
    writer.start()
    forks: list[SessionState] = []
    refusals = 0
    try:
        for _ in range(30):
            try:
                receipt = fork_session(OPERATOR, "s-race")
            except SessionForkError:
                refusals += 1
                continue
            loaded = SessionCheckpoint(project).load(receipt.session_id)
            assert loaded is not None
            forks.append(loaded)
    finally:
        stop.set()
        writer.join()
    final = SessionCheckpoint(project).load("s-race")
    assert final is not None and forks and refusals + len(forks) == 30
    for fork in forks:
        cut = fork.lineage["source_message_count"]
        assert _balanced(fork.messages)
        assert [m["content"] for m in fork.messages] == [m["content"] for m in final.messages[:cut]]


def test_legacy_checkpoint_and_index_load_unchanged(tmp_path: Path) -> None:
    session_dir = tmp_path / "s-old"
    session_dir.mkdir()
    (session_dir / "state.json").write_text(
        json.dumps({"session_id": "s-old", "status": "paused", "updated_at": 1.0})
    )
    (session_dir / "messages.json").write_text(json.dumps(_turn(1)))
    with sqlite3.connect(tmp_path / "sessions.db") as conn:
        conn.execute(
            """CREATE TABLE sessions (session_id TEXT PRIMARY KEY, created_at REAL NOT NULL,
               updated_at REAL NOT NULL, status TEXT NOT NULL DEFAULT 'active',
               model TEXT NOT NULL DEFAULT '', provider TEXT NOT NULL DEFAULT 'anthropic',
               user_input TEXT NOT NULL DEFAULT '', round_count INTEGER NOT NULL DEFAULT 0,
               message_count INTEGER NOT NULL DEFAULT 0)"""
        )
        conn.execute("INSERT INTO sessions VALUES ('s-old', 1, 1, 'paused', 'm', 'p', 'i', 2, 2)")

    for _ in range(2):  # additive migration is idempotent
        manager = SessionManager(tmp_path / "sessions.db")
        meta = manager.get("s-old")
        manager.close()
        assert meta is not None and (meta.round_count, meta.source_session_id) == (2, "")
    state = SessionCheckpoint(tmp_path).load("s-old")
    assert state is not None and state.lineage == {} and state.parent_session_id == ""
    assert [m["content"] for m in state.messages] == ["task 1", "done 1"]


# Independent review follow-ups (F1, F3, F4).


@pytest.mark.parametrize("pending", [{}, {"candidate": "new-guard"}])
def test_fork_refuses_messages_of_a_failed_save(
    project: Path, monkeypatch: pytest.MonkeyPatch, pending: dict[str, Any]
) -> None:
    """F1: rows written by a save whose state.json failed are not a committed cut."""
    _save(project, "s-src", _turn(1))
    real_write = session_checkpoint.atomic_write_json

    def failing_state_write(path: Path, data: Any, **kwargs: Any) -> None:
        if path.name == "state.json":
            raise OSError("disk full")
        real_write(path, data, **kwargs)

    monkeypatch.setattr(session_checkpoint, "atomic_write_json", failing_state_write)
    with pytest.raises(OSError, match="disk full"):
        _save(project, "s-src", [*_turn(1), *_turn(2)], pending_verification=pending)
    monkeypatch.setattr(session_checkpoint, "atomic_write_json", real_write)
    with pytest.raises(SessionForkError, match="committed checkpoint"):
        SessionCheckpoint(project).fork_completed_turn("s-src", forked_by="operator")
    # The next successful save commits again and the fork takes that cut.
    _save(project, "s-src", [*_turn(1), *_turn(2)])
    fork = SessionCheckpoint(project).fork_completed_turn("s-src", forked_by="operator")
    assert fork.messages[-1]["content"] == "done 2"


def test_legacy_checkpoint_without_digest_is_refused(project: Path) -> None:
    _save(project, "s-old", _turn(1))
    state_file = project / "s-old" / "state.json"
    data = json.loads(state_file.read_text())
    del data["messages_digest"]
    state_file.write_text(json.dumps(data))
    assert SessionCheckpoint(project).load("s-old") is not None  # still loads unchanged
    with pytest.raises(SessionForkError, match="predates fork verification"):
        SessionCheckpoint(project).fork_completed_turn("s-old", forked_by="operator")


@pytest.mark.parametrize("name", ["messages.json", "tools.json"])
def test_symlinked_legacy_source_file_is_refused(
    project: Path, tmp_path_factory: pytest.TempPathFactory, name: str
) -> None:
    """F3: a local session must not read a foreign transcript through a link."""
    outside = tmp_path_factory.mktemp("foreign")
    foreign = outside / name
    foreign.write_text(json.dumps([{"role": "user", "content": "FOREIGN_PRIVATE"}]))
    _save(project, "s-legacy", _turn(1))
    target = project / "s-legacy" / name
    target.unlink(missing_ok=True)
    target.symlink_to(foreign)
    with pytest.raises(SessionForkError, match="symlink"):
        fork_session(OPERATOR, "s-legacy")
    assert not any(
        "FOREIGN_PRIVATE" in (p / "messages.json").read_text()
        for p in project.iterdir()
        if p.is_dir()
        and not p.is_symlink()
        and (p / "messages.json").is_file()
        and not (p / "messages.json").is_symlink()
    )


@pytest.mark.parametrize(
    "history",
    [
        # orphan result: no matching call
        [
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "missing"}]},
            {"role": "assistant", "content": "done"},
        ],
        # duplicate result for one call
        [
            {"role": "user", "content": "go"},
            {"role": "assistant", "content": [{"type": "tool_use", "id": "c", "name": "n"}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "c"}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "c"}]},
            {"role": "assistant", "content": "done"},
        ],
        # reused call ID across turns
        [
            *_turn(1, tools=1),
            {"role": "user", "content": "again"},
            {"role": "assistant", "content": [{"type": "tool_use", "id": "call-1-0", "name": "n"}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "call-1-0"}]},
            {"role": "assistant", "content": "done again"},
        ],
    ],
    ids=["orphan-result", "duplicate-result", "reused-call-id"],
)
def test_unbalanced_tool_history_is_never_forked(
    project: Path, history: list[dict[str, Any]]
) -> None:
    """F4: only histories whose calls and results pair exactly are copied."""
    _save(project, "s-bad", history)
    with pytest.raises(SessionForkError):
        SessionCheckpoint(project).fork_completed_turn("s-bad", forked_by="operator")


def test_balanced_window_after_an_old_orphan_is_not_resurrected(project: Path) -> None:
    """A poisoned history yields no later boundary, even in a self-fork."""
    history = [
        *_turn(1),
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "ghost"}]},
        *_turn(2),
    ]
    assert completed_turn_boundaries(history) == [2]
    _save(project, "s-ghost", history)
    with pytest.raises(SessionForkError):
        SessionCheckpoint(project).fork_completed_turn("s-ghost", forked_by="operator")
    fork = SessionCheckpoint(project).fork_completed_turn(
        "s-ghost", forked_by="s-ghost", allow_in_flight_tail=True
    )
    assert [m["content"] for m in fork.messages] == ["task 1", "done 1"]


def test_ipc_cancellation_keeps_the_source_lane_until_the_fork_finishes(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F2: the real IPC caller holds the source Lane past a cancelled await."""
    from core.orchestration.lane_queue import SessionLane
    from core.server.ipc_server.poller import CLIPoller

    _save(project, "s-src", _turn(1))
    entered = threading.Event()
    release = threading.Event()
    original = SessionCheckpoint._sync_messages_to_db

    def blocking_sync(
        self: SessionCheckpoint, state: SessionState, *, strict: bool = False
    ) -> None:
        if state.session_id != "s-src":
            entered.set()
            release.wait(5)
        original(self, state, strict=strict)

    monkeypatch.setattr(SessionCheckpoint, "_sync_messages_to_db", blocking_sync)
    lane = SessionLane()
    services = SimpleNamespace(
        lane_queue=SimpleNamespace(session_lane=lane),
        command_registry=None,
        skill_registry=None,
        mcp_manager=None,
    )
    poller = CLIPoller(services=services)  # type: ignore[arg-type]

    def fork_command(_cmd: str, args: str, _verbose: bool, **_kw: Any) -> tuple[bool, bool, Any]:
        fork_session(OPERATOR, args)
        return False, False, None

    poller._command_handler = fork_command
    loop = SimpleNamespace(_session_id="s-other")

    async def scenario() -> None:
        caller = asyncio.ensure_future(
            poller._handle_fork_command({"cmd": "/fork", "args": "s-src"}, loop)
        )
        await asyncio.to_thread(entered.wait, 5)
        caller.cancel()
        with pytest.raises(asyncio.CancelledError):
            await caller
        # The fork is still writing: the source Lane must still be held.
        assert lane.try_acquire("s-src") is False
        release.set()
        for _ in range(200):
            if lane.try_acquire("s-src"):
                lane.manual_release("s-src")
                return
            await asyncio.sleep(0.01)
        raise AssertionError("source Lane was never released after the fork finished")

    asyncio.run(scenario())
    forks = [
        p.name
        for p in project.iterdir()
        if p.is_dir() and p.name != "s-src" and (p / "state.json").is_file()
    ]
    assert len(forks) == 1 and not (project / forks[0] / ".fork-pending").exists()


def test_cancelled_lane_acquire_releases_a_late_grant() -> None:
    """F2: an acquire that completes after its caller left releases its slot."""
    from core.server.ipc_server.poller import _release_if_acquired

    released: list[str] = []
    lane = SimpleNamespace(manual_release=released.append)

    async def scenario() -> None:
        granted: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
        granted.set_result(True)
        _release_if_acquired(granted, lane, "s-src")
        refused: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
        refused.set_result(False)
        _release_if_acquired(refused, lane, "s-src")

    asyncio.run(scenario())
    assert released == ["s-src"]


def _terminal_child(base: Path, child: str, parent: str, status: SessionStatus) -> None:
    _save(base, child, _turn(1), parent_session_id=parent)
    checkpoint = SessionCheckpoint(base)
    if status is SessionStatus.COMPLETED:
        checkpoint.mark_completed(child)
    elif status is SessionStatus.ERROR:
        checkpoint.mark_error(child)


@pytest.mark.parametrize("status", [SessionStatus.COMPLETED, SessionStatus.ERROR])
def test_owning_parent_forks_a_terminal_child_after_run_retention(
    project: Path, status: SessionStatus
) -> None:
    """F5: durable header ownership survives pruning of the run row."""
    _save(project, "s-parent", _turn(1))
    _save(project, "s-peer", _turn(1))
    _terminal_child(project, "agent-pruned", "s-parent", status)
    assert CollaborationStore(project / "sessions.db").child_run("agent-pruned") is None
    receipt = fork_session(SessionPrincipal(session_id="s-parent"), "agent-pruned")
    assert receipt.lineage["source_session_id"] == "agent-pruned"
    with pytest.raises(SessionForkError, match="owning parent"):
        fork_session(SessionPrincipal(session_id="s-peer"), "agent-pruned")
    with pytest.raises(SessionForkError):
        fork_session(
            SessionPrincipal(session_id="agent-pruned", parent_session_id="s-parent"),
            "agent-pruned",
        )


def test_pruned_child_that_is_not_durably_terminal_is_refused(project: Path) -> None:
    _save(project, "s-parent", _turn(1))
    _save(project, "agent-active", _turn(1), parent_session_id="s-parent")  # status active
    with pytest.raises(SessionForkError, match="not durably terminal"):
        fork_session(SessionPrincipal(session_id="s-parent"), "agent-active")


def test_conflicting_child_ownership_is_refused(project: Path) -> None:
    _save(project, "s-parent", _turn(1))
    _save(project, "s-other", _turn(1))
    store = CollaborationStore(project / "sessions.db")
    store.begin_run(task_id="agent-x", parent_session_id="s-other", task_type="analyze")
    store.finish_run(
        parent_session_id="s-other", task_id="agent-x", generation=1, status="completed"
    )
    _terminal_child(project, "agent-x", "s-parent", SessionStatus.COMPLETED)
    with pytest.raises(SessionForkError, match="conflict"):
        fork_session(SessionPrincipal(session_id="s-parent"), "agent-x")
    with pytest.raises(SessionForkError, match="conflict"):
        fork_session(OPERATOR, "agent-x")
