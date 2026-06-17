"""Command-execution sandbox for ``run_bash`` — codex-convergent shell-out.

Phase F of the computer-use enhancement (``docs/plans/2026-06-14-computer-use-
enhancement.md`` + ``docs/research/computer-use-sandbox-frontier.md``). GEODE is
Python (no Rust) so it cannot use codex's ``landlock`` / ``seccompiler`` crates;
the convergent pattern across codex and Claude Code's ``srt`` is to **shell out
to the OS sandbox binary** — macOS ``/usr/bin/sandbox-exec`` (Seatbelt) and Linux
``bwrap`` (bubblewrap). This module BUILDS the wrapping argv; ``bash_tool``
executes it.

Threat model: a ``run_bash`` command must not (a) write outside its working
directory (+ temp dirs) or (b) reach the network. Reads are NOT restricted (the
isolation targets WRITE + NETWORK, matching codex's broad-read / narrow-write
posture). The macOS profile is modelled on codex's ``seatbelt_base_policy.sbpl``
(``~/workspace/codex/codex-rs/sandboxing/src/``) — ``(deny default)`` + the
process/sysctl/pty allowances real commands need + writable roots, with NO
network rule so ``(deny default)`` blocks egress.

Opt-in via ``GEODE_BASH_SANDBOX`` (``off`` default | ``on`` | ``strict``). The
sandbox binary is resolved at runtime; when it is absent, ``on`` falls back to
unsandboxed execution with a loud warning (codex does the same — bwrap needs
user namespaces that CI / WSL1 / hardened hosts may lack), and ``strict`` fails.
A ``supports=True`` flag is deliberately NOT hardcoded.

Isolation guarantee is **live-only**: the argv/profile builders here are pure
functions (unit-tested), but actual write/network blocking requires a real
macOS (Seatbelt) or Linux+userns (bwrap) host and is ``unverified`` until a live
run proves it (macOS path live-verified 2026-06-18; Linux bwrap path
``unverified — live test required``).
"""

from __future__ import annotations

import logging
import os
import shutil
import sys

log = logging.getLogger(__name__)

# macOS: hardcode the absolute path (PATH-injection defense — a tampered
# ``sandbox-exec`` earlier on PATH would otherwise run unsandboxed). Mirrors
# codex ``seatbelt.rs`` ``MACOS_PATH_TO_SEATBELT_EXECUTABLE``.
_MACOS_SANDBOX_EXEC = "/usr/bin/sandbox-exec"

# Linux: prefer well-known absolute paths before falling back to PATH lookup —
# a PATH-controlled fake ``bwrap`` would otherwise be honoured even in strict
# mode (macOS sidesteps this by hardcoding the Seatbelt path above).
_LINUX_BWRAP_PATHS = ("/usr/bin/bwrap", "/usr/local/bin/bwrap", "/bin/bwrap")


def _resolve_bwrap() -> str | None:
    """Resolve the ``bwrap`` binary, preferring absolute paths (PATH-injection
    defense), falling back to ``PATH`` only for non-standard installs."""
    for candidate in _LINUX_BWRAP_PATHS:
        if os.path.exists(candidate):
            return candidate
    return shutil.which("bwrap")


def sandbox_binary_status() -> tuple[str, str | None]:
    """Report the current platform's bash-sandbox binary and whether it is found.

    Returns ``(binary_name, resolved_path_or_None)`` — e.g. ``("sandbox-exec",
    "/usr/bin/sandbox-exec")`` on macOS, ``("bwrap", None)`` on a Linux host
    without bubblewrap, ``("<platform>", None)`` on an unsupported OS. Used by
    ``geode doctor`` / ``geode setup`` to surface availability WITHOUT
    duplicating the per-platform resolution above — and to make clear the bash
    sandbox needs only this OS binary, never Docker.
    """
    platform = sys.platform
    if platform == "darwin":
        path = _MACOS_SANDBOX_EXEC if os.path.exists(_MACOS_SANDBOX_EXEC) else None
        return "sandbox-exec", path
    if platform.startswith("linux"):
        return "bwrap", _resolve_bwrap()
    return platform, None


# The Seatbelt profile. ``WRITABLE_ROOT_0`` (the command's cwd) is injected via
# ``-D WRITABLE_ROOT_0=<path>`` and referenced with ``(param ...)``. Temp dirs
# are writable so build tools function; everything else is read-only and there
# is no network allowance, so ``(deny default)`` blocks egress.
_MACOS_SEATBELT_PROFILE = """(version 1)
(deny default)

; child processes inherit the policy of their parent
(allow process-exec)
(allow process-fork)
(allow signal (target same-sandbox))
(allow process-info* (target same-sandbox))

; informational reads many tools (python, git, compilers) require
(allow sysctl-read)
(allow mach-lookup
  (global-name "com.apple.system.opendirectoryd.libinfo")
  (global-name "com.apple.cfprefsd.daemon")
  (global-name "com.apple.cfprefsd.agent"))
(allow ipc-posix-sem)
(allow user-preference-read)

; reads are unrestricted — isolation targets WRITE + NETWORK, not confidentiality
(allow file-read*)
(allow file-test-existence)

; writes: only the command's working dir + temp dirs + /dev/null
(allow file-write* (subpath (param "WRITABLE_ROOT_0")))
(allow file-write* (subpath "/tmp"))
(allow file-write* (subpath "/private/tmp"))
(allow file-write* (subpath "/var/tmp"))
(allow file-write* (subpath "/private/var/tmp"))
(allow file-write-data
  (require-all
    (path "/dev/null")
    (vnode-type CHARACTER-DEVICE)))

; ptys so interactive-style tools detect a tty and stay functional
(allow pseudo-tty)
(allow file-read* file-write* file-ioctl (literal "/dev/ptmx"))
(allow file-read* file-write* file-ioctl (regex #"^/dev/ttys[0-9]+"))

; No network rule is granted, so egress is denied by (deny default).
"""


def bash_sandbox_mode() -> str:
    """Resolve the ``GEODE_BASH_SANDBOX`` knob: ``off`` (default) | ``on`` | ``strict``.

    Reads ``settings.bash_sandbox`` (function-local import so a mid-session
    config reload is honoured, mirroring the routing-constant accessors).
    """
    from core.config import settings

    mode = str(getattr(settings, "bash_sandbox", "off") or "off").strip().lower()
    return mode if mode in {"off", "on", "strict"} else "off"


def _macos_argv(command: str, *, cwd: str, binary: str) -> list[str]:
    """``sandbox-exec -p <profile> -D WRITABLE_ROOT_0=<cwd> -- /bin/sh -c <cmd>``."""
    writable_root = os.path.realpath(cwd)
    return [
        binary,
        "-p",
        _MACOS_SEATBELT_PROFILE,
        "-D",
        f"WRITABLE_ROOT_0={writable_root}",
        "--",
        "/bin/sh",
        "-c",
        command,
    ]


def _linux_argv(command: str, *, cwd: str, binary: str) -> list[str]:
    """bubblewrap: read-only root, writable cwd, no network namespace.

    ``--unshare-net`` drops the command into an empty network namespace (no
    interfaces beyond loopback-down), so **IP egress** is blocked without a
    proxy. Two gaps vs codex's full Linux posture, deferred to a follow-up
    (Phase F+1, which needs ``libseccomp`` ctypes):

    - **Unix-domain sockets remain reachable by path**: ``--ro-bind / /`` keeps
      the host filesystem readable, so a command can still ``connect()`` to a
      host AF_UNIX socket (e.g. ``/var/run/docker.sock``). ``--unshare-net``
      only covers AF_INET. Full closure needs seccomp socket-deny or tmpfs over
      the socket dirs.
    - **No syscall filter**: codex adds seccomp (ptrace/io_uring/socket deny);
      this path does not yet.

    So the Linux path's guarantee is "no IP egress + no write outside cwd",
    NOT the stronger macOS Seatbelt closure. Mirrors codex ``bwrap.rs``
    (``--unshare-net`` + ``--ro-bind / /`` + cwd ``--bind``) minus seccomp.
    """
    writable_root = os.path.realpath(cwd)
    return [
        binary,
        "--unshare-user",
        "--unshare-pid",
        "--unshare-net",
        "--die-with-parent",
        "--ro-bind",
        "/",
        "/",
        "--bind",
        writable_root,
        writable_root,
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--",
        "/bin/sh",
        "-c",
        command,
    ]


def resolve_sandbox_argv(command: str, *, cwd: str) -> tuple[list[str] | None, str | None]:
    """Decide how ``command`` should run under the bash sandbox knob.

    Returns ``(argv, error)``:

    - ``(None, None)`` — run unsandboxed (knob ``off``, OR ``on`` with the
      sandbox binary / platform unavailable → a loud warning was logged).
    - ``(argv, None)`` — run this wrapped argv via ``create_subprocess_exec``.
    - ``(None, error)`` — ``strict`` mode but the sandbox is unavailable; the
      caller must FAIL the command with ``error`` (never silently run
      unsandboxed when the operator demanded strict isolation = fail-open hole).

    Binary presence is checked at call time (``os.path.exists`` for the
    hardcoded macOS path, ``shutil.which`` for ``bwrap``). No ``supports=True``
    is cached — availability can change across hosts/sessions.
    """
    mode = bash_sandbox_mode()
    if mode == "off":
        return None, None

    platform = sys.platform
    if platform == "darwin":
        binary = _MACOS_SANDBOX_EXEC if os.path.exists(_MACOS_SANDBOX_EXEC) else None
        builder, binname = _macos_argv, "sandbox-exec"
    elif platform.startswith("linux"):
        binary = _resolve_bwrap()
        builder, binname = _linux_argv, "bwrap"
    else:
        return _unavailable(mode, f"platform={platform} has no supported sandbox binary")

    if binary is None:
        return _unavailable(mode, f"{binname} missing on platform={platform}")

    return builder(command, cwd=cwd, binary=binary), None


def _unavailable(mode: str, reason: str) -> tuple[None, str | None]:
    """Resolve the no-sandbox-binary outcome by mode: strict → fail, else warn + run."""
    msg = f"GEODE_BASH_SANDBOX={mode} but {reason}"
    if mode == "strict":
        return None, msg + " — refusing to run unsandboxed (strict)."
    log.warning("%s — running UNSANDBOXED (set GEODE_BASH_SANDBOX=off to silence).", msg)
    return None, None
