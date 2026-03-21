"""User Profile — file-based persistent user profile (Tier 0.5).

Between SOUL identity (Tier 0) and Organization memory (Tier 1),
the User Profile stores personal preferences, role, expertise,
and auto-learned patterns across sessions.

Storage locations:
  Global:  ~/.geode/user_profile/
  Project: .geode/user_profile/ (overrides global)

Files:
  profile.md        — Core identity (YAML frontmatter + markdown body)
  learned.md        — Auto-learned patterns (dedup + max 100 rotation)
  preferences.json  — Structured key-value preferences
"""

from __future__ import annotations

import json
import logging
import re
import tomllib
from datetime import datetime
from pathlib import Path
from typing import Any

from core.infrastructure.atomic_io import atomic_write_text

log = logging.getLogger(__name__)

# Maximum learned patterns before oldest-drop rotation
MAX_LEARNED_PATTERNS = 100

# YAML frontmatter regex (same as project.py)
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)

_DEFAULT_CAREER_TOML = """\
# Career Identity — GEODE reads this to personalize agent behavior.
# Edit freely; the agent never writes to this file.

[identity]
title = ""           # e.g. "Senior AI Engineer"
years_experience = 0
skills = []          # e.g. ["Python", "ML", "LangGraph"]
industries = []      # e.g. ["Gaming", "AI/ML"]

[goals]
short_term = ""      # 3-6 month goal
long_term = ""       # 1-3 year goal

[preferences]
job_type = ""        # "full-time" | "contract" | "freelance"
remote = ""          # "remote" | "hybrid" | "onsite"
location = ""        # e.g. "Seoul, KR"
"""


def _parse_yaml_frontmatter(text: str) -> dict[str, str]:
    """Parse simple YAML frontmatter into key-value dict (no pyyaml dep)."""
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}
    result: dict[str, str] = {}
    for line in m.group(1).split("\n"):
        line = line.strip()
        if ":" in line and not line.startswith("#"):
            key, _, value = line.partition(":")
            result[key.strip()] = value.strip().strip('"').strip("'")
    return result


def _build_yaml_frontmatter(data: dict[str, str]) -> str:
    """Build YAML frontmatter from key-value dict."""
    lines = ["---"]
    for key, value in data.items():
        lines.append(f"{key}: {value}")
    lines.append("---")
    return "\n".join(lines) + "\n"


class FileBasedUserProfile:
    """File-based User Profile adapter.

    Implements Tier 0.5 user profile storage with global + project-local layers.
    Project-local values override global values.

    Usage:
        profile = FileBasedUserProfile()
        profile.load_profile()  # loads ~/.geode/user_profile/ + .geode/user_profile/
        profile.set_preference("language", "ko")
        profile.add_learned_pattern("User prefers dark fantasy IPs", "domain")
    """

    def __init__(
        self,
        global_dir: Path | None = None,
        project_dir: Path | None = None,
    ) -> None:
        self._global_dir = global_dir or (Path.home() / ".geode" / "user_profile")
        self._project_dir = project_dir  # None = no project-local override

    @property
    def global_dir(self) -> Path:
        return self._global_dir

    @property
    def project_dir(self) -> Path | None:
        return self._project_dir

    def exists(self) -> bool:
        """Check if any profile data exists (global or project)."""
        global_exists = (self._global_dir / "profile.md").exists()
        project_exists = (
            self._project_dir is not None and (self._project_dir / "profile.md").exists()
        )
        return global_exists or project_exists

    def load_profile(self) -> dict[str, Any]:
        """Load merged profile from global + project-local.

        Returns dict with 'role', 'expertise', 'bio', 'preferences', 'learned_patterns'.
        """
        # Start with global
        profile = self._load_profile_from_dir(self._global_dir)

        # Override with project-local if present
        if self._project_dir is not None:
            project_profile = self._load_profile_from_dir(self._project_dir)
            if project_profile:
                # Merge: project overrides global for non-empty values
                for key, value in project_profile.items():
                    if value:  # Only override with non-empty
                        if key == "preferences" and isinstance(value, dict):
                            profile.setdefault("preferences", {}).update(value)
                        elif key == "learned_patterns" and isinstance(value, list):
                            # Combine patterns, dedup
                            existing = set(profile.get("learned_patterns", []))
                            for p in value:
                                existing.add(p)
                            profile["learned_patterns"] = list(existing)
                        else:
                            profile[key] = value

        return profile

    def save_profile(self, data: dict[str, Any]) -> bool:
        """Save profile data to global directory.

        Args:
            data: Dict with optional keys: role, expertise, bio.

        Returns True on success.
        """
        self._global_dir.mkdir(parents=True, exist_ok=True)

        # Build frontmatter from structured fields
        fm_data: dict[str, str] = {}
        for key in ("role", "expertise", "name", "team"):
            if data.get(key):
                fm_data[key] = str(data[key])

        body = data.get("bio", "")
        content = _build_yaml_frontmatter(fm_data) + "\n" + body if fm_data else body

        try:
            atomic_write_text(self._global_dir / "profile.md", content)
            log.info("Saved user profile to %s", self._global_dir / "profile.md")
            return True
        except OSError as e:
            log.warning("Failed to save profile: %s", e)
            return False

    def get_preference(self, key: str, default: Any = None) -> Any:
        """Get a single preference value."""
        prefs = self._load_preferences(self._global_dir)
        if self._project_dir is not None:
            project_prefs = self._load_preferences(self._project_dir)
            prefs.update(project_prefs)
        return prefs.get(key, default)

    def set_preference(self, key: str, value: Any) -> bool:
        """Set a preference in global preferences.json."""
        self._global_dir.mkdir(parents=True, exist_ok=True)
        prefs = self._load_preferences(self._global_dir)
        prefs[key] = value
        return self._save_preferences(self._global_dir, prefs)

    def add_learned_pattern(self, pattern: str, category: str = "general") -> bool:
        """Add a learned pattern to learned.md.

        Dedup by content, newest-first, max MAX_LEARNED_PATTERNS entries.
        Returns True on success, False on dedup or write failure.
        """
        self._global_dir.mkdir(parents=True, exist_ok=True)
        learned_path = self._global_dir / "learned.md"

        # Load existing patterns
        existing: list[str] = []
        if learned_path.exists():
            try:
                content = learned_path.read_text(encoding="utf-8")
                existing = self._parse_learned_entries(content)
            except OSError:
                pass

        # Dedup: skip if pattern already exists (case-insensitive)
        pattern_lower = pattern.lower()
        for entry in existing:
            # Extract the pattern text (after timestamp and category)
            entry_text = entry.split("] ", 1)[-1] if "] " in entry else entry
            if pattern_lower in entry_text.lower():
                log.debug("Dedup: pattern already exists: %s", pattern[:50])
                return False

        # Build timestamped entry
        timestamp = datetime.now().strftime("%Y-%m-%d")
        entry = f"- [{timestamp}] [{category}] {pattern}"

        # Prepend (newest-first)
        existing.insert(0, entry)

        # Rotation: keep only MAX_LEARNED_PATTERNS
        if len(existing) > MAX_LEARNED_PATTERNS:
            existing = existing[:MAX_LEARNED_PATTERNS]

        # Write
        header = "# Learned Patterns\n\n"
        try:
            atomic_write_text(learned_path, header + "\n".join(existing) + "\n")
            log.info("Added learned pattern: %s", pattern[:80])
            return True
        except OSError as e:
            log.warning("Failed to write learned.md: %s", e)
            return False

    def get_learned_patterns(self, category: str | None = None) -> list[str]:
        """Get learned patterns, optionally filtered by category."""
        patterns: list[str] = []

        for directory in [self._global_dir, self._project_dir]:
            if directory is None:
                continue
            learned_path = directory / "learned.md"
            if not learned_path.exists():
                continue
            try:
                content = learned_path.read_text(encoding="utf-8")
                entries = self._parse_learned_entries(content)
                patterns.extend(entries)
            except OSError:
                continue

        # Dedup by content
        seen: set[str] = set()
        unique: list[str] = []
        for p in patterns:
            if p not in seen:
                seen.add(p)
                unique.append(p)

        if category is not None:
            unique = [p for p in unique if f"[{category}]" in p]

        return unique

    def load_career(self) -> dict[str, Any]:
        """Load career.toml from global profile directory.

        Returns parsed TOML data as dict, or empty dict if not found / invalid.
        The file is user-edited; the agent only reads.
        """
        career_path = self._global_dir / "career.toml"
        if not career_path.exists():
            return {}
        try:
            with open(career_path, "rb") as f:
                return dict(tomllib.load(f))
        except (tomllib.TOMLDecodeError, OSError) as e:
            log.warning("Failed to load career.toml: %s", e)
            return {}

    def get_context_summary(self) -> str:
        """Build a concise summary for LLM context injection.

        Returns a string like:
            "User: AI Engineer | Expertise: ML, LLM | Lang: ko | Title: Sr Engineer"
        """
        profile = self.load_profile()
        parts: list[str] = []

        role = profile.get("role", "")
        if role:
            parts.append(f"User: {role}")

        expertise = profile.get("expertise", "")
        if expertise:
            parts.append(f"Expertise: {expertise}")

        prefs = profile.get("preferences", {})
        lang = prefs.get("language", "")
        if lang:
            parts.append(f"Lang: {lang}")

        output_format = prefs.get("output_format", "")
        if output_format:
            parts.append(f"Format: {output_format}")

        # Career identity enrichment
        career = self.load_career()
        if career:
            title = career.get("identity", {}).get("title", "")
            if title:
                parts.append(f"Title: {title}")
            skills = career.get("identity", {}).get("skills", [])
            if skills:
                parts.append(f"Skills: {', '.join(skills[:5])}")

        return " | ".join(parts)

    def ensure_structure(self) -> bool:
        """Create global profile directory with defaults if not exists.

        Returns True if created, False if already existed.
        """
        if (self._global_dir / "profile.md").exists():
            return False

        self._global_dir.mkdir(parents=True, exist_ok=True)

        default_profile = """\
---
role: ""
expertise: ""
name: ""
team: ""
---

# User Profile

Write your bio, background, or any context you want GEODE to remember here.
"""
        atomic_write_text(self._global_dir / "profile.md", default_profile)

        default_prefs: dict[str, Any] = {
            "language": "",
            "output_format": "concise",
            "domains_of_interest": [],
        }
        self._save_preferences(self._global_dir, default_prefs)

        # Empty learned.md
        atomic_write_text(self._global_dir / "learned.md", "# Learned Patterns\n\n")

        # Career identity template (user-edited, agent reads only)
        career_path = self._global_dir / "career.toml"
        if not career_path.exists():
            atomic_write_text(
                career_path,
                _DEFAULT_CAREER_TOML,
            )

        log.info("Created user profile structure at %s", self._global_dir)
        return True

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_profile_from_dir(self, directory: Path) -> dict[str, Any]:
        """Load profile data from a single directory."""
        result: dict[str, Any] = {}
        profile_path = directory / "profile.md"

        if profile_path.exists():
            try:
                raw = profile_path.read_text(encoding="utf-8")
                # Parse frontmatter
                fm = _parse_yaml_frontmatter(raw)
                result.update(fm)

                # Extract body (after frontmatter)
                fm_match = _FRONTMATTER_RE.match(raw)
                if fm_match:
                    result["bio"] = raw[fm_match.end() :].strip()
                else:
                    result["bio"] = raw.strip()
            except OSError:
                pass

        # Load preferences
        prefs = self._load_preferences(directory)
        if prefs:
            result["preferences"] = prefs

        # Load learned patterns
        patterns = self._load_learned_from_dir(directory)
        if patterns:
            result["learned_patterns"] = patterns

        return result

    def _load_preferences(self, directory: Path) -> dict[str, Any]:
        """Load preferences.json from a directory."""
        prefs_path = directory / "preferences.json"
        if not prefs_path.exists():
            return {}
        try:
            raw = prefs_path.read_text(encoding="utf-8")
            return json.loads(raw)  # type: ignore[no-any-return]
        except (json.JSONDecodeError, OSError) as e:
            log.warning("Failed to load preferences from %s: %s", prefs_path, e)
            return {}

    def _save_preferences(self, directory: Path, prefs: dict[str, Any]) -> bool:
        """Save preferences.json to a directory."""
        directory.mkdir(parents=True, exist_ok=True)
        prefs_path = directory / "preferences.json"
        try:
            atomic_write_text(
                prefs_path,
                json.dumps(prefs, ensure_ascii=False, indent=2) + "\n",
            )
            return True
        except (TypeError, ValueError, OSError) as e:
            log.warning("Failed to save preferences: %s", e)
            return False

    def _load_learned_from_dir(self, directory: Path) -> list[str]:
        """Load learned patterns from learned.md in a directory."""
        learned_path = directory / "learned.md"
        if not learned_path.exists():
            return []
        try:
            content = learned_path.read_text(encoding="utf-8")
            return self._parse_learned_entries(content)
        except OSError:
            return []

    @staticmethod
    def _parse_learned_entries(content: str) -> list[str]:
        """Parse learned.md content into list of entry lines."""
        entries: list[str] = []
        for line in content.split("\n"):
            line = line.strip()
            if line.startswith("- "):
                entries.append(line)
        return entries
