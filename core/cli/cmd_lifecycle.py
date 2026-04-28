"""Lifecycle commands — stop, status, clean, uninstall.

Provides process management, disk usage reporting, selective cleanup,
and complete system removal for GEODE installations.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import signal
import subprocess  # nosec B404 — used for pgrep process discovery
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.paths import (
    APPROVE_HISTORY,
    CLI_SOCKET_PATH,
    CLI_STARTUP_LOCK,
    GEODE_HOME,
    GLOBAL_JOURNAL_DIR,
    GLOBAL_PROJECTS_DIR,
    GLOBAL_RUNS_DIR,
    GLOBAL_SCHEDULER_DIR,
    GLOBAL_USAGE_DIR,
    GLOBAL_WORKERS_DIR,
    MCP_REGISTRY_CACHE,
    PROJECT_EMBEDDING_CACHE,
    PROJECT_GEODE_DIR,
    PROJECT_RESULT_CACHE_DIR,
    PROJECT_SCHEDULER_LOG_DIR,
    PROJECT_TOOL_OFFLOAD,
    PROJECT_VECTORS_DIR,
    SERVE_LOG_PATH,
)
from core.ui.console import console

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _format_size(nbytes: int) -> str:
    """Format byte count as human-readable string."""
    if nbytes >= 1 << 30:
        return f"{nbytes / (1 << 30):.1f} GB"
    if nbytes >= 1 << 20:
        return f"{nbytes / (1 << 20):.1f} MB"
    if nbytes >= 1 << 10:
        return f"{nbytes / (1 << 10):.1f} KB"
    return f"{nbytes} B"


@dataclass
class DirUsage:
    """Disk usage summary for a single directory."""

    path: Path
    file_count: int = 0
    total_bytes: int = 0
    exists: bool = False


@dataclass
class CleanTarget:
    """A filesystem target to be cleaned."""

    path: Path
    label: str
    is_dir: bool = True
    size_bytes: int = 0
    file_count: int = 0


def _scan_directory(path: Path) -> DirUsage:
    """Walk a directory and sum file sizes."""
    if not path.exists():
        return DirUsage(path=path)
    total = 0
    count = 0
    for f in path.rglob("*"):
        if f.is_file():
            try:
                total += f.stat().st_size
                count += 1
            except OSError:
                continue
    return DirUsage(path=path, file_count=count, total_bytes=total, exists=True)


def _scan_file(path: Path) -> DirUsage:
    """Get size of a single file."""
    if not path.exists():
        return DirUsage(path=path)
    try:
        size = path.stat().st_size
        return DirUsage(path=path, file_count=1, total_bytes=size, exists=True)
    except OSError:
        return DirUsage(path=path)


def _find_serve_pid() -> int | None:
    """Find the PID of the running geode serve process via pgrep."""
    try:
        result = subprocess.run(
            ["pgrep", "-f", "geode serve"],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            # Return first PID (main serve process)
            for line in result.stdout.strip().split("\n"):
                pid = int(line.strip())
                # Skip our own process
                if pid != os.getpid():
                    return pid
    except (subprocess.TimeoutExpired, ValueError, OSError):
        pass
    return None


def _find_child_pids(parent_pid: int) -> list[int]:
    """Find all child PIDs recursively via pgrep -P."""
    children: list[int] = []
    try:
        result = subprocess.run(  # noqa: S603
            ["pgrep", "-P", str(parent_pid)],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            for line in result.stdout.strip().split("\n"):
                pid = int(line.strip())
                children.append(pid)
                children.extend(_find_child_pids(pid))
    except (subprocess.TimeoutExpired, ValueError, OSError):
        pass
    return children


def _is_socket_orphan(path: Path) -> bool:
    """Check if a socket file exists but nothing is listening."""
    if not path.exists():
        return False
    import socket as _socket

    try:
        sock = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
        sock.settimeout(1.0)
        sock.connect(str(path))
        sock.close()
    except (ConnectionRefusedError, OSError):
        return True  # File exists but nothing listens
    return False  # Something is listening — not orphan


def _confirm(message: str, *, force: bool = False) -> bool:
    """Ask for yes/no confirmation. Returns True if confirmed."""
    if force:
        return True
    try:
        response = console.input(f"  {message} [y/N] ").strip().lower()
        return response in ("y", "yes")
    except (KeyboardInterrupt, EOFError):
        console.print()
        return False


def _confirm_typed(prompt: str, expected: str, *, force: bool = False) -> bool:
    """Ask user to type a specific word to confirm."""
    if force:
        return True
    try:
        response: str = console.input(f"  {prompt} ").strip()
        return bool(response == expected)
    except (KeyboardInterrupt, EOFError):
        console.print()
        return False


# ---------------------------------------------------------------------------
# geode stop
# ---------------------------------------------------------------------------


def stop_serve(*, force: bool = False, timeout: int = 30) -> None:
    """Stop geode serve daemon and all child processes."""
    from core.cli.ipc_client import is_serve_running

    pid = _find_serve_pid()

    if pid is None and not is_serve_running():
        console.print("  [muted]Serve is not running.[/muted]")
        _clean_stale_artifacts()
        return

    if pid is None:
        console.print("  [warning]Serve socket is active but PID not found.[/warning]")
        _clean_stale_artifacts()
        return

    # Collect children before killing parent
    children = _find_child_pids(pid)

    # Phase 1: SIGTERM
    console.print(f"  Stopping serve (PID {pid})...")
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        console.print("  [muted]Process already exited.[/muted]")
        _clean_stale_artifacts()
        return

    # Phase 2: Wait for graceful shutdown
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)  # Check if still alive
        except ProcessLookupError:
            break
        time.sleep(0.5)
    else:
        # Timed out
        if force:
            console.print(f"  [warning]Timeout — force killing (PID {pid})...[/warning]")
            with contextlib.suppress(ProcessLookupError):
                os.kill(pid, signal.SIGKILL)
        else:
            console.print(
                f"  [error]Serve did not stop within {timeout}s. Use --force to SIGKILL.[/error]"
            )
            return

    # Phase 3: Clean up children
    killed_children = 0
    for cpid in children:
        try:
            os.kill(cpid, signal.SIGTERM)
            killed_children += 1
        except ProcessLookupError:
            continue

    if killed_children:
        time.sleep(1)
        for cpid in children:
            try:
                os.kill(cpid, signal.SIGKILL)
            except ProcessLookupError:
                continue

    # Phase 4: Clean stale artifacts
    _clean_stale_artifacts()

    console.print(f"  [success]Stopped serve (PID {pid}).[/success]")
    if killed_children:
        console.print(f"  [muted]Cleaned {killed_children} child process(es).[/muted]")


def _clean_stale_artifacts() -> None:
    """Remove orphan socket and lock files."""
    cleaned = 0
    if _is_socket_orphan(CLI_SOCKET_PATH):
        CLI_SOCKET_PATH.unlink(missing_ok=True)
        cleaned += 1
    if CLI_STARTUP_LOCK.exists():
        CLI_STARTUP_LOCK.unlink(missing_ok=True)
        cleaned += 1
    if cleaned:
        console.print(f"  [muted]Removed {cleaned} stale artifact(s).[/muted]")


# ---------------------------------------------------------------------------
# geode status
# ---------------------------------------------------------------------------


@dataclass
class StatusReport:
    """Structured status information."""

    serve_running: bool = False
    serve_pid: int | None = None
    global_usage: dict[str, DirUsage] = field(default_factory=dict)
    project_usage: dict[str, DirUsage] = field(default_factory=dict)
    build_usage: dict[str, DirUsage] = field(default_factory=dict)
    install_path: str = ""
    version: str = ""


def show_status(*, json_output: bool = False) -> None:
    """Show daemon status, disk usage, and installation info."""
    from core import __version__
    from core.cli.ipc_client import is_serve_running

    report = StatusReport()
    report.version = __version__
    report.serve_running = is_serve_running()
    report.serve_pid = _find_serve_pid() if report.serve_running else None

    # Global disk usage
    global_dirs = {
        "runs": GLOBAL_RUNS_DIR,
        "journal": GLOBAL_JOURNAL_DIR,
        "projects": GLOBAL_PROJECTS_DIR,
        "scheduler": GLOBAL_SCHEDULER_DIR,
        "usage": GLOBAL_USAGE_DIR,
        "workers": GLOBAL_WORKERS_DIR,
    }
    for name, path in global_dirs.items():
        report.global_usage[name] = _scan_directory(path)

    # Single files
    for name, path in [
        ("mcp-registry-cache", MCP_REGISTRY_CACHE),
        ("approve_history", APPROVE_HISTORY),
        ("serve.log", SERVE_LOG_PATH),
    ]:
        report.global_usage[name] = _scan_file(path)

    # Project disk usage
    project_dirs = {
        "embedding-cache": PROJECT_EMBEDDING_CACHE,
        "tool-offload": PROJECT_TOOL_OFFLOAD,
        "result_cache": PROJECT_RESULT_CACHE_DIR,
        "vectors": PROJECT_VECTORS_DIR,
        "scheduler_logs": PROJECT_SCHEDULER_LOG_DIR,
    }
    for name, path in project_dirs.items():
        report.project_usage[name] = _scan_directory(path)

    # Build caches
    cwd = Path.cwd()
    build_dirs = {
        ".venv": cwd / ".venv",
        ".mypy_cache": cwd / ".mypy_cache",
        ".pytest_cache": cwd / ".pytest_cache",
        ".ruff_cache": cwd / ".ruff_cache",
    }
    for name, path in build_dirs.items():
        report.build_usage[name] = _scan_directory(path)

    # Install path
    import shutil as _shutil

    geode_bin = _shutil.which("geode")
    report.install_path = geode_bin or "(not found)"

    if json_output:
        _print_status_json(report)
    else:
        _print_status_text(report)


def _print_status_json(report: StatusReport) -> None:
    """Print status as JSON."""
    import json

    def _usage_dict(usage: dict[str, DirUsage]) -> dict[str, Any]:
        return {
            name: {
                "path": str(u.path),
                "files": u.file_count,
                "bytes": u.total_bytes,
                "human": _format_size(u.total_bytes),
                "exists": u.exists,
            }
            for name, u in usage.items()
        }

    data = {
        "version": report.version,
        "serve": {
            "running": report.serve_running,
            "pid": report.serve_pid,
        },
        "disk": {
            "global": _usage_dict(report.global_usage),
            "project": _usage_dict(report.project_usage),
            "build": _usage_dict(report.build_usage),
        },
        "install": report.install_path,
    }
    console.print(json.dumps(data, indent=2, ensure_ascii=False))


def _print_status_text(report: StatusReport) -> None:
    """Print status as formatted text."""
    # Daemon
    console.print()
    console.print(f"  [header]GEODE v{report.version}[/header]")
    console.print()

    if report.serve_running:
        console.print(f"  Serve:   [success]Running[/success] (PID {report.serve_pid})")
    else:
        console.print("  Serve:   [muted]Stopped[/muted]")

    # Global disk
    console.print()
    console.print(f"  [header]Global ({GEODE_HOME})[/header]")
    global_total = 0
    for name, usage in report.global_usage.items():
        if usage.exists:
            size_str = _format_size(usage.total_bytes)
            console.print(f"    {name:<25s} {usage.file_count:>5d} files  {size_str:>10s}")
            global_total += usage.total_bytes
    console.print(f"    {'─ Total':<25s} {'':>11s} {_format_size(global_total):>10s}")

    # Project disk
    console.print()
    console.print(f"  [header]Project ({PROJECT_GEODE_DIR})[/header]")
    proj_total = 0
    for name, usage in report.project_usage.items():
        if usage.exists:
            size_str = _format_size(usage.total_bytes)
            console.print(f"    {name:<25s} {usage.file_count:>5d} files  {size_str:>10s}")
            proj_total += usage.total_bytes
    console.print(f"    {'─ Total':<25s} {'':>11s} {_format_size(proj_total):>10s}")

    # Build caches
    console.print()
    console.print("  [header]Build caches[/header]")
    build_total = 0
    for name, usage in report.build_usage.items():
        if usage.exists:
            size_str = _format_size(usage.total_bytes)
            console.print(f"    {name:<25s} {usage.file_count:>5d} files  {size_str:>10s}")
            build_total += usage.total_bytes
    console.print(f"    {'─ Total':<25s} {'':>11s} {_format_size(build_total):>10s}")

    # Install
    console.print()
    console.print(f"  Install: {report.install_path}")
    console.print()


# ---------------------------------------------------------------------------
# geode clean
# ---------------------------------------------------------------------------


def do_clean(
    *,
    scope: str = "all",
    all_data: bool = False,
    dry_run: bool = False,
    force: bool = False,
    older_than: int = 30,
) -> None:
    """Clean caches, logs, and temporary data."""
    targets: list[CleanTarget] = []

    include_project = scope in ("all", "project")
    include_global = scope in ("all", "global")
    include_build = scope in ("all", "build") if scope == "build" else False

    # Tier 1 — Safe (always included for matching scope)
    if include_project:
        for path, label in [
            (PROJECT_EMBEDDING_CACHE, "embedding-cache"),
            (PROJECT_TOOL_OFFLOAD, "tool-offload"),
            (PROJECT_RESULT_CACHE_DIR, "result_cache"),
            (PROJECT_VECTORS_DIR, "vectors"),
        ]:
            if path.exists():
                usage = _scan_directory(path)
                targets.append(
                    CleanTarget(
                        path=path,
                        label=label,
                        size_bytes=usage.total_bytes,
                        file_count=usage.file_count,
                    )
                )

    if include_global:
        # MCP registry cache
        if MCP_REGISTRY_CACHE.exists():
            usage = _scan_file(MCP_REGISTRY_CACHE)
            targets.append(
                CleanTarget(
                    path=MCP_REGISTRY_CACHE,
                    label="mcp-registry-cache",
                    is_dir=False,
                    size_bytes=usage.total_bytes,
                    file_count=1,
                )
            )
        # Stale artifacts
        if _is_socket_orphan(CLI_SOCKET_PATH):
            targets.append(CleanTarget(path=CLI_SOCKET_PATH, label="stale socket", is_dir=False))
        if CLI_STARTUP_LOCK.exists():
            from core.cli.ipc_client import is_serve_running

            if not is_serve_running():
                targets.append(CleanTarget(path=CLI_STARTUP_LOCK, label="stale lock", is_dir=False))

    # Tier 2 — With --all (logs, old sessions, transcripts)
    if all_data:
        if include_global:
            for path, label in [
                (GLOBAL_RUNS_DIR, "runs (execution logs)"),
                (GLOBAL_WORKERS_DIR, "workers"),
            ]:
                if path.exists():
                    usage = _scan_directory(path)
                    targets.append(
                        CleanTarget(
                            path=path,
                            label=label,
                            size_bytes=usage.total_bytes,
                            file_count=usage.file_count,
                        )
                    )
            if APPROVE_HISTORY.exists():
                usage = _scan_file(APPROVE_HISTORY)
                targets.append(
                    CleanTarget(
                        path=APPROVE_HISTORY,
                        label="approve_history",
                        is_dir=False,
                        size_bytes=usage.total_bytes,
                        file_count=1,
                    )
                )
            if SERVE_LOG_PATH.exists():
                usage = _scan_file(SERVE_LOG_PATH)
                targets.append(
                    CleanTarget(
                        path=SERVE_LOG_PATH,
                        label="serve.log",
                        is_dir=False,
                        size_bytes=usage.total_bytes,
                        file_count=1,
                    )
                )

        if include_project and PROJECT_SCHEDULER_LOG_DIR.exists():
            usage = _scan_directory(PROJECT_SCHEDULER_LOG_DIR)
            targets.append(
                CleanTarget(
                    path=PROJECT_SCHEDULER_LOG_DIR,
                    label="scheduler_logs",
                    size_bytes=usage.total_bytes,
                    file_count=usage.file_count,
                )
            )

    # Tier 3 — Build caches
    if include_build or scope == "build":
        cwd = Path.cwd()
        for name in (".venv", ".mypy_cache", ".pytest_cache", ".ruff_cache"):
            path = cwd / name
            if path.exists():
                usage = _scan_directory(path)
                targets.append(
                    CleanTarget(
                        path=path,
                        label=name,
                        size_bytes=usage.total_bytes,
                        file_count=usage.file_count,
                    )
                )

    if not targets:
        console.print("  [muted]Nothing to clean.[/muted]")
        return

    # Preview
    total_bytes = sum(t.size_bytes for t in targets)
    mode_label = "[muted](dry-run)[/muted] " if dry_run else ""

    console.print()
    console.print(f"  {mode_label}[header]Cleanup targets[/header]")
    for t in targets:
        console.print(
            f"    {'✓' if not dry_run else '○'} {t.label:<25s} "
            f"{t.file_count:>5d} file(s)  {_format_size(t.size_bytes):>10s}"
        )
    console.print(f"    {'─ Total':<25s} {'':>5s}       {_format_size(total_bytes):>10s}")
    console.print()

    if dry_run:
        console.print(f"  [muted]{_format_size(total_bytes)} would be freed.[/muted]")
        return

    # Confirmation for Tier 2 items
    if all_data and not force and not _confirm("Clean logs and old sessions?"):
        console.print("  [muted]Cancelled.[/muted]")
        return

    # Execute
    freed = 0
    for t in targets:
        try:
            if t.is_dir:
                shutil.rmtree(t.path, ignore_errors=True)
            else:
                t.path.unlink(missing_ok=True)
            freed += t.size_bytes
        except OSError as exc:
            console.print(f"  [warning]Failed to remove {t.label}: {exc}[/warning]")

    # Run existing cleanup utilities for --all mode
    if all_data and include_global:
        try:
            from core.cli.transcript import cleanup_old_transcripts

            removed = cleanup_old_transcripts(max_age_days=older_than)
            if removed:
                console.print(f"  [muted]Cleaned {removed} old transcript(s).[/muted]")
        except ImportError:
            pass

    console.print(f"  [success]Freed {_format_size(freed)}.[/success]")


# ---------------------------------------------------------------------------
# geode uninstall
# ---------------------------------------------------------------------------


def do_uninstall(
    *,
    dry_run: bool = False,
    force: bool = False,
    keep_config: bool = False,
    keep_data: bool = False,
) -> None:
    """Completely remove GEODE from this system."""
    mode_label = "[muted](dry-run)[/muted] " if dry_run else ""
    console.print()
    console.print(f"  {mode_label}[header]GEODE Uninstall[/header]")
    console.print()

    # Survey what exists
    items: list[tuple[str, Path, int, bool]] = []  # (label, path, bytes, is_dir)

    # 1. Project-local .geode/
    if PROJECT_GEODE_DIR.exists():
        usage = _scan_directory(PROJECT_GEODE_DIR)
        items.append(("Project data (.geode/)", PROJECT_GEODE_DIR, usage.total_bytes, True))

    # 2. Global ~/.geode/
    if GEODE_HOME.exists():
        usage = _scan_directory(GEODE_HOME)
        items.append((f"Global data ({GEODE_HOME})", GEODE_HOME, usage.total_bytes, True))

    # 3. Build caches
    cwd = Path.cwd()
    build_total = 0
    build_paths: list[Path] = []
    for name in (".venv", ".mypy_cache", ".pytest_cache", ".ruff_cache"):
        path = cwd / name
        if path.exists():
            u = _scan_directory(path)
            build_total += u.total_bytes
            build_paths.append(path)
    if build_paths:
        items.append(("Build caches", cwd, build_total, True))

    # 4. CLI binary
    geode_bin = shutil.which("geode")
    if geode_bin:
        items.append(("CLI binary", Path(geode_bin), 0, False))

    if not items:
        console.print("  [muted]Nothing to uninstall.[/muted]")
        return

    # Preview
    total_bytes = sum(size for _, _, size, _ in items)
    for label, _path, size, _ in items:
        console.print(f"    {label:<35s} {_format_size(size):>10s}")
    if keep_config:
        console.print("    [success]Keep: .env, config.toml[/success]")
    if keep_data:
        console.print("    [success]Keep: vault/, identity/, user_profile/[/success]")
    console.print()
    console.print(f"    Total: {_format_size(total_bytes)}")
    console.print()

    if dry_run:
        console.print(f"  [muted]{_format_size(total_bytes)} would be freed.[/muted]")
        return

    # Safety confirmations
    if not force:
        if not _confirm("This will remove ALL GEODE data. Continue?"):
            console.print("  [muted]Cancelled.[/muted]")
            return

        if not keep_config and not _confirm(
            "[warning]This includes API keys and credentials. Sure?[/warning]"
        ):
            console.print("  [muted]Cancelled.[/muted]")
            return

        if not _confirm_typed("Type 'uninstall' to confirm:", "uninstall"):
            console.print("  [muted]Cancelled.[/muted]")
            return

    # Execute
    freed = 0

    # Step 1: Stop processes
    console.print("  [muted]Stopping processes...[/muted]")
    stop_serve(force=True, timeout=10)

    # Step 2: Handle --keep-config and --keep-data (save before deletion)
    saved_files: list[tuple[Path, Path]] = []  # (original, temp)
    if keep_config and GEODE_HOME.exists():
        import tempfile

        tmpdir = Path(tempfile.mkdtemp(prefix="geode-keep-"))
        for name in (".env", "config.toml"):
            src = GEODE_HOME / name
            if src.exists():
                dst = tmpdir / name
                shutil.copy2(src, dst)
                saved_files.append((src, dst))

    saved_dirs: list[tuple[Path, Path]] = []  # (original, temp)
    if keep_data and GEODE_HOME.exists():
        import tempfile

        tmpdir_data = Path(tempfile.mkdtemp(prefix="geode-keep-data-"))
        for name in ("vault", "identity", "user_profile"):
            src = GEODE_HOME / name
            if src.exists():
                dst = tmpdir_data / name
                shutil.copytree(src, dst)
                saved_dirs.append((src, dst))

    # Step 3: Remove project-local .geode/
    if PROJECT_GEODE_DIR.exists():
        usage = _scan_directory(PROJECT_GEODE_DIR)
        shutil.rmtree(PROJECT_GEODE_DIR, ignore_errors=True)
        freed += usage.total_bytes
        console.print(f"  Removed .geode/ ({_format_size(usage.total_bytes)})")

    # Step 4: Remove global ~/.geode/
    if GEODE_HOME.exists():
        usage = _scan_directory(GEODE_HOME)
        shutil.rmtree(GEODE_HOME, ignore_errors=True)
        freed += usage.total_bytes
        console.print(f"  Removed {GEODE_HOME} ({_format_size(usage.total_bytes)})")

    # Step 5: Restore kept files
    if saved_files or saved_dirs:
        GEODE_HOME.mkdir(parents=True, exist_ok=True)
        for original, tmp in saved_files:
            shutil.copy2(tmp, original)
        for original, tmp in saved_dirs:
            shutil.copytree(tmp, original)
        # Clean temp dirs
        cleaned_parents: set[Path] = set()
        for _, tmp in [*saved_files, *saved_dirs]:
            if tmp.parent.exists() and tmp.parent not in cleaned_parents:
                shutil.rmtree(tmp.parent, ignore_errors=True)
                cleaned_parents.add(tmp.parent)

        kept = []
        if keep_config:
            kept.append(".env, config.toml")
        if keep_data:
            kept.append("vault/, identity/, user_profile/")
        console.print(f"  [success]Preserved: {', '.join(kept)}[/success]")

    # Step 6: Remove build caches
    for path in build_paths:
        u = _scan_directory(path)
        shutil.rmtree(path, ignore_errors=True)
        freed += u.total_bytes
    if build_paths:
        console.print(f"  Removed build caches ({_format_size(build_total)})")

    # Step 7: Uninstall CLI via uv tool
    if geode_bin:
        try:
            subprocess.run(
                ["uv", "tool", "uninstall", "geode"],  # noqa: S607
                capture_output=True,
                text=True,
                timeout=30,
            )
            console.print(f"  Removed CLI ({geode_bin})")
        except (subprocess.TimeoutExpired, OSError) as exc:
            console.print(f"  [warning]Failed to uninstall CLI: {exc}[/warning]")

    # Summary
    console.print()
    console.print(f"  [success]Uninstall complete. Freed {_format_size(freed)}.[/success]")
