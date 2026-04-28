"""Shared CLI helpers — DRY utility functions used by startup.py and commands.py."""

from __future__ import annotations

import os
import re
from pathlib import Path


def mask_key(key: str) -> str:
    """Mask an API key for display: show first 10 + last 4 chars."""
    if len(key) <= 14:
        return "***"
    return key[:10] + "..." + key[-4:]


def upsert_env(var_name: str, value: str) -> None:
    """Insert or update a variable in .env file. Creates .env if absent."""
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


def upsert_config_toml(section: str, key: str, value: str) -> None:
    """Insert or update ``[section] key = "value"`` in ``.geode/config.toml``.

    Creates the file (and ``[section]`` heading) if absent. Mirrors the
    write semantics of ``upsert_env``: durable layer for picker choices
    so the next session starts from the same effort / model after the
    user clears ``.env``. 3-codebase consensus pattern (Hermes
    ``~/.hermes/config.json``, Codex ``~/.codex/config.toml``, Claude
    Code project + global config) — chosen settings persist to the
    config layer, not just the env layer.

    Section headings use ``[section.subsection]`` notation per TOML.
    """
    config_path = Path(".geode") / "config.toml"
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


def parse_dry_run_flag(args: str) -> tuple[bool, str]:
    """Extract --dry-run / --dry_run flag from CLI args.

    Returns ``(has_flag, cleaned_args)`` where ``cleaned_args`` has the
    flag removed and is stripped of surrounding whitespace.
    """
    has_flag = "--dry-run" in args or "--dry_run" in args
    cleaned = args.replace("--dry-run", "").replace("--dry_run", "").strip()
    return has_flag, cleaned


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
