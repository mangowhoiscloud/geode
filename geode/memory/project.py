"""Project Memory — markdown-based persistent memory (OpenClaw SOUL.md pattern).

Loads .claude/MEMORY.md (project-level context) and .claude/rules/*.md
(modular rules with YAML frontmatter path matching).

Architecture-v6 §3 Layer 2: Project Memory tier.

Directory structure:
    .claude/
    ├── MEMORY.md           # Main project memory (first 200 lines → system context)
    └── rules/              # Modular rules
        ├── anime-ip.md     # Category-specific rules
        └── ...
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# MEMORY.md max lines loaded into context (SOT: 200)
MAX_MEMORY_LINES = 200

# Maximum insight entries before oldest-drop rotation
MAX_INSIGHTS = 50

# YAML frontmatter regex
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
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
        self._claude_dir = root / ".claude"
        self._memory_file = self._claude_dir / "MEMORY.md"
        self._rules_dir = self._claude_dir / "rules"

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
        """Load matching rules from .claude/rules/*.md.

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

            # Parse YAML frontmatter
            fm_match = _FRONTMATTER_RE.match(raw)
            if fm_match:
                frontmatter = fm_match.group(1)
                paths = _extract_paths(frontmatter)
                body = raw[fm_match.end() :]
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
            self._memory_file.write_text(content, encoding="utf-8")
            log.info("Added insight to MEMORY.md: %s", insight)
            return True
        except OSError as e:
            log.warning("Failed to write MEMORY.md: %s", e)
            return False

    def get_context_for_ip(self, ip_name: str) -> dict[str, Any]:
        """Get combined memory + rules context for a specific IP.

        Returns dict with 'memory' (str) and 'rules' (list) keys.
        """
        return {
            "memory": self.load_memory(),
            "rules": self.load_rules(ip_name),
        }

    def ensure_structure(self) -> bool:
        """Create .claude/MEMORY.md and .claude/rules/ if they don't exist.

        Returns True if created, False if already existed.
        """
        if self._memory_file.exists():
            return False

        self._claude_dir.mkdir(parents=True, exist_ok=True)
        self._rules_dir.mkdir(exist_ok=True)

        default_memory = """\
# GEODE Project Memory

## 프로젝트 개요
- 목적: 게임화 IP 중 저평가된 IP 발굴 및 회복 전략 도출
- 파이프라인: Cortex → Signals → Analysts → Evaluators → Scoring → Synthesis

## 분석 규칙
- @rules/ 디렉토리의 .md 파일이 자동 로딩됩니다

## 자주 분석하는 IP
- Berserk: 다크 판타지, S-tier, conversion_failure
- Cowboy Bebop: SF 느와르, A-tier, undermarketed
- Ghost in the Shell: 사이버펑크, B-tier, discovery_failure

## 팀 특화 루브릭 오버라이드
- (없음 — 기본 14-axis 루브릭 사용)

## 최근 인사이트
"""
        self._memory_file.write_text(default_memory, encoding="utf-8")

        # Create sample rule
        sample_rule = """\
---
name: anime-ip-rules
paths:
  - "**/*anime*"
  - "*cowboy*"
  - "*ghost*"
---

# 애니메이션 IP 분석 규칙

## 데이터 소스 우선순위
1. YouTube (트레일러, 리뷰 영상)
2. Reddit (r/anime, r/gaming)

## 특수 고려사항
- 원작 시즌 방영 중이면 Growth Velocity(J) 가중치 상향
- 원작 완결 후 2년 이상이면 Expansion Potential(F) 감점
"""
        (self._rules_dir / "anime-ip.md").write_text(sample_rule, encoding="utf-8")

        log.info("Created .claude/MEMORY.md and .claude/rules/ structure")
        return True
