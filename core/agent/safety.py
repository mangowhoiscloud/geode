"""Safety classification constants for tool execution.

Single source of truth for tool risk levels. Used by ToolExecutor
(immediate gating) and ToolCallProcessor (tier classification for
parallel batching).
"""

from __future__ import annotations

from contextvars import ContextVar

from core.tools.personal_data import PERSONAL_DATA_TOOLS

# --dangerously-skip-permissions — PER-SESSION state (not process-global).
#
# Set by the IPC ``client_capability`` handshake in the connection's task /
# thread (``_adopt_skip_permissions``), BEFORE the first prompt, and read at
# gate-call time by ``ApprovalWorkflow`` + the plan handler. Per-task isolation
# (a ContextVar, like ``_current_loop_ctx``) is the load-bearing property: a
# process-global flag would let a skip client flip approvals for ANOTHER
# session that is concurrently awaiting tool work (Codex review HIGH). Unset
# (internal sessions with no handshake) falls back to the daemon-wide
# ``settings.dangerously_skip_permissions`` env default.
_skip_permissions_var: ContextVar[bool | None] = ContextVar("geode_skip_permissions", default=None)


def set_skip_permissions(on: bool) -> None:
    """Set ``--dangerously-skip-permissions`` for the CURRENT session context."""
    _skip_permissions_var.set(on)


def current_skip_permissions() -> bool:
    """Resolve the effective skip-permissions flag for the current context.

    Per-session ContextVar wins when set (IPC capability adoption); otherwise
    the process-wide env default (``GEODE_DANGEROUSLY_SKIP_PERMISSIONS``, e.g.
    a daemon launched in skip mode) applies.
    """
    override = _skip_permissions_var.get()
    if override is not None:
        return override
    from core.config import settings

    return bool(getattr(settings, "dangerously_skip_permissions", False))


# Read-only tools — safe for sub-agent auto-approval
SAFE_TOOLS: frozenset[str] = frozenset(
    {
        "check_status",
        "calculate",
        "memory_search",
        "manage_rule",
        "web_fetch",
        "llms_txt_index",
        "general_web_search",
        "note_read",
        "read_document",
        "glob_files",
        "grep_files",
        "profile_show",
        "wanted_jobs_search",
    }
)

# Personal Workspace reads and mutations cross a user-data trust boundary.
# Google requires an affirmative action immediately before every agentic
# invocation, so this category cannot inherit the normal write cache, HITL-0,
# or --dangerously-skip-permissions bypasses.
SENSITIVE_TOOLS: frozenset[str] = PERSONAL_DATA_TOOLS

# System-access tools — always require HITL approval
DANGEROUS_TOOLS: frozenset[str] = frozenset(
    {
        "run_bash",
        "computer",  # computer-use: screen control
        "computer_use",  # emulated function-call computer-use: screen control
    }
)

# Write tools modify persistent state (credentials, memory, files).
# Require explicit user confirmation — never auto-approved, even for sub-agents.
WRITE_TOOLS: frozenset[str] = frozenset(
    {
        "memory_save",
        "note_save",
        "set_api_key",
        "manage_auth",
        "manage_login",
        "profile_update",
        "profile_preference",
        "profile_learn",
        "calendar_create_event",
        "calendar_sync_scheduler",
        "gmail_send",
        "google_drive_create",
        "google_docs_write",
        "google_sheets_write",
        "google_tasks_write",
        "manage_context",
        "switch_model",
        "document_ingest",
        "edit_file",
        "write_file",
    }
)

# Both provider-native and emulated desktop-control surfaces. Keep the pair in
# one home so a narrowly-scoped opt-in cannot accidentally expose only one
# execution route.
COMPUTER_USE_TOOLS: frozenset[str] = frozenset({"computer", "computer_use"})

# Tools denied on headless (no-human-to-approve) sessions: scheduler, daemon,
# and the MCP run_agent fork. A messaging DAEMON may subtract only
# ``COMPUTER_USE_TOOLS`` behind the explicit gateway opt-in; scheduler,
# run_agent, and personal-workspace consent boundaries remain fail-closed.
HEADLESS_DENIED_TOOLS: frozenset[str] = frozenset(
    {
        "run_bash",
        "delegate_task",
        *COMPUTER_USE_TOOLS,
        *SENSITIVE_TOOLS,
    }
)

# Expensive tools require cost confirmation before execution
EXPENSIVE_TOOLS: dict[str, float] = {
    # Petri audit — conservative ceiling. Real estimate is rendered by
    # ``plugins.petri_audit.runner.estimate_cost_usd`` and shown next to
    # the [Y/n] prompt; this number only needs to flip the gate on.
    "petri_audit": 5.00,
    # DSPy prompt re-compile (D 단계). Anchored to plan § R2 — Sonnet-class
    # compile averages $5-15. Real estimate / budget cap lives in
    # ``plugins.petri_audit.optimize`` (M3).
    "eval_dspy_optimize": 12.00,
}

# Bash commands starting with these prefixes are safe (read-only, no side effects).
# They execute without HITL approval to reduce friction for common queries.
SAFE_BASH_PREFIXES: tuple[str, ...] = (
    "cat ",
    "head ",
    "tail ",
    "ls ",
    "ls\n",
    "pwd",
    "echo ",
    "wc ",
    "grep ",
    "rg ",
    "find ",
    "which ",
    "whoami",
    "date",
    "env ",
    "printenv",
    "uname",
    "df ",
    "du ",
    "file ",
    "stat ",
    "curl -s",
    "curl --silent",
    "python3 -c",
    "python -c",
    "uv run pytest",
    "uv run ruff",
    "uv run mypy",
    "uv run python",
    "git status",
    "git log",
    "git diff",
    "git branch",
    "git show",
    "git remote",
    "gh pr",
    "gh run",
    "gh api",
)

# Stream filters/formatters that may appear *after* a `|` in a pipeline.
# These read stdin and write stdout — they do not modify the filesystem
# unless explicitly told to (e.g. `sed -i`, `tee`, `awk ... > file`).
# We pair this with a separate write-redirect (`>`, `>>`) reject in
# ``ApprovalController.is_bash_auto_approved`` so a `find ... | sed -e '...'
# | head -200` chain auto-approves while `... | tee out.txt` still requires
# HITL.
#
# References — frontier auto-approve patterns:
#   * claude-code settings.json `permissions.allow: ["Bash(find:*)", …]`
#     uses per-command globs; we approximate via prefix + pipeline rule.
#   * Codex CLI sandbox treats read-only stream filters as safe.
SAFE_BASH_PIPELINE_STAGES: tuple[str, ...] = (
    "head",
    "tail",
    "wc",
    "sort",
    "uniq",
    "cut",
    "tr",
    "grep",
    "rg",
    "cat",
    "less",
    "more",
    "sed",
    "awk",
    "jq",
    "yq",
    "column",
    "fold",
    "nl",
)


def is_bash_command_read_only(command: str) -> bool:
    """Static safety check — is ``command`` a read-only bash pipeline?

    Returns True only when:

      * The command contains no write redirect (``>``, ``>>``), sequential /
        background separator (``;``, ``&``, ``&&``, ``||``), command
        substitution (``$(...)``, ``\\`...\\``, ``<(...)``, ``>(...)``).
      * The first stage starts with a :data:`SAFE_BASH_PREFIXES` prefix.
      * Every subsequent ``|``-separated stage starts with a
        :data:`SAFE_BASH_PIPELINE_STAGES` prefix.
      * No ``sed -i`` / ``sed --in-place`` (which rewrites files even without
        a top-level redirect).

    Pure function — no instance state. Used by both
    :meth:`ApprovalController.is_bash_auto_approved` and the test mirror in
    ``tests/core/agent/test_bash_safe_prefix.py`` so the two cannot drift.
    """
    _UNSAFE_CHARS = frozenset(">;&`")
    if any(c in command for c in _UNSAFE_CHARS):
        return False
    if "$(" in command or "<(" in command or ">(" in command:
        return False

    stages = [s.strip() for s in command.split("|")]
    if not stages or not stages[0]:
        return False
    if not any(stages[0].startswith(p) for p in SAFE_BASH_PREFIXES):
        return False
    for stage in stages[1:]:
        if not stage:
            return False
        stage_matches = any(
            stage == p or stage.startswith(p + " ") or stage.startswith(p + "\t")
            for p in SAFE_BASH_PIPELINE_STAGES
        )
        if not stage_matches:
            return False
        if stage.startswith("sed ") and (" -i" in (" " + stage) or " --in-place" in (" " + stage)):
            return False
    return True


# MCP servers that are read-only and auto-approved (no HITL gate on first call).
AUTO_APPROVED_MCP_SERVERS: frozenset[str] = frozenset(
    {
        "steam",
        "arxiv",
        "linkedin-reader",
    }
)
