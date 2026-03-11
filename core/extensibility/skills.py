"""Skill System — load skill definitions from .claude/skills/*/SKILL.md.

Layer 5 extensibility component for defining domain-specific knowledge
and tools that can be injected into the system prompt at runtime.
Mirrors the SubagentLoader + AgentRegistry pattern from agents.py.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from core.extensibility._frontmatter import parse_yaml_frontmatter

log = logging.getLogger(__name__)

# Regex to extract trigger keywords from description's last segment
# Pattern: "keyword1", "keyword2" 키워드로 트리거
_TRIGGER_RE = re.compile(r'"([^"]+)"(?:\s*,\s*"([^"]+)")*\s*키워드로\s*트리거')


def _extract_triggers(description: str) -> list[str]:
    """Extract trigger keywords from description text.

    Looks for pattern: "kw1", "kw2", ... 키워드로 트리거.
    """
    # Find all quoted strings before "키워드로 트리거"
    match = _TRIGGER_RE.search(description)
    if not match:
        return []
    # Re-extract all quoted strings from the matched region
    region = description[match.start() : match.end()]
    return re.findall(r'"([^"]+)"', region)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class SkillDefinition(BaseModel):
    """Definition of a loadable skill from SKILL.md."""

    name: str
    description: str = ""
    triggers: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    body: str = ""
    source: str = ""
    risk: str = "safe"

    def summary(self, max_len: int = 80) -> str:
        """One-line summary: name + truncated description."""
        desc = self.description
        if len(desc) > max_len:
            desc = desc[: max_len - 3] + "..."
        return f"{self.name}: {desc}"


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class SkillRegistry:
    """In-memory registry for loaded skill definitions."""

    def __init__(self) -> None:
        self._skills: dict[str, SkillDefinition] = {}

    def register(self, skill: SkillDefinition) -> None:
        """Register a skill. Overwrites if name already exists."""
        self._skills[skill.name] = skill

    def get(self, name: str) -> SkillDefinition | None:
        """Get a skill by name."""
        return self._skills.get(name)

    def list_skills(self) -> list[str]:
        """List all registered skill names."""
        return sorted(self._skills.keys())

    def find_by_trigger(self, text: str) -> list[SkillDefinition]:
        """Find skills whose triggers match any word in the given text."""
        text_lower = text.lower()
        matches: list[SkillDefinition] = []
        for skill in self._skills.values():
            for trigger in skill.triggers:
                if trigger.lower() in text_lower:
                    matches.append(skill)
                    break
        return matches

    def get_context_block(self, max_chars: int = 8000) -> str:
        """Format all skills as a context block for system prompt injection."""
        if not self._skills:
            return ""

        lines: list[str] = []
        total = 0
        for skill in sorted(self._skills.values(), key=lambda s: s.name):
            line = f"- **{skill.name}**: {skill.description}"
            if skill.tools:
                line += f" (tools: {', '.join(skill.tools)})"
            if total + len(line) > max_chars:
                lines.append(f"- ... and {len(self._skills) - len(lines)} more skills")
                break
            lines.append(line)
            total += len(line)

        return "\n".join(lines)

    def __len__(self) -> int:
        return len(self._skills)

    def __contains__(self, name: str) -> bool:
        return name in self._skills


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


class SkillLoader:
    """Load skill definitions from .claude/skills/*/SKILL.md files."""

    def __init__(self, skills_dir: str | Path | None = None) -> None:
        if skills_dir is not None:
            self._skills_dir = Path(skills_dir)
        else:
            self._skills_dir = Path(".claude/skills")

    @property
    def skills_dir(self) -> Path:
        """Directory where skill definitions are stored."""
        return self._skills_dir

    def discover(self) -> list[Path]:
        """Find all SKILL.md files in subdirectories."""
        if not self._skills_dir.exists():
            return []
        return sorted(self._skills_dir.glob("*/SKILL.md"))

    def load_file(self, path: Path) -> SkillDefinition:
        """Load a single skill definition from a SKILL.md file."""
        if not path.exists():
            raise FileNotFoundError(f"Skill file not found: {path}")

        text = path.read_text(encoding="utf-8")
        metadata, body = parse_yaml_frontmatter(text)

        name = metadata.get("name", "")
        if not name:
            # Fall back to parent directory name
            name = path.parent.name

        description = metadata.get("description", "")

        # Extract triggers from description
        triggers = _extract_triggers(description)

        tools_raw: Any = metadata.get("tools", [])
        if isinstance(tools_raw, str):
            tools = [t.strip() for t in tools_raw.split(",")]
        else:
            tools = list(tools_raw)

        source = metadata.get("source", "")
        risk = metadata.get("risk", "safe")

        return SkillDefinition(
            name=name,
            description=description,
            triggers=triggers,
            tools=tools,
            body=body.strip(),
            source=source,
            risk=risk,
        )

    def load_all(self, registry: SkillRegistry | None = None) -> list[SkillDefinition]:
        """Discover and load all skill definitions.

        If a registry is provided, skills are automatically registered.
        """
        skills: list[SkillDefinition] = []
        for path in self.discover():
            try:
                skill = self.load_file(path)
                skills.append(skill)
                if registry is not None:
                    registry.register(skill)
                log.debug("Loaded skill: %s", skill.name)
            except Exception:
                log.warning("Failed to load skill from %s", path, exc_info=True)
        return skills
