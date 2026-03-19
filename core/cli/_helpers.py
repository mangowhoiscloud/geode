"""Shared CLI helpers — DRY utility functions used by startup.py and commands.py."""

from __future__ import annotations

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


def is_glm_key(value: str) -> bool:
    """Detect ZhipuAI API key pattern: {id}.{secret} (e.g. abc12345.def67890).

    GLM keys consist of two dot-separated segments, each at least 4 chars.
    """
    if "." not in value:
        return False
    parts = value.split(".", 1)
    return len(parts) == 2 and all(len(p) >= 4 for p in parts)
