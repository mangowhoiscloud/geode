"""bootstrap doctor — diagnostic checks for the first-run surface.

Verifies the things a beginner would otherwise have to debug by hand:
Python version, ``geode`` on PATH, ``~/.geode/.env`` state, Codex CLI
OAuth credentials, registered ProfileStore profiles, serve daemon
status, IPC socket presence, and install drift (PATH shadow between
multiple ``geode`` binaries, daemon/CLI version parity, ``[audit]``
extra presence).

Used by ``geode doctor`` (default target ``bootstrap``).
"""

from __future__ import annotations

import logging
import os
import platform
import re
import shutil
import socket
import sys
from dataclasses import dataclass, field
from importlib.util import find_spec
from pathlib import Path

log = logging.getLogger(__name__)

# Repo root pyproject.toml — present for editable/source installs, absent for
# wheel installs (where the [audit] extra check degrades to a skip).
_PYPROJECT_PATH = Path(__file__).resolve().parents[2] / "pyproject.toml"

# [audit] extra: distribution name (PEP 503 normalized) -> top-level import
# name, verified against the imports the codebase itself performs
# (core/self_improving/bench_means.py, core/audit/). Only distributions with
# an unambiguous import name are probed — ``mcp`` is deliberately absent
# because the separate [mcp] extra provides the same module, so its presence
# proves nothing about [audit].
_AUDIT_DIST_IMPORTS: dict[str, str] = {
    "inspect-ai": "inspect_ai",
    "inspect-petri": "inspect_petri",
    "inspect-evals": "inspect_evals",
    "inspect-harbor": "inspect_harbor",
}

_SERVE_RESTART_FIX = (
    "Rebuild landed but serve still runs the old code — restart it: "
    "`launchctl kickstart -k gui/$(id -u)/com.geode.serve`"
)


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str = ""
    fix: str = ""


@dataclass
class BootstrapReport:
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def all_ok(self) -> bool:
        return all(c.ok for c in self.checks)


def _check_python_version() -> CheckResult:
    major, minor = sys.version_info[:2]
    ok = (major, minor) >= (3, 12)
    return CheckResult(
        name="Python 3.12+",
        ok=ok,
        detail=f"running {major}.{minor}.{sys.version_info[2]}",
        fix="" if ok else "Install Python 3.12 or newer (python.org/downloads)",
    )


def _check_geode_on_path() -> CheckResult:
    geode_bin = shutil.which("geode")
    ok = geode_bin is not None
    return CheckResult(
        name="`geode` on PATH",
        ok=ok,
        detail=geode_bin or "not found",
        fix=(
            ""
            if ok
            else "Run `uv tool install geode-agent` for PyPI, or "
            "`uv tool install -e . --force` from a source checkout"
        ),
    )


def _check_env_file() -> CheckResult:
    from core.paths import GLOBAL_ENV_FILE  # PR-CLEANUP-D2 anchor

    env_path = GLOBAL_ENV_FILE
    ok = env_path.exists()
    return CheckResult(
        name="~/.geode/.env",
        ok=ok,
        detail=f"{env_path} ({'present' if ok else 'absent'})",
        fix="" if ok else "Run `geode setup` to create one",
    )


def _check_codex_oauth() -> CheckResult:
    """Check Codex CLI OAuth token (Path A)."""
    try:
        from core.auth.codex_cli_oauth import read_codex_cli_credentials

        creds = read_codex_cli_credentials()
    except Exception as exc:
        return CheckResult(
            name="Codex CLI OAuth",
            ok=False,
            detail=f"probe failed: {exc}",
            fix="Run `codex auth login` to sign in with your ChatGPT account",
        )

    if not creds:
        return CheckResult(
            name="Codex CLI OAuth",
            ok=False,
            detail="no token at ~/.codex/auth.json",
            fix="Optional. Run `codex auth login` if you have a ChatGPT subscription",
        )

    import time

    expires_at = float(creds.get("expires_at", 0))
    expired = time.time() > expires_at if expires_at else False
    if expired:
        return CheckResult(
            name="Codex CLI OAuth",
            ok=False,
            detail="token expired",
            fix="Run `codex auth login` to refresh",
        )
    account = creds.get("account_id", "unknown")
    return CheckResult(
        name="Codex CLI OAuth",
        ok=True,
        detail=f"valid (account={account})",
    )


def _check_profile_store() -> CheckResult:
    """Confirm at least one usable profile is registered."""
    try:
        from core.wiring.container import ensure_profile_store

        store = ensure_profile_store()
        profiles = [p for p in store.list_all() if p.key]
    except Exception as exc:
        return CheckResult(
            name="ProfileStore",
            ok=False,
            detail=f"load failed: {exc}",
            fix="Run `geode setup` to register a credential",
        )

    if not profiles:
        return CheckResult(
            name="ProfileStore",
            ok=False,
            detail="no usable profiles",
            fix="Run `geode setup` to add a ChatGPT subscription OAuth or API key credential",
        )
    summary = ", ".join(sorted({p.provider for p in profiles}))
    return CheckResult(
        name="ProfileStore",
        ok=True,
        detail=f"{len(profiles)} profile(s) — providers: {summary}",
    )


def _check_serve_socket() -> CheckResult:
    """Check whether geode serve is listening on its IPC socket."""
    from core.paths import CLI_SOCKET_PATH  # PR-CLEANUP-D2 anchor

    sock_path = CLI_SOCKET_PATH
    if not sock_path.exists():
        return CheckResult(
            name="geode serve",
            ok=False,
            detail=f"{sock_path} not present",
            fix="Run `geode serve &` (or just `geode` — auto-starts the daemon)",
        )

    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        s.settimeout(1.0)
        s.connect(str(sock_path))
        return CheckResult(
            name="geode serve",
            ok=True,
            detail=f"listening on {sock_path}",
        )
    except OSError as exc:
        return CheckResult(
            name="geode serve",
            ok=False,
            detail=f"socket present but not accepting: {exc}",
            fix="Stale socket. Kill any zombie `geode serve` PIDs and re-run `geode`",
        )
    finally:
        s.close()


def _check_local_bin_on_path() -> CheckResult:
    """Verify ~/.local/bin is on PATH (where uv tool install puts geode)."""
    local_bin = str(Path("~/.local/bin").expanduser())
    path_entries = os.environ.get("PATH", "").split(os.pathsep)
    ok = local_bin in path_entries
    return CheckResult(
        name="~/.local/bin on PATH",
        ok=ok,
        detail="present" if ok else f"missing — PATH does not include {local_bin}",
        fix="" if ok else 'Add `export PATH="$HOME/.local/bin:$PATH"` to ~/.zshrc or ~/.bashrc',
    )


def _iter_path_geode_installs() -> list[tuple[Path, Path]]:
    """Collect every executable named ``geode`` on PATH, in PATH order.

    Returns ``(candidate, resolved)`` pairs. ``shutil.which`` stops at the
    first hit; this walks the PATH entries itself because the whole point is
    seeing the SHADOWED installs behind the winner. Duplicate PATH entries
    are visited once (only the first occurrence of a directory can win).
    """
    installs: list[tuple[Path, Path]] = []
    seen_dirs: set[str] = set()
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        if not entry or entry in seen_dirs:
            continue
        seen_dirs.add(entry)
        candidate = Path(entry) / "geode"
        try:
            if not candidate.is_file() or not os.access(candidate, os.X_OK):
                continue
            installs.append((candidate, candidate.resolve()))
        except OSError:
            continue
    return installs


def _classify_geode_install(resolved: Path) -> str:
    """Classify a resolved ``geode`` binary: homebrew / uv-tool / other."""
    text = str(resolved)
    if "/Cellar/" in text or text.startswith(("/opt/homebrew/", "/usr/local/Cellar/")):
        return "homebrew"
    home = Path.home()
    uv_tools = home / ".local" / "share" / "uv" / "tools"
    local_bin = home / ".local" / "bin"
    if resolved.is_relative_to(uv_tools) or resolved.is_relative_to(local_bin):
        return "uv-tool"
    return "other"


def _check_path_install_shadow() -> CheckResult:
    """Detect multiple distinct ``geode`` binaries shadowing each other on PATH.

    Incident: a Homebrew ``geode`` earlier on PATH shadowed the editable
    uv-tool install, so operators verified changes against the wrong (stale)
    binary. The first PATH hit wins; every other distinct target is dead
    weight that will eventually be run by accident.
    """
    name = "geode PATH shadow"
    installs = _iter_path_geode_installs()
    if not installs:
        return CheckResult(
            name=name,
            ok=True,
            detail="no geode on PATH — nothing to shadow (see `geode` on PATH check)",
        )

    distinct: dict[Path, str] = {}
    for _candidate, resolved in installs:
        distinct.setdefault(resolved, _classify_geode_install(resolved))

    _winner_candidate, winner_resolved = installs[0]
    winner_kind = distinct[winner_resolved]
    if len(distinct) == 1:
        return CheckResult(
            name=name,
            ok=True,
            detail=f"single install: {winner_resolved} ({winner_kind})",
        )

    shadowed = ", ".join(
        f"{path} ({kind})" for path, kind in distinct.items() if path != winner_resolved
    )
    if any(kind == "homebrew" for kind in distinct.values()):
        fix = (
            f"PATH picks the {winner_kind} install. Remove the Homebrew copy "
            "(`brew uninstall geode`) or reorder PATH so the intended binary wins"
        )
    else:
        fix = (
            f"PATH picks the {winner_kind} install. Remove the unintended install "
            "or reorder PATH so the intended binary wins"
        )
    return CheckResult(
        name=name,
        ok=False,
        detail=(
            f"{len(distinct)} distinct installs — winner: {winner_resolved} "
            f"({winner_kind}); shadowed: {shadowed}"
        ),
        fix=fix,
    )


def _check_serve_version_drift() -> CheckResult:
    """Compare the CLI's own version against the running serve daemon's.

    The daemon reports its version in the IPC session greeting
    (``core/server/ipc_server/poller.py::_session_greeting``). After a
    rebuild, a daemon that was never restarted keeps answering prompts with
    the old code while ``geode version`` prints the new one — the classic
    "verified against the wrong build" drift.
    """
    from core import __version__
    from core.cli.ipc_client import query_serve_version

    name = "serve/CLI version"
    daemon_version = query_serve_version()
    if daemon_version is None:
        return CheckResult(
            name=name,
            ok=True,
            detail=f"CLI v{__version__}; daemon not running — skipped",
        )
    if not daemon_version:
        return CheckResult(
            name=name,
            ok=False,
            detail=(
                f"CLI v{__version__}; daemon greeting carries no version "
                "(daemon build predates the version handshake)"
            ),
            fix=_SERVE_RESTART_FIX,
        )
    if daemon_version != __version__:
        return CheckResult(
            name=name,
            ok=False,
            detail=f"CLI v{__version__} != daemon v{daemon_version}",
            fix=_SERVE_RESTART_FIX,
        )
    return CheckResult(name=name, ok=True, detail=f"CLI and daemon both v{__version__}")


def _audit_extra_dists() -> list[str] | None:
    """Read the ``[audit]`` optional-dependency distribution names.

    Parses ``pyproject.toml`` at the repo root and returns PEP 503-normalized
    distribution names, or ``None`` when no pyproject is present next to the
    installed package (wheel installs).
    """
    import tomllib

    if not _PYPROJECT_PATH.exists():
        return None
    data = tomllib.loads(_PYPROJECT_PATH.read_text(encoding="utf-8"))
    requirements = data.get("project", {}).get("optional-dependencies", {}).get("audit", [])
    names: list[str] = []
    for requirement in requirements:
        dist = re.split(r"[\s\[<>=!~;@]", str(requirement).strip(), maxsplit=1)[0]
        if dist:
            names.append(dist.lower().replace("_", "-").replace(".", "-"))
    return names


def _check_audit_extra() -> CheckResult:
    """Verify the ``[audit]`` extra's packages are importable.

    Incident: rebuilding with plain ``uv tool install -e . --force`` (no
    ``[audit]`` extra) silently zero-fills the self-improving loop's
    dim_means — the loop keeps running, the numbers are fiction.
    """
    name = "[audit] extra"
    try:
        dists = _audit_extra_dists()
    except (OSError, ValueError) as exc:
        return CheckResult(name=name, ok=True, detail=f"pyproject probe failed ({exc}) — skipped")
    if dists is None:
        return CheckResult(
            name=name,
            ok=True,
            detail="pyproject.toml not found (wheel install) — skipped",
        )
    probes = [(dist, _AUDIT_DIST_IMPORTS[dist]) for dist in dists if dist in _AUDIT_DIST_IMPORTS]
    if not probes:
        return CheckResult(
            name=name,
            ok=True,
            detail="no probeable [audit] distributions declared — skipped",
        )

    missing: list[str] = []
    for _dist, module in probes:
        try:
            spec = find_spec(module)
        except (ImportError, ValueError):
            spec = None
        if spec is None:
            missing.append(module)
    if missing:
        return CheckResult(
            name=name,
            ok=False,
            detail=(
                "installed without [audit] extra — self-improving dim_means will "
                f"zero-fill (missing: {', '.join(missing)})"
            ),
            fix='uv tool install -e ".[audit]" --force',
        )
    return CheckResult(
        name=name,
        ok=True,
        detail=f"all {len(probes)} probed package(s) importable",
    )


def _check_bash_sandbox() -> CheckResult:
    """Report the run_bash command sandbox (Phase F) — OS-native, no Docker.

    The bash sandbox shells out to the platform's OS sandbox binary
    (macOS ``sandbox-exec`` / Linux ``bwrap``); it does NOT use Docker. So this
    check reports the OS-binary availability + the ``GEODE_BASH_SANDBOX`` mode,
    and notes Docker only as optional info (relevant to the future GUI sandbox,
    never to this one). It FAILS only when the operator turned the sandbox
    on/strict but the OS binary is missing — a real misconfiguration.
    """
    from core.tools.bash_sandbox import bash_sandbox_mode, sandbox_binary_status

    mode = bash_sandbox_mode()
    binname, binpath = sandbox_binary_status()
    docker_present = "present" if shutil.which("docker") else "absent"
    docker_note = f"Docker {docker_present} — not required (GUI sandbox only)"

    if binpath is None:
        if mode in {"on", "strict"}:
            if binname == "sandbox-exec":
                install = "macOS ships it at /usr/bin/sandbox-exec"
            elif binname == "bwrap":
                install = "install bubblewrap (e.g. apt install bubblewrap)"
            else:
                install = f"the bash sandbox is unsupported on {binname}"
            return CheckResult(
                name="run_bash sandbox",
                ok=False,
                detail=f"mode={mode} but {binname} not found",
                fix=f"{install}, or set GEODE_BASH_SANDBOX=off. {docker_note}.",
            )
        return CheckResult(
            name="run_bash sandbox",
            ok=True,
            detail=f"mode=off; {binname} unavailable on this host. {docker_note}.",
        )

    if mode == "off":
        detail = f"available ({binname}), off — GEODE_BASH_SANDBOX=on to enable. {docker_note}."
    else:
        detail = f"mode={mode} via {binpath}. {docker_note}."
    return CheckResult(name="run_bash sandbox", ok=True, detail=detail)


def _check_desktop_computer_use() -> CheckResult:
    """Report desktop computer-use dependency and macOS AX readiness."""
    try:
        from core.config import settings
        from core.tools.computer_use import (
            computer_use_driver,
            computer_use_env,
            computer_use_helper_path,
            computer_use_helper_status,
        )
    except Exception as exc:
        return CheckResult(
            name="computer-use desktop",
            ok=False,
            detail=f"config probe failed: {exc}",
            fix="Run `uv sync --extra desktop --group dev`, then retry `geode doctor`.",
        )

    if not getattr(settings, "computer_use_enabled", False):
        return CheckResult(
            name="computer-use desktop",
            ok=True,
            detail="disabled by config",
        )

    env = computer_use_env()
    if env == "sandbox":
        return CheckResult(
            name="computer-use desktop",
            ok=True,
            detail="computer_use_env=sandbox; host desktop dependencies are not required",
        )

    driver = computer_use_driver()
    helper_path = computer_use_helper_path()
    if driver == "helper" or (driver == "auto" and helper_path is not None):
        if helper_path is None:
            return CheckResult(
                name="computer-use desktop",
                ok=False,
                detail="computer_use_driver=helper but GEODE Computer Use Helper is not installed",
                fix=(
                    "Build it with `scripts/macos/build_computer_helper.sh`, "
                    "then retry `geode doctor`."
                ),
            )
        status = computer_use_helper_status()
        if status.get("error"):
            return CheckResult(
                name="computer-use desktop",
                ok=False,
                detail=f"helper probe failed: {status.get('error')}",
                fix=(
                    "Rebuild with `scripts/macos/build_computer_helper.sh`, "
                    "then retry `geode doctor`."
                ),
            )
        ax_trusted = bool(status.get("ax_trusted"))
        screenshot_ok = bool(status.get("screenshot_ok"))
        if platform.system() == "Darwin" and not ax_trusted:
            return CheckResult(
                name="computer-use desktop",
                ok=False,
                detail=(
                    "GEODE Computer Use Helper is installed; macOS Accessibility "
                    "permission is not trusted"
                ),
                fix=(
                    "Grant Accessibility permission to `GEODE Computer Use Helper.app` "
                    "in System Settings, restart the helper path, then retry."
                ),
            )
        if platform.system() == "Darwin" and not screenshot_ok:
            return CheckResult(
                name="computer-use desktop",
                ok=False,
                detail="GEODE Computer Use Helper is installed but screen capture failed",
                fix=(
                    "Grant Screen Recording permission to `GEODE Computer Use Helper.app` "
                    "in System Settings, restart the helper path, then retry."
                ),
            )
        return CheckResult(
            name="computer-use desktop",
            ok=True,
            detail=f"helper driver ready ({helper_path})",
        )

    missing = [module for module in ("pyautogui", "PIL") if find_spec(module) is None]
    if missing:
        return CheckResult(
            name="computer-use desktop",
            ok=False,
            detail=f"missing host dependency: {', '.join(missing)}",
            fix="Install the desktop extra: `uv sync --extra desktop --group dev`.",
        )

    if platform.system() != "Darwin":
        return CheckResult(
            name="computer-use desktop",
            ok=True,
            detail=f"host dependencies present; AX check skipped on {platform.system()}",
        )

    missing_ax = [
        module for module in ("ApplicationServices", "AppKit") if find_spec(module) is None
    ]
    if missing_ax:
        return CheckResult(
            name="computer-use desktop",
            ok=False,
            detail=f"missing macOS AX bridge: {', '.join(missing_ax)}",
            fix="Install the desktop extra: `uv sync --extra desktop --group dev`.",
        )

    try:
        from ApplicationServices import AXIsProcessTrusted
    except Exception as exc:
        return CheckResult(
            name="computer-use desktop",
            ok=False,
            detail=f"AX trust probe failed: {exc}",
            fix="Install the desktop extra: `uv sync --extra desktop --group dev`.",
        )

    if not AXIsProcessTrusted():
        return CheckResult(
            name="computer-use desktop",
            ok=False,
            detail="dependencies present; macOS Accessibility permission is not trusted",
            fix=(
                "Grant Accessibility permission to the app launching GEODE "
                "(Terminal/iTerm/Codex), then restart that app and retry."
            ),
        )

    return CheckResult(
        name="computer-use desktop",
        ok=True,
        detail="host dependencies present; macOS Accessibility trusted",
    )


def run_bootstrap_doctor() -> BootstrapReport:
    """Run all bootstrap checks and return the aggregated report."""
    report = BootstrapReport()
    report.checks.append(_check_python_version())
    report.checks.append(_check_geode_on_path())
    report.checks.append(_check_path_install_shadow())
    report.checks.append(_check_local_bin_on_path())
    report.checks.append(_check_env_file())
    report.checks.append(_check_codex_oauth())
    report.checks.append(_check_profile_store())
    report.checks.append(_check_bash_sandbox())
    report.checks.append(_check_desktop_computer_use())
    report.checks.append(_check_serve_socket())
    report.checks.append(_check_serve_version_drift())
    report.checks.append(_check_audit_extra())
    return report


def format_bootstrap_report(report: BootstrapReport) -> str:
    """Render the bootstrap report for terminal display."""
    lines: list[str] = []
    lines.append("")
    lines.append("  [header]GEODE bootstrap doctor[/header]")
    lines.append("")
    for c in report.checks:
        marker = "[success]✓[/success]" if c.ok else "[warning]✗[/warning]"
        lines.append(f"  {marker}  [bold]{c.name}[/bold]  [muted]{c.detail}[/muted]")
        if not c.ok and c.fix:
            lines.append(f"        [muted]→ {c.fix}[/muted]")
    lines.append("")
    if report.all_ok:
        lines.append("  [success]All checks passed.[/success]")
    else:
        failed = sum(1 for c in report.checks if not c.ok)
        lines.append(f"  [warning]{failed} check(s) need attention.[/warning]")
    lines.append("")
    return "\n".join(lines)
