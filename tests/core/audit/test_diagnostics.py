"""Tests for ``core.audit.diagnostics`` — file-based diagnostics log
surviving inspect_ai subprocess boundaries.

Mirrors PR E/F (2026-05-11) 의 fa4 pattern 의 정식 인프라화 검증.
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from core.audit.diagnostics import DEFAULT_DIAGNOSTICS_DIR, diag, diagnostics_path


class TestDiagnosticsPath:
    def test_env_override_takes_priority(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        target = tmp_path / "subdir" / "custom.log"
        monkeypatch.setenv("GEODE_DIAGNOSTICS_LOG", str(target))
        assert diagnostics_path() == target

    def test_env_override_expands_user(self, monkeypatch: pytest.MonkeyPatch):
        # ~ in the override path expands to $HOME — supports the docs
        # snippet ``GEODE_DIAGNOSTICS_LOG=~/scratch/fa4.log``.
        monkeypatch.setenv("GEODE_DIAGNOSTICS_LOG", "~/scratch/fa4.log")
        path = diagnostics_path()
        assert str(path).startswith(str(Path.home()))
        assert path.name == "fa4.log"

    def test_default_path_uses_monthly_rotation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        # Redirect ~/.geode/diagnostics/ to tmp via HOME override so
        # the test does not touch the real user dir.
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.delenv("GEODE_DIAGNOSTICS_LOG", raising=False)
        # DEFAULT_DIAGNOSTICS_DIR was resolved at import time relative
        # to the original HOME, so patch the module constant too.
        import core.audit.diagnostics as diag_mod

        monkeypatch.setattr(
            diag_mod, "DEFAULT_DIAGNOSTICS_DIR", tmp_path / ".geode" / "diagnostics"
        )
        path = diagnostics_path()
        # Format: <YYYY>-<MM>.log
        assert path.parent == tmp_path / ".geode" / "diagnostics"
        assert path.name.endswith(".log")
        assert len(path.stem) == 7  # YYYY-MM
        assert path.stem[4] == "-"
        # mkdir was triggered
        assert path.parent.is_dir()

    def test_default_dir_constant_under_dot_geode(self):
        # Documented contract — caller-friendly constant for grep + jq.
        assert Path.home() / ".geode" / "diagnostics" == DEFAULT_DIAGNOSTICS_DIR


class TestDiag:
    @pytest.fixture()
    def log_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        p = tmp_path / "fa4.log"
        monkeypatch.setenv("GEODE_DIAGNOSTICS_LOG", str(p))
        return p

    def test_writes_ts_pid_component_msg(self, log_path: Path):
        diag("petri.runner", "entry msg_count=4")
        lines = log_path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        parts = lines[0].split(" ", 3)
        assert len(parts) == 4
        ts_str, pid_str, component, msg = parts
        # ts is a unix-epoch float with millisecond precision
        assert float(ts_str) == pytest.approx(time.time(), abs=5.0)
        assert int(pid_str) == os.getpid()
        assert component == "petri.runner"
        assert msg == "entry msg_count=4"

    def test_appends_multiple_lines(self, log_path: Path):
        for i in range(3):
            diag("petri.anthropic", f"event {i}")
        lines = log_path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 3
        assert all("petri.anthropic" in line for line in lines)
        assert "event 0" in lines[0]
        assert "event 2" in lines[2]

    def test_swallows_oserror_on_write(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        # Point to a path inside a *file* (not a dir) so the `open(append)`
        # call raises ``NotADirectoryError`` — the swallow path's job is
        # to suppress that without re-raising.
        blocker = tmp_path / "not-a-dir"
        blocker.write_text("blocking the path", encoding="utf-8")
        monkeypatch.setenv("GEODE_DIAGNOSTICS_LOG", str(blocker / "child" / "fa4.log"))
        # Must not raise
        diag("petri.runner", "should be swallowed")

    def test_concurrent_writes_preserve_all_lines(self, log_path: Path):
        # Append mode plus per-call open/close keeps multi-threaded
        # writers from clobbering each other. PoC-level robustness —
        # full atomic guarantees are POSIX-dependent, but at least
        # ``len(lines) == N`` must hold for N typical writers.
        N = 20

        def worker(i: int) -> None:
            diag("petri.runner", f"thread-{i}")

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(N)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        lines = log_path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == N
        # Each thread's message is present somewhere
        tags = {f"thread-{i}" for i in range(N)}
        assert {line.rsplit(" ", 1)[-1] for line in lines} == tags


class TestPackageReexport:
    def test_diag_importable_from_core_audit(self):
        # Convenience surface — caller can ``from core.audit import diag``
        # without knowing the submodule path.
        from core.audit import diag as diag_top
        from core.audit import diagnostics_path as path_top
        from core.audit.diagnostics import diag as diag_sub

        assert diag_top is diag_sub
        assert callable(path_top)


def test_diag_callable_signature() -> None:
    """Public surface signature — caller-facing contract."""
    import inspect

    sig = inspect.signature(diag)
    params: dict[str, Any] = dict(sig.parameters)
    assert list(params) == ["component", "msg"]
    # PEP 563 (`from __future__ import annotations`) keeps the
    # annotation as a string until eval.
    assert sig.return_annotation in (None, "None")
