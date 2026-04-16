"""GEODE directory hierarchy — centralized path resolution.

Two-tier directory structure following Claude Code's ~/.claude pattern:

  User-level (~/.geode/):
    Global config, credentials, identity, vault, models, usage.
    Project-scoped session data lives in ~/.geode/projects/{project_id}/.

  Project-level ({workspace}/.geode/):
    Project config (gateway bindings), memory, rules, skills, reports, cache.

Project ID encoding follows Claude Code's convention:
  /home/user/workspace/geode  ->  -home-user-workspace-geode
"""

from __future__ import annotations

import logging as _logging
import os
from functools import lru_cache
from pathlib import Path

# ---------------------------------------------------------------------------
# User-level (global) — ~/.geode/
# ---------------------------------------------------------------------------

GEODE_HOME = Path.home() / ".geode"

# Global config & credentials
GLOBAL_CONFIG_TOML = GEODE_HOME / "config.toml"
GLOBAL_ENV_FILE = GEODE_HOME / ".env"

# User identity & profile
GLOBAL_IDENTITY_DIR = GEODE_HOME / "identity"
GLOBAL_USER_PROFILE_DIR = GEODE_HOME / "user_profile"

# Non-project-scoped data
GLOBAL_VAULT_DIR = GEODE_HOME / "vault"
GLOBAL_MODELS_DIR = GEODE_HOME / "models"
GLOBAL_RUNS_DIR = GEODE_HOME / "runs"
GLOBAL_USAGE_DIR = GEODE_HOME / "usage"
GLOBAL_MCP_DIR = GEODE_HOME / "mcp"
GLOBAL_SCHEDULER_DIR = GEODE_HOME / "scheduler"

# Project-scoped user data root
GLOBAL_PROJECTS_DIR = GEODE_HOME / "projects"

# ---------------------------------------------------------------------------
# Project-level — {workspace}/.geode/
# ---------------------------------------------------------------------------

PROJECT_GEODE_DIR = Path(".geode")
PROJECT_CONFIG_TOML = PROJECT_GEODE_DIR / "config.toml"
PROJECT_MEMORY_DIR = PROJECT_GEODE_DIR / "memory"
PROJECT_RULES_DIR = PROJECT_GEODE_DIR / "rules"
PROJECT_SKILLS_DIR = PROJECT_GEODE_DIR / "skills"
PROJECT_REPORTS_DIR = PROJECT_GEODE_DIR / "reports"
PROJECT_RESULT_CACHE_DIR = PROJECT_GEODE_DIR / "result_cache"
PROJECT_SCHEDULER_FILE = PROJECT_GEODE_DIR / "scheduled_tasks.json"
PROJECT_SCHEDULER_LOCK = PROJECT_GEODE_DIR / "scheduled_tasks.lock"
PROJECT_SCHEDULER_LOG_DIR = PROJECT_GEODE_DIR / "scheduler_logs"
PROJECT_LEARNING_FILE = PROJECT_GEODE_DIR / "LEARNING.md"
PROJECT_MEMORY_INDEX = PROJECT_GEODE_DIR / "MEMORY.md"


# ---------------------------------------------------------------------------
# Project root — CWD at startup (Claude Code's originalCwd pattern)
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def get_project_root() -> Path:
    """Return the resolved CWD captured at first call.

    Follows Claude Code's ``originalCwd`` pattern: the sandbox boundary is
    the directory where the CLI was invoked, **not** the package installation
    path.  ``lru_cache`` ensures the value is frozen after the first call,
    which happens during CLI startup.
    """
    return Path.cwd().resolve()


# ---------------------------------------------------------------------------
# Project ID — Claude Code-style path encoding
# ---------------------------------------------------------------------------


def encode_project_id(workspace_path: str | Path | None = None) -> str:
    """Encode a workspace path into a project ID.

    Follows Claude Code's convention: replace ``/`` with ``-``.
    Example: ``/home/user/workspace/geode`` -> ``-home-user-workspace-geode``

    Args:
        workspace_path: Absolute workspace path. Defaults to ``cwd()``.
    """
    if workspace_path is None:
        workspace_path = Path.cwd()
    path_str = str(Path(workspace_path).resolve())
    return path_str.replace(os.sep, "-")


@lru_cache(maxsize=4)
def get_project_data_dir(workspace_path: str | Path | None = None) -> Path:
    """User-level project-scoped data directory.

    Returns ``~/.geode/projects/{project_id}/``.
    """
    project_id = encode_project_id(workspace_path)
    return GLOBAL_PROJECTS_DIR / project_id


# ---------------------------------------------------------------------------
# Project-scoped user directories (session, journal, snapshots)
# ---------------------------------------------------------------------------


def get_project_journal_dir(workspace_path: str | Path | None = None) -> Path:
    """Journal directory: ``~/.geode/projects/{id}/journal/``."""
    return get_project_data_dir(workspace_path) / "journal"


def get_project_sessions_dir(workspace_path: str | Path | None = None) -> Path:
    """Sessions directory: ``~/.geode/projects/{id}/sessions/``."""
    return get_project_data_dir(workspace_path) / "sessions"


def get_project_snapshots_dir(workspace_path: str | Path | None = None) -> Path:
    """Snapshots directory: ``~/.geode/projects/{id}/snapshots/``."""
    return get_project_data_dir(workspace_path) / "snapshots"


# ---------------------------------------------------------------------------
# Backward-compat: fallback to old project-level paths
# ---------------------------------------------------------------------------

# Old paths (pre-v0.31) stored these under {workspace}/.geode/
_OLD_JOURNAL_DIR = PROJECT_GEODE_DIR / "journal"
_OLD_SESSION_DIR = PROJECT_GEODE_DIR / "session"
_OLD_SNAPSHOT_DIR = PROJECT_GEODE_DIR / "snapshots"
_OLD_RESULT_CACHE_DIR = PROJECT_GEODE_DIR / "result_cache"
_OLD_VAULT_DIR = PROJECT_GEODE_DIR / "vault"
_OLD_MODELS_DIR = PROJECT_GEODE_DIR / "models"


def resolve_journal_dir(workspace_path: str | Path | None = None) -> Path:
    """Resolve journal directory with backward-compat fallback.

    Returns new path if it exists or old path doesn't exist.
    Falls back to old path if it has data and new path is empty.
    """
    new = get_project_journal_dir(workspace_path)
    return _resolve_with_fallback(new, _OLD_JOURNAL_DIR)


def resolve_sessions_dir(workspace_path: str | Path | None = None) -> Path:
    """Resolve sessions directory with backward-compat fallback."""
    new = get_project_sessions_dir(workspace_path)
    return _resolve_with_fallback(new, _OLD_SESSION_DIR)


def resolve_snapshots_dir(workspace_path: str | Path | None = None) -> Path:
    """Resolve snapshots directory with backward-compat fallback."""
    new = get_project_snapshots_dir(workspace_path)
    return _resolve_with_fallback(new, _OLD_SNAPSHOT_DIR)


def resolve_result_cache_dir(workspace_path: str | Path | None = None) -> Path:
    """Resolve result cache directory with backward-compat fallback."""
    new = get_project_data_dir(workspace_path) / "result_cache"
    return _resolve_with_fallback(new, _OLD_RESULT_CACHE_DIR)


def resolve_vault_dir() -> Path:
    """Resolve vault directory with backward-compat fallback."""
    return _resolve_with_fallback(GLOBAL_VAULT_DIR, _OLD_VAULT_DIR)


def resolve_models_dir() -> Path:
    """Resolve models directory with backward-compat fallback."""
    return _resolve_with_fallback(GLOBAL_MODELS_DIR, _OLD_MODELS_DIR)


def _resolve_with_fallback(new_path: Path, old_path: Path) -> Path:
    """Return new_path unless old_path has data and new_path is empty/missing."""
    if new_path.exists() and any(new_path.iterdir()):
        return new_path
    if old_path.exists() and any(old_path.iterdir()):
        return old_path
    # Neither has data — use new path (will be created on first write)
    return new_path


# ---------------------------------------------------------------------------
# Lazy directory creation — Claude Code pattern (mkdir recursive on-demand)
# ---------------------------------------------------------------------------

_paths_log = _logging.getLogger(__name__)


def ensure_directories() -> None:
    """Create all required directories if missing.

    Called once at bootstrap. Follows Claude Code's lazy creation pattern:
    ``mkdir(parents=True, exist_ok=True)`` — no error if already present,
    creates full tree if absent.

    Two tiers:
    - Global (``~/.geode/``): runs, vault, models, usage, projects
    - Project (``.geode/``): memory, rules, skills, reports, scheduler_logs
    """
    created: list[str] = []

    # --- Global tier ---
    global_dirs = [
        GEODE_HOME,
        GLOBAL_RUNS_DIR,
        GLOBAL_VAULT_DIR,
        GLOBAL_MODELS_DIR,
        GLOBAL_USAGE_DIR,
        GLOBAL_MCP_DIR,
        GLOBAL_SCHEDULER_DIR,
        GLOBAL_PROJECTS_DIR,
        GLOBAL_IDENTITY_DIR,
        GLOBAL_USER_PROFILE_DIR,
    ]
    for d in global_dirs:
        if not d.exists():
            d.mkdir(parents=True, exist_ok=True)
            created.append(str(d))

    # --- Project-scoped user data (under ~/.geode/projects/{id}/) ---
    project_data = get_project_data_dir()
    project_user_dirs = [
        project_data,
        project_data / "journal",
        project_data / "sessions",
        project_data / "snapshots",
        project_data / "result_cache",
    ]
    for d in project_user_dirs:
        if not d.exists():
            d.mkdir(parents=True, exist_ok=True)
            created.append(str(d))

    # --- Project tier (.geode/) ---
    project_dirs = [
        PROJECT_GEODE_DIR,
        PROJECT_MEMORY_DIR,
        PROJECT_RULES_DIR,
        PROJECT_SKILLS_DIR,
        PROJECT_REPORTS_DIR,
        PROJECT_SCHEDULER_LOG_DIR,
    ]
    for d in project_dirs:
        if not d.exists():
            d.mkdir(parents=True, exist_ok=True)
            created.append(str(d))

    # --- .gitignore entry for .geode/ ---
    _ensure_geode_gitignore()

    if created:
        _paths_log.info("Created %d directories: %s", len(created), ", ".join(created))


def _ensure_geode_gitignore() -> None:
    """Add .geode/ to .gitignore if not already present."""
    gitignore = Path(".gitignore")
    entry = ".geode/"
    try:
        if gitignore.exists():
            content = gitignore.read_text(encoding="utf-8")
            if entry in content:
                return
            if not content.endswith("\n"):
                content += "\n"
        else:
            content = ""
        content += f"\n# GEODE\n{entry}\n"
        gitignore.write_text(content, encoding="utf-8")
    except OSError:
        pass  # read-only filesystem, CI, etc.
