"""PR-COMM-1 (S2 scope) — HookSystem ↔ ActivityRow mirror tests.

Pins union-channel invariants from
``docs/plans/2026-05-24-hookevent-activity-schema.md`` §5.2 (M1-M3).
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from core.hooks.system import HookEvent, HookSystem
from core.observability.run_dir import run_dir_scope
from core.self_improving.loop.observe.run_transcript import RunTranscript, run_transcript_scope


def _read_rows(transcript_path: Path) -> list[dict]:
    return [json.loads(line) for line in transcript_path.read_text().splitlines() if line.strip()]


def test_m1_trigger_appends_one_activity_row() -> None:
    """``HookSystem.trigger(event, data)`` inside an active
    ``run_transcript_scope`` appends exactly one row to
    ``transcript.jsonl`` with the typed classification quintuple
    (paperclip activity_log parity)."""
    with tempfile.TemporaryDirectory() as tmp, run_dir_scope(tmp):
        journal = RunTranscript(
            session_id="gen1-X",
            gen_tag="gen1",
            component="seed-generation",
            path=Path(tmp) / "transcript.jsonl",
        )
        with run_transcript_scope(journal):
            hs = HookSystem()
            hs.trigger(
                HookEvent.SUBAGENT_STARTED,
                {"task_id": "gen-gen1-001", "task_type": "seed_generator"},
            )
        rows = _read_rows(Path(tmp) / "transcript.jsonl")
        assert len(rows) == 1
        row = rows[0]
        assert row["action"] == "subagent.started"
        assert row["actor_type"] == "agent"
        assert row["entity_type"] == "task"
        assert row["task_id"] == "gen-gen1-001"


def test_m1_typed_lifecycle_event_carries_typed_details() -> None:
    """Group C ``LifecycleFailedRow`` carries the typed details
    (``error_type`` + ``message``) plus ``level=error``."""
    with tempfile.TemporaryDirectory() as tmp, run_dir_scope(tmp):
        journal = RunTranscript(
            session_id="gen1-X",
            gen_tag="gen1",
            component="seed-generation",
            path=Path(tmp) / "transcript.jsonl",
        )
        with run_transcript_scope(journal):
            hs = HookSystem()
            hs.trigger(
                HookEvent.LLM_CALL_FAILED,
                {
                    "session_id": "s1",
                    "call_id": "c1",
                    "error_type": "rate_limit",
                    "message": "429 Too Many Requests",
                },
            )
        rows = _read_rows(Path(tmp) / "transcript.jsonl")
        assert len(rows) == 1
        row = rows[0]
        assert row["action"] == "llm.call.failed"
        assert row["level"] == "error"
        assert row["payload"]["error_type"] == "rate_limit"
        assert "429" in row["payload"]["message"]


def test_m1_non_lifecycle_event_falls_through_to_generic() -> None:
    """A K-group event (MEMORY_SAVED) now mirrors as its concrete typed
    row (PR-OBS-CONTRACT typed all 43 formerly-generic events). The
    payload is the validated details schema, not a free-form dict."""
    with tempfile.TemporaryDirectory() as tmp, run_dir_scope(tmp):
        journal = RunTranscript(
            session_id="gen1-X",
            gen_tag="gen1",
            component="seed-generation",
            path=Path(tmp) / "transcript.jsonl",
        )
        with run_transcript_scope(journal):
            hs = HookSystem()
            hs.trigger(HookEvent.MEMORY_SAVED, {"key": "recipe-pho", "persistent": True})
        rows = _read_rows(Path(tmp) / "transcript.jsonl")
        assert len(rows) == 1
        row = rows[0]
        assert row["action"] == "memory.saved"
        assert row["actor_type"] == "agent"
        # Typed details schema — only declared fields, validated.
        assert row["payload"] == {"key": "recipe-pho", "persistent": True}
        assert row["entity_id"] == "recipe-pho"


def test_m1b_builder_failure_falls_through_to_distinguishable_generic() -> None:
    """A malformed payload (missing a required details field) must NOT
    break the timeline — it fail-softs to ``GenericActivityRow`` carrying
    a ``_fallback_reason`` so operators can tell a forced-generic row from
    an intentionally-typed one (silent-fallback anti-pattern guard)."""
    with tempfile.TemporaryDirectory() as tmp, run_dir_scope(tmp):
        journal = RunTranscript(
            session_id="gen1-Y",
            gen_tag="gen1",
            component="seed-generation",
            path=Path(tmp) / "transcript.jsonl",
        )
        with run_transcript_scope(journal):
            hs = HookSystem()
            # MUTATION_APPLIED requires ``mutation_id`` — omit it.
            hs.trigger(HookEvent.MUTATION_APPLIED, {"target_kind": "prompt"})
        rows = _read_rows(Path(tmp) / "transcript.jsonl")
        assert len(rows) == 1
        row = rows[0]
        assert row["action"] == "mutation.applied"
        assert "_fallback_reason" in row["payload"], (
            "forced-generic fallback must be distinguishable in the timeline"
        )


def test_m2_mirror_no_op_outside_run_transcript_scope() -> None:
    """Without an active ``RunTranscript`` (REPL / gateway / tests)
    the mirror is a silent no-op — the trigger must NOT raise and
    no file should be created."""
    with tempfile.TemporaryDirectory() as tmp:
        hs = HookSystem()
        # No run_transcript_scope active.
        hs.trigger(HookEvent.SUBAGENT_STARTED, {"task_id": "ghost"})
        # No transcript file expected in tmp (which was never bound).
        assert not (Path(tmp) / "transcript.jsonl").exists()


def test_m3_malformed_payload_still_produces_a_row() -> None:
    """A ``LifecycleFailedRow`` with a malformed payload (missing
    ``error_type`` + ``message``) must still emit a row — the registry
    fills defaults rather than letting the trigger silently fail.
    The "always emit" contract mirrors paperclip's swallow-and-warn
    pattern in ``activity-log.ts:65``."""
    with tempfile.TemporaryDirectory() as tmp, run_dir_scope(tmp):
        journal = RunTranscript(
            session_id="gen1-X",
            gen_tag="gen1",
            component="seed-generation",
            path=Path(tmp) / "transcript.jsonl",
        )
        with run_transcript_scope(journal):
            hs = HookSystem()
            # Empty payload — registry builder fills defaults.
            hs.trigger(HookEvent.LLM_CALL_FAILED, {})
        rows = _read_rows(Path(tmp) / "transcript.jsonl")
        assert len(rows) == 1
        row = rows[0]
        assert row["action"] == "llm.call.failed"
        # Defaults present so the row is still classifier-clean.
        assert row["payload"].get("error_type") == "unknown"
        assert row["level"] == "error"


def test_m3_malformed_value_still_produces_a_row() -> None:
    """Codex MCP review of #1587 caught this: pre-pydantic coercion
    (``float(data["duration_ms"])``) raises ``ValueError`` *before*
    pydantic's ``ValidationError`` when the payload carries a bad
    value (e.g. ``{"duration_ms": "bad"}``). The original M3 test only
    covered missing fields (which get defaulted). This pins the broader
    contract: malformed *values* must also fall through to
    ``GenericActivityRow`` so the timeline stays complete."""
    with tempfile.TemporaryDirectory() as tmp, run_dir_scope(tmp):
        journal = RunTranscript(
            session_id="gen1-X",
            gen_tag="gen1",
            component="seed-generation",
            path=Path(tmp) / "transcript.jsonl",
        )
        with run_transcript_scope(journal):
            hs = HookSystem()
            # ``duration_ms="bad"`` triggers ValueError inside the
            # _lifecycle_completed builder. Pre-Codex-catch the row
            # would have been dropped entirely.
            hs.trigger(
                HookEvent.LLM_CALL_ENDED,
                {"session_id": "s1", "call_id": "c1", "duration_ms": "bad"},
            )
        rows = _read_rows(Path(tmp) / "transcript.jsonl")
        assert len(rows) == 1
        row = rows[0]
        # The row landed via GenericActivityRow fall-through (the builder
        # raised ValueError → registry caught it → generic emit).
        # The action keeps the dotted-name convention.
        assert row["action"] == "llm.call.end"


def test_m1_async_mirror_appends_one_row() -> None:
    """``trigger_async`` must call the same mirror as ``trigger`` —
    otherwise the async dispatch path silently drops events. Codex
    MCP review of #1587 flagged this as a missing test."""
    import asyncio

    with tempfile.TemporaryDirectory() as tmp, run_dir_scope(tmp):
        journal = RunTranscript(
            session_id="gen1-X",
            gen_tag="gen1",
            component="seed-generation",
            path=Path(tmp) / "transcript.jsonl",
        )
        with run_transcript_scope(journal):
            hs = HookSystem()
            asyncio.run(
                hs.trigger_async(
                    HookEvent.SUBAGENT_STARTED,
                    {"task_id": "gen-async-001", "task_type": "seed_generator"},
                )
            )
        rows = _read_rows(Path(tmp) / "transcript.jsonl")
        assert len(rows) == 1
        assert rows[0]["action"] == "subagent.started"
        assert rows[0]["task_id"] == "gen-async-001"


def test_m1_hook_handler_failure_does_not_break_mirror() -> None:
    """If a registered hook handler raises, the union-channel mirror
    must still run — we're capturing observability, not gating on
    handler success."""
    with tempfile.TemporaryDirectory() as tmp, run_dir_scope(tmp):
        journal = RunTranscript(
            session_id="gen1-X",
            gen_tag="gen1",
            component="seed-generation",
            path=Path(tmp) / "transcript.jsonl",
        )
        with run_transcript_scope(journal):
            hs = HookSystem()

            def _broken_handler(event: HookEvent, data: dict) -> None:
                raise RuntimeError("simulated handler bug")

            hs.register(HookEvent.SUBAGENT_STARTED, _broken_handler, name="broken")
            hs.trigger(HookEvent.SUBAGENT_STARTED, {"task_id": "gen-gen1-001"})
        # Handler raised but the mirror still wrote one row.
        rows = _read_rows(Path(tmp) / "transcript.jsonl")
        assert len(rows) == 1
        assert rows[0]["action"] == "subagent.started"
