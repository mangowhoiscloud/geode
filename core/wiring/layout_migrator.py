"""Version-aware migration for ``~/.geode/`` directory layout.

Implements three frontier patterns synthesized from Hermes Agent
(NousResearch) + OpenClaw + GEODE's own ``_resolve_with_fallback``:

1. **Schema version marker** — ``~/.geode/.layout-version`` dotfile holds
   an integer. Mirrors Hermes' ``schema_version`` table-inside-state.db
   approach (the version travels *with* the data), adapted for a
   directory-level schema where there is no single state.db. Hermes
   precedent for dotfile markers: ``.managed``, ``active_profile``
   (``hermes_constants.py:14-68``).

2. **Idempotent runner** — :func:`ensure_layout_migrated` is safe to call
   on every boot. Pattern mirrors Hermes ``SessionDB._init_schema``
   (``hermes_state.py:550-678``): read version → run pending steps →
   bump marker, with each step independently version-gated
   (``if current_version < N``).

3. **Module-level once-flag** — `_migration_checked` ensures one
   migration check per process even if multiple bootstraps call in.
   Mirrors OpenClaw ``autoMigrateStateDirChecked``
   (``src/infra/state-migrations.ts:76-77``) and Hermes
   ``_bootstrap_applied`` (``hermes_bootstrap.py:59-129``).

Migrations recorded here are **path-level** (file renames, directory
restructures). Data-level migrations (auth.toml schema, etc.) live in
their respective modules (``core/auth/auth_toml.py``,
``core/auth/oauth_login.py:_migrate_legacy_auth_json_if_present``).

Adding a new migration:

  1. Bump :data:`GEODE_LAYOUT_VERSION`.
  2. Append a step in :func:`_run_pending_migrations` under the
     ``if current_version < N`` guard.
  3. Each step must be *idempotent* (safe to re-run partially completed).
  4. Each step must be *lossless* — moves use :func:`shutil.move` so the
     filesystem either has the source or the destination, never neither.
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import logging
import os
import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from core.paths import GEODE_HOME

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Current target layout schema version. Bumped each time a path-level
#: migration is added.
GEODE_LAYOUT_VERSION = 3

#: TTL in days for v2→v3 archival steps (runs/vault/projects). Override via
#: ``GEODE_ARCHIVE_TTL_DAYS`` env var. Lowering for tests / aggressive
#: cleanup; raising preserves more history at the cost of disk.
DEFAULT_ARCHIVE_TTL_DAYS = 30.0
ARCHIVE_TTL_ENV_VAR = "GEODE_ARCHIVE_TTL_DAYS"

#: Marker file recording the migrated-up-to version. Absent ⇒ version 0
#: (pre-versioned install — every existing user starts here on first run
#: after this PR lands).
LAYOUT_VERSION_FILE = GEODE_HOME / ".layout-version"

#: Env var escape hatch — set to skip migration entirely (for tests, CI,
#: or operator override). Mirrors OpenClaw ``OPENCLAW_STATE_DIR`` opt-out
#: at ``src/infra/state-migrations.ts:528``.
DISABLE_ENV_VAR = "GEODE_DISABLE_LAYOUT_MIGRATION"

# Module-level idempotency guard. Multiple bootstrap call sites
# (`build_memory_components`, `build_default_runtime`, etc.) all call
# `ensure_layout_migrated()` — only the first one in this process does work.
_migration_checked = False
_migration_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class MigrationResult:
    """Outcome of a single migration step. Lifted from OpenClaw's
    ``StateDirMigrationResult`` shape (``state-migrations.ts:430-435``)."""

    name: str
    moved: list[tuple[str, str]] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class LayoutMigrationReport:
    """Aggregate report — what ran, what changed, what stayed put."""

    from_version: int
    to_version: int
    steps: list[MigrationResult] = field(default_factory=list)
    disabled: bool = False
    no_op: bool = False


# ---------------------------------------------------------------------------
# Version marker read / write
# ---------------------------------------------------------------------------


def read_layout_version() -> int:
    """Return the migrated-up-to version, or ``0`` if marker is absent.

    Pre-versioned installs (any directory created before this PR) return 0.
    Corrupt marker (non-integer content) is treated as 0 and overwritten
    on the next successful migration pass.
    """
    try:
        text = LAYOUT_VERSION_FILE.read_text(encoding="utf-8").strip()
        return int(text)
    except FileNotFoundError:
        return 0
    except (ValueError, OSError):
        log.warning("Corrupt %s — treating as version 0", LAYOUT_VERSION_FILE)
        return 0


def write_layout_version(version: int) -> None:
    """Persist the layout version using an atomic write.

    Hermes pattern: ``atomic_yaml_write`` (``utils.py:139-188``) — write to
    temp file in same dir, ``fsync``, then ``os.replace``. We do the same
    minus YAML serialization since this is a single integer.
    """
    LAYOUT_VERSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = LAYOUT_VERSION_FILE.with_suffix(LAYOUT_VERSION_FILE.suffix + ".tmp")
    payload = f"{version}\n"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, LAYOUT_VERSION_FILE)
    except OSError as exc:
        log.warning("Failed to persist layout version marker: %s", exc)
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def ensure_layout_migrated(*, force: bool = False) -> LayoutMigrationReport:
    """Bring ``~/.geode/`` up to the current target layout version.

    Called from :func:`core.paths.ensure_directories` on every bootstrap.
    Idempotent — second call in the same process returns immediately
    (module-level ``_migration_checked`` guard). ``force=True`` bypasses
    the guard, used by tests.

    Returns a :class:`LayoutMigrationReport` describing what was done.
    Never raises on partial failure — individual migration steps catch
    and warn so the rest of bootstrap can proceed.
    """
    global _migration_checked

    if os.environ.get(DISABLE_ENV_VAR):
        return LayoutMigrationReport(from_version=-1, to_version=-1, disabled=True)

    with _migration_lock:
        if _migration_checked and not force:
            return LayoutMigrationReport(
                from_version=GEODE_LAYOUT_VERSION,
                to_version=GEODE_LAYOUT_VERSION,
                no_op=True,
            )
        _migration_checked = True

    GEODE_HOME.mkdir(parents=True, exist_ok=True)
    current = read_layout_version()
    if current >= GEODE_LAYOUT_VERSION:
        return LayoutMigrationReport(from_version=current, to_version=current, no_op=True)

    report = LayoutMigrationReport(from_version=current, to_version=GEODE_LAYOUT_VERSION)
    _run_pending_migrations(current, report)
    write_layout_version(GEODE_LAYOUT_VERSION)
    _log_migration_summary(report)
    return report


def _log_migration_summary(report: LayoutMigrationReport) -> None:
    """Emit a per-step INFO summary so operators can confirm at-a-glance
    that archival actually ran.

    Diagnostic for the v1→v2 trigger gap: the previous one-line summary
    only said "N step(s)" — operators had no way to tell whether each
    step found work to do or no-op'd. We now log moved/skipped/warning
    counts per step so a glance at ``~/.geode/logs/serve.log`` answers
    "did v3 archive anything?"
    """
    total_moved = sum(len(s.moved) for s in report.steps)
    log.info(
        "Layout migration v%d → v%d: %d step(s), %d entr%s moved",
        report.from_version,
        report.to_version,
        len(report.steps),
        total_moved,
        "y" if total_moved == 1 else "ies",
    )
    for step in report.steps:
        log.info(
            "  step %r: moved=%d skipped=%d warnings=%d",
            step.name,
            len(step.moved),
            len(step.skipped),
            len(step.warnings),
        )
        for warning in step.warnings:
            log.info("    warning: %s", warning)


def reset_migration_guard() -> None:
    """Test helper — clear the once-per-process flag."""
    global _migration_checked
    with _migration_lock:
        _migration_checked = False


# ---------------------------------------------------------------------------
# Migration step registry
# ---------------------------------------------------------------------------


def _run_pending_migrations(current_version: int, report: LayoutMigrationReport) -> None:
    """Run every migration step whose version > current_version.

    Hermes pattern (``hermes_state.py:594-651``): each step is gated by
    an ``if current_version < N`` block. After this function returns
    successfully, the caller bumps the persisted version to TARGET.
    """
    if current_version < 1:
        report.steps.append(_migrate_v0_to_v1())
    if current_version < 2:
        report.steps.append(_migrate_v1_to_v2())
    if current_version < 3:
        report.steps.append(_migrate_v2_to_v3())


# ---------------------------------------------------------------------------
# v0 → v1: path-bug corrections (3 known mismatches in core/paths.py)
# ---------------------------------------------------------------------------


def _migrate_v0_to_v1() -> MigrationResult:
    """v1 — reconcile three known path mismatches.

    1. ``~/.geode/serve.log`` → ``~/.geode/logs/serve.log``
       (``paths.py:SERVE_LOG_PATH`` already expects the new path)
    2. ``~/.geode/approve_history.json`` → ``~/.geode/approval_history.jsonl``
       (paths.py used the old name; actual writer in
       ``approval_tracker.py`` uses the new name — old file is stranded)
    3. ``~/.geode/mcp-registry-cache.json`` → ``~/.geode/mcp/registry-cache.json``
       (group with the rest of MCP state under the ``mcp/`` subdir)

    Strategy — :func:`shutil.move` (atomic on same filesystem). If the
    destination already exists, the source is left in place with a
    warning so the operator can resolve manually (we never silently
    overwrite user data).
    """
    result = MigrationResult(name="v0→v1: path reconciliation")

    moves = [
        (GEODE_HOME / "serve.log", GEODE_HOME / "logs" / "serve.log"),
        (
            GEODE_HOME / "approve_history.json",
            GEODE_HOME / "approval_history.jsonl",
        ),
        (
            GEODE_HOME / "mcp-registry-cache.json",
            GEODE_HOME / "mcp" / "registry-cache.json",
        ),
    ]

    for src, dst in moves:
        if not src.exists():
            result.skipped.append(f"{src.name}: source absent")
            continue
        if dst.exists():
            result.warnings.append(
                f"{src.name}: both source and destination present — left {src} for manual review"
            )
            continue
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            result.moved.append((str(src), str(dst)))
            log.info("Layout v0→v1: moved %s → %s", src, dst)
        except OSError as exc:
            result.warnings.append(f"{src.name}: move failed: {exc}")

    return result


# ---------------------------------------------------------------------------
# v1 → v2: vestigial directory archival (embedding-cache, vectors)
# ---------------------------------------------------------------------------


def _migrate_v1_to_v2() -> MigrationResult:
    """v2 — archive `.geode/embedding-cache/` and `.geode/vectors/`.

    The on-disk directories exist for legacy reasons but have no writer
    since 2026-04-05. The corresponding ``paths.py`` constants
    (``PROJECT_EMBEDDING_CACHE`` / ``PROJECT_VECTORS_DIR``) were removed
    in the same PR.

    Strategy — **archive, not delete**. Move to
    ``{workspace}/.geode/_archive/<name>-<UTC>/`` so the operator can
    inspect or restore. Reversible by design — mirrors the user-data
    safety pattern from v0→v1 (`shutil.move`, never `rmtree`).

    Scope — current workspace only. Other workspaces archive themselves
    on their next bootstrap. The migration step is keyed off
    ``core.paths.get_project_root()`` which respects the
    `core/paths.get_project_root` resolution rules.

    Skip cases — directory absent (fresh install), or directory present
    but empty (nothing to archive; just `rmdir`).
    """
    from core.paths import get_project_root

    result = MigrationResult(name="v1→v2: vestigial dir archival")

    project_root = get_project_root()
    geode_dir = project_root / ".geode"
    if not geode_dir.exists():
        result.skipped.append(".geode/: absent in current workspace")
        return result

    stamp = _dt.datetime.now(_dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    archive_root = geode_dir / "_archive"
    candidates = [
        geode_dir / "embedding-cache",
        geode_dir / "vectors",
    ]

    for src in candidates:
        if not src.exists():
            result.skipped.append(f"{src.name}: absent")
            continue
        try:
            entries = list(src.iterdir())
        except OSError as exc:
            result.warnings.append(f"{src.name}: iterdir failed: {exc}")
            continue
        if not entries:
            try:
                src.rmdir()
                result.moved.append((str(src), "(empty — removed)"))
                log.info("Layout v1→v2: removed empty %s", src)
            except OSError as exc:
                result.warnings.append(f"{src.name}: empty rmdir failed: {exc}")
            continue
        dst = archive_root / f"{src.name}-{stamp}"
        if dst.exists():
            result.warnings.append(
                f"{src.name}: archive target {dst} already exists — left source untouched"
            )
            continue
        try:
            archive_root.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            result.moved.append((str(src), str(dst)))
            log.info("Layout v1→v2: archived %s → %s", src, dst)
        except OSError as exc:
            result.warnings.append(f"{src.name}: archive failed: {exc}")

    return result


# ---------------------------------------------------------------------------
# v2 → v3: TTL-based archival of runs/, vault/, projects/
# ---------------------------------------------------------------------------


def _resolve_archive_ttl_days() -> float:
    """Return the configured TTL in days. Falls back to default on any
    parse / sign error so a misconfigured env var never blocks bootstrap.
    """
    raw = os.environ.get(ARCHIVE_TTL_ENV_VAR)
    if raw is None:
        return DEFAULT_ARCHIVE_TTL_DAYS
    try:
        value = float(raw)
    except ValueError:
        log.warning(
            "%s=%r is not numeric — using default %.0f days",
            ARCHIVE_TTL_ENV_VAR,
            raw,
            DEFAULT_ARCHIVE_TTL_DAYS,
        )
        return DEFAULT_ARCHIVE_TTL_DAYS
    if value <= 0:
        log.warning(
            "%s=%r is non-positive — using default %.0f days",
            ARCHIVE_TTL_ENV_VAR,
            raw,
            DEFAULT_ARCHIVE_TTL_DAYS,
        )
        return DEFAULT_ARCHIVE_TTL_DAYS
    return value


def _archive_old_entries_by_mtime(
    source_dir: Path,
    archive_root: Path,
    cutoff: float,
    result: MigrationResult,
    *,
    label: str,
    bucket_by_month: bool = True,
) -> None:
    """Move every direct child of ``source_dir`` older than ``cutoff`` into
    ``archive_root/<YYYY-MM>/`` (or ``archive_root/`` flat if
    ``bucket_by_month=False``).

    Uses ``mtime`` for files and the directory's own ``mtime`` for
    subdirectories — sufficient signal for "user hasn't touched this
    bucket in N days." Records moves on ``result`` (one entry per child).
    Skips ``archive_root`` itself if it happens to live inside
    ``source_dir`` so the migration cannot eat its own tail.
    """
    if not source_dir.exists():
        result.skipped.append(f"{label}: {source_dir} absent")
        return
    try:
        entries = list(source_dir.iterdir())
    except OSError as exc:
        result.warnings.append(f"{label}: iterdir({source_dir}) failed: {exc}")
        return

    archive_resolved = archive_root.resolve()
    for entry in entries:
        try:
            if entry.resolve() == archive_resolved:
                continue
        except OSError:
            pass
        try:
            mtime = entry.stat().st_mtime
        except OSError as exc:
            result.warnings.append(f"{label}: stat({entry.name}) failed: {exc}")
            continue
        if mtime >= cutoff:
            continue

        if bucket_by_month:
            bucket = _dt.datetime.fromtimestamp(mtime, tz=_dt.UTC).strftime("%Y-%m")
            dst_dir = archive_root / bucket
        else:
            dst_dir = archive_root
        dst = dst_dir / entry.name
        if dst.exists():
            result.warnings.append(
                f"{label}: {entry.name} already present in archive — left source untouched"
            )
            continue
        try:
            dst_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(entry), str(dst))
            result.moved.append((str(entry), str(dst)))
        except OSError as exc:
            result.warnings.append(f"{label}: archive of {entry.name} failed: {exc}")


def _migrate_v2_to_v3() -> MigrationResult:
    """v3 — TTL-based archival of high-volume global directories.

    Three target categories under ``~/.geode/``:

    1. ``runs/`` — per-execution receipts. Currently 600+ flat files,
       indefinite retention. Archive children older than TTL to
       ``runs/_archive/<YYYY-MM>/``.

    2. ``vault/general/`` and ``vault/research/`` — long-term memory.
       Currently 1800+ files across both, no eviction policy. Archive
       per-file by ``mtime`` to ``vault/<scope>/_archive/<YYYY-MM>/``.

    3. ``projects/<encoded-cwd>/`` — per-workspace state. Many entries
       correspond to removed worktrees (``.claude/worktrees/*``).
       Archive entire workspace dirs whose own ``mtime`` is past TTL to
       ``projects/_archive/<YYYY-MM>/``.

    TTL defaults to 30 days, overridable via ``GEODE_ARCHIVE_TTL_DAYS``.
    Bucketing by month matches Claude Code's project-tracking dir
    structure and keeps the archive browsable.

    Lossless — uses :func:`shutil.move`. Reversible — operator can move
    bucket contents back. No writer change: existing call sites keep
    writing to the un-bucketed directories; archival is a periodic
    sweep run at bootstrap, gated by the version marker so it only runs
    once per install.
    """
    result = MigrationResult(name="v2→v3: TTL archival (runs/vault/projects)")

    ttl_days = _resolve_archive_ttl_days()
    cutoff = time.time() - ttl_days * 86400.0
    result.warnings.append(f"TTL={ttl_days:.1f} days, cutoff={int(cutoff)}")

    from core.paths import GLOBAL_PROJECTS_DIR, GLOBAL_RUNS_DIR, GLOBAL_VAULT_DIR

    _archive_old_entries_by_mtime(
        GLOBAL_RUNS_DIR,
        GLOBAL_RUNS_DIR / "_archive",
        cutoff,
        result,
        label="runs",
    )

    for scope in ("general", "research"):
        scope_dir = GLOBAL_VAULT_DIR / scope
        _archive_old_entries_by_mtime(
            scope_dir,
            scope_dir / "_archive",
            cutoff,
            result,
            label=f"vault/{scope}",
        )

    _archive_old_entries_by_mtime(
        GLOBAL_PROJECTS_DIR,
        GLOBAL_PROJECTS_DIR / "_archive",
        cutoff,
        result,
        label="projects",
    )

    return result
