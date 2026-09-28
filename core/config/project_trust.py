"""Workspace trust for project-scoped configuration.

A repository can ship ``.geode/config.toml``, ``.env`` and ``.claude/mcp_servers.json``.
Until the user trusts the folder, GEODE reads only project settings that cannot widen
what the agent may do, where data goes, or which credentials and servers it uses.
Codex keeps untrusted project config layers off, and Claude Code holds
capability-granting project settings until the folder is trusted; restrictive
project settings such as ``[policy.org] denied_tools`` still apply.

Trust is recorded the way Codex records it, in the global config.toml:
``[projects."<absolute path>"] trust_level = "trusted"``. Only ``geode config trust``
writes it, and a project's own config.toml is never consulted, so a repository cannot
trust itself.
"""

from __future__ import annotations

import logging
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from core.config.toml_edit import (
    persist_toml_section,
    read_config_toml,
    resolve_config_toml_path,
    toml_escape,
)
from core.paths import GLOBAL_ENV_FILE

log = logging.getLogger(__name__)

#: Project config keys that widen capability or redirect data. A project
#: ``.geode/config.toml`` sets them only after the folder is trusted.
TRUST_REQUIRED_KEYS: frozenset[str] = frozenset(
    {
        "bash_sandbox.mode",
        "computer_use.enabled",
        "computer_use.driver",
        "cost.limit_usd",
        "gateway.allow_computer_use",
        "gateway.enabled",
        "gateway.max_concurrent",
        "gateway.poll_interval_s",
        "llm.model_policy_path",
        "notification.channel",
        "notification.recipient",
        "paths.organization_fixture_dir",
        "paths.user_profile_dir",
        "scheduler.auto_start",
        "session.storage_dir",
        "tools.package_install_guard",
        "webhook.enabled",
        "webhook.port",
    }
)

#: Never read from a project, trusted or not: a repository must not turn off
#: permission prompts or choose a local executable.
PROJECT_DENIED_KEYS: frozenset[str] = frozenset(
    {"computer_use.helper_path", "hitl.dangerously_skip_permissions"}
)

_warned: set[str] = set()


def _warn_once(message: str) -> None:
    if message not in _warned:
        _warned.add(message)
        log.warning(message)


def _root(root: Path | None) -> Path:
    return (root or Path.cwd()).resolve()


def trusted_projects() -> frozenset[str]:
    """Absolute paths marked trusted in the global config; an unreadable file trusts nothing."""
    path = resolve_config_toml_path()
    try:
        projects = read_config_toml(path).get("projects", {})
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        _warn_once(f"Unreadable {path}; treating every project as untrusted")
        return frozenset()
    if not isinstance(projects, dict):
        return frozenset()
    return frozenset(
        folder
        for folder, entry in projects.items()
        if isinstance(entry, dict) and entry.get("trust_level") == "trusted"
    )


def is_project_trusted(root: Path | None = None) -> bool:
    return str(_root(root)) in trusted_projects()


def set_project_trust(root: Path, *, trusted: bool) -> Path:
    """Record ``root``'s trust in the global config.toml; returns that file."""
    section = f'projects."{toml_escape(str(_root(root)))}"'
    return persist_toml_section(section, {"trust_level": "trusted" if trusted else "untrusted"})


def filter_project_keys(flat: Mapping[str, Any], *, root: Path | None = None) -> dict[str, Any]:
    """Drop project keys the folder's trust state does not allow; warn once per key set."""
    trusted = is_project_trusted(root)
    kept: dict[str, Any] = {}
    dropped: list[str] = []
    for key, value in flat.items():
        if key in PROJECT_DENIED_KEYS or (not trusted and key in TRUST_REQUIRED_KEYS):
            dropped.append(key)
        else:
            kept[key] = value
    if dropped:
        hint = "" if trusted else " until you run `geode config trust`"
        _warn_once(f"Project config ignores {', '.join(sorted(dropped))}{hint}")
    return kept


def project_files_allowed(what: str, *, root: Path | None = None) -> bool:
    """True when project-supplied ``what`` may load; warns once when it is held back."""
    if is_project_trusted(root):
        return True
    _warn_once(f"Ignoring project {what} in {_root(root)} until you run `geode config trust`")
    return False


def dotenv_files() -> tuple[str, ...]:
    """The Settings dotenv layer: the project ``.env`` joins only for a trusted folder."""
    project_env = Path(".env")
    if project_env.exists() and project_files_allowed(".env"):
        return (str(project_env), str(GLOBAL_ENV_FILE))
    return (str(GLOBAL_ENV_FILE),)
