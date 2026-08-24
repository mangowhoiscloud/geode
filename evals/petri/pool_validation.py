"""Read and validate seed-pool target-dimension metadata."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import yaml


def _seed_target_dims(seed_md: Path) -> list[str]:
    """Return normalized ``target_dims`` from one seed's YAML frontmatter."""
    try:
        parts = seed_md.read_text(encoding="utf-8").split("---")
    except OSError:
        return []
    if len(parts) < 3 or parts[0].strip():
        return []
    try:
        frontmatter = yaml.safe_load(parts[1])
    except yaml.YAMLError:
        return []
    if not isinstance(frontmatter, dict):
        return []
    raw = frontmatter.get("target_dims") or []
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, (list, tuple)):
        return []
    return [str(dim).strip() for dim in raw if str(dim).strip()]


def validate_pool_target_dims(
    pool_dir: Path | str, live_dims: Iterable[str]
) -> dict[str, list[str]]:
    """Return seed-relative paths mapped to target dimensions absent from ``live_dims``."""
    live = frozenset(live_dims)
    pool = Path(pool_dir)
    if not pool.is_dir():
        return {}
    offending: dict[str, list[str]] = {}
    for seed_md in sorted(pool.rglob("*.md")):
        stale = [dim for dim in _seed_target_dims(seed_md) if dim not in live]
        if stale:
            offending[str(seed_md.relative_to(pool))] = stale
    return offending


__all__ = ["_seed_target_dims", "validate_pool_target_dims"]
