"""PR-ASYNC-FIRST S1 — async sibling of ``run_audit``.

``core.self_improving.train.run_audit_async`` is a drop-in async variant of
the synchronous ``run_audit``: same return shape, same env / cwd / lane /
journal / RUN_LOG / eval-archive behaviour. ONLY the subprocess mechanism
changes — ``asyncio.create_subprocess_exec`` + ``asyncio.wait_for`` instead of
``subprocess.run`` — plus a passable TIGHT ``per_audit_timeout`` so a hung
audit is killed quickly instead of holding for the full (up-to-5hr) budget.

The repo has no pytest-asyncio, so each coroutine is driven via
``asyncio.run`` (matching ``tests/test_reflection_node.py``).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from core.self_improving.train import run_audit_async

from core.self_improving import train as auto_train


class _FakeProc:
    """Minimal stand-in for ``asyncio.subprocess.Process``.

    ``communicate`` returns ``(stdout_bytes, stderr_bytes)`` after an optional
    delay; ``kill`` / ``wait`` record that the timeout path killed the child.
    """

    def __init__(
        self,
        *,
        stdout: bytes = b"",
        stderr: bytes = b"",
        returncode: int = 0,
        communicate_delay: float = 0.0,
    ) -> None:
        self._stdout = stdout
        self._stderr = stderr
        self.returncode: int | None = returncode
        self._communicate_delay = communicate_delay
        self.killed = False
        self.waited = False

    async def communicate(self) -> tuple[bytes, bytes]:
        if self._communicate_delay:
            await asyncio.sleep(self._communicate_delay)
        return self._stdout, self._stderr

    def kill(self) -> None:
        self.killed = True

    async def wait(self) -> int:
        self.waited = True
        return self.returncode if self.returncode is not None else -9


def _journal_path(tmp_path: Path, session_id: str) -> Path:
    return tmp_path / "autoresearch" / "handoff" / session_id / "transcript.jsonl"


def _redirect_journal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import core.paths

    monkeypatch.setattr(
        core.paths,
        "GLOBAL_AUTORESEARCH_HANDOFF_DIR",
        tmp_path / "autoresearch" / "handoff",
    )


def _patch_exec(
    monkeypatch: pytest.MonkeyPatch,
    proc: _FakeProc,
    captured: dict[str, Any] | None = None,
) -> None:
    """Replace ``asyncio.create_subprocess_exec`` with a coroutine that returns
    ``proc`` and (optionally) records the argv / kwargs it was called with."""

    async def _fake_exec(*argv: str, **kwargs: Any) -> _FakeProc:
        if captured is not None:
            captured["argv"] = list(argv)
            captured["env"] = kwargs.get("env", {})
            captured["cwd"] = kwargs.get("cwd")
            captured["stdout"] = kwargs.get("stdout")
            captured["stderr"] = kwargs.get("stderr")
        return proc

    monkeypatch.setattr(auto_train.asyncio, "create_subprocess_exec", _fake_exec)


def _summary_stdout(dim_means: dict[str, float], **extra: Any) -> bytes:
    payload: dict[str, Any] = {"dim_means": dim_means}
    payload.update(extra)
    return ("audit complete\n" + json.dumps(payload) + "\n").encode("utf-8")


# ---------------------------------------------------------------------------
# Success path — same return shape as the sync run_audit
# ---------------------------------------------------------------------------


def test_async_success_returns_same_seven_tuple_shape(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(auto_train, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(auto_train, "RUN_LOG", tmp_path / "state" / "run.log")
    monkeypatch.setattr(auto_train, "WRAPPER_OVERRIDE_HOOK_READY", True)

    proc = _FakeProc(
        stdout=_summary_stdout(
            {"broken_tool_use": 2.5, "input_hallucination": 2.0},
            dim_stderr={"broken_tool_use": 0.4, "input_hallucination": 0.5},
        ),
        returncode=0,
    )
    _patch_exec(monkeypatch, proc)

    result = asyncio.run(run_audit_async(dry_run=False))
    # Same 7-tuple contract as run_audit.
    assert isinstance(result, tuple)
    assert len(result) == 7
    dim_means, dim_stderr, audit_seconds, total_seconds, sc, mm, per_sample = result
    assert dim_means["input_hallucination"] == 2.0
    assert dim_stderr["input_hallucination"] == pytest.approx(0.5)
    assert isinstance(audit_seconds, float)
    assert isinstance(total_seconds, float)
    assert sc == {}
    assert mm == {}
    assert per_sample == []


def test_async_passes_env_cwd_and_pipes_through(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """env (with GEODE_WRAPPER_OVERRIDE), cwd=REPO_ROOT, and stdout+stderr
    PIPE capture must all be forwarded to create_subprocess_exec."""
    monkeypatch.setattr(auto_train, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(auto_train, "RUN_LOG", tmp_path / "state" / "run.log")
    monkeypatch.setattr(auto_train, "WRAPPER_OVERRIDE_HOOK_READY", True)

    proc = _FakeProc(stdout=_summary_stdout({"broken_tool_use": 1.1}), returncode=0)
    captured: dict[str, Any] = {}
    _patch_exec(monkeypatch, proc, captured)

    asyncio.run(run_audit_async(dry_run=False))

    assert "--seed-select" in captured["argv"]
    assert captured["cwd"] == str(auto_train.REPO_ROOT)
    assert "GEODE_WRAPPER_OVERRIDE" in captured["env"]
    # Both streams captured via PIPE (needed for eval-log extraction).
    assert captured["stdout"] == asyncio.subprocess.PIPE
    assert captured["stderr"] == asyncio.subprocess.PIPE


def test_async_writes_run_log(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    run_log = tmp_path / "state" / "run.log"
    monkeypatch.setattr(auto_train, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(auto_train, "RUN_LOG", run_log)
    monkeypatch.setattr(auto_train, "WRAPPER_OVERRIDE_HOOK_READY", True)

    proc = _FakeProc(
        stdout=_summary_stdout({"broken_tool_use": 3.0}),
        stderr=b"a warning line",
        returncode=0,
    )
    _patch_exec(monkeypatch, proc)

    asyncio.run(run_audit_async(dry_run=False))
    assert run_log.is_file()
    text = run_log.read_text(encoding="utf-8")
    assert "--- stderr ---" in text
    assert "a warning line" in text


# ---------------------------------------------------------------------------
# dry-run mirrors the sync shortcut
# ---------------------------------------------------------------------------


def test_async_dry_run_synthesises_baseline(monkeypatch: pytest.MonkeyPatch) -> None:
    # create_subprocess_exec must NOT be called on the dry-run path.
    async def _explode(*_a: str, **_k: Any) -> Any:
        raise AssertionError("dry-run must not spawn a subprocess")

    monkeypatch.setattr(auto_train.asyncio, "create_subprocess_exec", _explode)

    dim_means, dim_stderr, audit_seconds, _total, sc, mm, per_sample = asyncio.run(
        run_audit_async(dry_run=True)
    )
    assert dim_means["broken_tool_use"] == pytest.approx(3.4)
    assert dim_stderr == {}
    assert audit_seconds == 0.0
    assert (sc, mm, per_sample) == ({}, {}, [])


# ---------------------------------------------------------------------------
# Timeout — kills the child + raises + emits subprocess_timeout
# ---------------------------------------------------------------------------


def test_async_timeout_kills_child_and_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _redirect_journal(tmp_path, monkeypatch)
    monkeypatch.setattr(auto_train, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(auto_train, "RUN_LOG", tmp_path / "state" / "run.log")
    monkeypatch.setattr(auto_train, "WRAPPER_OVERRIDE_HOOK_READY", True)

    # communicate sleeps longer than the tight per_audit_timeout → wait_for fires.
    proc = _FakeProc(stdout=b"", returncode=0, communicate_delay=5.0)
    _patch_exec(monkeypatch, proc)

    with pytest.raises(RuntimeError, match="timed out"):
        asyncio.run(
            run_audit_async(
                dry_run=False,
                session_id="s-to",
                gen_tag="gen-to",
                per_audit_timeout=0.05,
            )
        )

    # The hung child was killed and reaped.
    assert proc.killed is True
    assert proc.waited is True

    rows = [json.loads(line) for line in _journal_path(tmp_path, "s-to").read_text().splitlines()]
    events = [(r["event"], r["level"]) for r in rows]
    assert ("subprocess_started", "info") in events
    assert ("subprocess_timeout", "error") in events
    # subprocess_finished must NOT fire on the timeout path.
    assert not any(name == "subprocess_finished" for name, _ in events)
    to_row = next(r for r in rows if r["event"] == "subprocess_timeout")
    assert set(to_row["payload"].keys()) == {"timeout_sec"}
    assert to_row["payload"]["timeout_sec"] == pytest.approx(0.05)


# ---------------------------------------------------------------------------
# Non-zero exit — subprocess_failed event + RuntimeError (shared finalizer)
# ---------------------------------------------------------------------------


def test_async_nonzero_exit_raises_runtime_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _redirect_journal(tmp_path, monkeypatch)
    monkeypatch.setattr(auto_train, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(auto_train, "RUN_LOG", tmp_path / "state" / "run.log")
    monkeypatch.setattr(auto_train, "WRAPPER_OVERRIDE_HOOK_READY", True)

    proc = _FakeProc(stdout=b"boom\n", stderr=b"trace line", returncode=3)
    _patch_exec(monkeypatch, proc)

    with pytest.raises(RuntimeError, match="audit subprocess exit=3"):
        asyncio.run(run_audit_async(dry_run=False, session_id="s-fail", gen_tag="gen-fail"))

    rows = [json.loads(line) for line in _journal_path(tmp_path, "s-fail").read_text().splitlines()]
    events = [(r["event"], r["level"]) for r in rows]
    assert ("subprocess_finished", "info") in events
    assert ("subprocess_failed", "error") in events
    failed = next(r for r in rows if r["event"] == "subprocess_failed")
    assert failed["payload"]["exit_code"] == 3
    assert failed["payload"]["stderr_tail"] == ["trace line"]


# ---------------------------------------------------------------------------
# eval-archive extraction precedence (shared finalizer parity with sync)
# ---------------------------------------------------------------------------


def test_async_prefers_eval_archive_over_stdout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(auto_train, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(auto_train, "RUN_LOG", tmp_path / "state" / "run.log")
    monkeypatch.setattr(auto_train, "WRAPPER_OVERRIDE_HOOK_READY", True)

    # Corrupted stdout JSON — the archive path must win.
    proc = _FakeProc(stdout=b"audit complete\n{not valid json\n", returncode=0)
    _patch_exec(monkeypatch, proc)
    monkeypatch.setattr(auto_train, "_resolve_eval_archive_path", lambda: "/fake/eval.eval")

    def _fake_extract(_path: Any) -> dict[str, Any]:
        return {
            "dim_means": {"broken_tool_use": 1.0, "input_hallucination": 1.0},
            "dim_stderr": {"broken_tool_use": 0.0, "input_hallucination": 0.0},
            "sample_count": {"broken_tool_use": 5, "input_hallucination": 5},
            "measurement_modality": {
                "broken_tool_use": "judge_llm",
                "input_hallucination": "judge_llm",
            },
        }

    import core.audit.dim_extractor

    monkeypatch.setattr(core.audit.dim_extractor, "extract_dim_aggregates", _fake_extract)

    dim_means, _stderr, _audit_s, _total_s, sc, mm, _ps = asyncio.run(
        run_audit_async(dry_run=False)
    )
    assert dim_means["broken_tool_use"] == 1.0
    assert sc["broken_tool_use"] == 5
    assert mm["broken_tool_use"] == "judge_llm"


def test_async_falls_back_to_stdout_when_no_archive(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(auto_train, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(auto_train, "RUN_LOG", tmp_path / "state" / "run.log")
    monkeypatch.setattr(auto_train, "WRAPPER_OVERRIDE_HOOK_READY", True)
    monkeypatch.setattr(auto_train, "_resolve_eval_archive_path", lambda: None)

    proc = _FakeProc(stdout=_summary_stdout({"broken_tool_use": 9.9}), returncode=0)
    _patch_exec(monkeypatch, proc)

    dim_means, *_rest = asyncio.run(run_audit_async(dry_run=False))
    assert dim_means["broken_tool_use"] == 9.9


# ---------------------------------------------------------------------------
# Default timeout falls back to the sync resolver when not overridden
# ---------------------------------------------------------------------------


def test_async_default_timeout_matches_sync_resolver(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _redirect_journal(tmp_path, monkeypatch)
    monkeypatch.setattr(auto_train, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(auto_train, "RUN_LOG", tmp_path / "state" / "run.log")
    monkeypatch.setattr(auto_train, "WRAPPER_OVERRIDE_HOOK_READY", True)

    proc = _FakeProc(stdout=_summary_stdout({"broken_tool_use": 2.0}), returncode=0)
    _patch_exec(monkeypatch, proc)

    asyncio.run(run_audit_async(dry_run=False, session_id="s-def", gen_tag="gen-def"))

    rows = [json.loads(line) for line in _journal_path(tmp_path, "s-def").read_text().splitlines()]
    started = next(r for r in rows if r["event"] == "subprocess_started")
    # When per_audit_timeout is omitted, the started event reports the sync
    # default (float-coerced).
    assert started["payload"]["timeout_sec"] == pytest.approx(
        float(auto_train._resolve_audit_timeout_sec())
    )
