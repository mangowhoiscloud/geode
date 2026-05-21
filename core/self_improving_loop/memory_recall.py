"""Memory recall reader — ADR-012 M4.4.1 (in-context slot follow-up).

Activates the ``memory_recall`` slot declared in S5 (#1425). Reads
frontmatter-style memory entries from ``~/.geode/memory/recall/`` (or
``GEODE_MEMORY_RECALL_DIR``), ranks by keyword overlap with the current
task prompt × file recency, and emits a formatted block for the
in-context wiring orchestrator to prepend to the system prompt.

**File layout** — one ``.md`` per memory, frontmatter-then-body shape
(same convention as Claude Code's auto-memory)::

    ---
    name: feedback-cli-budget
    description: User wants Sonnet over Opus when Opus quota is exhausted.
    metadata:
      type: feedback
    ---

    The user has a hard preference for switching to Sonnet …

**Resolution**:

1. ``$GEODE_MEMORY_RECALL_DIR`` (operator override) — points at an
   alternate directory; useful when the operator wants to recall from
   Claude Code's ``~/.claude/projects/<X>/memory/`` instead.
2. ``~/.geode/memory/recall/`` (default) — GEODE-owned location. When
   the directory is missing or empty, the reader returns ``[]`` and
   the orchestrator's per-slot try/except keeps the LLM call clean.

**Ranking** — pure-stdlib keyword overlap (no embeddings dependency).
Score = ``|prompt_tokens ∩ memory_tokens|`` × ``recency_weight``, where
``recency_weight = 1 / (1 + age_days)`` so a fresh-yesterday memory beats
a year-old high-overlap one. Ties tolerate insertion order (stable sort).

**Format** — one ``- [type] description`` line per ranked entry inside
a ``<memory-recall>`` tag, mirroring the ``<system-reminder>`` framing
Claude Code uses for its own auto-memory injection.
"""

from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

from core.paths import GLOBAL_MEMORY_DIR

log = logging.getLogger(__name__)

__all__ = [
    "GEODE_MEMORY_RECALL_DIR_ENV",
    "MemoryEntry",
    "format_memory_block",
    "load_memory_entries",
    "rank_memory_entries",
    "resolve_recall_dir",
]

GEODE_MEMORY_RECALL_DIR_ENV = "GEODE_MEMORY_RECALL_DIR"
_DEFAULT_RECALL_DIR = GLOBAL_MEMORY_DIR / "recall"

# Frontmatter parsing — minimal YAML-light. Memory files are
# operator-curated so we accept only the simple ``key: value`` lines we
# actually read (name / description / metadata.type). Anything fancier
# is silently ignored per the per-file graceful contract.
_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n(.*)", re.DOTALL)
_TOKEN_RE = re.compile(r"[A-Za-z0-9_]{3,}")  # min 3-char tokens to skip noise


@dataclass(frozen=True, slots=True)
class MemoryEntry:
    """Parsed memory file ready for ranking + formatting."""

    name: str
    type: str  # "user" / "feedback" / "project" / "reference" / "" (default)
    description: str
    body: str
    mtime: float


def resolve_recall_dir() -> Path | None:
    """Return the directory the reader should walk, or ``None`` to skip.

    ``$GEODE_MEMORY_RECALL_DIR`` wins if set. Otherwise fall back to
    ``~/.geode/memory/recall/`` when the dir exists. Missing default
    dir → ``None`` (graceful: orchestrator no-ops the slot).
    """
    override = os.environ.get(GEODE_MEMORY_RECALL_DIR_ENV)
    if override:
        path = Path(override).expanduser()
        if not path.is_dir():
            log.debug(
                "%s=%s but directory missing; skipping memory_recall",
                GEODE_MEMORY_RECALL_DIR_ENV,
                override,
            )
            return None
        return path
    if not _DEFAULT_RECALL_DIR.is_dir():
        return None
    return _DEFAULT_RECALL_DIR


def load_memory_entries() -> list[MemoryEntry]:
    """Walk the resolved recall dir, parse each ``.md`` → :class:`MemoryEntry`.

    Per-file graceful — a malformed frontmatter, missing required field,
    or unreadable file is logged at DEBUG and silently skipped; the
    remaining files still come through.
    """
    base = resolve_recall_dir()
    if base is None:
        return []
    entries: list[MemoryEntry] = []
    for path in sorted(base.glob("*.md")):
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as exc:
            log.debug("memory_recall: %s unreadable: %s", path, exc)
            continue
        parsed = _parse_frontmatter(raw)
        if parsed is None:
            log.debug("memory_recall: %s missing frontmatter; skipping", path)
            continue
        meta, body = parsed
        name = str(meta.get("name") or path.stem)
        description = str(meta.get("description") or "").strip()
        type_label = str(meta.get("metadata.type") or "").strip()
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = 0.0
        entries.append(
            MemoryEntry(
                name=name,
                type=type_label,
                description=description,
                body=body.strip(),
                mtime=mtime,
            )
        )
    return entries


def rank_memory_entries(
    entries: list[MemoryEntry],
    query: str,
    *,
    top_k: int,
    now: float | None = None,
) -> list[MemoryEntry]:
    """Top-K by ``keyword_overlap × recency_weight``.

    Memories with zero keyword overlap rank by recency alone, so a fresh
    memory still surfaces in a topic-unrelated session (Claude Code
    auto-memory parity — recent feedback wins over stale alignment).

    Args:
        entries: All loaded entries.
        query: The current task's user prompt (latest user message).
        top_k: Cap. Zero / negative → empty.
        now: Override the recency anchor (test-only). Defaults to
            ``time.time()``.
    """
    if top_k <= 0 or not entries:
        return []
    anchor = now if now is not None else time.time()
    query_tokens = _tokenize(query)
    scored: list[tuple[float, int, MemoryEntry]] = []
    for idx, entry in enumerate(entries):
        memory_tokens = _tokenize(entry.description + " " + entry.body)
        overlap = float(len(query_tokens & memory_tokens))
        age_days = max(0.0, (anchor - entry.mtime) / 86400.0)
        recency = 1.0 / (1.0 + age_days)
        # ``overlap + 0.1`` so the recency channel still differentiates
        # entries with zero overlap (otherwise they'd all tie at 0).
        score = (overlap + 0.1) * recency
        scored.append((score, idx, entry))
    scored.sort(key=lambda t: (-t[0], t[1]))
    return [entry for _, _, entry in scored[:top_k]]


def format_memory_block(entries: list[MemoryEntry]) -> str:
    """Render ranked entries as a ``<memory-recall>`` block, or ``""`` if empty."""
    if not entries:
        return ""
    lines = ["<memory-recall>"]
    for entry in entries:
        type_tag = f"[{entry.type}]" if entry.type else "[memory]"
        desc = entry.description or entry.body.splitlines()[0] if entry.body else ""
        lines.append(f"- {type_tag} {desc}".rstrip())
    lines.append("</memory-recall>")
    return "\n".join(lines)


# ---------------------------------------------------------------------------


def _parse_frontmatter(raw: str) -> tuple[dict[str, str], str] | None:
    """Return ``(meta, body)`` or ``None`` when the file lacks frontmatter.

    YAML-light parser — handles flat ``key: value`` lines plus the single
    nested ``metadata.type`` we care about. Other YAML constructs (lists,
    nested dicts beyond depth 1) are silently dropped.
    """
    m = _FRONTMATTER_RE.match(raw)
    if not m:
        return None
    head, body = m.group(1), m.group(2)
    meta: dict[str, str] = {}
    indent_parent: str | None = None
    for line in head.splitlines():
        if not line.strip():
            continue
        if ":" not in line:
            continue
        if line.startswith(" ") or line.startswith("\t"):
            # Nested under a parent — only ``metadata: { type: X }`` is
            # consumed.
            key_part, _, val_part = line.strip().partition(":")
            if indent_parent and val_part:
                meta[f"{indent_parent}.{key_part.strip()}"] = val_part.strip()
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip()
        if not val:
            indent_parent = key  # next nested lines belong to this parent
            continue
        indent_parent = None
        meta[key] = val
    return meta, body


def _tokenize(text: str) -> set[str]:
    """Lowercase 3+ alphanumeric tokens. Set for overlap calc."""
    return {tok.lower() for tok in _TOKEN_RE.findall(text)}
