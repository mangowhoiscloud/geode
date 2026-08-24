"""Cross-writer invariants for canonical session and run timelines."""

from __future__ import annotations

import json
from pathlib import Path


def test_agentic_loop_honours_caller_supplied_session_id() -> None:
    from core.agent.conversation import ConversationContext
    from core.agent.loop import AgenticLoop, AgenticLoopConfig
    from core.agent.tool_executor import ToolExecutor

    loop = AgenticLoop(
        ConversationContext(),
        ToolExecutor(),
        config=AgenticLoopConfig(session_id="gen-gen1-001-bd2e3854"),
        quiet=True,
    )
    assert loop._session_id == "gen-gen1-001-bd2e3854"
    assert loop._timeline is not None
    assert loop._timeline.session_id == loop._session_id


def test_sub_agent_outputs_share_one_run_directory(tmp_path: Path) -> None:
    from core.agent.worker import WorkerResult, _save_result_backup
    from core.observability.run_dir import run_dir_scope
    from core.observability.session_timeline import SessionTimeline
    from core.orchestration.isolated_execution import IsolatedRunner

    task_id = "gen-gen1-001-bd2e3854"
    with run_dir_scope(tmp_path):
        _save_result_backup(WorkerResult(task_id=task_id, success=True, output="x"))
        IsolatedRunner._save_stderr(task_id, b"stderr")
        timeline = SessionTimeline(task_id, db_path=tmp_path / "sessions.db")
        timeline.record_session_start(model="gpt-5.6")

    sub_agent_dir = tmp_path / "sub_agents" / task_id
    assert {path.name for path in sub_agent_dir.iterdir()} == {
        "events.jsonl",
        "result.json",
        "stderr.log",
    }
    row = json.loads((sub_agent_dir / "events.jsonl").read_text().splitlines()[0])
    assert row["session_id"] == task_id
    assert row["kind"] == "session.started"


def test_run_timeline_keeps_current_append_contract(tmp_path: Path) -> None:
    from evals.run_timeline import RunTimeline

    path = tmp_path / "events.jsonl"
    timeline = RunTimeline(
        session_id="gen1-X",
        gen_tag="gen1",
        component="seed-generation",
        path=path,
    )
    timeline.append("phase_started", payload={"role": "generator"})

    row = json.loads(path.read_text())
    assert row["kind"] == "phase_started"
    assert row["action"] == "pipeline.phase_started"
    assert row["payload"] == {"role": "generator"}


def test_session_timeline_without_run_scope_writes_sqlite_only(tmp_path: Path) -> None:
    from core.observability.session_timeline import SessionTimeline

    timeline = SessionTimeline("s-standalone", db_path=tmp_path / "sessions.db")
    timeline.record_user_message("standalone")
    timeline.record_assistant_message("ok")

    assert timeline.projection_path is None
    assert [row["kind"] for row in timeline.read_events()] == [
        "message.user",
        "message.assistant",
    ]
