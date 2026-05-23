"""Literature snapshot reader + cache helpers (PR-CSP-14, Loop 3 plugin side).

The writer lives in ``core/tools/literature_snapshot.py`` (delegated tool
``freeze_paper_snapshot``). This module is the read-side counterpart used
by the ``LiteratureReview`` agent + (eventually) the build step for the
Pages bundle.

Two read shapes:

- :func:`load_snapshot` — given an arxiv_id, return the latest snapshot
  dict (or ``None``). Used by per-paper analysis sub-agents that want to
  skip re-fetching when an unchanged snapshot exists.
- :func:`iter_snapshots` — yield every snapshot under
  ``docs/petri-bundle/literature/`` in deterministic order. Used by the
  build step + the orchestrator's state.json serialization (rolls a
  count into the final report).

The reader does NOT mutate snapshots — that's the writer's job (atomic
tmp+rename via the delegated tool). Test fixtures use the same
``GEODE_REPO_ROOT`` env var the writer honors, so a tmp dir override
flows through both sides.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_SNAPSHOT_DIR",
    "iter_snapshots",
    "load_snapshot",
    "resolve_snapshot_root",
]


_SNAPSHOT_DIR_NAME = "docs/petri-bundle/literature"


def resolve_snapshot_root() -> Path:
    """Locate the snapshot directory — matches the writer's resolution order.

    Order:
      1. ``GEODE_REPO_ROOT`` env (test fixtures).
      2. Working directory ancestor that contains ``pyproject.toml``.
      3. Last-resort cwd.

    Returns a ``Path`` even when the directory doesn't exist (callers
    handle the missing-dir case via ``is_dir()`` checks).
    """
    env_root = os.environ.get("GEODE_REPO_ROOT", "").strip()
    if env_root:
        return Path(env_root) / _SNAPSHOT_DIR_NAME
    here = Path.cwd().resolve()
    for ancestor in [here, *here.parents]:
        if (ancestor / "pyproject.toml").is_file():
            return ancestor / _SNAPSHOT_DIR_NAME
    return here / _SNAPSHOT_DIR_NAME


# Public alias for callers that want a ``Path`` constant rather than a
# function call. Lazy-evaluated since the resolved root depends on the
# CWD at first import.
DEFAULT_SNAPSHOT_DIR = resolve_snapshot_root


def load_snapshot(arxiv_id: str, root: Path | None = None) -> dict[str, Any] | None:
    """Return the latest snapshot dict for ``arxiv_id``, or ``None``.

    "Latest" = lexicographically last ``<arxiv_id>-<retrieved_at>.json``
    in the directory (the writer's ``retrieved_at`` timestamp is ISO so
    lex order == chrono order). Missing dir, missing arxiv_id, or
    unreadable file → ``None`` (defensive — the LiteratureReview agent
    should treat a cache miss as "fetch needed").
    """
    root = root or resolve_snapshot_root()
    if not root.is_dir():
        return None
    matches = sorted(root.glob(f"{arxiv_id}-*.json"))
    if not matches:
        return None
    latest = matches[-1]
    try:
        data = json.loads(latest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("literature_snapshot: unreadable snapshot %s: %s", latest, exc)
        return None
    if not isinstance(data, dict):
        return None
    return data


def iter_snapshots(root: Path | None = None) -> Iterator[tuple[Path, dict[str, Any]]]:
    """Yield ``(path, snapshot_dict)`` for every snapshot under root.

    Deterministic ordering: by file name (i.e. ``<arxiv_id>-<retrieved_at>``).
    Skips ``listing.json`` and any non-snapshot junk gracefully. Skips
    unreadable files with a warning rather than raising — callers
    typically aggregate counts.
    """
    root = root or resolve_snapshot_root()
    if not root.is_dir():
        return
    for path in sorted(root.glob("*.json")):
        if path.name == "listing.json":
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("literature_snapshot: skipping unreadable %s: %s", path, exc)
            continue
        if not isinstance(data, dict):
            continue
        yield path, data
