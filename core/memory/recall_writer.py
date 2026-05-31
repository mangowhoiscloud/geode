"""Memory-recall MD writer — OL-C3 (2026-05-22) substrate.

M4.4.1 (PR #1436) shipped the *reader* — `memory_recall.load_memory_entries`
walks `~/.geode/memory/recall/*.md`, ranks by keyword overlap × recency,
prepends a `<memory-recall>` block to the system prompt. But no writer
existed in GEODE itself — the slot's input pool was either operator-
hand-curated or empty.

OL-C3 ships the writer that closes that loop. The writer is a *pure
utility* — caller decides when to invoke it and what to record. We
deliberately do NOT auto-fire on every SESSION_ENDED because:

* Noise: every interactive turn is rarely worth persisting.
* Cost: auto-LLM-curator on every session would cost real money.
* Schema lock-in: deciding what counts as a "memory" is operator-
  domain-specific and we don't want to bake one choice into core.

Auto-trigger paths (SESSION_ENDED hook handler + LLM curator) land as
OL-C3.2 follow-up after we have:
1. An ADR on selection (every session? promoted only? LLM-curator?).
2. A cost ceiling on the curator path.
3. A cap on memory-pool disk usage.

For now: operator calls `write_recall_entry(...)` via CLI / REPL slash
when a session yields a memory worth keeping.

**File shape** (matches M4.4.1 reader's frontmatter parser):

.. code-block:: markdown

    ---
    name: feedback-cli-budget
    description: User prefers Sonnet over Opus when quota is exhausted.
    metadata:
      type: feedback
    ---

    Body text — verbatim or curated insight. M4.4.1 ranker uses
    description + body for keyword overlap scoring.

**Path resolution**: writes to `core.memory.recall_writer.resolve_recall_dir()`
which mirrors M4.4.1's reader resolution — `$GEODE_MEMORY_RECALL_DIR`
env override > `~/.geode/memory/recall/` default. Parent dir is
created lazily.
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Iterable
from pathlib import Path

from core.paths import GLOBAL_MEMORY_DIR

log = logging.getLogger(__name__)

__all__ = [
    "GEODE_MEMORY_RECALL_DIR_ENV",
    "RECALL_TYPE_FEEDBACK",
    "RECALL_TYPE_PROJECT",
    "RECALL_TYPE_REFERENCE",
    "RECALL_TYPE_USER",
    "VALID_RECALL_TYPES",
    "resolve_recall_dir",
    "write_recall_entry",
]

GEODE_MEMORY_RECALL_DIR_ENV = "GEODE_MEMORY_RECALL_DIR"
"""Match M4.4.1 reader's env var (`core/self_improving/loop/memory_recall.py`)
so writer + reader honour the same operator override."""

_DEFAULT_RECALL_DIR = GLOBAL_MEMORY_DIR / "recall"

# 4 canonical types — match Claude Code's auto-memory schema. Operators
# can write any string but using the canonical set keeps the reader's
# type-tag rendering consistent.
RECALL_TYPE_USER = "user"
RECALL_TYPE_FEEDBACK = "feedback"
RECALL_TYPE_PROJECT = "project"
RECALL_TYPE_REFERENCE = "reference"

VALID_RECALL_TYPES: frozenset[str] = frozenset(
    {RECALL_TYPE_USER, RECALL_TYPE_FEEDBACK, RECALL_TYPE_PROJECT, RECALL_TYPE_REFERENCE}
)

# Filenames must be filesystem-safe — alnum + hyphen + underscore.
_NAME_SLUG_RE = re.compile(r"[^A-Za-z0-9_\-]+")


def resolve_recall_dir() -> Path:
    """Where to write — env override > default. Always returns a Path
    (does NOT verify existence; the writer creates it lazily)."""
    override = os.environ.get(GEODE_MEMORY_RECALL_DIR_ENV)
    if override:
        return Path(override).expanduser()
    return _DEFAULT_RECALL_DIR


def _slugify_name(name: str) -> str:
    """Turn an operator-provided name into a filesystem-safe slug.

    Replaces non-alnum runs with single hyphen, lowercases, strips
    leading/trailing hyphens. Empty result → ``"untitled"`` (so the
    writer always produces a usable filename even on bizarre input).
    """
    slug = _NAME_SLUG_RE.sub("-", name).strip("-").lower()
    return slug or "untitled"


def _escape_frontmatter_value(value: str) -> str:
    """Strip newlines from frontmatter scalar values — they'd break the
    YAML-light parser in M4.4.1's reader (which is single-line-per-key)."""
    return value.replace("\n", " ").replace("\r", " ").strip()


def write_recall_entry(
    *,
    name: str,
    description: str,
    body: str,
    type_label: str = RECALL_TYPE_FEEDBACK,
    recall_dir: Path | None = None,
    overwrite: bool = False,
) -> Path | None:
    """Write one frontmatter MD entry to the recall dir.

    Args:
        name: Slug for the filename + frontmatter ``name`` field. Will
            be slugified (alnum + hyphen).
        description: One-line summary. M4.4.1 ranker uses this for
            keyword overlap (along with body).
        body: Verbatim memory content (multi-line allowed).
        type_label: Canonical type (``"user"`` / ``"feedback"`` /
            ``"project"`` / ``"reference"``). Free-form strings allowed
            but logged at DEBUG so operators notice typos.
        recall_dir: Override the resolved dir (test fixture; defaults
            to :func:`resolve_recall_dir`).
        overwrite: When True, replace an existing file with the same
            slug. When False (default), the function returns ``None``
            if the file already exists (idempotent no-op).

    Returns:
        ``Path`` to the written file on success.
        ``None`` if (a) ``overwrite=False`` and file exists, or
        (b) write failed (OSError, logged at WARNING).
    """
    target_dir = recall_dir if recall_dir is not None else resolve_recall_dir()
    slug = _slugify_name(name)
    if type_label not in VALID_RECALL_TYPES:
        log.debug(
            "recall_writer: type %r not in canonical set %s; writing anyway",
            type_label,
            sorted(VALID_RECALL_TYPES),
        )
    safe_name = _escape_frontmatter_value(name)
    safe_desc = _escape_frontmatter_value(description)
    safe_type = _escape_frontmatter_value(type_label)
    file_path = target_dir / f"{slug}.md"
    if file_path.exists() and not overwrite:
        log.debug("recall_writer: %s already exists; skip (overwrite=False)", file_path)
        return None
    content = (
        f"---\nname: {safe_name}\ndescription: {safe_desc}\n"
        f"metadata:\n  type: {safe_type}\n---\n\n{body.rstrip()}\n"
    )
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
    except OSError as exc:
        log.warning("recall_writer: failed to write %s: %s", file_path, exc)
        return None
    return file_path


def list_recall_entries(recall_dir: Path | None = None) -> list[Path]:
    """Light-weight enumeration — returns sorted ``.md`` paths.

    Tests use this to verify the writer's output without re-implementing
    the M4.4.1 reader. Returns an empty list if the dir is missing.
    """
    target_dir = recall_dir if recall_dir is not None else resolve_recall_dir()
    if not target_dir.is_dir():
        return []
    return sorted(target_dir.glob("*.md"))


def write_recall_entries(
    entries: Iterable[dict[str, str]],
    *,
    recall_dir: Path | None = None,
    overwrite: bool = False,
) -> list[Path]:
    """Batch convenience — write multiple entries, return paths that succeeded.

    Each entry must carry ``name`` + ``description`` + ``body``;
    optional ``type_label``. Failures (already-exists / OSError) are
    logged + skipped — return list only includes the writes that
    actually persisted to disk.
    """
    out: list[Path] = []
    for entry in entries:
        path = write_recall_entry(
            name=entry["name"],
            description=entry["description"],
            body=entry["body"],
            type_label=entry.get("type_label", RECALL_TYPE_FEEDBACK),
            recall_dir=recall_dir,
            overwrite=overwrite,
        )
        if path is not None:
            out.append(path)
    return out
