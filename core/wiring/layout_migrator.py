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
import logging
import os
import shutil
import threading
from dataclasses import dataclass, field

from core.paths import GEODE_HOME

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Current target layout schema version. Bumped each time a path-level
#: migration is added.
GEODE_LAYOUT_VERSION = 2

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
    log.info(
        "Layout migration v%d → v%d completed: %d step(s)",
        report.from_version,
        report.to_version,
        len(report.steps),
    )
    return report


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

    import datetime as _dt

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
