"""Tests for the structured per-session journal (P1c).

Covers schema fidelity, multi-append, OSError safety, ContextVar
scope, and the hook-handler round-trip via journal_hooks.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from core.hooks import HookEvent
from core.self_improving.loop.observe.run_timeline import (
    RunTimeline,
    current_run_timeline,
    run_timeline_scope,
)


def _make_journal(tmp_path: Path) -> RunTimeline:
    return RunTimeline(
        session_id="s-test",
        gen_tag="autoresearch-test",
        component="autoresearch",
        path=tmp_path / "events.jsonl",
    )


def test_append_writes_jsonl_row(tmp_path: Path) -> None:
    """append() writes one JSONL row with the full schema.

    PR-U (2026-05-24, see docs/plans/2026-05-24-transcript-
    standardization-and-claude-resume.md) — the schema gained paperclip
    activity_log fields (``actor_type`` / ``actor_id`` / ``action``).
    Legacy ``append(event, payload=)`` callers (this test) get them
    auto-inferred as ``orchestrator`` / ``pipeline`` /
    ``f"pipeline.{event}"`` so the classification quintuple is uniform
    across every row without forcing every existing caller to add the
    new kwargs.
    """
    journal = _make_journal(tmp_path)
    journal.append("audit_finished", payload={"fitness": 0.5}, ts=1700000000.0)
    rows = (tmp_path / "events.jsonl").read_text().splitlines()
    assert len(rows) == 1
    payload = json.loads(rows[0])
    from core.observability.record_schema import validate_record

    validate_record(payload)
    assert payload["schema_id"] == "geode.run-event@1"
    assert payload["occurred_at"] == payload["ts"] == 1700000000.0
    assert payload["ordinal"] == payload["seq"] == 1
    assert payload["session_id"] == "s-test"
    assert payload["gen_tag"] == "autoresearch-test"
    assert payload["component"] == "autoresearch"
    assert payload["kind"] == payload["event"] == "audit_finished"
    assert payload["payload"] == {"fitness": 0.5}
    assert payload["actor_type"] == "orchestrator"
    assert payload["actor_id"] == "pipeline"
    assert payload["action"] == "pipeline.audit_finished"


def test_append_supports_level_and_default_payload(tmp_path: Path) -> None:
    """level kwarg defaults to 'info'; missing payload becomes empty dict."""
    journal = _make_journal(tmp_path)
    journal.append("subagent_failed", level="error", ts=1.0)
    row = json.loads((tmp_path / "events.jsonl").read_text().splitlines()[0])
    assert row["level"] == "error"
    assert row["payload"] == {}


def test_append_bounds_schema_fields_and_marks_invalid_time(tmp_path: Path) -> None:
    timeline = RunTimeline(
        session_id="session-" + ("x" * 400),
        gen_tag="g",
        component="test",
        path=tmp_path / "events.jsonl",
    )
    timeline.append(
        "",
        ts=float("nan"),
        turn_id="turn-" + ("y" * 400),
        call_id="call-" + ("z" * 400),
    )
    row = json.loads((tmp_path / "events.jsonl").read_text())
    from core.observability.record_schema import validate_record

    validate_record(row)
    assert len(row["session_id"]) == 256
    assert len(row["turn_id"]) == 256
    assert len(row["call_id"]) == 256
    assert row["kind"] == "event.unknown"
    assert row["payload"]["_invalid_occurred_at"] is True


def test_append_creates_parent_dirs(tmp_path: Path) -> None:
    """Nested paths are auto-mkdir'd before write."""
    deep = tmp_path / "nested" / "deeper" / "events.jsonl"
    journal = RunTimeline(
        session_id="s",
        gen_tag="g",
        component="autoresearch",
        path=deep,
    )
    journal.append("event")
    assert deep.is_file()


def test_append_appends_not_overwrites(tmp_path: Path) -> None:
    """Multiple appends accumulate, preserving prior rows."""
    journal = _make_journal(tmp_path)
    for i in range(3):
        journal.append(f"event-{i}", ts=float(i))
    rows = (tmp_path / "events.jsonl").read_text().splitlines()
    assert len(rows) == 3
    events = [json.loads(r)["event"] for r in rows]
    assert events == ["event-0", "event-1", "event-2"]


def test_append_swallows_oserror(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A failing mkdir/write must not raise."""

    def _raise(*_args: object, **_kwargs: object) -> None:
        raise OSError("simulated")

    monkeypatch.setattr(Path, "mkdir", _raise)
    journal = RunTimeline(
        session_id="s",
        gen_tag="g",
        component="autoresearch",
        path=tmp_path / "nonexistent" / "events.jsonl",
    )
    journal.append("event")  # Must not raise.
    assert journal.write_failed is True


def test_separate_writers_share_unique_projection_ordinals(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"

    def append(index: int) -> None:
        RunTimeline(
            session_id="s-shared",
            gen_tag="g",
            component="test",
            path=path,
        ).append("worker.event", payload={"index": index})

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(append, range(40)))

    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert sorted(row["ordinal"] for row in rows) == list(range(1, 41))
    assert len({row["event_id"] for row in rows}) == 40


def test_current_run_timeline_returns_none_outside_scope() -> None:
    """ContextVar default is None when no scope is active."""
    assert current_run_timeline() is None


def test_run_timeline_scope_binds_and_resets(tmp_path: Path) -> None:
    """The context manager binds the journal and restores prior value on exit."""
    journal = _make_journal(tmp_path)
    assert current_run_timeline() is None
    with run_timeline_scope(journal):
        assert current_run_timeline() is journal
    assert current_run_timeline() is None


def test_run_timeline_scope_restores_on_exception(tmp_path: Path) -> None:
    """Exception inside the scope still restores the ContextVar."""
    journal = _make_journal(tmp_path)
    with pytest.raises(RuntimeError, match="boom"), run_timeline_scope(journal):
        raise RuntimeError("boom")
    assert current_run_timeline() is None


def test_default_path_uses_geode_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Unset path falls back to ``GLOBAL_AUTORESEARCH_HANDOFF_DIR`` / <session> / events.jsonl."""
    fake_home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: fake_home))
    # Reload both core.paths and core.self_improving.loop.observe.run_timeline so
    # the lazy import resolves under the monkeypatched Path.home().
    import importlib

    import core.paths as paths_mod
    import core.self_improving.loop.observe.run_timeline as journal_mod

    importlib.reload(paths_mod)
    importlib.reload(journal_mod)
    journal = journal_mod.RunTimeline(
        session_id="s-default",
        gen_tag="g",
        component="autoresearch",
    )
    expected = fake_home / ".geode" / "autoresearch" / "handoff" / "s-default" / "events.jsonl"
    assert journal.path == expected
    journal.append("event")
    assert expected.is_file()
    # Restore originals so subsequent tests see the real home.
    monkeypatch.undo()
    importlib.reload(paths_mod)
    importlib.reload(journal_mod)


def test_hook_handlers_route_subagent_events_to_journal(tmp_path: Path) -> None:
    """journal_hooks._on_subagent_* writes to the active RunTimeline."""
    from unittest.mock import MagicMock

    from core.memory.journal_hooks import make_journal_handlers

    project_journal = MagicMock()
    handlers = dict(
        make_journal_handlers(
            project_journal,
            activity_sink_provider=current_run_timeline,
        )
    )
    # P1c — three new handlers expected.
    for name in (
        "journal_subagent",
        "journal_subagent_started",
        "journal_subagent_failed",
    ):
        assert name in handlers, f"missing handler {name!r}"

    journal = _make_journal(tmp_path)
    with run_timeline_scope(journal):
        handlers["journal_subagent_started"](
            HookEvent.SUBAGENT_STARTED,
            {"task_id": "t-1", "task_type": "seed-generator-spawn"},
        )
        handlers["journal_subagent"](
            HookEvent.SUBAGENT_COMPLETED,
            {"task_id": "t-1", "summary": "ok", "session_id": "s"},
        )
        handlers["journal_subagent_failed"](
            HookEvent.SUBAGENT_FAILED,
            {"task_id": "t-2", "error": "boom", "session_id": "s"},
        )

    rows = [json.loads(r) for r in (tmp_path / "events.jsonl").read_text().splitlines()]
    events = [r["event"] for r in rows]
    levels = [r["level"] for r in rows]
    assert events == ["subagent_started", "subagent_completed", "subagent_failed"]
    assert levels == ["info", "info", "error"]


def test_hook_handlers_noop_without_active_journal() -> None:
    """Outside run_timeline_scope, the hooks fall through silently."""
    from unittest.mock import MagicMock

    from core.memory.journal_hooks import make_journal_handlers

    project_journal = MagicMock()
    handlers = dict(make_journal_handlers(project_journal))
    # Should not raise even though no session journal is bound.
    handlers["journal_subagent_started"](
        HookEvent.SUBAGENT_STARTED,
        {"task_id": "t-x", "task_type": "x"},
    )


def test_bootstrap_registers_started_and_failed_handlers() -> None:
    """core/wiring/bootstrap.py registers the new handlers for STARTED + FAILED."""
    from core.wiring import bootstrap

    src = Path(bootstrap.__file__).read_text(encoding="utf-8")
    assert '"journal_subagent_started": [HookEvent.SUBAGENT_STARTED]' in src
    assert '"journal_subagent_failed": [HookEvent.SUBAGENT_FAILED]' in src
