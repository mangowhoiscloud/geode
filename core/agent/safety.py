"""Safety classification constants for tool execution.

Single source of truth for tool risk levels. Used by ToolExecutor
(immediate gating) and ToolCallProcessor (tier classification for
parallel batching).
"""

from __future__ import annotations

# Read-only tools — safe for sub-agent auto-approval
SAFE_TOOLS: frozenset[str] = frozenset(
    {
        "list_ips",
        "search_ips",
        "show_help",
        "check_status",
        "memory_search",
        "manage_rule",
        "web_fetch",
        "general_web_search",
        "note_read",
        "read_document",
        "glob_files",
        "grep_files",
        "profile_show",
        "calendar_list_events",
    }
)

# System-access tools — always require HITL approval
DANGEROUS_TOOLS: frozenset[str] = frozenset(
    {
        "run_bash",
        "computer",  # computer-use: screen control
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
        "manage_context",
        "switch_model",
        "edit_file",
        "write_file",
    }
)

# Expensive tools require cost confirmation before execution
EXPENSIVE_TOOLS: dict[str, float] = {
    "analyze_ip": 1.50,
    "batch_analyze": 5.00,
    "compare_ips": 3.00,
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

# MCP servers that are read-only and auto-approved (no HITL gate on first call).
AUTO_APPROVED_MCP_SERVERS: frozenset[str] = frozenset(
    {
        "steam",
        "arxiv",
        "linkedin-reader",
    }
)
