"""PR1 (Q.5 + U) invariant tests.

Pins the four invariants from
``docs/plans/2026-05-24-transcript-standardization-and-claude-resume.md``
section 2.2 — drift here means the doc's spec and the code diverged.

* I1 — single-anchor identifier: ``WorkerRequest.task_id ==
  IsolationConfig.session_id == AgenticLoop.session_id ==
  SessionTranscript._session_id``.
* I2 — single sub-agent directory: ``result.json`` + ``stderr.log`` +
  ``dialogue.jsonl`` all land under ``<run_dir>/sub_agents/<task_id>/``.
* I3 — navigation: the pipeline transcript's ``task_id`` (or
  ``entity_id``) maps deterministically to
  ``<run_dir>/sub_agents/<task_id>/dialogue.jsonl``.
* I4 — backwards-compat: existing ``RunTranscript.append(event, payload=)``
  callers keep working without supplying the new
  ``actor_type`` / ``action`` / ``entity_*`` kwargs.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

# ---------------------------------------------------------------------------
# I1 — single-anchor identifier
# ---------------------------------------------------------------------------


def test_i1_agentic_loop_honours_caller_supplied_session_id() -> None:
    """``AgenticLoop(session_id="...")`` must use the supplied identifier
    verbatim instead of auto-generating ``s-<uuid>``. Pre-PR-Q.5 the
    constructor unconditionally generated a fresh uuid, causing the
    worker's SessionTranscript to land in a directory the parent could
    not reach from ``WorkerRequest.task_id``."""
    from core.agent.conversation import ConversationContext
    from core.agent.loop import AgenticLoop
    from core.agent.tool_executor import ToolExecutor

    loop = AgenticLoop(
        ConversationContext(),
        ToolExecutor(),
        session_id="gen-gen1-001-bd2e3854",
        quiet=True,
    )
    assert loop._session_id == "gen-gen1-001-bd2e3854"
    assert loop._transcript is not None
    # SessionTranscript exposed the same identifier on .session_id (public)
    assert loop._transcript.session_id == "gen-gen1-001-bd2e3854"


def test_i1_agentic_loop_falls_back_to_uuid_when_no_session_id() -> None:
    """When the caller leaves ``session_id`` empty (REPL / gateway /
    tests with no per-task identity) the legacy ``s-<uuid>`` path
    still works — non-worker callers must not regress."""
    from core.agent.conversation import ConversationContext
    from core.agent.loop import AgenticLoop
    from core.agent.tool_executor import ToolExecutor

    loop = AgenticLoop(
        ConversationContext(),
        ToolExecutor(),
        quiet=True,
    )
    assert loop._session_id.startswith("s-")
    assert len(loop._session_id) > 2  # not just "s-"


# ---------------------------------------------------------------------------
# I2 — single sub-agent directory
# ---------------------------------------------------------------------------


def test_i2_sub_agent_dir_unity_under_run_scope() -> None:
    """Inside a ``run_dir_scope`` all three writers (worker result,
    isolated_execution stderr, SessionTranscript dialogue) land in the
    SAME ``<run_dir>/sub_agents/<task_id>/`` directory."""
    from core.agent.worker import WorkerResult, _save_result_backup
    from core.observability.run_dir import run_dir_scope
    from core.observability.transcript import SessionTranscript
    from core.orchestration.isolated_execution import IsolatedRunner

    task_id = "gen-gen1-001-bd2e3854"
    with tempfile.TemporaryDirectory() as tmp, run_dir_scope(tmp):
        sub_agent_dir = Path(tmp) / "sub_agents" / task_id

        # W2 worker.py — result.json
        _save_result_backup(WorkerResult(task_id=task_id, success=True, output="x"))
        assert (sub_agent_dir / "result.json").exists()

        # W3 isolated_execution — stderr.log (uses session_id == task_id by
        # SubAgentManager wiring; here we simulate by passing task_id directly)
        IsolatedRunner._save_stderr(task_id, b"stderr")
        assert (sub_agent_dir / "stderr.log").exists()

        # W4 SessionTranscript — dialogue.jsonl (uses _session_id == task_id
        # because PR-Q.5 wires WorkerRequest.task_id → AgenticLoop.session_id
        # → SessionTranscript._session_id)
        tx = SessionTranscript(task_id)
        tx.record_session_start(model="claude-opus-4-7")
        assert (sub_agent_dir / "dialogue.jsonl").exists()

        # All three live in ONE directory — operator can tar the whole
        # sub-agent's output with one path.
        assert {p.name for p in sub_agent_dir.iterdir()} == {
            "result.json",
            "stderr.log",
            "dialogue.jsonl",
        }


# ---------------------------------------------------------------------------
# I3 — pipeline-timeline → dialogue navigation is deterministic
# ---------------------------------------------------------------------------


def test_i3_pipeline_timeline_task_id_resolves_to_dialogue_path() -> None:
    """Every ``agent.*`` row in the pipeline transcript carries a
    ``task_id`` field whose value, joined with the active run_dir,
    points to the dialogue file. paperclip equivalent: the
    ``activity_log.entityId`` FK joins to ``issue_comments.issueId``."""
    from core.observability.run_dir import run_dir_scope
    from core.observability.transcript import SessionTranscript
    from core.self_improving_loop.run_transcript import RunTranscript, run_transcript_scope

    task_id = "gen-gen1-001-bd2e3854"
    with tempfile.TemporaryDirectory() as tmp, run_dir_scope(tmp):
        run_transcript = RunTranscript(
            session_id="gen1-X",
            gen_tag="gen1",
            component="seed-generation",
            path=Path(tmp) / "transcript.jsonl",
        )
        with run_transcript_scope(run_transcript):
            tx = SessionTranscript(task_id)
            tx.record_user_message("Generate ONE seed scenario...")
            tx.record_assistant_message("# Overlapping log windows ...")

        timeline_rows = [
            json.loads(line)
            for line in (Path(tmp) / "transcript.jsonl").read_text().splitlines()
            if line.strip()
        ]
        agent_rows = [row for row in timeline_rows if row.get("actor_type") == "agent"]
        assert len(agent_rows) == 2  # user_message + assistant_message mirrors

        for row in agent_rows:
            referenced_task_id = row.get("task_id")
            assert referenced_task_id == task_id
            # Determinism: same identifier → same path
            dialogue_path = Path(tmp) / "sub_agents" / referenced_task_id / "dialogue.jsonl"
            assert dialogue_path.exists()
            # The dialogue file actually carries the full body whose
            # truncated preview is in the timeline.
            dialogue_rows = [
                json.loads(line) for line in dialogue_path.read_text().splitlines() if line.strip()
            ]
            # Each timeline preview matches a corresponding dialogue event
            # by event-verb (user_message ↔ user_message etc.).
            verb = row["event"]
            assert any(d.get("event") == verb for d in dialogue_rows)


# ---------------------------------------------------------------------------
# I4 — backwards-compat for legacy RunTranscript.append callers
# ---------------------------------------------------------------------------


def test_i4_legacy_run_transcript_append_still_works() -> None:
    """Pre-PR-U callers (seed_generation/cli.py + 25 other callers)
    use ``journal.append("phase_started", payload={...})`` with no
    actor/action kwargs. After PR-U the same shape must keep working
    — the defaults auto-infer the orchestrator classification."""
    from core.self_improving_loop.run_transcript import RunTranscript

    with tempfile.TemporaryDirectory() as tmp:
        journal = RunTranscript(
            session_id="gen1-X",
            gen_tag="gen1",
            component="seed-generation",
            path=Path(tmp) / "transcript.jsonl",
        )
        # Legacy call shape — exactly how cli.py uses it today.
        journal.append("phase_started", payload={"role": "generator"})
        journal.append(
            "preflight_passed",
            payload={"issue_count": 0},
        )

        rows = [
            json.loads(line)
            for line in (Path(tmp) / "transcript.jsonl").read_text().splitlines()
            if line.strip()
        ]
        assert len(rows) == 2
        # Auto-inferred classification — paperclip activity_log shape preserved.
        for row in rows:
            assert row.get("actor_type") == "orchestrator"
            assert row.get("actor_id") == "pipeline"
            assert row.get("action", "").startswith("pipeline.")
            # Original event + payload still present so legacy readers
            # (operator grep on ``.event``) keep working.
            assert "event" in row
            assert "payload" in row
        assert rows[0]["action"] == "pipeline.phase_started"
        assert rows[1]["action"] == "pipeline.preflight_passed"


def test_i5_worker_subprocess_rebinds_run_transcript_from_env() -> None:
    """Codex MCP review of #1584 caught that ContextVars don't cross
    subprocess boundaries — the parent's ``run_transcript_scope`` is
    invisible to worker subprocesses, so SessionTranscript mirrors
    would silently no-op in production. Worker.main() must re-create a
    ``RunTranscript`` pointing at the same ``transcript.jsonl`` when
    ``GEODE_RUN_DIR`` env is set. This test asserts that bridge."""
    import subprocess
    import sys

    from core.observability.run_dir import RUN_DIR_ENV

    with tempfile.TemporaryDirectory() as tmp:
        # Worker subprocess script: simulates what worker.main() does at
        # entry — read env, set ContextVar + RunTranscript, then call
        # SessionTranscript.record_user_message to trigger the mirror.
        worker_script = (
            "import os, sys; "
            "from core.observability.run_dir import RUN_DIR_ENV, set_active_run_dir; "
            "from core.self_improving_loop.run_transcript import RunTranscript, set_current_run_transcript; "
            "from core.observability.transcript import SessionTranscript; "
            "from pathlib import Path; "
            "inherited = os.environ.get(RUN_DIR_ENV, ''); "
            "set_active_run_dir(inherited); "
            "rd = Path(inherited); "
            "rt = RunTranscript(session_id=rd.name, gen_tag='', component='seed-generation', "
            "                   path=rd / 'transcript.jsonl'); "
            "set_current_run_transcript(rt); "
            "tx = SessionTranscript('gen-task-001'); "
            "tx.record_user_message('hello from worker subprocess'); "
            "sys.exit(0)"
        )
        env = {**os.environ, RUN_DIR_ENV: tmp}
        result = subprocess.run(  # noqa: S603 — sys.executable + fixed -c, no shell, no user input
            [sys.executable, "-c", worker_script],
            env=env,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        assert result.returncode == 0, f"worker subprocess failed: stderr={result.stderr!r}"

        # The mirror MUST have appended to the same transcript.jsonl the
        # parent would write to. Pre-Codex-catch this assertion failed
        # silently because the mirror's ContextVar lookup returned None.
        transcript_path = Path(tmp) / "transcript.jsonl"
        assert transcript_path.exists(), (
            "worker did not rebind RunTranscript — mirror is broken across process boundary"
        )
        rows = [
            json.loads(line) for line in transcript_path.read_text().splitlines() if line.strip()
        ]
        agent_rows = [r for r in rows if r.get("actor_type") == "agent"]
        assert len(agent_rows) == 1
        assert agent_rows[0]["action"] == "agent.user_message"
        assert agent_rows[0]["task_id"] == "gen-task-001"

        # Sub-agent dialogue.jsonl ALSO landed in run_dir/sub_agents/<task_id>/
        dialogue_path = Path(tmp) / "sub_agents" / "gen-task-001" / "dialogue.jsonl"
        assert dialogue_path.exists()


def test_i6_seed_generation_cli_opens_run_dir_scope() -> None:
    """Codex MCP review of #1584 caught that
    ``plugins/seed_generation/cli.py:run_audit_seeds`` was computing
    ``run_dir`` but never opening ``run_dir_scope`` on it — so
    ``IsolatedRunner._aexecute_subprocess`` saw ``get_active_run_dir()
    == None`` and never forwarded ``GEODE_RUN_DIR`` to the child. The
    fix wraps the orchestrator body in both ``run_dir_scope`` and
    ``run_transcript_scope``. This test grep-pins that wrapping so the
    binding doesn't silently drop in a future refactor."""
    cli_source = Path(__file__).resolve().parents[3] / "plugins" / "seed_generation" / "cli.py"
    source = cli_source.read_text(encoding="utf-8")
    # Both scopes must appear, and run_dir_scope must wrap the
    # run_transcript_scope (same `with` line or earlier).
    assert "from core.observability.run_dir import run_dir_scope" in source
    assert "with run_dir_scope(run_dir), run_transcript_scope(journal):" in source, (
        "cli.py must wrap the orchestrator body in both scopes — pre-Codex-catch "
        "only run_transcript_scope was opened and PR-Q's redirect path silently "
        "fell back to legacy ~/.geode/ globals."
    )


def test_i4_mirror_no_op_outside_run_transcript_scope() -> None:
    """SessionTranscript outside a ``run_transcript_scope`` (REPL /
    gateway / tests) must NOT raise and must write its own
    dialogue.jsonl normally. The mirror is a silent no-op."""
    from core.observability.transcript import SessionTranscript

    with tempfile.TemporaryDirectory() as tmp:
        tx = SessionTranscript("s-orphan01", transcript_dir=tmp)
        # No active run_transcript — these must not raise.
        tx.record_user_message("standalone")
        tx.record_assistant_message("ok")
        dialogue_path = Path(tmp) / "s-orphan01.jsonl"
        assert dialogue_path.exists()
        rows = [json.loads(line) for line in dialogue_path.read_text().splitlines() if line.strip()]
        events = [r["event"] for r in rows]
        assert "user_message" in events
        assert "assistant_message" in events
