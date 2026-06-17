"""Unit guards for the run_bash command sandbox (Phase F).

The argv/profile BUILDERS are pure functions — these tests pin the security
invariants (deny-default, writable-root scoping, no network allowance, knob
gating, binary-absent fallback) WITHOUT a live sandbox. Actual write/network
blocking is a live test (macOS Seatbelt / Linux bwrap) — see
``test_bash_sandbox_live.py``.
"""

from __future__ import annotations

import pytest
from core.tools import bash_sandbox as bs


@pytest.fixture
def _mode(monkeypatch: pytest.MonkeyPatch):
    """Set settings.bash_sandbox to a given mode for the test."""
    from core.config import settings

    def _set(mode: str) -> None:
        monkeypatch.setattr(settings, "bash_sandbox", mode, raising=False)

    return _set


class TestModeResolution:
    def test_default_off(self, _mode) -> None:
        _mode("off")
        assert bs.bash_sandbox_mode() == "off"

    def test_on_and_strict(self, _mode) -> None:
        _mode("on")
        assert bs.bash_sandbox_mode() == "on"
        _mode("strict")
        assert bs.bash_sandbox_mode() == "strict"

    def test_unknown_value_falls_back_off(self, _mode) -> None:
        _mode("bogus")
        assert bs.bash_sandbox_mode() == "off"


class TestMacosArgv:
    def test_wraps_with_sandbox_exec_and_writable_root(self) -> None:
        argv = bs._macos_argv("echo hi", cwd="/work", binary=bs._MACOS_SANDBOX_EXEC)
        assert argv[0] == "/usr/bin/sandbox-exec"
        assert "-p" in argv and "--" in argv
        # command runs via /bin/sh -c <command> AFTER the `--` separator
        dd = argv.index("--")
        assert argv[dd + 1 : dd + 4] == ["/bin/sh", "-c", "echo hi"]
        # WRITABLE_ROOT_0 is injected as the realpath of cwd (/tmp → /private/tmp on macOS)
        droot = next(a for a in argv if a.startswith("WRITABLE_ROOT_0="))
        assert droot.endswith("/work") or "tmp/work" in droot

    def test_profile_is_deny_default_with_no_network_allow(self) -> None:
        profile = bs._MACOS_SEATBELT_PROFILE
        assert "(deny default)" in profile
        # the writable-root param is referenced
        assert '(subpath (param "WRITABLE_ROOT_0"))' in profile
        # CRITICAL: no network allowance anywhere → (deny default) blocks egress
        assert "allow network" not in profile
        # reads allowed (isolation targets write+network, not reads)
        assert "(allow file-read*)" in profile


class TestLinuxArgv:
    def test_unshares_net_and_binds_cwd_readonly_root(self) -> None:
        argv = bs._linux_argv("echo hi", cwd="/home/u/proj", binary="/usr/bin/bwrap")
        assert argv[0] == "/usr/bin/bwrap"
        # network namespace dropped → egress blocked
        assert "--unshare-net" in argv
        # whole fs read-only, cwd writable
        assert "--ro-bind" in argv
        assert "--bind" in argv
        bind_i = argv.index("--bind")
        assert argv[bind_i + 1] == argv[bind_i + 2]  # writable_root bound to itself
        dd = argv.index("--")
        assert argv[dd + 1 : dd + 4] == ["/bin/sh", "-c", "echo hi"]

    def test_resolve_bwrap_prefers_absolute_over_path(self, monkeypatch) -> None:
        """PATH-injection defense: an absolute well-known bwrap is preferred over
        a PATH-resolved one (which a tampered PATH could point at a fake)."""
        monkeypatch.setattr(bs.os.path, "exists", lambda p: p == "/usr/bin/bwrap")
        monkeypatch.setattr(bs.shutil, "which", lambda name: "/opt/evil/bwrap")
        assert bs._resolve_bwrap() == "/usr/bin/bwrap"

    def test_resolve_bwrap_falls_back_to_path_when_no_absolute(self, monkeypatch) -> None:
        monkeypatch.setattr(bs.os.path, "exists", lambda p: False)
        monkeypatch.setattr(bs.shutil, "which", lambda name: "/opt/custom/bwrap")
        assert bs._resolve_bwrap() == "/opt/custom/bwrap"


class TestResolveGating:
    def test_off_returns_no_wrapping(self, _mode) -> None:
        _mode("off")
        argv, err = bs.resolve_sandbox_argv("echo hi", cwd="/work")
        assert argv is None and err is None

    def test_on_macos_wraps_when_binary_present(self, _mode, monkeypatch) -> None:
        _mode("on")
        monkeypatch.setattr(bs.sys, "platform", "darwin")
        monkeypatch.setattr(bs.os.path, "exists", lambda p: True)
        argv, err = bs.resolve_sandbox_argv("echo hi", cwd="/work")
        assert err is None
        assert argv is not None and argv[0] == "/usr/bin/sandbox-exec"

    def test_on_linux_wraps_when_bwrap_present(self, _mode, monkeypatch) -> None:
        _mode("on")
        monkeypatch.setattr(bs.sys, "platform", "linux")
        # force the PATH fallback deterministically (no absolute candidate exists)
        monkeypatch.setattr(bs.os.path, "exists", lambda p: False)
        monkeypatch.setattr(bs.shutil, "which", lambda name: "/usr/bin/bwrap")
        argv, err = bs.resolve_sandbox_argv("echo hi", cwd="/home/u")
        assert err is None
        assert argv is not None and argv[0] == "/usr/bin/bwrap" and "--unshare-net" in argv

    def test_on_unavailable_falls_back_unsandboxed(self, _mode, monkeypatch) -> None:
        """on + no binary → run unsandboxed (None, None) with a warning, NOT a fail."""
        _mode("on")
        monkeypatch.setattr(bs.sys, "platform", "darwin")
        monkeypatch.setattr(bs.os.path, "exists", lambda p: False)
        argv, err = bs.resolve_sandbox_argv("echo hi", cwd="/work")
        assert argv is None and err is None

    def test_strict_unavailable_fails_loud(self, _mode, monkeypatch) -> None:
        """strict + no binary → (None, error). Caller MUST fail — never fail-open."""
        _mode("strict")
        monkeypatch.setattr(bs.sys, "platform", "darwin")
        monkeypatch.setattr(bs.os.path, "exists", lambda p: False)
        argv, err = bs.resolve_sandbox_argv("echo hi", cwd="/work")
        assert argv is None
        assert err is not None and "strict" in err.lower()

    def test_strict_unsupported_platform_fails(self, _mode, monkeypatch) -> None:
        _mode("strict")
        monkeypatch.setattr(bs.sys, "platform", "win32")
        argv, err = bs.resolve_sandbox_argv("echo hi", cwd="C:/work")
        assert argv is None and err is not None
