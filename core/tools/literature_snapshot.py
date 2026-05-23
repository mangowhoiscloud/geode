"""Literature snapshot writer — Loop 3 (paper-analysis) of the seed-generation 3-loop port.

Background
==========

open-coscientist (``nodes/literature_review.py:840-873``) runs an
N-paper analysis loop inside its ``literature_review`` node. Each
fetched paper hits a per-paper LLM call (``_analyze_single_paper``)
and the dispatcher uses ``asyncio.gather`` to fan out. The papers
themselves come from external arXiv / PubMed fetches.

GEODE's port (PR-CSP-14, 2026-05-23) preserves this loop semantically
but wraps each fetch in a **git-tracked snapshot** so audit replay
remains reproducible even though the loop reaches outside the
closed-loop autoresearch state. See
``docs/plans/2026-05-23-seed-gen-loop3-bundle-serving.md`` § 4 for
the snapshot storage decision tree (`Option 2 + snapshot freeze`).

This tool is the writer. The ``LiteratureReview`` agent's sub-agent
calls ``freeze_paper_snapshot`` once per fetched paper. The tool:

- validates the arxiv_id pattern,
- computes a deterministic ``content_hash`` over the normalized
  abstract,
- short-circuits on cache hit (same arxiv_id + same content_hash),
- atomically writes the snapshot JSON to
  ``docs/petri-bundle/literature/<arxiv_id>-<retrieved_at>.json``,
- enforces path containment so the LLM cannot redirect writes.

Cache hit semantics
===================

If a snapshot file already exists for ``<arxiv_id>`` and the
``content_hash`` (computed over the *new* abstract) matches the
hash on disk, the tool returns ``cache_hit=True`` without writing.
This makes a re-run with no new arxiv churn near-zero LLM cost (the
LiteratureReview agent's Phase 3 ``per_paper_analysis`` insights are
also keyed on ``(arxiv_id, target_dim)`` upstream so the chain
collapses).

Bounds + safety (Phase 1 PR-CSP-13 lessons applied)
====================================================

- ``arxiv_id`` must match ``^\\d{4}\\.\\d{4,5}(v\\d+)?$``.
- ``snapshot_path`` is derived inside the tool — the LLM passes
  the fields, not the path. Prevents arbitrary disk writes via tool
  surface even on hallucinated paths.
- Atomic write (``tmp + rename``) so a crashed editor never leaves a
  partial json.
- Path containment: resolved snapshot must live under
  ``<repo_root>/docs/petri-bundle/literature/``.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

__all__ = ["FreezePaperSnapshotTool", "compute_content_hash"]


_ARXIV_ID_RE = re.compile(r"^\d{4}\.\d{4,5}(v\d+)?$")
_SNAPSHOT_DIR_NAME = "docs/petri-bundle/literature"


def compute_content_hash(abstract: str) -> str:
    """Deterministic sha256 over the normalized abstract.

    Normalization: lower-case + strip leading/trailing whitespace +
    collapse internal whitespace. Title + categories changes do NOT
    affect the hash — only the substantive content (abstract). This
    matches the Phase 2 SoT § 4.3 contract: re-fetch only when the
    abstract text changes.
    """
    normalized = " ".join(abstract.strip().lower().split())
    return "sha256:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _resolve_snapshot_root() -> Path:
    """Locate the docs/petri-bundle/literature/ directory.

    Resolution order:
      1. ``GEODE_REPO_ROOT`` env var (test fixture override) →
         ``<root>/docs/petri-bundle/literature``
      2. Working directory ancestor that contains ``pyproject.toml``.
      3. Last-resort cwd.

    Tests monkeypatch via env var to point at a tmp dir.
    """
    env_root = os.environ.get("GEODE_REPO_ROOT", "").strip()
    if env_root:
        return Path(env_root) / _SNAPSHOT_DIR_NAME
    here = Path.cwd().resolve()
    for ancestor in [here, *here.parents]:
        if (ancestor / "pyproject.toml").is_file():
            return ancestor / _SNAPSHOT_DIR_NAME
    return here / _SNAPSHOT_DIR_NAME


def _find_existing_snapshot(snapshot_root: Path, arxiv_id: str) -> Path | None:
    """Glob the literature dir for an existing snapshot matching arxiv_id.

    File name pattern: ``<arxiv_id>-<retrieved_at>.json``. Multiple
    snapshots for the same arxiv_id can exist (re-fetches with different
    abstracts); the LATEST one wins for cache-hit comparison.
    Returns ``None`` when no snapshot exists.
    """
    if not snapshot_root.is_dir():
        return None
    matches = sorted(snapshot_root.glob(f"{arxiv_id}-*.json"))
    return matches[-1] if matches else None


class FreezePaperSnapshotTool:
    """Freeze one arXiv paper fetch into a git-tracked snapshot file."""

    @property
    def name(self) -> str:
        return "freeze_paper_snapshot"

    @property
    def description(self) -> str:
        return (
            "Freeze one fetched arXiv paper into a git-tracked JSON snapshot "
            "under docs/petri-bundle/literature/. Call once per paper after "
            "arxiv_search + paper_fetch_arxiv. Computes a content_hash over the "
            "normalized abstract; returns cache_hit=true when an existing "
            "snapshot for the same arxiv_id has a matching hash (no rewrite). "
            "Refuses arxiv_id that doesn't match the arXiv pattern and paths "
            "that escape the bundle root. Used by the seed-generation Loop 3 "
            "(literature_review) per-paper analysis loop."
        )

    async def aexecute(self, **kwargs: Any) -> dict[str, Any]:
        """Async entry — sync body via to_thread (only local JSON write)."""
        return await asyncio.to_thread(self._execute_sync, **kwargs)

    def _execute_sync(self, **kwargs: Any) -> dict[str, Any]:
        try:
            arxiv_id = str(kwargs["arxiv_id"]).strip()
            title = str(kwargs["title"]).strip()
            abstract = str(kwargs["abstract"]).strip()
            authors = kwargs.get("authors", []) or []
            categories = kwargs.get("categories", []) or []
            published_at = str(kwargs.get("published_at", "")).strip()
            pdf_url = str(kwargs.get("pdf_url", "")).strip()
        except (KeyError, TypeError, ValueError) as exc:
            return {
                "result": {
                    "ok": False,
                    "error": f"missing or malformed arg: {exc}",
                }
            }

        if not _ARXIV_ID_RE.match(arxiv_id):
            return {
                "result": {
                    "ok": False,
                    "error": (
                        f"arxiv_id {arxiv_id!r} does not match arXiv pattern "
                        f"(expected NNNN.NNNN[N][vN]); refusing snapshot"
                    ),
                }
            }
        if not title or not abstract:
            return {
                "result": {
                    "ok": False,
                    "error": "title and abstract must both be non-empty",
                }
            }

        snapshot_root = _resolve_snapshot_root()
        try:
            snapshot_root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return {
                "result": {
                    "ok": False,
                    "error": f"failed to create snapshot dir: {exc}",
                }
            }

        # Containment check — resolved snapshot dir must end with the
        # canonical relative path. Prevents an env override that points
        # at, say, /tmp from being mistaken for the repo bundle.
        resolved = snapshot_root.resolve()
        if not str(resolved).endswith(_SNAPSHOT_DIR_NAME):
            return {
                "result": {
                    "ok": False,
                    "error": (
                        f"snapshot dir {resolved!s} does not end with "
                        f"{_SNAPSHOT_DIR_NAME!r}; refusing to write"
                    ),
                }
            }

        content_hash = compute_content_hash(abstract)
        existing = _find_existing_snapshot(snapshot_root, arxiv_id)
        if existing is not None:
            try:
                prior = json.loads(existing.read_text(encoding="utf-8"))
                if prior.get("content_hash") == content_hash:
                    return {
                        "result": {
                            "ok": True,
                            "cache_hit": True,
                            "snapshot_path": str(existing),
                            "content_hash": content_hash,
                            "note": (
                                "existing snapshot has matching content_hash; skipping rewrite"
                            ),
                        }
                    }
            except (OSError, json.JSONDecodeError) as exc:
                log.warning(
                    "freeze_paper_snapshot: prior snapshot %s unreadable: %s",
                    existing,
                    exc,
                )

        retrieved_at = datetime.now(UTC).isoformat(timespec="seconds")
        retrieved_at_compact = retrieved_at.replace(":", "").replace("-", "").replace("+0000", "Z")
        # Codex MCP MEDIUM fix-up — same-arxiv concurrent writes inside the
        # same second collided on the deterministic ``retrieved_at`` stamp.
        # Add a short uuid hex nonce so both the final + tmp paths stay
        # unique. Cache-hit semantics unaffected (those run on the abstract
        # content_hash, not the path).
        nonce = uuid.uuid4().hex[:6]
        snapshot_path = snapshot_root / f"{arxiv_id}-{retrieved_at_compact}-{nonce}.json"

        # Final containment check on the resolved target.
        target_resolved = snapshot_path.resolve()
        if snapshot_root.resolve() not in target_resolved.parents:
            return {
                "result": {
                    "ok": False,
                    "error": (
                        f"snapshot path {target_resolved!s} escapes the "
                        f"literature bundle root; refusing to write"
                    ),
                }
            }

        payload: dict[str, Any] = {
            "arxiv_id": arxiv_id,
            "title": title,
            "abstract": abstract,
            "authors": list(authors),
            "categories": list(categories),
            "published_at": published_at or None,
            "retrieved_at": retrieved_at,
            "content_hash": content_hash,
            "arxiv_url": f"https://arxiv.org/abs/{arxiv_id}",
            "pdf_url": pdf_url or None,
            "cited_by": {},
        }

        try:
            tmp = snapshot_path.with_suffix(".json.tmp")
            tmp.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            tmp.replace(snapshot_path)
        except OSError as exc:
            return {
                "result": {
                    "ok": False,
                    "error": f"failed to write snapshot: {exc}",
                }
            }

        return {
            "result": {
                "ok": True,
                "cache_hit": False,
                "snapshot_path": str(snapshot_path),
                "content_hash": content_hash,
            }
        }
