"""Seed-tree flattener — bridge from the hierarchical seed tree to
inspect-petri's flat ``directory.glob("*.md")`` loader.

PR 0 (2026-05-18) introduced the hierarchical
``plugins/petri_audit/seeds/<tier>/<dim>/<NN>_<variant>.md`` layout so
seeds organize by Petri rubric dim. inspect-petri's
``_seeds/_markdown.py:_load_markdown_seeds`` does a flat ``glob`` only
— no recursion — so a direct pass of the tree root would find zero
files.

This module provides :func:`flatten_for_inspect_petri` which:

1. Detects whether the input path is a hierarchical tree (has ``critical/``
   ``auxiliary/`` ``info/`` subdirs) or already flat.
2. For hierarchical input, creates a stable scratch directory at
   ``<geode_home>/petri-audit/seed-stage/<tree-hash>/`` containing one
   relative symlink per ``.md`` file. The symlink names encode the
   tier + dim so the original organization is recoverable from the
   flat dir.
3. Returns the path to pass to ``inspect eval`` as
   ``-T seed_instructions=<path>``.

The staging directory is content-addressed (hash of the tree's file
list) so repeated calls reuse the same staging — no churn between
audits, and stale stagings can be garbage-collected by clearing the
parent directory.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from core.paths import GEODE_HOME

log = logging.getLogger(__name__)

__all__ = ["flatten_for_inspect_petri", "is_hierarchical_seed_tree"]


_TIER_DIRS = frozenset({"critical", "auxiliary", "info"})


def is_hierarchical_seed_tree(path: Path) -> bool:
    """Return True when ``path`` is a directory containing tier subdirs.

    Heuristic: ``<path>/{critical,auxiliary,info}`` all exist as dirs.
    Loose enough to allow extra siblings (e.g., a ``README.md`` at
    the root); strict enough to avoid false-positives on flat dirs.
    """
    if not path.is_dir():
        return False
    return all((path / tier).is_dir() for tier in ("critical", "auxiliary", "info"))


def _list_md_files(tree_root: Path) -> list[Path]:
    """Recursively collect ``.md`` files under ``tree_root``, sorted for
    deterministic hashing.
    """
    return sorted(tree_root.rglob("*.md"))


def _tree_hash(md_files: list[Path]) -> str:
    """Hash the sorted relative-path list — stable per tree state.

    Uses the relative paths (not contents) so a seed body edit alone
    doesn't invalidate the staging; only structural changes (added /
    removed / renamed files) trigger a fresh stage.
    """
    payload = "\n".join(str(p) for p in md_files).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def _stage_dir(tree_root: Path) -> Path:
    """Compute the staging directory path for ``tree_root``.

    Path: ``<GEODE_HOME>/petri-audit/seed-stage/<tree-hash>/``.
    Content-addressed by file list so two trees with the same
    structure share a stage.
    """
    files = _list_md_files(tree_root)
    return GEODE_HOME / "petri-audit" / "seed-stage" / _tree_hash(files)


def _populate_stage(tree_root: Path, stage: Path) -> None:
    """Create the stage directory with symlinks to every ``.md`` file.

    Symlink names encode tier + dim + variant for traceability:
    ``<tier>__<dim>__<variant>.md``.

    Skip already-populated stages (idempotent — content-addressed
    hash means the contents would be identical anyway).
    """
    if stage.exists():
        return
    stage.mkdir(parents=True, exist_ok=True)
    for md_path in _list_md_files(tree_root):
        # Path structure: tree_root/<tier>/<dim>/<variant>.md
        try:
            rel = md_path.relative_to(tree_root)
        except ValueError:
            continue
        parts = rel.parts
        if len(parts) < 3:
            # Top-level files at tree root (unlikely after PR 0 migration) —
            # use the bare filename.
            target_name = rel.name
        else:
            tier, dim, variant = parts[0], parts[1], parts[-1]
            target_name = f"{tier}__{dim}__{variant}"
        link_path = stage / target_name
        # Use relative symlink so the stage survives geode_home moves
        # within reason. abspath fallback when relative is too long.
        try:
            link_path.symlink_to(md_path.resolve())
        except (OSError, NotImplementedError) as exc:
            log.warning(
                "seed_tree: failed to symlink %s -> %s (%s); copying instead",
                md_path,
                link_path,
                exc,
            )
            link_path.write_bytes(md_path.read_bytes())


def flatten_for_inspect_petri(seed_select: str | Path) -> str | Path:
    """Return a value inspect-petri can resolve to seeds.

    When ``seed_select`` is a hierarchical seed tree, populate (or
    reuse) a staging dir of symlinks and return that path. When it's
    a sentinel string (``id:<...>`` / ``tags:<...>``) or otherwise
    not a hierarchical tree, return the input unchanged so
    inspect-petri's native handling kicks in.

    Strings stay strings; paths stay paths — the caller renders the
    final value via f-string for the inspect eval CLI.
    """
    # Sentinel strings — never touch the filesystem.
    if isinstance(seed_select, str) and seed_select.startswith(("id:", "tags:")):
        return seed_select
    path = Path(seed_select).expanduser()
    if not path.exists() or not is_hierarchical_seed_tree(path):
        # Pass through unchanged — non-existent paths fail at
        # inspect-petri's boundary with a clearer error message.
        return seed_select if isinstance(seed_select, str) else path
    path = path.resolve()
    stage = _stage_dir(path)
    _populate_stage(path, stage)
    log.info(
        "seed_tree: flattened %s → %s (%d files)",
        path,
        stage,
        sum(1 for _ in stage.iterdir()),
    )
    return stage
