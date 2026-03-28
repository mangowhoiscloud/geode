"""Skill System v2 — Agent Skills spec-aligned runtime skill engine.

Implements 3-tier Progressive Disclosure, multi-scope discovery,
dynamic context injection (!`cmd`), $ARGUMENTS substitution,
context:fork subagent execution, and user-invocable control.

Storage: .geode/skills/<name>/SKILL.md (project) + ~/.geode/skills/ (global)
"""

from __future__ import annotations

import logging
import re
import subprocess  # nosec B404 — skill dynamic context requires shell execution
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from core.skills._frontmatter import parse_yaml_frontmatter

log = logging.getLogger(__name__)

_PACKAGE_ROOT = Path(__file__).resolve().parent.parent.parent

_TRIGGER_RE = re.compile(r'"([^"]+)"(?:\s*,\s*"([^"]+)")*\s*키워드로\s*트리거')
_DYNAMIC_CMD_RE = re.compile(r"!`([^`]+)`")


def _extract_triggers(description: str) -> list[str]:
    """Extract trigger keywords from description text."""
    match = _TRIGGER_RE.search(description)
    if not match:
        return []
    region = description[match.start() : match.end()]
    return re.findall(r'"([^"]+)"', region)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class SkillDefinition(BaseModel):
    """Skill definition loaded from SKILL.md (Agent Skills spec + extensions)."""

    name: str
    description: str = ""
    triggers: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    body: str = ""  # Tier 2: loaded on invoke (empty at startup in lazy mode)
    source: str = ""
    risk: str = "safe"
    # --- Skill 2.0 fields (Agent Skills spec extensions) ---
    user_invocable: bool = True  # False = background knowledge, hidden from /skills
    context_fork: bool = False  # True = run in isolated subagent
    argument_hint: str = ""  # autocomplete hint, e.g. "[issue-number]"
    source_path: Path | None = None  # path to SKILL.md for lazy body loading

    model_config = {"arbitrary_types_allowed": True}

    def summary(self, max_len: int = 80) -> str:
        """One-line summary: name + truncated description."""
        desc = self.description
        if len(desc) > max_len:
            desc = desc[: max_len - 3] + "..."
        return f"{self.name}: {desc}"

    def load_body(self) -> str:
        """Tier 2: load full body from disk (lazy loading)."""
        if self.body:
            return self.body
        if self.source_path and self.source_path.exists():
            text = self.source_path.read_text(encoding="utf-8")
            _, body = parse_yaml_frontmatter(text)
            self.body = body.strip()
        return self.body

    def render(self, arguments: str = "") -> str:
        """Render skill body with dynamic context and argument substitution.

        - ``!`command` `` → replaced with command stdout
        - ``$ARGUMENTS`` → replaced with arguments string
        - ``$0``, ``$1``, ... → replaced with positional arguments
        """
        body = self.load_body()
        if not body:
            return ""

        # Dynamic context: !`cmd` → stdout
        def _exec_cmd(match: re.Match[str]) -> str:
            cmd = match.group(1)
            try:
                result = subprocess.run(  # noqa: S602  # nosec B602
                    cmd,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                return result.stdout.strip()[:2000]
            except Exception as exc:
                return f"(error: {exc})"

        rendered = _DYNAMIC_CMD_RE.sub(_exec_cmd, body)

        # $ARGUMENTS substitution
        if arguments:
            rendered = rendered.replace("$ARGUMENTS", arguments)
            parts = arguments.split()
            for i, part in enumerate(parts[:10]):
                rendered = rendered.replace(f"${i}", part)

        return rendered


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class SkillRegistry:
    """In-memory registry for loaded skill definitions.

    Supports Progressive Disclosure: stores metadata at startup,
    defers body loading to invoke time via skill.load_body().
    """

    def __init__(self) -> None:
        self._skills: dict[str, SkillDefinition] = {}

    def register(self, skill: SkillDefinition) -> None:
        """Register a skill. Overwrites if name already exists."""
        self._skills[skill.name] = skill

    def get(self, name: str) -> SkillDefinition | None:
        """Get a skill by name."""
        return self._skills.get(name)

    def list_skills(self) -> list[str]:
        """List all registered skill names (user-invocable only)."""
        return sorted(
            name for name, s in self._skills.items() if s.user_invocable
        )

    def list_all(self) -> list[str]:
        """List all skill names including background knowledge."""
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
        """Tier 1: Format skill metadata for system prompt.

        Only name + description (not body). Progressive Disclosure:
        body is loaded on-demand when skill is invoked.
        """
        if not self._skills:
            return ""

        lines: list[str] = []
        total = 0
        for skill in sorted(self._skills.values(), key=lambda s: s.name):
            line = f"- **{skill.name}**: {skill.description[:200]}"
            if skill.tools:
                line += f" (tools: {', '.join(skill.tools)})"
            if skill.context_fork:
                line += " [fork]"
            if not skill.user_invocable:
                line += " [background]"
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
# Loader (multi-scope discovery)
# ---------------------------------------------------------------------------


class SkillLoader:
    """Load skill definitions from SKILL.md files across multiple scopes.

    Discovery priority (low → high, later overrides):
      1. Bundled (GEODE package .geode/skills/)
      2. Global user (~/.geode/skills/)
      3. Project local (CWD/.geode/skills/)
      4. Extra dirs (explicit)
    """

    def __init__(
        self,
        skills_dir: str | Path | None = None,
        extra_dirs: list[Path] | None = None,
        lazy: bool = True,
    ) -> None:
        self._primary_dir = Path(skills_dir) if skills_dir else None
        self._extra_dirs = extra_dirs or []
        self._lazy = lazy  # True = load metadata only, defer body

    @property
    def skills_dir(self) -> Path:
        """Primary skills directory (first non-empty scope)."""
        if self._primary_dir:
            return self._primary_dir
        return _PACKAGE_ROOT / ".geode" / "skills"

    def _resolve_skill_dirs(self) -> list[Path]:
        """Return skill directories in priority order (low → high)."""
        if self._primary_dir:
            return [self._primary_dir, *self._extra_dirs]

        cwd = Path.cwd()
        dirs: list[Path] = [
            _PACKAGE_ROOT / ".geode" / "skills",  # 1. Bundled
            Path.home() / ".geode" / "skills",  # 2. User global
            cwd / ".geode" / "skills",  # 3. Project local (CWD)
        ]
        dirs.extend(self._extra_dirs)  # 4. Extra
        return dirs

    def discover(self) -> list[Path]:
        """Find all SKILL.md files across all scopes."""
        seen_names: dict[str, Path] = {}
        for d in self._resolve_skill_dirs():
            if not d.exists():
                continue
            for path in sorted(d.glob("*/SKILL.md")):
                name = path.parent.name
                seen_names[name] = path  # later scope overrides
        return list(seen_names.values())

    def load_file(self, path: Path) -> SkillDefinition:
        """Load a single skill definition from a SKILL.md file."""
        if not path.exists():
            raise FileNotFoundError(f"Skill file not found: {path}")

        text = path.read_text(encoding="utf-8")
        metadata, body = parse_yaml_frontmatter(text)

        name = metadata.get("name", "") or path.parent.name
        description = metadata.get("description", "")
        triggers = _extract_triggers(description)

        tools_raw: Any = metadata.get("tools", [])
        if isinstance(tools_raw, str):
            tools = [t.strip() for t in tools_raw.split(",")]
        else:
            tools = list(tools_raw)

        # Skill 2.0 fields
        user_invocable = metadata.get("user-invocable", True)
        if isinstance(user_invocable, str):
            user_invocable = user_invocable.lower() not in ("false", "no", "0")
        context_fork = metadata.get("context", "") == "fork"
        argument_hint = metadata.get("argument-hint", "")

        return SkillDefinition(
            name=name,
            description=description,
            triggers=triggers,
            tools=tools,
            body="" if self._lazy else body.strip(),
            source=metadata.get("source", ""),
            risk=metadata.get("risk", "safe"),
            user_invocable=bool(user_invocable),
            context_fork=context_fork,
            argument_hint=argument_hint,
            source_path=path,
        )

    def load_all(self, registry: SkillRegistry | None = None) -> list[SkillDefinition]:
        """Discover and load all skill definitions across all scopes.

        If a registry is provided, skills are automatically registered.
        """
        skills: list[SkillDefinition] = []
        for path in self.discover():
            try:
                skill = self.load_file(path)
                skills.append(skill)
                if registry is not None:
                    registry.register(skill)
                log.debug(
                    "Loaded skill: %s (invocable=%s, fork=%s)",
                    skill.name, skill.user_invocable, skill.context_fork,
                )
            except Exception:
                log.warning("Failed to load skill from %s", path, exc_info=True)
        return skills
