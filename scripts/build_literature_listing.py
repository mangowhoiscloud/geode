"""Build ``docs/self-improving/petri-bundle/literature/listing.json`` from individual snapshots.

Run from Pages workflow (and locally via ``uv run python scripts/build_literature_listing.py``).

Algorithm (per ``docs/plans/2026-05-23-seed-gen-loop3-bundle-serving.md`` § 6):

1. Scan ``docs/self-improving/petri-bundle/literature/*.json`` (skip ``listing.json``).
2. For each snapshot, extract the lightweight row fields (arxiv_id, title,
   retrieved_at, content_hash short, categories, url).
3. Scan ``autoresearch/state/mutations.jsonl`` (if present) for evidence
   rows that cite snapshots (defensive parser — handles both the typed-
   array shape from the petri-autoresearch session AND the flat-shape
   pre-realign).
4. Scan seed candidate frontmatter for ``references: [arxiv_id, ...]``
   so seed-gen citations also flow into the reverse index.
5. Merge cited_by counts into the rows.
6. Atomic write to ``listing.json`` with deterministic ordering.

Idempotency: a re-run with no new snapshots + no new citations produces
byte-identical ``listing.json``.

Exit codes:
  0 — listing built (or no-op when no snapshots).
  1 — fatal I/O error.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

LITERATURE_DIR = "docs/self-improving/petri-bundle/literature"
MUTATIONS_LOG = "autoresearch/state/mutations.jsonl"
SEED_GLOB = "plugins/petri_audit/seeds_gen*/**/*.md"
LISTING_FILENAME = "listing.json"


def _resolve_repo_root() -> Path:
    """Locate the repo root.

    Resolution order: ``GEODE_REPO_ROOT`` env (test fixtures), then the
    ancestor that contains ``pyproject.toml`` from CWD, then last-resort
    CWD.
    """
    env_root = os.environ.get("GEODE_REPO_ROOT", "").strip()
    if env_root:
        return Path(env_root)
    here = Path.cwd().resolve()
    for ancestor in [here, *here.parents]:
        if (ancestor / "pyproject.toml").is_file():
            return ancestor
    return here


def _load_snapshots(literature_dir: Path) -> list[dict[str, Any]]:
    """Return parsed snapshot dicts, skipping listing.json + unreadable files."""
    if not literature_dir.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(literature_dir.glob("*.json")):
        if path.name == LISTING_FILENAME:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("build_literature_listing: skip unreadable %s: %s", path, exc)
            continue
        if not isinstance(data, dict) or "arxiv_id" not in data:
            log.warning("build_literature_listing: skip non-snapshot %s", path)
            continue
        # Carry the file name so the listing row's ``url`` field stays
        # stable across content_hash re-fetches (a re-snapshot writes a
        # new file with a fresh retrieved_at suffix, but the row points
        # at that latest file).
        data["__source_path"] = path
        rows.append(data)
    return rows


def _scan_mutations_citations(mutations_log: Path) -> dict[str, list[dict[str, str]]]:
    """Scan mutations.jsonl for arxiv_id citations.

    Returns ``{arxiv_id: [{gen_tag, mutation_id, run_id}, ...]}``.

    Defensive parser — handles BOTH expected evidence shapes:

    - Typed array (post petri-autoresearch realign):
      ``"evidence": [{"kind": "literature_snapshot", "arxiv_id": "..."}, ...]``
    - Flat shape (pre-realign): no per-mutation arxiv_id reference.

    Missing or malformed mutations.jsonl → empty dict (the listing
    still builds, just with empty ``cited_by`` per snapshot).
    """
    index: dict[str, list[dict[str, str]]] = {}
    if not mutations_log.is_file():
        return index
    try:
        lines = mutations_log.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        log.warning("build_literature_listing: mutations log unreadable: %s", exc)
        return index
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        evidence = row.get("evidence")
        if not isinstance(evidence, list):
            continue
        for ev in evidence:
            if not isinstance(ev, dict):
                continue
            if ev.get("kind") != "literature_snapshot":
                continue
            arxiv_id = ev.get("arxiv_id")
            if not isinstance(arxiv_id, str) or not arxiv_id:
                continue
            citers = index.setdefault(arxiv_id, [])
            citers.append(
                {
                    "gen_tag": str(row.get("gen_tag", "")),
                    "mutation_id": str(row.get("mutation_id", row.get("id", ""))),
                    "run_id": str(row.get("run_id", "")),
                }
            )
    return index


def _scan_seed_frontmatter_citations(repo_root: Path) -> dict[str, list[dict[str, str]]]:
    """Scan seed candidate ``references:`` frontmatter for arxiv_id citations.

    The CSP-3 generator.md spec asks the LLM to populate ``references:``
    in the frontmatter of each seed. We grep for that field across
    ``plugins/petri_audit/seeds_gen*/``. Best-effort — the frontmatter
    is YAML but we don't pull yaml in here; a simple line-based scan
    of ``references:`` + ``arxiv_id`` strings is enough.

    Returns ``{arxiv_id: [{seed_id, target_dim}, ...]}``.
    """
    index: dict[str, list[dict[str, str]]] = {}
    for seed_path in sorted(repo_root.glob(SEED_GLOB)):
        try:
            text = seed_path.read_text(encoding="utf-8")
        except OSError:
            continue
        # Crude but sufficient: find an arxiv_id pattern inside the file.
        # The frontmatter is at the top so we can stop at the second '---'.
        head, _, _ = text.partition("\n---\n")
        # If the file has no frontmatter, partition returns the whole text
        # as ``head``; that's still safe to grep but typically yields nothing.
        if "references:" not in head:
            continue
        import re as _re

        # Match arxiv-pattern strings — same shape as the snapshot tool.
        for match in _re.finditer(r'"(\d{4}\.\d{4,5}(?:v\d+)?)"', head):
            arxiv_id = match.group(1)
            citers = index.setdefault(arxiv_id, [])
            citers.append(
                {
                    "seed_id": seed_path.stem,
                    "target_dim": _extract_target_dim(head),
                }
            )
    return index


def _extract_target_dim(frontmatter_head: str) -> str:
    """Best-effort target_dim extraction from frontmatter head."""
    import re as _re

    match = _re.search(r"^target_dim:\s*(\S+)", frontmatter_head, _re.MULTILINE)
    return match.group(1).strip("\"'") if match else ""


def _build_row(
    snapshot: dict[str, Any],
    literature_dir: Path,
    mutation_citations: dict[str, list[dict[str, str]]],
    seed_citations: dict[str, list[dict[str, str]]],
) -> dict[str, Any]:
    """Build one listing row from a snapshot + reverse-index lookups."""
    arxiv_id = snapshot["arxiv_id"]
    content_hash = snapshot.get("content_hash", "")
    content_hash_short = (
        content_hash.removeprefix("sha256:")[:8] + "…" + content_hash[-4:]
        if content_hash and len(content_hash) > 16
        else content_hash
    )
    source_path: Path = snapshot["__source_path"]
    # ``url`` is a relative path under ``docs/self-improving/petri-bundle/`` so the
    # Next.js export resolves it without an absolute prefix.
    rel = source_path.relative_to(literature_dir.parent)
    mut_citers = mutation_citations.get(arxiv_id, [])
    seed_citers = seed_citations.get(arxiv_id, [])
    return {
        "arxiv_id": arxiv_id,
        "title": snapshot.get("title", ""),
        "retrieved_at": snapshot.get("retrieved_at", ""),
        "content_hash_short": content_hash_short,
        "categories": list(snapshot.get("categories", []) or []),
        "url": str(rel),
        "cited_by_count": len(mut_citers) + len(seed_citers),
        "cited_by": {
            "mutations": mut_citers,
            "seeds": seed_citers,
        },
    }


def build_listing(
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Build the listing dict (does not write to disk)."""
    root = repo_root or _resolve_repo_root()
    literature_dir = root / LITERATURE_DIR
    snapshots = _load_snapshots(literature_dir)
    mutation_citations = _scan_mutations_citations(root / MUTATIONS_LOG)
    seed_citations = _scan_seed_frontmatter_citations(root)
    rows = [_build_row(s, literature_dir, mutation_citations, seed_citations) for s in snapshots]
    # Deterministic ordering: by arxiv_id then retrieved_at.
    rows.sort(key=lambda r: (r["arxiv_id"], r["retrieved_at"]))
    return {
        "kind": "literature",
        "count": len(rows),
        "snapshots": rows,
    }


def write_listing(repo_root: Path | None = None) -> Path | None:
    """Build the listing and write it to the bundle's literature directory.

    Output: ``docs/self-improving/petri-bundle/literature/listing.json``.

    Returns the path written, or ``None`` if the literature dir doesn't
    exist (no snapshots yet — the build step is a no-op until Loop 3
    actually runs).
    """
    root = repo_root or _resolve_repo_root()
    literature_dir = root / LITERATURE_DIR
    if not literature_dir.is_dir():
        return None
    listing = build_listing(root)
    listing_path = literature_dir / LISTING_FILENAME
    # Atomic write — tmp then rename so a concurrent read never sees a
    # partial JSON.
    tmp = listing_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(listing, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(listing_path)
    return listing_path


def main(argv: list[str] | None = None) -> int:
    """CLI entry: build the listing + log the count."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        path = write_listing()
    except OSError as exc:
        log.error("build_literature_listing: write failed: %s", exc)
        return 1
    if path is None:
        log.info("build_literature_listing: no literature dir; nothing to do")
        return 0
    listing = json.loads(path.read_text(encoding="utf-8"))
    log.info(
        "build_literature_listing: wrote %d snapshots → %s",
        listing["count"],
        path.relative_to(_resolve_repo_root()),
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry
    sys.exit(main(sys.argv[1:]))
