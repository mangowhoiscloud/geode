"""PR-SMOKE-LOG-FLAG (2026-05-26) — ``audit-seeds generate --smoke-log``
helper invariants.

Operators have been hand-redirecting smoke stdout to
``.audit/smoke-archives/smoke-<N>-<TS>.log`` since smoke 21. The
redirect is easy to forget (smoke 24 landed in ``/tmp/`` because the
operator forgot the ``>``) and has no compile-time gate. This flag
auto-resolves the path while staying opt-in (default off).

These tests pin the helper invariants without invoking the full
``audit-seeds generate`` pipeline (which would require a real
self-improving-loop config + adapter chain). The pipeline integration
itself is exercised by the next smoke run; this file gates the path
resolution + tee behavior independently.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from plugins.seed_generation.cli import (
    _next_smoke_counter,
    _resolve_smoke_log_path,
    _setup_smoke_log_tee,
    _TeeStream,
)


def test_next_smoke_counter_empty_dir_returns_one(tmp_path: Path) -> None:
    """No existing smoke-*-*.log files → counter starts at 1."""
    assert _next_smoke_counter(tmp_path) == 1


def test_next_smoke_counter_missing_dir_returns_one(tmp_path: Path) -> None:
    """Directory does not exist → counter starts at 1 (no crash)."""
    nonexistent = tmp_path / "definitely-not-there"
    assert not nonexistent.exists()
    assert _next_smoke_counter(nonexistent) == 1


def test_next_smoke_counter_picks_max_plus_one(tmp_path: Path) -> None:
    """The new counter must be ``max(existing) + 1`` so two smoke runs
    in the same wallsecond still get distinct counter values."""
    (tmp_path / "smoke-1-1779000000.log").touch()
    (tmp_path / "smoke-23-1779700000.log").touch()
    (tmp_path / "smoke-7-1779500000.log").touch()
    assert _next_smoke_counter(tmp_path) == 24


def test_next_smoke_counter_ignores_malformed_names(tmp_path: Path) -> None:
    """Files that don't match ``smoke-<int>-<TS>.log`` are skipped — a
    stale ``smoke-rundir-1779662494/`` style entry must not break the
    counter."""
    (tmp_path / "smoke-1-1779000000.log").touch()
    (tmp_path / "smoke-abc-foo.log").touch()  # malformed
    (tmp_path / "other.log").touch()  # unrelated
    assert _next_smoke_counter(tmp_path) == 2


def test_resolve_auto_returns_archives_path() -> None:
    """``auto`` resolves under ``.audit/smoke-archives/`` with the
    ``smoke-<N>-<TS>.log`` naming convention."""
    path = _resolve_smoke_log_path("auto", now_ts=1779999999)
    assert path.parent.name == "smoke-archives"
    assert path.parent.parent.name == ".audit"
    assert path.name.startswith("smoke-")
    assert path.name.endswith("-1779999999.log")


def test_resolve_explicit_path_passes_through(tmp_path: Path) -> None:
    """Any value other than ``auto`` is treated as a literal path."""
    custom = tmp_path / "my-smoke.log"
    path = _resolve_smoke_log_path(str(custom))
    assert path == custom


def test_setup_none_returns_none_and_leaves_stdout_untouched() -> None:
    """Default ``--smoke-log`` (None) is a no-op — the test invariant
    that smoke 23 / smoke 24 era operators do not get surprised when
    omitting the flag."""
    import sys

    orig_stdout = sys.stdout
    result = _setup_smoke_log_tee(None)
    try:
        assert result is None
        assert sys.stdout is orig_stdout
    finally:
        sys.stdout = orig_stdout


def test_setup_writes_to_target_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When set, the tee actually writes through to the target file
    so the smoke log captures whatever ``print()`` / ``typer.echo``
    emit."""
    import sys

    log_path = tmp_path / "smoke-test.log"
    orig_stdout = sys.stdout
    result = _setup_smoke_log_tee(str(log_path))
    try:
        assert result == log_path
        print("hello smoke log")
        sys.stdout.flush()
        contents = log_path.read_text(encoding="utf-8")
        assert "hello smoke log" in contents
    finally:
        sys.stdout = orig_stdout


def test_tee_stream_forwards_write_count() -> None:
    """``_TeeStream.write`` must return the primary stream's byte
    count so callers that expect ``print`` -semantics keep working."""
    primary = io.StringIO()
    secondary = io.StringIO()
    tee = _TeeStream(primary, secondary)
    n = tee.write("abc")
    assert n == 3
    assert primary.getvalue() == "abc"
    assert secondary.getvalue() == "abc"


def test_tee_stream_secondary_failure_does_not_crash() -> None:
    """A failed write to the secondary (e.g. disk full mid-smoke) must
    never crash the actual pipeline — the primary stream is
    authoritative."""

    class _BrokenWriter:
        def write(self, s: str) -> int:
            raise OSError("disk full")

        def flush(self) -> None:
            raise OSError("disk full")

    primary = io.StringIO()
    tee = _TeeStream(primary, _BrokenWriter())  # type: ignore[arg-type]
    n = tee.write("survives")
    assert n == len("survives")
    assert primary.getvalue() == "survives"
    tee.flush()  # also must not raise


def test_tee_stream_forwards_arbitrary_attrs() -> None:
    """``_TeeStream`` must proxy non-write attributes (``isatty``,
    ``encoding``, ``buffer`` etc.) to the primary so ``typer.echo`` +
    Rich formatting keep their feature detection."""
    primary = io.StringIO()
    primary_encoding = getattr(primary, "encoding", None)
    secondary = io.StringIO()
    tee = _TeeStream(primary, secondary)
    assert getattr(tee, "encoding", None) == primary_encoding
