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
# P3 (v0.95.x) — user preferences TOML inside user_profile/.
# Read by `core/tools/policy.py` to seed ProfilePolicy at boot.
GLOBAL_USER_PREFERENCES = GLOBAL_USER_PROFILE_DIR / "preferences.toml"

# Non-project-scoped data
GLOBAL_VAULT_DIR = GEODE_HOME / "vault"
GLOBAL_MODELS_DIR = GEODE_HOME / "models"
GLOBAL_RUNS_DIR = GEODE_HOME / "runs"
GLOBAL_USAGE_DIR = GEODE_HOME / "usage"
GLOBAL_MCP_DIR = GEODE_HOME / "mcp"
GLOBAL_SCHEDULER_DIR = GEODE_HOME / "scheduler"
# P4 (v0.95.x) — added during lint-guardrail rollout. fa4 diagnostics
# log dir (cross-process append-only) and the auth.toml SoT path.
# `core.auth.auth_toml` overrides via `GEODE_AUTH_TOML` env var; this
# constant is the default fallback.
GLOBAL_DIAGNOSTICS_DIR = GEODE_HOME / "diagnostics"
# P1a + P1c (2026-05-19) — self-improving-loop wiring sprint. Shared cross-loop
# namespace: ``sessions.jsonl`` (P1a, run-level index, one row per
# autoresearch/seed-generation run) + ``<session_id>/journal.jsonl``
# (P1c, event stream within a single run). See
# ``docs/plans/2026-05-19-self-improving-loop-wiring-sprint.md``.
GLOBAL_SELF_IMPROVING_LOOP_DIR = GEODE_HOME / "self-improving-loop"
# PR-RATCHET-1 (2026-05-21) — the 5 mutation SoT files now live in
# the in-repo ``autoresearch/state/sot/`` directory rather than the
# operator's ``~/.geode/self-improving-loop/``. The rename converges
# on upstream Karpathy's "branch tip = current best" principle: the
# SoT is git-tracked, so ``git diff`` shows the current mutation
# state and ``git revert`` discards a hypothesis. The constants below
# keep their ``GLOBAL_*_SOT`` names for backwards compatibility with
# existing callers; only the value moves. Lazy migration of any
# legacy ``~/.geode/self-improving-loop/<file>.json`` payload is
# handled by :mod:`core.self_improving_loop.policies`.
_REPO_ROOT = Path(__file__).resolve().parents[1]
_AUTORESEARCH_STATE_DIR = _REPO_ROOT / "autoresearch" / "state"
GLOBAL_SOT_DIR = _AUTORESEARCH_STATE_DIR / "sot"
LEGACY_SOT_DIR = GLOBAL_SELF_IMPROVING_LOOP_DIR
"""Pre-RATCHET-1 SoT dir under ``~/.geode/self-improving-loop/``.
Kept for the lazy migration path so an upgrade of an existing
operator install copies their last-known wrapper/policy state into
the new in-repo location on first read/write."""
# G5a (2026-05-20) — cross-process SoT for the AgenticLoop wrapper prompt
# sections. Written by ``autoresearch.train.write_wrapper_prompt_sections``
# after a self-improving-loop promotion; read by
# ``core.agent.system_prompt._load_wrapper_override`` for daily GEODE runs.
GLOBAL_WRAPPER_SECTIONS_SOT = GLOBAL_SOT_DIR / "wrapper-sections.json"
# PR-6 C-5 (2026-05-21) — policy mutation SoT files. Each
# ``target_kind`` (tool_policy / decomposition / retrieval /
# reflection) gets its own ``dict[str, str]`` JSON file alongside
# ``wrapper-sections.json``. ``prompt`` keeps the legacy wrapper-
# sections name so older mutation rows replay correctly; the others
# land in fresh files because they evolve independently. Read /
# written by :mod:`core.self_improving_loop.policies`.
GLOBAL_TOOL_POLICY_SOT = GLOBAL_SOT_DIR / "tool-policy.json"
GLOBAL_DECOMPOSITION_POLICY_SOT = GLOBAL_SOT_DIR / "decomposition.json"
GLOBAL_RETRIEVAL_POLICY_SOT = GLOBAL_SOT_DIR / "retrieval.json"
GLOBAL_REFLECTION_POLICY_SOT = GLOBAL_SOT_DIR / "reflection.json"
GLOBAL_AUTH_TOML = GEODE_HOME / "auth.toml"
# PR-4 C-3 (2026-05-21) — cross-session episodic action-outcome log
# (~/.geode/memory/episodes.jsonl). Append-only JSONL: one row per
# tool execution with (timestamp, session_id, tool_name, tool_input,
# success/error, cognitive_state snapshot). Rolling cap of
# ``EPISODE_LOG_MAX_ROWS`` keeps the file bounded. Read by
# :class:`core.memory.episodic.EpisodicStore` retrieval API.
GLOBAL_MEMORY_DIR = GEODE_HOME / "memory"
GLOBAL_EPISODES_LOG = GLOBAL_MEMORY_DIR / "episodes.jsonl"
# P1-F (2026-05-17) — per-user Petri audit role × model × source override.
# Read by ``plugins.petri_audit.user_overrides`` and merged into the
# binding resolver. Kept as a separate TOML (rather than wedged into
# ``config.toml``) so main GEODE config stays decoupled from Petri-only
# concerns; the /petri command writes here.
GLOBAL_PETRI_TOML = GEODE_HOME / "petri.toml"
# P2-A (2026-05-17) — global user override for the routing manifest.
# Loaded by ``core.config.routing_manifest.load_routing_manifest`` and
# merged section-by-section over the shipped ``core/config/routing.toml``
# default. Distinct from ``PROJECT_ROUTING_CONFIG`` (per-project node
# routing legacy file); P2-B..E migrate the legacy consumers onto the
# global manifest.
GLOBAL_ROUTING_TOML = GEODE_HOME / "routing.toml"
# P5 (Session 63, S5.5) — per-user seed-generation role × source override.
# Read by ``plugins.seed_generation.picker.load_user_overrides`` and merged
# into the picker's per-role binding resolver. Distinct from
# ``GLOBAL_PETRI_TOML`` because seed-generation owns its own 7-role × judge-
# panel binding model (see ADR-003 §"override surface").
GLOBAL_SEED_PIPELINE_TOML = GEODE_HOME / "seed-generation.toml"
# P3 (v0.95.x) — user-tier installed skills (priority 2 of 4-tier
# resolution; see `core/llm/skill_registry.py`). Bundled skills live
# inside the package source tree, not at `GEODE_HOME` — resolve via
# `__file__` in skill_registry, do NOT add a constant for them here.
GLOBAL_SKILLS_DIR = GEODE_HOME / "skills"

# Project-scoped user data root
GLOBAL_PROJECTS_DIR = GEODE_HOME / "projects"

# Lifecycle / daemon paths (v0.63.0 — surfaced for /stop, /clean, /uninstall).
# Single source of truth so any future relocation is one-line. Existing
# duplicates in ``ipc_client.py`` + ``poller.py`` (DEFAULT_SOCKET_PATH) +
# ``mcp/registry.py`` (_CACHE_FILE) match these values; dedup is a
# follow-up refactor.
CLI_SOCKET_PATH = GEODE_HOME / "cli.sock"
CLI_STARTUP_LOCK = GEODE_HOME / "cli.startup.lock"
SERVE_LOG_PATH = GEODE_HOME / "logs" / "serve.log"
GLOBAL_JOURNAL_DIR = GEODE_HOME / "journal"
GLOBAL_WORKERS_DIR = GEODE_HOME / "workers"
# v0.95.x layout migration v1 — moved under mcp/ to group with other MCP state.
# Legacy ``~/.geode/mcp-registry-cache.json`` migrated by
# ``core.wiring.layout_migrator._migrate_v0_to_v1`` on first bootstrap.
MCP_REGISTRY_CACHE = GEODE_HOME / "mcp" / "registry-cache.json"
# v0.95.x layout migration v1 — renamed to match the actual writer
# (``core.hooks.approval_tracker``, which has always used ``approval_history.jsonl``).
# Legacy ``~/.geode/approve_history.json`` (paths.py-side typo) migrated by
# ``core.wiring.layout_migrator._migrate_v0_to_v1``.
APPROVE_HISTORY = GEODE_HOME / "approval_history.jsonl"

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
PROJECT_PLANS_FILE = PROJECT_GEODE_DIR / "plans.json"
PROJECT_LEARNING_FILE = PROJECT_GEODE_DIR / "LEARNING.md"
PROJECT_MEMORY_INDEX = PROJECT_GEODE_DIR / "MEMORY.md"
# P4 (v0.95.x) — added during the lint-guardrail rollout. project-local
# user_profile override (read by `core.cli.bootstrap` + `core.wiring.bootstrap`)
# and project-local hooks dir (read by `core.wiring.bootstrap` plugin loader).
PROJECT_USER_PROFILE_DIR = PROJECT_GEODE_DIR / "user_profile"
PROJECT_HOOKS_DIR = PROJECT_GEODE_DIR / "hooks"

# Per-project caches surfaced by /clean for selective wipe.
#
# v0.95.x — `PROJECT_EMBEDDING_CACHE` and `PROJECT_VECTORS_DIR` were
# removed (vestigial). No writer ever used either constant; the
# corresponding on-disk directories (`.geode/embedding-cache/`,
# `.geode/vectors/`) stopped receiving writes on 2026-04-05 and are
# archived to `.geode/_archive/` by layout migration v1 → v2 (see
# `core/wiring/layout_migrator.py:_migrate_v1_to_v2`).
PROJECT_TOOL_OFFLOAD = PROJECT_GEODE_DIR / "tool-offload"

# P3 (v0.95.x) — project-level state files. Surfaced here so writers stop
# hardcoding `Path(".geode/<file>")` literals (frontier parity — Hermes
# `hermes_constants.py:14-68` keeps every path on a single SoT module).
PROJECT_AGENT_MEMORY_DIR = PROJECT_GEODE_DIR / "agent-memory"
PROJECT_MODEL_POLICY = PROJECT_GEODE_DIR / "model-policy.toml"
PROJECT_ROUTING_CONFIG = PROJECT_GEODE_DIR / "routing.toml"


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

    # --- Layout migration (Hermes `_init_schema` pattern) ---
    # Runs on every bootstrap, idempotent via the module-level once-flag
    # inside :mod:`core.wiring.layout_migrator`. Reconciles legacy paths
    # produced by older GEODE versions with the current constants above.
    # Lazy import — keeps `core.paths` free of `core.wiring` dependency for
    # consumers that need pure path utilities without bootstrap side-effects.
    try:
        from core.wiring.layout_migrator import ensure_layout_migrated

        ensure_layout_migrated()
    except Exception:  # pragma: no cover — migration must never block boot
        _paths_log.warning("Layout migration skipped", exc_info=True)


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
