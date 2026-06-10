"""Environment + config IO helpers — pure utilities with no CLI dependencies.

Originally extracted from ``core/cli/_helpers.py`` in v0.85.0 so that
non-CLI layers (e.g. ``core/wiring/``) could use these IO helpers
without crossing the CLI boundary. ``core/cli/_helpers.py`` was then
removed entirely in PR-CLEANUP-6 (2026-05-23) — the one CLI-specific
helper that remained (``parse_dry_run_flag``) turned out to be dead
code with zero callers.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

# C-3 (2026-06-11) — behavior(model-pick) env keys. These are SESSION-scoped
# manual overrides only: tools never write them (C-2), the serve daemon drops
# them from its inherited os.environ at startup (so per-session disk reloads
# always win — hazard H2), and the bootstrap .env promotion skips them.
BEHAVIOR_ENV_KEYS: tuple[str, ...] = (
    "GEODE_MODEL",
    "GEODE_PLAN_MODEL",
    "GEODE_ACT_MODEL",
    "GEODE_JUDGE_MODEL",
    "GEODE_COGNITIVE_REFLECTION_MODEL",
    "GEODE_LEARNING_EXTRACT_MODEL",
    "GEODE_AGENTIC_EFFORT",
    "GEODE_ANTHROPIC_CREDENTIAL_SOURCE",
    "GEODE_OPENAI_CREDENTIAL_SOURCE",
)


def mask_key(key: str) -> str:
    """Mask an API key for display: show first 10 + last 4 chars."""
    if len(key) <= 14:
        return "***"
    return key[:10] + "..." + key[-4:]


def upsert_env(var_name: str, value: str) -> None:
    """Insert or update a variable in the CWD ``.env``. Creates it if absent.

    C-2 contract (config-unification, 2026-06-11): the ``.env`` layer is
    **secrets-only** — API keys and credentials. Behavior settings (model
    picks, effort, credential_source) persist to ``config.toml``; tools
    MUST NOT write them here, because the env layer outranks every toml
    layer and one written line silently masks all future toml edits
    (hazards H3/H4). Manual ``GEODE_*`` exports remain a power-user
    session override — by hand only.
    """
    env_path = Path(".env")
    lines: list[str] = []
    found = False

    if env_path.exists():
        raw = env_path.read_text(encoding="utf-8")
        for line in raw.splitlines():
            if re.match(rf"^{re.escape(var_name)}\s*=", line):
                lines.append(f"{var_name}={value}")
                found = True
            else:
                lines.append(line)

    if not found:
        lines.append(f"{var_name}={value}")

    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    # Keep os.environ in sync so Settings() re-instantiation picks up
    # the new value (Pydantic reads os.environ before .env file).
    os.environ[var_name] = value


def upsert_config_toml(section: str, key: str, value: str, *, scope: str = "project") -> None:
    """Insert or update ``[section] key = "value"`` in a ``config.toml``.

    Creates the file (and ``[section]`` heading) if absent. Mirrors the
    write semantics of ``upsert_env``: durable layer for picker choices
    so the next session starts from the same effort / model after the
    user clears ``.env``. 3-codebase consensus pattern (Hermes
    ``~/.hermes/config.json``, Codex ``~/.codex/config.toml``, Claude
    Code project + global config) — chosen settings persist to the
    config layer, not just the env layer.

    ``scope`` picks the durable target, matching the config precedence
    (CLI > env > project ``.geode/config.toml`` > global
    ``~/.geode/config.toml`` > routing default):

    * ``"project"`` (default) — the *session's* project config,
      ``PROJECT_CONFIG_TOML`` (``.geode/config.toml`` relative to the
      thin-CLI cwd). Scoped to the current workspace only.
    * ``"global"`` — the user-global ``~/.geode/config.toml``, inherited
      by every project that has no project-level override.

    Section headings use ``[section.subsection]`` notation per TOML.
    """
    from core.paths import GLOBAL_CONFIG_TOML, PROJECT_CONFIG_TOML

    # P2 (v0.95.x) — was literal `Path(".geode") / "config.toml"`
    config_path = GLOBAL_CONFIG_TOML if scope == "global" else PROJECT_CONFIG_TOML
    config_path.parent.mkdir(parents=True, exist_ok=True)

    target_line = f'{key} = "{value}"'
    section_heading = f"[{section}]"

    raw = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    lines = raw.splitlines()

    in_section = False
    found_section = False
    found_key = False
    new_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped == section_heading:
            in_section = True
            found_section = True
            new_lines.append(line)
            continue
        if in_section and stripped.startswith("["):
            # Hit the next section without finding the key — insert before it
            if not found_key:
                new_lines.append(target_line)
                found_key = True
            in_section = False
        if in_section and re.match(rf"^\s*#?\s*{re.escape(key)}\s*=", line):
            new_lines.append(target_line)
            found_key = True
            continue
        new_lines.append(line)

    if found_section and not found_key:
        new_lines.append(target_line)
    elif not found_section:
        if new_lines and new_lines[-1] != "":
            new_lines.append("")
        new_lines.append(section_heading)
        new_lines.append(target_line)

    config_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def is_glm_key(value: str) -> bool:
    """Detect ZhipuAI API key pattern: {id}.{secret} (e.g. abc12345.def67890).

    GLM keys consist of two dot-separated ASCII alphanumeric segments,
    each at least 4 chars. Rejects emails, URLs, and natural-language text.
    """
    if "." not in value:
        return False
    # GLM keys are pure ASCII alphanumeric + dot — reject @, non-ASCII, etc.
    if "@" in value or not value.isascii():
        return False
    parts = value.split(".", 1)
    if len(parts) != 2 or not all(len(p) >= 4 for p in parts):
        return False
    # Each segment must be alphanumeric with at least one digit (machine-generated)
    return all(p.isalnum() and any(c.isdigit() for c in p) for p in parts)


def remove_env(var_name: str) -> bool:
    """Remove ``var_name`` from the CWD ``.env`` (and ``os.environ``).

    C-2 stale-mask cleanup: earlier releases' ``/model`` wrote model picks
    into ``.env``; those lines outrank every toml edit forever. The picker
    now calls this after its toml write so a tool-created mask is removed
    by the tool. Returns True when a line was removed.
    """
    env_path = Path(".env")
    removed = False
    if env_path.exists():
        kept: list[str] = []
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if re.match(rf"^{re.escape(var_name)}\s*=", line):
                removed = True
                continue
            kept.append(line)
        if removed:
            env_path.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
    if os.environ.pop(var_name, None) is not None:
        removed = True
    return removed
