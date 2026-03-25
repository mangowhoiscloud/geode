"""Project Memory — markdown-based persistent memory.

Loads .geode/memory/PROJECT.md (project-level context) and .geode/rules/*.md
(modular rules with YAML frontmatter path matching).

Architecture-v6 §3 Layer 2: Project Memory tier.

Directory structure:
    .geode/
    ├── memory/
    │   └── PROJECT.md      # GEODE project memory (first 200 lines → system context)
    └── rules/              # Modular domain rules
        ├── anime-ip.md     # Category-specific rules
        └── ...
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from core.infrastructure.atomic_io import atomic_write_text
from core.skills._frontmatter import _FRONTMATTER_RE

log = logging.getLogger(__name__)

# MEMORY.md max lines loaded into context (SOT: 200)
MAX_MEMORY_LINES = 200

# Maximum insight entries before oldest-drop rotation
MAX_INSIGHTS = 50

# Project-specific path extraction from YAML frontmatter (multi-line list format)
_PATHS_RE = re.compile(r"paths:\s*\n((?:\s*-\s*.+\n)*)", re.MULTILINE)
_PATH_ITEM_RE = re.compile(r'^\s*-\s*["\']?(.+?)["\']?\s*$', re.MULTILINE)


def _extract_paths(frontmatter: str) -> list[str]:
    """Extract paths list from YAML frontmatter (simple parser, no pyyaml dep)."""
    m = _PATHS_RE.search(frontmatter)
    if not m:
        return []
    return _PATH_ITEM_RE.findall(m.group(1))


def _matches_any_pattern(text: str, patterns: list[str]) -> bool:
    """Check if text matches any glob-like pattern (simplified: * = any)."""
    text_lower = text.lower()
    for pattern in patterns:
        # Convert glob to simple substring check
        pattern_lower = pattern.lower().strip("*").strip("/").replace("*", "")
        if pattern_lower and pattern_lower in text_lower:
            return True
    return False


class ProjectMemory:
    """File-based Project Memory — SOUL.md equivalent for GEODE.

    Usage:
        mem = ProjectMemory(Path("."))
        context = mem.load_memory()     # → str (first 200 lines of MEMORY.md)
        rules = mem.load_rules("anime") # → list of matching rule contents
    """

    def __init__(self, project_root: Path | None = None) -> None:
        root = project_root or Path(".")
        self._geode_dir = root / ".geode"
        self._memory_dir = self._geode_dir / "memory"
        self._memory_file = self._memory_dir / "PROJECT.md"
        self._rules_dir = self._geode_dir / "rules"

    @property
    def memory_file(self) -> Path:
        return self._memory_file

    @property
    def rules_dir(self) -> Path:
        return self._rules_dir

    def exists(self) -> bool:
        """Check if MEMORY.md exists."""
        return self._memory_file.exists()

    def load_memory(self, max_lines: int = MAX_MEMORY_LINES) -> str:
        """Load MEMORY.md content (first N lines for context window efficiency)."""
        if not self._memory_file.exists():
            return ""
        try:
            content = self._memory_file.read_text(encoding="utf-8")
            lines = content.split("\n")[:max_lines]
            return "\n".join(lines)
        except OSError as e:
            log.warning("Failed to read MEMORY.md: %s", e)
            return ""

    def load_rules(self, context: str = "*") -> list[dict[str, Any]]:
        """Load matching rules from .geode/rules/*.md.

        Args:
            context: Context string to match against rule paths (e.g. "anime", "berserk").

        Returns:
            List of dicts with 'name', 'paths', 'content' for each matching rule.
        """
        if not self._rules_dir.exists():
            return []

        matched: list[dict[str, Any]] = []
        for rule_file in sorted(self._rules_dir.glob("*.md")):
            try:
                raw = rule_file.read_text(encoding="utf-8")
            except OSError:
                continue

            # Parse YAML frontmatter (canonical regex from _frontmatter.py)
            fm_match = _FRONTMATTER_RE.match(raw)
            if fm_match:
                frontmatter = fm_match.group(1)
                paths = _extract_paths(frontmatter)
                body = fm_match.group(2)
            else:
                paths = []
                body = raw

            # Match against context (or load all if context="*")
            if context == "*" or not paths or _matches_any_pattern(context, paths):
                matched.append(
                    {
                        "name": rule_file.stem,
                        "paths": paths,
                        "content": body.strip(),
                    }
                )

        return matched

    def add_insight(self, insight: str) -> bool:
        """Add an insight to the '## 최근 인사이트' section of MEMORY.md.

        - Dedup: same date + same IP substring → skip (return False)
        - Newest-first: new entry prepended at top of section
        - Rotation: keeps only MAX_INSIGHTS entries, oldest dropped

        Returns True if successfully written, False otherwise.
        """
        if not self._memory_file.exists():
            log.warning("MEMORY.md does not exist — cannot add insight")
            return False

        try:
            content = self._memory_file.read_text(encoding="utf-8")
        except OSError:
            return False

        timestamp = datetime.now().strftime("%Y-%m-%d")
        entry = f"- {timestamp}: {insight}"

        marker = "## 최근 인사이트"

        if marker in content:
            marker_idx = content.index(marker)
            newline_idx = content.find("\n", marker_idx + len(marker))
            if newline_idx == -1:
                # Marker at end of file with no trailing newline
                before = content + "\n"
                after = ""
            else:
                before = content[: newline_idx + 1]
                after = content[newline_idx + 1 :]
        else:
            before = content.rstrip() + f"\n\n{marker}\n"
            after = ""

        # Parse existing insight lines from 'after'
        existing_lines: list[str] = []
        remainder_lines: list[str] = []
        in_insights = True
        for line in after.split("\n"):
            if in_insights and line.startswith("- "):
                existing_lines.append(line)
            elif in_insights and line.strip() == "":
                existing_lines.append(line)  # preserve blank between entries
            else:
                in_insights = False
                remainder_lines.append(line)

        # Strip trailing blank lines from insight block
        while existing_lines and existing_lines[-1].strip() == "":
            existing_lines.pop()

        # Dedup: skip if same date + same IP substring already exists
        # Extract IP token from insight, e.g. "[Berserk]" → "Berserk"
        ip_token = ""
        if insight.startswith("[") and "]" in insight:
            ip_token = insight[1 : insight.index("]")]

        if ip_token:
            for line in existing_lines:
                if timestamp in line and f"[{ip_token}]" in line:
                    log.debug("Dedup: insight for [%s] on %s already exists", ip_token, timestamp)
                    return False

        # Prepend new entry (newest-first)
        existing_lines.insert(0, entry)

        # Rotation: keep only MAX_INSIGHTS entries
        insight_entries = [ln for ln in existing_lines if ln.startswith("- ")]
        if len(insight_entries) > MAX_INSIGHTS:
            # Keep first MAX_INSIGHTS entries, drop oldest (at the end)
            keep_count = MAX_INSIGHTS
            kept = 0
            trimmed: list[str] = []
            for ln in existing_lines:
                if ln.startswith("- "):
                    if kept < keep_count:
                        trimmed.append(ln)
                        kept += 1
                    # else: drop (oldest)
                else:
                    trimmed.append(ln)
            existing_lines = trimmed

        # Reassemble
        insight_block = "\n".join(existing_lines)
        remainder = "\n".join(remainder_lines)
        content = before + insight_block + "\n" + remainder

        try:
            atomic_write_text(self._memory_file, content)
            log.info("Added insight to MEMORY.md: %s", insight)
            return True
        except OSError as e:
            log.warning("Failed to write MEMORY.md: %s", e)
            return False

    # ------------------------------------------------------------------
    # Rule CRUD (P0-B: agent-driven rule management)
    # ------------------------------------------------------------------

    def create_rule(self, name: str, paths: list[str], content: str) -> bool:
        """Create a new rule file in .geode/rules/.

        Args:
            name: Rule name (used as filename, e.g. 'dark-fantasy').
            paths: Glob patterns for IP matching (e.g. ['*berserk*', '*dark*']).
            content: Rule body in markdown.

        Returns True if created, False if already exists or write failed.
        """
        self._rules_dir.mkdir(parents=True, exist_ok=True)
        safe_name = re.sub(r"[^\w\-]", "-", name.lower().strip())
        rule_path = self._rules_dir / f"{safe_name}.md"

        if rule_path.exists():
            log.warning("Rule '%s' already exists — use update_rule()", safe_name)
            return False

        paths_yaml = "\n".join(f'  - "{p}"' for p in paths)
        frontmatter = f"---\nname: {safe_name}\npaths:\n{paths_yaml}\n---\n\n"
        try:
            atomic_write_text(rule_path, frontmatter + content)
            log.info("Created rule: %s", rule_path)
            return True
        except OSError as e:
            log.warning("Failed to create rule '%s': %s", safe_name, e)
            return False

    def update_rule(self, name: str, content: str) -> bool:
        """Update an existing rule's content (preserves frontmatter).

        Returns True if updated, False if not found or write failed.
        """
        safe_name = re.sub(r"[^\w\-]", "-", name.lower().strip())
        rule_path = self._rules_dir / f"{safe_name}.md"

        if not rule_path.exists():
            log.warning("Rule '%s' not found — use create_rule()", safe_name)
            return False

        try:
            raw = rule_path.read_text(encoding="utf-8")
        except OSError:
            return False

        fm_match = _FRONTMATTER_RE.match(raw)
        frontmatter_block = raw[: fm_match.start(2)] if fm_match else ""

        try:
            atomic_write_text(rule_path, frontmatter_block + content)
            log.info("Updated rule: %s", rule_path)
            return True
        except OSError as e:
            log.warning("Failed to update rule '%s': %s", safe_name, e)
            return False

    def delete_rule(self, name: str) -> bool:
        """Delete a rule file. Returns True if deleted, False if not found."""
        safe_name = re.sub(r"[^\w\-]", "-", name.lower().strip())
        rule_path = self._rules_dir / f"{safe_name}.md"

        if not rule_path.exists():
            return False

        try:
            rule_path.unlink()
            log.info("Deleted rule: %s", safe_name)
            return True
        except OSError as e:
            log.warning("Failed to delete rule '%s': %s", safe_name, e)
            return False

    def list_rules(self) -> list[dict[str, Any]]:
        """List all rules with name, paths, and content preview."""
        if not self._rules_dir.exists():
            return []

        rules: list[dict[str, Any]] = []
        for rule_file in sorted(self._rules_dir.glob("*.md")):
            try:
                raw = rule_file.read_text(encoding="utf-8")
            except OSError:
                continue

            fm_match = _FRONTMATTER_RE.match(raw)
            paths: list[str] = []
            if fm_match:
                paths = _extract_paths(fm_match.group(1))
                body = fm_match.group(2).strip()
            else:
                body = raw.strip()

            rules.append(
                {
                    "name": rule_file.stem,
                    "paths": paths,
                    "preview": body[:200] + ("..." if len(body) > 200 else ""),
                }
            )
        return rules

    def get_context_for_ip(self, ip_name: str) -> dict[str, Any]:
        """Get combined memory + rules context for a specific IP.

        Returns dict with 'memory' (str) and 'rules' (list) keys.
        """
        return {
            "memory": self.load_memory(),
            "rules": self.load_rules(ip_name),
        }

    def ensure_structure(self) -> bool:
        """Create .geode/memory/PROJECT.md and .geode/rules/ if they don't exist.

        Returns True if created, False if already existed.
        """
        if self._memory_file.exists():
            return False

        self._memory_dir.mkdir(parents=True, exist_ok=True)
        self._rules_dir.mkdir(parents=True, exist_ok=True)

        default_memory = """\
# Project Memory

## Overview
- Type: (auto-detected by `geode init`)
- Commands: see `.geode/config.toml` [commands] section

## Rules
- .geode/rules/ 디렉토리의 .md 파일이 자동 로딩됩니다

## Recent Insights
"""
        atomic_write_text(self._memory_file, default_memory)

        log.info("Created .geode/memory/PROJECT.md and .geode/rules/ structure")
        return True
