"""Project Memory — markdown-based persistent memory.

Loads .geode/memory/PROJECT.md (project-level context) and .geode/rules/*.md
(modular rules with YAML frontmatter path matching).

Architecture-v6 §3 Layer 2: Project Memory tier.

Directory structure:
    .geode/
    ├── memory/
    │   └── PROJECT.md      # GEODE project memory (first 200 lines → system context)
    └── rules/              # Modular project rules
        ├── research.md     # Category-specific rules
        └── ...
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from core.memory.atomic_write import atomic_write_text, exclusive_file_lock
from core.skills._frontmatter import _FRONTMATTER_RE

log = logging.getLogger(__name__)

_LOCK_FILENAME = ".memory.lock"
_MAX_RULE_NAME = 64


class MemoryWrite(StrEnum):
    """Outcome of one ProjectMemory mutation; only ``APPLIED`` changed a file."""

    APPLIED = "applied"
    UNCHANGED = "unchanged"  # idempotent: the same insight is already recorded
    NOT_FOUND = "not_found"  # PROJECT.md or the named rule does not exist
    CONFLICT = "conflict"  # create of a rule that already exists
    INVALID = "invalid"  # rejected input, unsafe name, or symlinked/escaping target
    FAILED = "failed"  # existing content unreadable, lock timeout, or write error


class _OutsideTierError(Exception):
    """The project memory tier is a symlink or resolves outside the project."""


class _UnreadableError(Exception):
    """An existing file could not be read; it must be left byte-identical."""


def _contained(path: Path, root: Path) -> bool:
    """True when *path* is a non-symlink whose parent resolves under *root*."""
    if path.is_symlink():
        return False
    try:
        return path.parent.resolve().is_relative_to(root.resolve())
    except OSError:
        return False


def _read_text(path: Path, root: Path) -> str | None:
    """Read a tier file without following a symlink out of its tier.

    Returns None when the file is absent; raises :class:`_UnreadableError` when it
    exists but is a symlink, escapes *root*, or cannot be read or decoded.
    """
    if not path.exists() and not path.is_symlink():
        return None
    if not _contained(path, root):
        raise _UnreadableError(f"{path} is a symlink or outside {root}")
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, encoding="utf-8") as handle:
            return handle.read()
    except (OSError, UnicodeDecodeError) as exc:
        raise _UnreadableError(f"{path}: {exc}") from exc


def _safe_rule_name(name: str) -> str | None:
    """Filesystem-safe rule stem, or None when nothing meaningful remains."""
    safe_name = re.sub(r"[^\w\-]", "-", name.lower().strip())
    if not safe_name.strip("-") or len(safe_name) > _MAX_RULE_NAME:
        return None
    return safe_name


# MEMORY.md max lines loaded into context (SOT: 200)
MAX_MEMORY_LINES = 200

# Maximum insight entries before oldest-drop rotation
MAX_INSIGHTS = 50

# Project-specific path extraction from YAML frontmatter (multi-line list format)
_PATHS_RE = re.compile(r"paths:\s*\n((?:\s*-\s*.+\n)*)", re.MULTILINE)
_PATH_ITEM_RE = re.compile(r'^\s*-\s*["\']?(.+?)["\']?\s*$', re.MULTILINE)

# --- Insight content quality gate (Claude Code validation-pyramid pattern) ---
MAX_INSIGHT_LENGTH = 500  # chars; longer content → journal, not insights
MIN_INSIGHT_LENGTH = 10  # chars; reject pure whitespace / stubs

_REJECT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"tier=\?"),  # pipeline stub: missing tier
    re.compile(r"score=0\.00\b"),  # pipeline stub: zero score
    re.compile(r"tools=\[[\s,]*\]"),  # empty tool arrays in turn records
]


def _is_valid_insight(insight: str) -> bool:
    """Content quality gate — reject known-bad patterns before disk write.

    Returns True if the insight is acceptable, False if it should be rejected.
    """
    stripped = insight.strip()

    if len(stripped) < MIN_INSIGHT_LENGTH:
        log.debug("Insight rejected (too short, %d chars): %s", len(stripped), stripped[:50])
        return False

    if "\n" in stripped:
        log.debug("Insight rejected (multi-line): %s", stripped[:80])
        return False

    if len(stripped) > MAX_INSIGHT_LENGTH:
        log.debug("Insight rejected (too long, %d chars): %s", len(stripped), stripped[:80])
        return False

    if stripped.startswith("[unknown]"):
        log.debug("Insight rejected (unknown subject): %s", stripped[:80])
        return False

    for pattern in _REJECT_PATTERNS:
        if pattern.search(stripped):
            log.debug("Insight rejected (pattern %s): %s", pattern.pattern, stripped[:80])
            return False

    return True


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
        # P2 (v0.95.x) — `Path` division joins relative `PROJECT_GEODE_DIR` to
        # the caller-supplied root, replacing the previous literal
        # `root / ".geode"` while still respecting the test-supplied root.
        # `GEODE_HOME` is the SoT for the user-home tier.
        from core.paths import GEODE_HOME, PROJECT_GEODE_DIR

        # Resolved once so a later chdir cannot redirect reads or writes.
        root = (project_root or Path(".")).resolve()
        self._root = root
        self._geode_dir = root / PROJECT_GEODE_DIR
        self._global_geode_dir = GEODE_HOME
        self._memory_dir = self._geode_dir / "memory"
        self._memory_file = self._memory_dir / "PROJECT.md"
        self._rules_dir = self._geode_dir / "rules"
        # Global fallback dirs
        self._global_memory_dir = self._global_geode_dir / "memory"
        self._global_rules_dir = self._global_geode_dir / "rules"

    @property
    def memory_file(self) -> Path:
        return self._memory_file

    @property
    def rules_dir(self) -> Path:
        return self._rules_dir

    def exists(self) -> bool:
        """Check if MEMORY.md exists."""
        return self._memory_file.exists()

    def _tier_contained(self) -> bool:
        """``.geode`` (and its memory/rules dirs, if present) stays in the project.

        Checked before any lock file or directory is created, so a symlinked
        tier never receives even a rejected write.
        """
        for directory in (self._geode_dir, self._memory_dir, self._rules_dir):
            if directory.is_symlink():
                return False
            if directory.exists() and not directory.resolve().is_relative_to(self._root):
                return False
        return True

    def _project_lock(self) -> Any:
        if not self._tier_contained():
            raise _OutsideTierError(f"{self._geode_dir} resolves outside {self._root}")
        return exclusive_file_lock(self._geode_dir / _LOCK_FILENAME)

    def load_memory(self, max_lines: int = MAX_MEMORY_LINES) -> str:
        """Load MEMORY.md content (first N lines for context window efficiency).

        Cascade: project .geode/memory/ → global ~/.geode/memory/. A symlinked
        or tier-escaping file is never followed into the prompt.
        """
        for target, root in (
            (self._memory_file, self._root),
            (self._global_memory_dir / "PROJECT.md", self._global_geode_dir),
        ):
            try:
                content = _read_text(target, root)
            except _UnreadableError as exc:
                log.warning("Failed to read MEMORY.md: %s", exc)
                return ""
            if content is not None:
                return "\n".join(content.split("\n")[:max_lines])
        return ""

    def _rule_files(self) -> dict[str, Path]:
        """Rule files by stem: global first, project overrides; symlinks skipped."""
        rule_files: dict[str, Path] = {}
        for rules_dir, root in (
            (self._global_rules_dir, self._global_geode_dir),
            (self._rules_dir, self._root),
        ):
            if not rules_dir.is_dir():
                continue
            for f in sorted(rules_dir.glob("*.md")):
                if _contained(f, root):
                    rule_files[f.stem] = f
                else:
                    log.warning("Skipping rule outside its memory tier: %s", f)
        return rule_files

    def _read_rule(self, rule_file: Path) -> str | None:
        root = self._root if rule_file.parent == self._rules_dir else self._global_geode_dir
        try:
            return _read_text(rule_file, root)
        except _UnreadableError as exc:
            log.warning("Skipping unreadable rule: %s", exc)
            return None

    def load_rules(self, context: str = "*") -> list[dict[str, Any]]:
        """Load matching rules from .geode/rules/*.md.

        Cascade: global ~/.geode/rules/ → project .geode/rules/
        Global rules are loaded first, project rules override by name.

        Args:
            context: Context string to match against rule paths (e.g. "research", "demo").

        Returns:
            List of dicts with 'name', 'paths', 'content' for each matching rule.
        """
        matched: list[dict[str, Any]] = []
        for rule_file in self._rule_files().values():
            raw = self._read_rule(rule_file)
            if raw is None:
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
        """Compatibility form of :meth:`record_insight`: True only when written."""
        return self.record_insight(insight) is MemoryWrite.APPLIED

    def record_insight(self, insight: str) -> MemoryWrite:
        """Add an insight to the '## 최근 인사이트' section of MEMORY.md.

        Runs as one locked reload → validate → modify → atomic write, so
        concurrent writers (threads or processes) never lose each other's
        entries, and an unreadable existing file is left byte-identical.

        - Dedup: the same text, or same date + same ``[subject]``, is UNCHANGED
        - Newest-first: new entry prepended at top of section
        - Rotation: keeps only MAX_INSIGHTS entries, oldest dropped
        """
        if not _is_valid_insight(insight):
            return MemoryWrite.INVALID
        if not self._tier_contained() or not _contained(self._memory_file, self._root):
            log.warning("Refusing MEMORY.md outside the project: %s", self._memory_file)
            return MemoryWrite.INVALID
        try:
            with self._project_lock():
                try:
                    content = _read_text(self._memory_file, self._root)
                except _UnreadableError as exc:
                    log.warning("MEMORY.md unreadable; left unchanged: %s", exc)
                    return MemoryWrite.FAILED
                if content is None:
                    log.warning("MEMORY.md does not exist — cannot add insight")
                    return MemoryWrite.NOT_FOUND
                updated = self._with_insight(content, insight.strip())
                if updated is None:
                    return MemoryWrite.UNCHANGED
                atomic_write_text(self._memory_file, updated)
        except _OutsideTierError:
            return MemoryWrite.INVALID
        except (OSError, TimeoutError) as e:
            log.warning("Failed to write MEMORY.md: %s", e)
            return MemoryWrite.FAILED
        log.info("Added insight to MEMORY.md: %s", insight)
        return MemoryWrite.APPLIED

    @staticmethod
    def _with_insight(content: str, insight: str) -> str | None:
        """Return MEMORY.md with *insight* added, or None when already present."""
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

        # Idempotent: the exact same insight text is already recorded.
        if any(line.split(": ", 1)[-1] == insight for line in existing_lines):
            return None

        # Dedup: skip if same date + same subject substring already exists.
        ip_token = ""
        if insight.startswith("[") and "]" in insight:
            ip_token = insight[1 : insight.index("]")]

        if ip_token:
            for line in existing_lines:
                if timestamp in line and f"[{ip_token}]" in line:
                    log.debug("Dedup: insight for [%s] on %s already exists", ip_token, timestamp)
                    return None

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
        return before + insight_block + "\n" + remainder

    def purge_bad_insights(self) -> int:
        """Remove existing insight entries that fail the quality gate.

        Scans both '## Recent Insights' and '## 최근 인사이트' sections.
        Returns the number of entries removed.
        """
        try:
            with self._project_lock():
                try:
                    content = _read_text(self._memory_file, self._root)
                except _UnreadableError:
                    return 0
                if content is None:
                    return 0
                content, total_removed = self._without_bad_insights(content)
                if total_removed == 0:
                    return 0
                atomic_write_text(self._memory_file, content)
        except (_OutsideTierError, OSError, TimeoutError) as e:
            log.warning("Failed to purge insights: %s", e)
            return 0
        log.info("Purged %d bad insights from MEMORY.md", total_removed)
        return total_removed

    @staticmethod
    def _without_bad_insights(content: str) -> tuple[str, int]:
        markers = ("## 최근 인사이트", "## Recent Insights")
        total_removed = 0

        for marker in markers:
            if marker not in content:
                continue

            marker_idx = content.index(marker)
            newline_idx = content.find("\n", marker_idx + len(marker))
            if newline_idx == -1:
                continue

            before = content[: newline_idx + 1]
            after = content[newline_idx + 1 :]

            kept_lines: list[str] = []
            remainder_lines: list[str] = []
            removed = 0
            in_insights = True
            for line in after.split("\n"):
                if in_insights and line.startswith("- "):
                    colon_idx = line.find(": ", 2)
                    insight_text = line[colon_idx + 2 :] if colon_idx > 0 else line[2:]
                    if _is_valid_insight(insight_text):
                        kept_lines.append(line)
                    else:
                        removed += 1
                        log.info("Purged bad insight: %s", line[:100])
                elif in_insights and line.strip() == "":
                    kept_lines.append(line)
                else:
                    in_insights = False
                    remainder_lines.append(line)

            if removed == 0:
                continue

            while kept_lines and kept_lines[-1].strip() == "":
                kept_lines.pop()

            insight_block = "\n".join(kept_lines)
            remainder = "\n".join(remainder_lines)
            content = before + insight_block + "\n" + remainder
            total_removed += removed

        return content, total_removed

    # ------------------------------------------------------------------
    # Rule CRUD (P0-B: agent-driven rule management)
    # ------------------------------------------------------------------

    def change_rule(
        self,
        action: str,
        name: str,
        *,
        paths: list[str] | None = None,
        content: str = "",
    ) -> MemoryWrite:
        """Create, update, or delete one project rule under the memory lock.

        ``create`` reports CONFLICT for an existing rule; ``update``/``delete``
        report NOT_FOUND for an absent one. Symlinked rule files, a rules
        directory resolving outside the project, and names that sanitize to
        nothing are INVALID; an unreadable rule being updated stays unchanged.
        """
        safe_name = _safe_rule_name(name)
        if safe_name is None or action not in ("create", "update", "delete"):
            return MemoryWrite.INVALID
        if not self._tier_contained():
            log.warning("Refusing rule write: %s resolves outside the project", self._geode_dir)
            return MemoryWrite.INVALID
        rule_path = self._rules_dir / f"{safe_name}.md"
        try:
            with self._project_lock():
                self._rules_dir.mkdir(parents=True, exist_ok=True)
                if not _contained(rule_path, self._root):
                    log.warning("Refusing rule outside the project: %s", rule_path)
                    return MemoryWrite.INVALID
                exists = rule_path.exists()
                if action == "create":
                    if exists:
                        log.warning("Rule '%s' already exists — use update_rule()", safe_name)
                        return MemoryWrite.CONFLICT
                    paths_yaml = "\n".join(f'  - "{p}"' for p in paths or [])
                    frontmatter = f"---\nname: {safe_name}\npaths:\n{paths_yaml}\n---\n\n"
                    atomic_write_text(rule_path, frontmatter + content)
                elif not exists:
                    log.warning("Rule '%s' not found", safe_name)
                    return MemoryWrite.NOT_FOUND
                elif action == "update":
                    try:
                        raw = _read_text(rule_path, self._root) or ""
                    except _UnreadableError as exc:
                        log.warning("Rule unreadable; left unchanged: %s", exc)
                        return MemoryWrite.FAILED
                    fm_match = _FRONTMATTER_RE.match(raw)
                    frontmatter_block = raw[: fm_match.start(2)] if fm_match else ""
                    atomic_write_text(rule_path, frontmatter_block + content)
                else:
                    rule_path.unlink()
        except _OutsideTierError:
            return MemoryWrite.INVALID
        except (OSError, TimeoutError) as e:
            log.warning("Failed to %s rule '%s': %s", action, safe_name, e)
            return MemoryWrite.FAILED
        log.info("Rule %s: %s", action, rule_path)
        return MemoryWrite.APPLIED

    def create_rule(self, name: str, paths: list[str], content: str) -> bool:
        """Create a new rule file in .geode/rules/; True only when created."""
        return self.change_rule("create", name, paths=paths, content=content) is MemoryWrite.APPLIED

    def update_rule(self, name: str, content: str) -> bool:
        """Update an existing rule's content (preserves frontmatter); True when updated."""
        return self.change_rule("update", name, content=content) is MemoryWrite.APPLIED

    def delete_rule(self, name: str) -> bool:
        """Delete a rule file. Returns True if deleted, False if not found."""
        return self.change_rule("delete", name) is MemoryWrite.APPLIED

    def list_rules(self) -> list[dict[str, Any]]:
        """List project rules with name, paths, and content preview."""
        if not self._rules_dir.is_dir():
            return []

        rules: list[dict[str, Any]] = []
        for rule_file in sorted(self._rules_dir.glob("*.md")):
            if not _contained(rule_file, self._root):
                log.warning("Skipping rule outside the project: %s", rule_file)
                continue
            raw = self._read_rule(rule_file)
            if raw is None:
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

    def get_context_for_subject(self, subject_id: str) -> dict[str, Any]:
        """Get combined memory + rules context for a specific subject.

        Returns dict with 'memory' (str) and 'rules' (list) keys.
        """
        return {
            "memory": self.load_memory(),
            "rules": self.load_rules(subject_id),
        }

    def ensure_structure(self) -> bool:
        """Create .geode/memory/PROJECT.md and .geode/rules/ if they don't exist.

        Returns True if created, False if already existed.
        """
        if self._memory_file.exists():
            return False
        if not self._tier_contained():
            raise PermissionError(f"{self._geode_dir} resolves outside {self._root}")

        self._memory_dir.mkdir(parents=True, exist_ok=True)
        self._rules_dir.mkdir(parents=True, exist_ok=True)
        with self._project_lock():
            if self._memory_file.exists():
                return False
            atomic_write_text(self._memory_file, _DEFAULT_MEMORY)
        log.info("Created .geode/memory/PROJECT.md and .geode/rules/ structure")
        return True


_DEFAULT_MEMORY = """\
# Project Memory

## Overview
- Type: (auto-detected by `geode init`)
- Commands: see `.geode/config.toml` [commands] section

## Rules
- .geode/rules/ 디렉토리의 .md 파일이 자동 로딩됩니다

## Recent Insights
"""
