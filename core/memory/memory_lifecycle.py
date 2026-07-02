"""Project-memory lifecycle — evidence-based decay + HITL promotion proposals.

Project memory accumulates one-file-per-insight markdown entries (the same
frontmatter-then-body convention the memory-recall reader uses) with no
lifecycle: resolved defect insights keep getting injected forever and the
same insight re-appears across sessions. This module adds two coupled,
non-destructive mechanisms:

1. **Resolution metadata + decay** — an entry may declare how it was
   resolved in its frontmatter::

       ---
       name: defect-cron-double-fire
       description: CRON jobs fired twice in the same minute.
       metadata:
         type: defect
       resolution:
         pr: "#2412"
         guard_test: tests/core/scheduler/test_scheduler.py::test_cron_dedup
         resolved_at: 2026-06-20T09:00:00
       ---

       body...

   :func:`evaluate_decay` archives an entry **iff** the referenced guard
   test still exists in the tree (static ``ast`` parse of the test file —
   never runs pytest). If the guard test disappeared, the verdict is
   ``resurface``: the memory becomes active again and a WARNING is logged,
   because the regression pin that justified archiving is gone. There is
   NO time-based decay. Archived entries move to ``<memory_dir>/_archive/``
   (file kept, excluded from prompt injection — every injection reader
   walks ``glob("*.md")`` non-recursively, pinned by tests).

2. **Dedup + promotion proposal** — :func:`propose_memory_promotions`
   clusters ``context_artifacts`` dream rows (written by
   :mod:`core.memory.dreaming`) together with active project-memory
   entries by token-Jaccard overlap. When one insight cluster spans >= 3
   DISTINCT sessions, a HITL proposal file is written to
   ``<memory_dir>/_proposals/<slug>.md`` and
   ``HookEvent.MEMORY_PROMOTION_PROPOSED`` fires. Promotion into
   ``.geode/rules/`` or ``PROJECT.md`` is NEVER automatic — project rules
   inject into every turn's prompt (high blast radius), so a human applies
   or rejects the proposal.

Weekly entry point: ``geode memory-lifecycle`` (dry-run default,
``--apply`` to move files / write proposals).
"""

from __future__ import annotations

import ast
import hashlib
import logging
import os
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from core.memory.atomic_write import atomic_write_text
from core.skills._frontmatter import _FRONTMATTER_RE

if TYPE_CHECKING:
    from core.hooks import HookSystem
    from core.memory.session_manager import SessionManager

log = logging.getLogger(__name__)

__all__ = [
    "ARCHIVE_DIR_NAME",
    "DEFAULT_JACCARD_THRESHOLD",
    "DEFAULT_MIN_SESSIONS",
    "PROPOSALS_DIR_NAME",
    "DecayVerdict",
    "LifecycleEntry",
    "PromotionProposal",
    "PromotionSource",
    "Resolution",
    "apply_decay",
    "evaluate_decay",
    "guard_test_exists",
    "load_lifecycle_entries",
    "propose_memory_promotions",
]

ARCHIVE_DIR_NAME = "_archive"
PROPOSALS_DIR_NAME = "_proposals"

# PROJECT.md is the index/context file read by ProjectMemory.load_memory(),
# not a lifecycle entry — never archive or cluster it.
_RESERVED_FILENAMES = frozenset({"PROJECT.md"})

DEFAULT_MIN_SESSIONS = 3
DEFAULT_JACCARD_THRESHOLD = 0.6

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]{3,}|[\uac00-\ud7a3]{2,}")  # ASCII words + Hangul runs

Verdict = Literal["active", "archived", "resurface"]


@dataclass(frozen=True, slots=True)
class Resolution:
    """Optional ``resolution:`` frontmatter block on a memory entry."""

    pr: str = ""
    guard_test: str = ""  # "tests/path.py::test_name" (or ::Class::test_name)
    resolved_at: str = ""  # ISO timestamp string (informational)


@dataclass(frozen=True, slots=True)
class LifecycleEntry:
    """One parsed project-memory entry file."""

    path: Path
    name: str
    description: str
    body: str
    sessions: tuple[str, ...]
    resolution: Resolution | None
    archived: bool  # True when the file currently lives in _archive/


@dataclass(frozen=True, slots=True)
class DecayVerdict:
    """Lifecycle verdict for one entry.

    ``archived``  — guard test exists; entry belongs in ``_archive/``.
    ``resurface`` — guard test referenced but GONE; entry belongs in the
                    active dir again (WARNING logged).
    ``active``    — no lifecycle-managed resolution; entry stays put.
    """

    entry: LifecycleEntry
    verdict: Verdict
    reason: str


@dataclass(frozen=True, slots=True)
class PromotionSource:
    """One clusterable insight source (dream artifact or memory entry)."""

    kind: str  # "dream" | "memory_entry"
    identifier: str  # artifact_id or entry file name
    session_id: str  # "" when the source has no session attribution
    text: str


@dataclass(frozen=True, slots=True)
class PromotionProposal:
    """A HITL promotion proposal (written only with ``apply=True``)."""

    slug: str
    path: Path
    session_ids: tuple[str, ...]
    sources: tuple[PromotionSource, ...]
    merged_text: str
    content: str = field(repr=False, default="")


# ---------------------------------------------------------------------------
# Entry parsing
# ---------------------------------------------------------------------------


def _parse_front_block(head: str) -> tuple[dict[str, str], dict[str, list[str]]]:
    """YAML-light frontmatter parse: flat + one-level nesting + string lists.

    Returns ``(scalars, lists)`` where nested scalars key as
    ``parent.child`` (same convention as the memory-recall reader).
    """
    scalars: dict[str, str] = {}
    lists: dict[str, list[str]] = {}
    parent: str | None = None
    for line in head.splitlines():
        if not line.strip():
            continue
        indented = line.startswith((" ", "\t"))
        stripped = line.strip()
        if indented and parent is not None:
            if stripped.startswith("- "):
                lists.setdefault(parent, []).append(stripped[2:].strip().strip("\"'"))
                continue
            key_part, sep, val_part = stripped.partition(":")
            if sep and val_part.strip():
                scalars[f"{parent}.{key_part.strip()}"] = val_part.strip().strip("\"'")
            continue
        key, sep, val = stripped.partition(":")
        if not sep:
            continue
        key = key.strip()
        val = val.strip()
        if not val:
            parent = key
            continue
        parent = None
        scalars[key] = val.strip("\"'")
    return scalars, lists


def _parse_entry(path: Path, *, archived: bool) -> LifecycleEntry | None:
    """Parse one entry file; WARN + skip on unreadable/missing frontmatter."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        log.warning("memory_lifecycle: %s unreadable: %s", path, exc)
        return None
    match = _FRONTMATTER_RE.match(raw)
    if not match:
        log.warning("memory_lifecycle: %s has no frontmatter; skipping", path)
        return None
    scalars, lists = _parse_front_block(match.group(1))
    resolution: Resolution | None = None
    if any(key.startswith("resolution.") for key in scalars):
        resolution = Resolution(
            pr=scalars.get("resolution.pr", ""),
            guard_test=scalars.get("resolution.guard_test", ""),
            resolved_at=scalars.get("resolution.resolved_at", ""),
        )
    return LifecycleEntry(
        path=path,
        name=scalars.get("name", path.stem),
        description=scalars.get("description", ""),
        body=match.group(2).strip(),
        sessions=tuple(lists.get("sessions", [])),
        resolution=resolution,
        archived=archived,
    )


def load_lifecycle_entries(
    memory_dir: Path,
    *,
    include_archived: bool = True,
) -> list[LifecycleEntry]:
    """Load entry files from ``memory_dir`` (active) and ``_archive/``.

    ``PROJECT.md`` and the ``_proposals/`` dir are never entries. The glob
    is deliberately non-recursive — subdirectories are lifecycle-owned.
    """
    entries: list[LifecycleEntry] = []
    if memory_dir.is_dir():
        for path in sorted(memory_dir.glob("*.md")):
            if path.name in _RESERVED_FILENAMES:
                continue
            parsed = _parse_entry(path, archived=False)
            if parsed is not None:
                entries.append(parsed)
    archive_dir = memory_dir / ARCHIVE_DIR_NAME
    if include_archived and archive_dir.is_dir():
        for path in sorted(archive_dir.glob("*.md")):
            parsed = _parse_entry(path, archived=True)
            if parsed is not None:
                entries.append(parsed)
    return entries


# ---------------------------------------------------------------------------
# Decay — guard-test existence check (static parse, never pytest)
# ---------------------------------------------------------------------------


def guard_test_exists(guard_test: str, *, repo_root: Path) -> bool:
    """True iff ``tests/file.py::[Class::]test_name`` exists in the tree.

    Existence = the file parses and defines a (sync or async) function with
    that name — inside the named class when one is given. Parametrize ids
    (``test_x[case]``) are stripped. This is a static ``ast`` check; running
    pytest here would be a cost/side-effect violation.
    """
    file_part, sep, rest = guard_test.partition("::")
    if not sep or not rest:
        return False
    # Sanitize: the guard path is untrusted frontmatter — reject absolute
    # paths and traversal so evidence can only come from inside the repo.
    candidate = Path(file_part)
    if candidate.is_absolute() or ".." in candidate.parts:
        log.warning("memory_lifecycle: rejecting suspicious guard path %r", file_part)
        return False
    test_file = (repo_root / candidate).resolve()
    try:
        test_file.relative_to(repo_root.resolve())
    except ValueError:
        log.warning("memory_lifecycle: guard path escapes repo root: %r", file_part)
        return False
    if not test_file.is_file():
        return False
    try:
        tree = ast.parse(test_file.read_text(encoding="utf-8"))
    except (OSError, SyntaxError) as exc:
        log.warning("memory_lifecycle: guard test file %s unparseable: %s", test_file, exc)
        return False
    parts = rest.split("::")
    func_name = parts[-1].split("[", 1)[0]
    class_name = parts[0] if len(parts) > 1 else ""

    def _direct_child_defines(body: list[ast.stmt]) -> bool:
        # Direct children only — a method inside some class must not satisfy a
        # module-level guard reference (and vice versa).
        return any(
            isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef) and child.name == func_name
            for child in body
        )

    if class_name:
        return any(
            isinstance(node, ast.ClassDef)
            and node.name == class_name
            and _direct_child_defines(node.body)
            for node in tree.body
        )
    return _direct_child_defines(tree.body)


def evaluate_decay(
    entries: list[LifecycleEntry],
    *,
    repo_root: Path,
) -> list[DecayVerdict]:
    """Evidence-based decay verdicts. No time-based decay.

    An entry with ``resolution.guard_test`` set is ``archived`` iff that
    test exists; a vanished guard test yields ``resurface`` + WARNING.
    Entries without a guard test are ``active`` (lifecycle leaves manually
    archived files where the operator put them).
    """
    verdicts: list[DecayVerdict] = []
    for entry in entries:
        guard = entry.resolution.guard_test if entry.resolution else ""
        if not guard:
            verdicts.append(
                DecayVerdict(
                    entry=entry,
                    verdict="archived" if entry.archived else "active",
                    reason="no resolution.guard_test — not lifecycle-managed",
                )
            )
            continue
        if guard_test_exists(guard, repo_root=repo_root):
            verdicts.append(
                DecayVerdict(
                    entry=entry,
                    verdict="archived",
                    reason=f"guard test exists: {guard}",
                )
            )
            continue
        log.warning(
            "memory_lifecycle: guard test %s referenced by %s no longer exists — "
            "resurfacing the memory",
            guard,
            entry.path,
        )
        verdicts.append(
            DecayVerdict(
                entry=entry,
                verdict="resurface",
                reason=f"guard test missing: {guard}",
            )
        )
    return verdicts


def apply_decay(verdicts: list[DecayVerdict], *, memory_dir: Path) -> list[tuple[Path, Path]]:
    """Move entry files to match their verdicts. Idempotent.

    Returns ``(src, dst)`` pairs for every move performed. A destination
    collision fails loud (two different entries may not share a filename
    across active/_archive).
    """
    archive_dir = memory_dir / ARCHIVE_DIR_NAME
    moves: list[tuple[Path, Path]] = []
    for verdict in verdicts:
        entry = verdict.entry
        if verdict.verdict == "archived" and not entry.archived:
            archive_dir.mkdir(parents=True, exist_ok=True)
            dst = archive_dir / entry.path.name
        elif verdict.verdict == "resurface" and entry.archived:
            dst = memory_dir / entry.path.name
        else:
            continue  # already in the right place — idempotent no-op
        if os.path.lexists(dst):
            raise FileExistsError(
                f"memory_lifecycle: refusing to overwrite {dst} while moving {entry.path}"
            )
        entry.path.rename(dst)
        moves.append((entry.path, dst))
        log.info("memory_lifecycle: %s -> %s (%s)", entry.path, dst, verdict.verdict)
    return moves


# ---------------------------------------------------------------------------
# Dedup + promotion proposals
# ---------------------------------------------------------------------------


def _tokenize(text: str) -> set[str]:
    return {tok.lower() for tok in _TOKEN_RE.findall(text)}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def cluster_sources(
    sources: list[PromotionSource],
    *,
    threshold: float = DEFAULT_JACCARD_THRESHOLD,
) -> list[list[PromotionSource]]:
    """Greedy token-Jaccard clustering.

    ponytail: single-pass greedy clustering against each cluster's FIRST
    member is the deliberate ceiling here — pure-python token Jaccard misses
    paraphrases and can split a cluster when the seed member is
    unrepresentative. Good enough for near-duplicate defect insights;
    embeddings are an explicit non-goal (no new dependency).
    """
    clusters: list[tuple[set[str], list[PromotionSource]]] = []
    for source in sources:
        tokens = _tokenize(source.text)
        for seed_tokens, members in clusters:
            if _jaccard(tokens, seed_tokens) >= threshold:
                members.append(source)
                break
        else:
            clusters.append((tokens, [source]))
    return [members for _, members in clusters]


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:48] or "memory-promotion"


def _render_proposal(
    slug: str,
    cluster: list[PromotionSource],
    session_ids: tuple[str, ...],
    *,
    now_iso: str,
) -> tuple[str, str]:
    """Render (merged_text, proposal file content)."""
    representative = max(cluster, key=lambda s: len(s.text))
    merged_lines = [representative.text.strip()]
    seen_firsts = {representative.text.strip().splitlines()[0] if representative.text else ""}
    for source in cluster:
        first_line = source.text.strip().splitlines()[0] if source.text.strip() else ""
        if first_line and first_line not in seen_firsts:
            seen_firsts.add(first_line)
            merged_lines.append(f"- variant ({source.kind} {source.identifier}): {first_line}")
    merged_text = "\n".join(merged_lines)

    lineage = "\n".join(
        f"- superseded_by this proposal: {source.kind} `{source.identifier}`"
        + (f" (session `{source.session_id}`)" if source.session_id else "")
        for source in cluster
    )
    sessions_block = "\n".join(f"- `{sid}`" for sid in session_ids)
    content = (
        "---\n"
        f"slug: {slug}\n"
        "status: proposed\n"
        f"created: {now_iso}\n"
        f"session_count: {len(session_ids)}\n"
        f"source_count: {len(cluster)}\n"
        "---\n\n"
        f"# Memory promotion proposal — {slug}\n\n"
        "HITL PROPOSAL. A human reviews this file and decides whether to fold\n"
        "the merged insight into `.geode/rules/` (high blast: rules inject into\n"
        "every turn's prompt). Nothing is promoted automatically.\n\n"
        "## Merged insight\n\n"
        f"{merged_text}\n\n"
        "## Source sessions\n\n"
        f"{sessions_block}\n\n"
        "## Lineage\n\n"
        f"{lineage}\n"
    )
    return merged_text, content


def propose_memory_promotions(
    *,
    memory_dir: Path,
    session_manager: SessionManager | None = None,
    min_sessions: int = DEFAULT_MIN_SESSIONS,
    threshold: float = DEFAULT_JACCARD_THRESHOLD,
    artifact_limit: int = 200,
    apply: bool = False,
    hooks: HookSystem | None = None,
) -> list[PromotionProposal]:
    """Cluster dream artifacts + active memory entries; propose promotions.

    A cluster must span >= ``min_sessions`` DISTINCT session ids (from dream
    rows / entry ``sessions:`` frontmatter) to become a proposal. With
    ``apply=True`` each proposal is written to
    ``<memory_dir>/_proposals/<slug>.md`` (deterministic slug — re-runs
    overwrite, idempotent) and ``MEMORY_PROMOTION_PROPOSED`` fires per
    proposal when ``hooks`` is provided. Never touches ``.geode/rules/`` or
    ``PROJECT.md``.
    """
    from core.memory.dreaming import DREAM_ARTIFACT_KIND

    sources: list[PromotionSource] = []
    if session_manager is not None:
        for artifact in session_manager.list_context_artifacts(
            kinds=(DREAM_ARTIFACT_KIND,),
            limit=artifact_limit,
        ):
            sources.append(
                PromotionSource(
                    kind="dream",
                    identifier=artifact.artifact_id,
                    session_id=artifact.session_id,
                    text=artifact.content,
                )
            )
    for entry in load_lifecycle_entries(memory_dir, include_archived=False):
        text = f"{entry.description}\n{entry.body}".strip()
        # One source per originating session — an entry citing N sessions must
        # contribute N toward the distinct-session promotion gate (Codex MED).
        for session_id in entry.sessions or ("",):
            sources.append(
                PromotionSource(
                    kind="memory_entry",
                    identifier=entry.path.name,
                    session_id=session_id,
                    text=text,
                )
            )

    proposals: list[PromotionProposal] = []
    now_iso = datetime.now(UTC).isoformat(timespec="seconds")
    proposals_dir = memory_dir / PROPOSALS_DIR_NAME
    for cluster in cluster_sources(sources, threshold=threshold):
        session_ids = tuple(sorted({s.session_id for s in cluster if s.session_id}))
        if len(session_ids) < min_sessions:
            continue
        representative = max(cluster, key=lambda s: len(s.text))
        digest = hashlib.sha256(
            "\n".join(sorted(s.identifier for s in cluster)).encode("utf-8")
        ).hexdigest()[:8]
        first_line = representative.text.strip().splitlines()[0] if representative.text else ""
        slug = f"{_slugify(first_line)}-{digest}"
        path = proposals_dir / f"{slug}.md"
        merged_text, content = _render_proposal(slug, cluster, session_ids, now_iso=now_iso)
        proposal = PromotionProposal(
            slug=slug,
            path=path,
            session_ids=session_ids,
            sources=tuple(cluster),
            merged_text=merged_text,
            content=content,
        )
        proposals.append(proposal)
        if not apply:
            continue
        proposals_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_text(path, content)
        log.info(
            "memory_lifecycle: promotion proposal %s (%d sessions, %d sources)",
            path,
            len(session_ids),
            len(cluster),
        )
        if hooks is not None:
            from core.hooks import HookEvent

            hooks.trigger(
                HookEvent.MEMORY_PROMOTION_PROPOSED,
                {
                    "slug": slug,
                    "proposal_path": str(path),
                    "session_ids": list(session_ids),
                    "source_count": len(cluster),
                    "ts": time.time(),
                },
            )
    return proposals
