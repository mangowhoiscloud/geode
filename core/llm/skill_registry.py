"""Skill registry -- discover and manage .md skill files.

Skills are YAML frontmatter + Markdown body files that inject prompt fragments
into the PromptAssembler pipeline. (ADR-007)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Frontmatter parser (no PyYAML dependency)
# ---------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n(.*)", re.DOTALL)
_KV_RE = re.compile(r"^(\w[\w-]*)\s*:\s*(.+)$", re.MULTILINE)


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str] | None:
    """Parse YAML-like frontmatter from ``---``-delimited block.

    Returns ``(metadata_dict, body)`` or ``None`` if no frontmatter found.
    Only supports simple ``key: value`` pairs (no nesting, no lists).
    Quoted string values have surrounding quotes stripped.
    """
    m = _FRONTMATTER_RE.match(text)
    if m is None:
        return None
    raw_meta, body = m.group(1), m.group(2)
    meta: dict[str, str] = {}
    for kv in _KV_RE.finditer(raw_meta):
        key = kv.group(1)
        val = kv.group(2).strip()
        # Strip surrounding quotes (single or double)
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
            val = val[1:-1]
        meta[key] = val
    return meta, body


# ---------------------------------------------------------------------------
# Skill Definition
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SkillDefinition:
    """Parsed skill ``.md`` file."""

    name: str
    node: str  # "analyst", "evaluator", "synthesizer", "biasbuster"
    type: str  # "game_mechanics", "quality_judge", etc. ("*" = all types)
    priority: int  # lower = higher priority (injected first)
    version: str
    role: str  # "system" or "user" (which prompt to inject into)
    enabled: bool
    prompt_body: str  # Markdown body (frontmatter excluded)
    source_path: Path


# ---------------------------------------------------------------------------
# Skill Registry
# ---------------------------------------------------------------------------


class SkillRegistry:
    """Skill ``.md`` file discovery and management.

    Discovery priority (4-priority pattern from OpenClaw):
      1. Bundled:    .claude/skills/        (project .claude/ directory)
      2. Project:    ./skills/              (project root)
      3. User:       ~/.geode/skills/       (user global)
      4. Extra:      config-specified paths  (CLI --skills-dir)
    """

    def __init__(self, extra_dirs: list[Path] | None = None) -> None:
        self._skills: list[SkillDefinition] = []
        self._extra_dirs: list[Path] = extra_dirs or []

    # -- Public API ---------------------------------------------------------

    def discover(self) -> list[SkillDefinition]:
        """Scan all skill directories and return discovered SkillDefinitions."""
        dirs = self._resolve_skill_dirs()
        skills: list[SkillDefinition] = []
        for d in dirs:
            if not d.is_dir():
                continue
            for md_file in sorted(d.glob("*.md")):
                try:
                    skill = self._parse_skill_file(md_file)
                    if skill and skill.enabled:
                        skills.append(skill)
                except Exception:
                    log.warning("Failed to parse skill file: %s", md_file, exc_info=True)
        self._skills = skills
        return skills

    def get_skills(
        self,
        *,
        node: str,
        role_type: str,
        role: str = "system",
    ) -> list[SkillDefinition]:
        """Return skills matching *node* + *role_type*.

        Skills with ``type: "*"`` match all role_types for their node.
        """
        return [
            s
            for s in self._skills
            if s.node == node and (s.type == role_type or s.type == "*") and s.role == role
        ]

    # -- Internal -----------------------------------------------------------

    def _resolve_skill_dirs(self) -> list[Path]:
        """Return skill directories in 4-priority order."""
        # project root: core/llm/ → core/ → root
        root = Path(__file__).resolve().parent.parent.parent
        dirs: list[Path] = [
            root / ".claude" / "skills",  # 1. Bundled (.claude/skills/)
            Path.cwd() / "skills",  # 2. Project
            Path.home() / ".geode" / "skills",  # 3. User
        ]
        dirs.extend(self._extra_dirs)  # 4. Extra
        return dirs

    @staticmethod
    def _parse_skill_file(path: Path) -> SkillDefinition | None:
        """Parse YAML frontmatter + Markdown body from a skill file."""
        text = path.read_text(encoding="utf-8")

        result = _parse_frontmatter(text)
        if result is None:
            return None

        meta, body = result
        if not meta:
            return None

        body = body.strip()

        # Convert typed values from string representations
        enabled_raw = meta.get("enabled", "true").lower()
        enabled = enabled_raw not in ("false", "0", "no")

        try:
            priority = int(meta.get("priority", "100"))
        except ValueError:
            priority = 100

        return SkillDefinition(
            name=meta.get("name", path.stem),
            node=meta.get("node", ""),
            type=meta.get("type", "*"),
            priority=priority,
            version=str(meta.get("version", "0.1")),
            role=meta.get("role", "system"),
            enabled=enabled,
            prompt_body=body,
            source_path=path,
        )
