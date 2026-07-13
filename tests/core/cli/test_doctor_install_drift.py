"""Tests for the install-drift checks in the bootstrap doctor.

Three real incidents these pin:

- PATH shadow: a Homebrew ``geode`` earlier on PATH shadowed the editable
  uv-tool install, so operators verified against the wrong (stale) binary.
- Daemon/CLI version drift: after a rebuild, a never-restarted serve daemon
  keeps answering with old code while ``geode version`` prints the new one.
- Missing ``[audit]`` extra: rebuilding without it silently zero-fills the
  self-improving loop's dim_means.
"""

from __future__ import annotations

import contextlib
import json
import os
import socket
import tempfile
import threading
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

from core import __version__
from core.cli.doctor_bootstrap import (
    _audit_extra_dists,
    _check_audit_extra,
    _check_path_install_shadow,
    _check_serve_version_drift,
    _classify_geode_install,
    _iter_path_geode_installs,
    run_bootstrap_doctor,
)
from core.cli.ipc_client import query_serve_version
from core.server.ipc_server.poller import _session_greeting


def _make_executable(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\nexit 0\n")
    path.chmod(0o755)
    return path


class TestIterPathGeodeInstalls:
    def test_collects_in_path_order(self, tmp_path, monkeypatch):
        first = _make_executable(tmp_path / "a" / "geode")
        second = _make_executable(tmp_path / "b" / "geode")
        empty = tmp_path / "c"
        empty.mkdir()
        monkeypatch.setenv(
            "PATH", os.pathsep.join([str(tmp_path / "a"), str(empty), str(tmp_path / "b")])
        )
        installs = _iter_path_geode_installs()
        assert [candidate for candidate, _resolved in installs] == [first, second]

    def test_skips_non_executable_and_duplicate_dirs(self, tmp_path, monkeypatch):
        plain = tmp_path / "a" / "geode"
        plain.parent.mkdir(parents=True)
        plain.write_text("not executable")
        real = _make_executable(tmp_path / "b" / "geode")
        # Duplicate PATH entry must be visited once, not reported twice.
        monkeypatch.setenv(
            "PATH", os.pathsep.join([str(tmp_path / "a"), str(tmp_path / "b"), str(tmp_path / "b")])
        )
        installs = _iter_path_geode_installs()
        assert [candidate for candidate, _resolved in installs] == [real]

    def test_resolves_symlinks(self, tmp_path, monkeypatch):
        target = _make_executable(tmp_path / "real" / "geode")
        link_dir = tmp_path / "bin"
        link_dir.mkdir()
        (link_dir / "geode").symlink_to(target)
        monkeypatch.setenv("PATH", str(link_dir))
        installs = _iter_path_geode_installs()
        assert installs == [(link_dir / "geode", target.resolve())]


class TestClassifyGeodeInstall:
    def test_homebrew_prefix(self):
        assert (
            _classify_geode_install(Path("/opt/homebrew/Cellar/geode/0.99.0/bin/geode"))
            == "homebrew"
        )
        assert _classify_geode_install(Path("/usr/local/Cellar/geode/0.99.0/bin/geode")) == (
            "homebrew"
        )

    def test_cellar_anywhere_is_homebrew(self, tmp_path):
        assert _classify_geode_install(tmp_path / "Cellar" / "geode" / "bin" / "geode") == (
            "homebrew"
        )

    def test_uv_tool_locations(self, tmp_path, monkeypatch):
        fake_home = tmp_path / "home"
        monkeypatch.setattr(Path, "home", lambda: fake_home)
        tools_bin = fake_home / ".local" / "share" / "uv" / "tools" / "geode-agent" / "bin"
        assert _classify_geode_install(tools_bin / "geode") == "uv-tool"
        assert _classify_geode_install(fake_home / ".local" / "bin" / "geode") == "uv-tool"

    def test_other(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
        assert _classify_geode_install(Path("/usr/bin/geode")) == "other"


class TestCheckPathInstallShadow:
    def test_no_geode_on_path_passes(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PATH", str(tmp_path))
        result = _check_path_install_shadow()
        assert result.ok is True
        assert "nothing to shadow" in result.detail

    def test_single_install_passes(self, tmp_path, monkeypatch):
        _make_executable(tmp_path / "bin" / "geode")
        monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
        monkeypatch.setenv("PATH", str(tmp_path / "bin"))
        result = _check_path_install_shadow()
        assert result.ok is True
        assert "single install" in result.detail

    def test_two_entries_same_resolved_target_pass(self, tmp_path, monkeypatch):
        target = _make_executable(tmp_path / "real" / "geode")
        link_dir = tmp_path / "links"
        link_dir.mkdir()
        (link_dir / "geode").symlink_to(target)
        monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
        monkeypatch.setenv("PATH", os.pathsep.join([str(link_dir), str(tmp_path / "real")]))
        result = _check_path_install_shadow()
        assert result.ok is True
        assert "single install" in result.detail

    def test_homebrew_shadowing_uv_tool_warns(self, tmp_path, monkeypatch):
        # The incident shape: Homebrew wins, editable uv-tool install shadowed.
        # resolve() so the classifier's home-relative compare survives a
        # symlinked tmp base (/var/folders -> /private/var/folders on macOS).
        fake_home = tmp_path.resolve() / "home"
        monkeypatch.setattr(Path, "home", lambda: fake_home)
        brew_target = _make_executable(tmp_path / "Cellar" / "geode" / "0.9" / "bin" / "geode")
        brew_bin = tmp_path / "brewbin"
        brew_bin.mkdir()
        (brew_bin / "geode").symlink_to(brew_target)
        uv_geode = _make_executable(fake_home / ".local" / "bin" / "geode")
        monkeypatch.setenv("PATH", os.pathsep.join([str(brew_bin), str(uv_geode.parent)]))

        result = _check_path_install_shadow()

        assert result.ok is False
        assert "winner" in result.detail
        assert str(brew_target.resolve()) in result.detail
        assert "(homebrew)" in result.detail
        assert str(uv_geode.resolve()) in result.detail
        assert "(uv-tool)" in result.detail
        assert "brew uninstall geode" in result.fix

    def test_two_other_installs_warn_without_brew_hint(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
        a = _make_executable(tmp_path / "a" / "geode")
        b = _make_executable(tmp_path / "b" / "geode")
        monkeypatch.setenv("PATH", os.pathsep.join([str(a.parent), str(b.parent)]))

        result = _check_path_install_shadow()

        assert result.ok is False
        assert "2 distinct installs" in result.detail
        assert "brew uninstall" not in result.fix
        assert "reorder PATH" in result.fix


class TestSessionGreeting:
    def test_greeting_carries_daemon_version(self):
        greeting = _session_greeting("cli-abc123")
        assert greeting["type"] == "session"
        assert greeting["session_id"] == "cli-abc123"
        assert greeting["version"] == __version__


@contextlib.contextmanager
def _fake_daemon(sock_path: Path, raw: bytes) -> Iterator[None]:
    """One-shot fake serve daemon: accept a connection, send ``raw``, close."""
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(sock_path))
    server.listen(1)

    def _serve() -> None:
        try:
            conn, _addr = server.accept()
        except OSError:
            return
        with conn:
            conn.sendall(raw)

    thread = threading.Thread(target=_serve, daemon=True)
    thread.start()
    try:
        yield
    finally:
        server.close()
        thread.join(timeout=2.0)


@contextlib.contextmanager
def _short_socket_path() -> Iterator[Path]:
    """AF_UNIX paths are length-limited (~104 bytes on macOS); pytest's
    tmp_path can exceed that, so bind in a short mkdtemp dir instead."""
    tmp_dir = tempfile.mkdtemp(prefix="gd-")
    try:
        yield Path(tmp_dir) / "s.sock"
    finally:
        import shutil

        shutil.rmtree(tmp_dir, ignore_errors=True)


class TestQueryServeVersion:
    def test_socket_absent_returns_none(self, tmp_path):
        assert query_serve_version(tmp_path / "missing.sock") is None

    def test_stale_socket_file_returns_none(self, tmp_path):
        stale = tmp_path / "stale.sock"
        stale.write_text("")
        assert query_serve_version(stale) is None

    def test_greeting_with_version(self):
        greeting = json.dumps({"type": "session", "session_id": "cli-x", "version": "1.2.3"})
        with (
            _short_socket_path() as sock_path,
            _fake_daemon(sock_path, (greeting + "\n").encode("utf-8")),
        ):
            assert query_serve_version(sock_path) == "1.2.3"

    def test_greeting_without_version_returns_empty(self):
        # A daemon build predating the version handshake.
        greeting = json.dumps({"type": "session", "session_id": "cli-x"})
        with (
            _short_socket_path() as sock_path,
            _fake_daemon(sock_path, (greeting + "\n").encode("utf-8")),
        ):
            assert query_serve_version(sock_path) == ""

    def test_non_session_greeting_returns_none(self):
        with (
            _short_socket_path() as sock_path,
            _fake_daemon(sock_path, b'{"type": "error", "message": "nope"}\n'),
        ):
            assert query_serve_version(sock_path) is None

    def test_garbled_greeting_returns_none(self):
        with (
            _short_socket_path() as sock_path,
            _fake_daemon(sock_path, b"not json\n"),
        ):
            assert query_serve_version(sock_path) is None


class TestCheckServeVersionDrift:
    def test_daemon_not_running_skips(self):
        with patch("core.cli.ipc_client.query_serve_version", return_value=None):
            result = _check_serve_version_drift()
        assert result.ok is True
        assert "skipped" in result.detail

    def test_matching_versions_pass(self):
        with patch("core.cli.ipc_client.query_serve_version", return_value=__version__):
            result = _check_serve_version_drift()
        assert result.ok is True
        assert __version__ in result.detail

    def test_mismatch_warns_with_kickstart_fix(self):
        with patch("core.cli.ipc_client.query_serve_version", return_value="0.0.1"):
            result = _check_serve_version_drift()
        assert result.ok is False
        assert "0.0.1" in result.detail
        assert __version__ in result.detail
        assert "launchctl kickstart -k gui/$(id -u)/com.geode.serve" in result.fix

    def test_versionless_greeting_warns(self):
        with patch("core.cli.ipc_client.query_serve_version", return_value=""):
            result = _check_serve_version_drift()
        assert result.ok is False
        assert "predates" in result.detail
        assert "launchctl kickstart" in result.fix


class TestAuditExtraDists:
    def test_parses_and_normalizes_requirement_names(self, tmp_path):
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            "[project]\n"
            'name = "x"\n'
            'version = "0.0.0"\n'
            "[project.optional-dependencies]\n"
            "audit = [\n"
            '    "inspect-ai>=0.3.211",\n'
            '    "inspect_petri @ git+https://example.invalid/inspect_petri@abc",\n'
            '    "mcp>=1.0.0",\n'
            "]\n"
        )
        with patch("core.cli.doctor_bootstrap._PYPROJECT_PATH", pyproject):
            dists = _audit_extra_dists()
        assert dists == ["inspect-ai", "inspect-petri", "mcp"]

    def test_missing_pyproject_returns_none(self, tmp_path):
        with patch("core.cli.doctor_bootstrap._PYPROJECT_PATH", tmp_path / "absent.toml"):
            assert _audit_extra_dists() is None

    def test_real_pyproject_declares_probeable_audit_dists(self):
        # Wiring guard: the shipped pyproject must keep at least one dist the
        # doctor knows how to probe, or the check silently degrades to a skip.
        from core.cli.doctor_bootstrap import _AUDIT_DIST_IMPORTS

        dists = _audit_extra_dists()
        assert dists is not None
        assert any(dist in _AUDIT_DIST_IMPORTS for dist in dists)


class TestCheckAuditExtra:
    def _pyproject(self, tmp_path, audit_line: str) -> Path:
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            "[project]\n"
            'name = "x"\n'
            'version = "0.0.0"\n'
            "[project.optional-dependencies]\n"
            f"audit = [{audit_line}]\n"
        )
        return pyproject

    def test_all_present_passes(self, tmp_path):
        pyproject = self._pyproject(tmp_path, '"inspect-ai>=0.3", "inspect-petri"')
        with (
            patch("core.cli.doctor_bootstrap._PYPROJECT_PATH", pyproject),
            patch("core.cli.doctor_bootstrap.find_spec", return_value=object()),
        ):
            result = _check_audit_extra()
        assert result.ok is True
        assert "2 probed package(s)" in result.detail

    def test_missing_module_warns_with_install_fix(self, tmp_path):
        pyproject = self._pyproject(tmp_path, '"inspect-ai>=0.3", "inspect-petri"')

        def fake_find_spec(name: str):
            return object() if name == "inspect_ai" else None

        with (
            patch("core.cli.doctor_bootstrap._PYPROJECT_PATH", pyproject),
            patch("core.cli.doctor_bootstrap.find_spec", side_effect=fake_find_spec),
        ):
            result = _check_audit_extra()
        assert result.ok is False
        assert "zero-fill" in result.detail
        assert "inspect_petri" in result.detail
        assert result.fix == 'uv tool install -e ".[audit]" --force'

    def test_wheel_install_without_pyproject_skips(self, tmp_path):
        with patch("core.cli.doctor_bootstrap._PYPROJECT_PATH", tmp_path / "absent.toml"):
            result = _check_audit_extra()
        assert result.ok is True
        assert "skipped" in result.detail

    def test_only_unmapped_dists_skips(self, tmp_path):
        # ``mcp`` is ambiguous (also provided by the [mcp] extra) — never probed.
        pyproject = self._pyproject(tmp_path, '"mcp>=1.0.0"')
        with patch("core.cli.doctor_bootstrap._PYPROJECT_PATH", pyproject):
            result = _check_audit_extra()
        assert result.ok is True
        assert "no probeable" in result.detail


class TestRunWiring:
    def test_run_bootstrap_doctor_includes_drift_checks(self):
        # No real daemon: force the version probe to the not-running branch.
        with patch("core.cli.ipc_client.query_serve_version", return_value=None):
            report = run_bootstrap_doctor()
        names = [check.name for check in report.checks]
        assert "geode PATH shadow" in names
        assert "serve/CLI version" in names
        assert "[audit] extra" in names
