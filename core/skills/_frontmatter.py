"""Shared YAML frontmatter parser for agents and skills.

Extracts YAML-style frontmatter from markdown files without requiring
PyYAML as a dependency. Used by SubagentLoader and SkillLoader.
"""

from __future__ import annotations

import re
from typing import Any

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)", re.DOTALL)


def parse_yaml_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Parse YAML frontmatter from a markdown file.

    Returns (metadata_dict, body_markdown). Falls back to empty dict + full
    text if no frontmatter is found. Uses a simple key-value parser to avoid
    requiring PyYAML as a dependency.
    """
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text

    raw_frontmatter = match.group(1)
    body = match.group(2)

    metadata: dict[str, Any] = {}
    for line in raw_frontmatter.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()

        # Handle list values: "[a, b, c]"
        if value.startswith("[") and value.endswith("]"):
            items = [item.strip().strip("\"'") for item in value[1:-1].split(",")]
            metadata[key] = [item for item in items if item]
        # Handle quoted strings
        elif (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            metadata[key] = value[1:-1]
        else:
            metadata[key] = value

    return metadata, body
