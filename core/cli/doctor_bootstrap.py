"""bootstrap doctor — diagnostic checks for the first-run surface.

Verifies the things a beginner would otherwise have to debug by hand:
Python version, ``geode`` on PATH, ``~/.geode/.env`` state, Codex CLI
OAuth credentials, registered ProfileStore profiles, serve daemon
status, IPC socket presence.

Used by ``geode doctor`` (default target ``bootstrap``).
"""

from __future__ import annotations

import logging
import os
import shutil
import socket
import sys
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)


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


def run_bootstrap_doctor() -> BootstrapReport:
    """Run all bootstrap checks and return the aggregated report."""
    report = BootstrapReport()
    report.checks.append(_check_python_version())
    report.checks.append(_check_geode_on_path())
    report.checks.append(_check_local_bin_on_path())
    report.checks.append(_check_env_file())
    report.checks.append(_check_codex_oauth())
    report.checks.append(_check_profile_store())
    report.checks.append(_check_bash_sandbox())
    report.checks.append(_check_serve_socket())
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
