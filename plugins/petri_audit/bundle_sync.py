"""Sync newly-archived ``.eval`` logs from the agent context layer
(``~/.geode/petri/logs/``) into the repo-tracked bundle
(``docs/petri-bundle/logs/``) so the Pages publish stays fresh.

Wired into :func:`plugins.petri_audit.cli_audit._post_run_emit` so every
successful audit auto-syncs its archived ``.eval`` to the bundle dir and
refreshes ``listing.json``. The runtime dir at ``~/.geode/petri/logs/`` is
the agent context SoT (per-machine, accumulating); the bundle dir at
``docs/petri-bundle/`` is the repo-tracked publish surface (committable,
Pages-served).

Bypass via ``GEODE_PETRI_BUNDLE_SYNC_DISABLED=1`` — useful for test fixtures
or operators who curate the bundle manually. Best-effort: any failure logs
a warning and returns ``None`` rather than breaking the audit return path.

Schema for ``listing.json`` entries matches the inspect-ai viewer contract:
``eval_id`` / ``run_id`` / ``task`` / ``task_id`` / ``task_version`` /
``version`` / ``status`` / ``invalidated`` / ``model`` / ``model_roles`` /
``started_at`` / ``completed_at`` / ``primary_metric``. ``model_roles`` is
flattened from inspect-ai's nested ``{role: {model, config, args}}`` shape
to the viewer's expected ``{role: model_id}`` shape. ``primary_metric``
picks the first scorer's first metric (typically ``mean``) — same heuristic
inspect-ai's own viewer uses for the cold-start summary.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import zipfile
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

__all__ = [
    "BUNDLE_LOGS_DIR",
    "RUNTIME_LOGS_DIR",
    "sync_eval_to_bundle",
]

#: Agent context layer — per-machine runtime accumulation.
RUNTIME_LOGS_DIR: Path = Path.home() / ".geode" / "petri" / "logs"

#: Repo-tracked bundle — committable, Pages-served.
#: Resolved relative to this module's path so it works from any cwd.
_REPO_ROOT: Path = Path(__file__).resolve().parents[2]
BUNDLE_LOGS_DIR: Path = _REPO_ROOT / "docs" / "petri-bundle" / "logs"

_LISTING_FILENAME = "listing.json"

# zstd entries inside .eval require the zipfile-zstd monkey-patch on
# Python < 3.14. Try to import it once at module load; on failure the
# listing entry is built from filename-only (still copyable, but the
# row in the viewer's index loses model_roles / metric until a future
# run regenerates the full entry).
try:
    import zipfile_zstd  # type: ignore[import-untyped]  # noqa: F401 — patches zipfile

    _ZSTD_AVAILABLE = True
except ImportError:
    import sys

    _ZSTD_AVAILABLE = sys.version_info >= (3, 14)


def sync_eval_to_bundle(eval_path: Path | str) -> Path | None:
    """Copy one ``.eval`` to the bundle dir + merge a listing entry.

    Returns the destination path on success, ``None`` when the sync was
    skipped (env knob set, source missing, or unrecoverable error).
    Idempotent — re-syncing the same ``.eval`` overwrites the file and
    refreshes the listing entry in place.
    """
    if os.environ.get("GEODE_PETRI_BUNDLE_SYNC_DISABLED") == "1":
        log.debug("bundle_sync: GEODE_PETRI_BUNDLE_SYNC_DISABLED=1, skipping")
        return None

    src = Path(eval_path).resolve()
    if not src.is_file():
        log.warning("bundle_sync: source missing: %s", src)
        return None
    if src.suffix != ".eval":
        log.warning("bundle_sync: not a .eval file: %s", src)
        return None

    try:
        BUNDLE_LOGS_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        log.warning("bundle_sync: cannot create bundle dir %s: %s", BUNDLE_LOGS_DIR, exc)
        return None

    dst = BUNDLE_LOGS_DIR / src.name
    try:
        shutil.copy2(src, dst)
    except OSError as exc:
        log.warning("bundle_sync: copy failed %s → %s: %s", src, dst, exc)
        return None

    try:
        entry = _extract_listing_entry(dst)
        _merge_listing(BUNDLE_LOGS_DIR / _LISTING_FILENAME, dst.name, entry)
    except Exception:
        log.warning("bundle_sync: listing update failed for %s", dst, exc_info=True)
        # File copy already succeeded — return dst so caller knows
        # the .eval is in place even if the index couldn't be updated.

    log.info("bundle_sync: %s → %s", src.name, dst)
    return dst


def _extract_listing_entry(eval_path: Path) -> dict[str, Any]:
    """Read ``.eval`` header.json and shape it into a listing.json entry."""
    if not _ZSTD_AVAILABLE:
        # No header decompression available — minimal entry from filename.
        return {"status": "unknown", "model": "none/none"}

    with zipfile.ZipFile(eval_path) as zf, zf.open("header.json") as fp:
        header = json.loads(fp.read())

    eval_block = header.get("eval", {})
    stats = header.get("stats", {})
    results = header.get("results", {})

    # Flatten inspect-ai's nested model_roles {role: {model, ...}} to the
    # viewer's expected {role: model_id} shape.
    raw_roles = eval_block.get("model_roles") or {}
    flat_roles: dict[str, str] = {}
    for role, spec in raw_roles.items():
        if isinstance(spec, dict) and "model" in spec:
            flat_roles[role] = spec["model"]
        elif isinstance(spec, str):
            flat_roles[role] = spec

    # primary_metric — first scorer's first metric (viewer's own heuristic).
    primary_metric: dict[str, Any] = {}
    scores = results.get("scores") or []
    if scores:
        first_metrics = scores[0].get("metrics") or {}
        if isinstance(first_metrics, dict) and first_metrics:
            first_name = next(iter(first_metrics))
            primary_metric = first_metrics[first_name]
        elif isinstance(first_metrics, list) and first_metrics:
            primary_metric = first_metrics[0]

    entry: dict[str, Any] = {
        "eval_id": eval_block.get("eval_id", ""),
        "run_id": eval_block.get("run_id", ""),
        "task": eval_block.get("task", ""),
        "task_id": eval_block.get("task_id", ""),
        "task_version": eval_block.get("task_version", 0),
        "version": header.get("version", 0),
        "status": header.get("status", "unknown"),
        "invalidated": header.get("invalidated", False),
        "model": eval_block.get("model", "none/none"),
        "model_roles": flat_roles,
        "started_at": stats.get("started_at", ""),
        "completed_at": stats.get("completed_at", ""),
        "primary_metric": primary_metric,
    }
    return entry


def _merge_listing(listing_path: Path, filename: str, entry: dict[str, Any]) -> None:
    """Read existing listing.json, set/overwrite one entry, write back.

    Preserves existing entries — only the keyed filename's entry is replaced.
    Creates listing.json with the single new entry if absent.
    """
    listing: dict[str, dict[str, Any]] = {}
    if listing_path.is_file():
        try:
            existing = json.loads(listing_path.read_text(encoding="utf-8"))
            if isinstance(existing, dict):
                listing = existing
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("bundle_sync: cannot parse existing listing %s: %s", listing_path, exc)
            # Continue with empty listing — the entry being merged will
            # bootstrap a fresh, valid listing.json on the next write.

    listing[filename] = entry
    listing_path.write_text(json.dumps(listing, indent=2) + "\n", encoding="utf-8")
