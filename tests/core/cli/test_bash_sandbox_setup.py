"""Guards for the run_bash sandbox doctor check + setup affordance (no Docker).

The bash sandbox (Phase F) is OS-native (sandbox-exec / bwrap), never Docker —
``geode doctor`` must report it without requiring Docker, and ``geode setup``
must be able to enable it on any machine. These pin both surfaces.
"""

from __future__ import annotations

import pytest
from core.cli import doctor_bootstrap as db
from core.cli import onboarding as ob
from core.config import toml_edit as te
from core.tools import bash_sandbox as bs


@pytest.fixture
def _mode(monkeypatch: pytest.MonkeyPatch):
    from core.config import settings

    def _set(mode: str) -> None:
        monkeypatch.setattr(settings, "bash_sandbox", mode, raising=False)

    return _set


class TestSandboxBinaryStatus:
    def test_macos(self, monkeypatch) -> None:
        monkeypatch.setattr(bs.sys, "platform", "darwin")
        monkeypatch.setattr(bs.os.path, "exists", lambda p: p == "/usr/bin/sandbox-exec")
        assert bs.sandbox_binary_status() == ("sandbox-exec", "/usr/bin/sandbox-exec")

    def test_linux_missing(self, monkeypatch) -> None:
        monkeypatch.setattr(bs.sys, "platform", "linux")
        monkeypatch.setattr(bs.os.path, "exists", lambda p: False)
        monkeypatch.setattr(bs.shutil, "which", lambda name: None)
        assert bs.sandbox_binary_status() == ("bwrap", None)

    def test_unsupported_platform(self, monkeypatch) -> None:
        monkeypatch.setattr(bs.sys, "platform", "win32")
        assert bs.sandbox_binary_status() == ("win32", None)


class TestDoctorCheck:
    def test_available_but_off_is_ok(self, _mode, monkeypatch) -> None:
        _mode("off")
        monkeypatch.setattr(db, "shutil", db.shutil)  # keep real which for docker note
        monkeypatch.setattr(
            "core.tools.bash_sandbox.sandbox_binary_status",
            lambda: ("sandbox-exec", "/usr/bin/sandbox-exec"),
        )
        r = db._check_bash_sandbox()
        assert r.ok is True
        assert "GEODE_BASH_SANDBOX=on" in r.detail
        assert "not required" in r.detail  # Docker note present + optional

    def test_on_with_binary_present_is_ok(self, _mode, monkeypatch) -> None:
        _mode("on")
        monkeypatch.setattr(
            "core.tools.bash_sandbox.sandbox_binary_status",
            lambda: ("bwrap", "/usr/bin/bwrap"),
        )
        r = db._check_bash_sandbox()
        assert r.ok is True and "mode=on" in r.detail

    def test_on_but_binary_missing_fails(self, _mode, monkeypatch) -> None:
        _mode("on")
        monkeypatch.setattr(
            "core.tools.bash_sandbox.sandbox_binary_status", lambda: ("bwrap", None)
        )
        r = db._check_bash_sandbox()
        assert r.ok is False
        assert "not found" in r.detail and r.fix

    def test_never_fails_on_docker_absence(self, _mode, monkeypatch) -> None:
        """Docker absent + sandbox off/available → still OK (Docker not required)."""
        _mode("off")
        monkeypatch.setattr(db.shutil, "which", lambda name: None)  # docker absent
        monkeypatch.setattr(
            "core.tools.bash_sandbox.sandbox_binary_status",
            lambda: ("sandbox-exec", "/usr/bin/sandbox-exec"),
        )
        r = db._check_bash_sandbox()
        assert r.ok is True
        assert "Docker absent" in r.detail


class TestSpliceConfig:
    def test_append_when_absent(self) -> None:
        assert (
            te.splice_toml_section("", "bash_sandbox", {"mode": "on"})
            == '[bash_sandbox]\nmode = "on"\n'
        )

    def test_replace_existing_mode(self) -> None:
        out = te.splice_toml_section(
            '[bash_sandbox]\nmode = "off"\n', "bash_sandbox", {"mode": "strict"}
        )
        assert out == '[bash_sandbox]\nmode = "strict"\n'

    def test_insert_when_section_has_no_mode(self) -> None:
        out = te.splice_toml_section(
            "[bash_sandbox]\n[other]\nx=1\n", "bash_sandbox", {"mode": "on"}
        )
        assert 'mode = "on"' in out and "[other]" in out

    def test_coexists_with_other_sections(self) -> None:
        out = te.splice_toml_section("[llm]\nx = 1\n", "bash_sandbox", {"mode": "on"})
        assert "[llm]" in out and '[bash_sandbox]\nmode = "on"' in out


class TestPersistAndConfigure:
    def test_persist_round_trips_through_settings(self, tmp_path, monkeypatch) -> None:
        cfg = tmp_path / "config.toml"
        monkeypatch.setenv("GEODE_CONFIG_TOML", str(cfg))
        path = te.persist_toml_section("bash_sandbox", {"mode": "strict"})
        assert path == cfg
        assert 'mode = "strict"' in cfg.read_text()

    def test_resolve_config_toml_expands_tilde(self, monkeypatch) -> None:
        """A ``~``-prefixed override expands to the same path the loaders read
        (write/read parity — Codex MCP catch)."""
        monkeypatch.setenv("GEODE_CONFIG_TOML", "~/some/config.toml")
        resolved = str(te.resolve_config_toml_path())
        assert "~" not in resolved
        assert resolved.endswith("some/config.toml")

    def test_configure_eof_does_not_crash(self, _mode, monkeypatch) -> None:
        """Non-interactive (piped/no stdin) setup must skip gracefully."""
        _mode("off")
        monkeypatch.setattr(
            "core.tools.bash_sandbox.sandbox_binary_status",
            lambda: ("sandbox-exec", "/usr/bin/sandbox-exec"),
        )
        monkeypatch.setattr(ob.console, "input", lambda *a, **k: (_ for _ in ()).throw(EOFError()))
        ob.configure_bash_sandbox()  # must not raise

    def test_configure_persists_chosen_mode(self, _mode, tmp_path, monkeypatch) -> None:
        _mode("off")
        cfg = tmp_path / "config.toml"
        monkeypatch.setenv("GEODE_CONFIG_TOML", str(cfg))
        monkeypatch.setattr(
            "core.tools.bash_sandbox.sandbox_binary_status",
            lambda: ("sandbox-exec", "/usr/bin/sandbox-exec"),
        )
        monkeypatch.setattr(ob.console, "input", lambda *a, **k: "strict")
        ob.configure_bash_sandbox()
        assert 'mode = "strict"' in cfg.read_text()

    def test_configure_unavailable_binary_skips_write(self, _mode, tmp_path, monkeypatch) -> None:
        _mode("off")
        cfg = tmp_path / "config.toml"
        monkeypatch.setenv("GEODE_CONFIG_TOML", str(cfg))
        monkeypatch.setattr(
            "core.tools.bash_sandbox.sandbox_binary_status", lambda: ("bwrap", None)
        )
        ob.configure_bash_sandbox()
        assert not cfg.exists()  # no binary → no prompt, no write
