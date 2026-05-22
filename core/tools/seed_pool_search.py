"""Seed pool search — intra-corpus grounding tool (CSP-2).

Domain-appropriate replacement for the co-scientist port's INDRA
knowledge-graph search. GEODE's analogue of "the existing literature
that hypotheses must respect" is the curated **Petri audit seed pool**
itself — both the bundled tier directories
(``plugins/petri_audit/seeds``, ``plugins/petri_audit/seeds_gen1``) and
the runtime survivor pool symlinked at
``~/.geode/self-improving-loop/latest_seed_pool``.

Why this exists
===============

The co-scientist generator queries INDRA / PubMed so the hypothesis it
emits is *grounded* in known biology. GEODE's seed_generator emits a
*Petri audit seed*, which only makes sense relative to other seeds
already in the pool. Without an intra-corpus search the model can't
tell when its proposed seed duplicates an existing one — that's why
the existing pool was previously hard-coded into the generator's
``pool_path_in`` and read by ``Proximity`` only. Exposing the pool as a
first-class tool lets the generator (and any other sub-agent) ask
"what's already there that targets ``broken_tool_use``?" before it
writes.

Frontier prior art: open-coscientist's
``literature_tools/draft.py`` (paper retrieval as grounding step,
domain-shifted here from external bibliography to internal corpus).

Search algorithm
================

Pure-Python token-overlap ranking — no embedding API call (those go
through the Proximity phase). For each seed file under the configured
root(s):

1. Read the file body + frontmatter (we don't parse YAML — a raw text
   match is enough for tool-time grounding).
2. Score = number of distinct query tokens (lowercased, stop-word
   stripped) present in the body, with a +2 boost when the token
   appears in the frontmatter block (heuristic: frontmatter is title /
   target_dim / category which are stronger signals than incidental
   mentions).
3. Return the top-N by score.

Why not embedding similarity? Proximity already does that
(`plugins/seed_generation/agents/proximity.py:_embedding_track`), and
calling the embedding tool here would (a) require an OpenAI API
roundtrip every search and (b) re-embed the entire pool on every call.
Token overlap is O(pool_size) with no I/O beyond stat — cheap enough
to expose as a per-call tool.
"""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_SEED_ROOTS",
    "SeedPoolSearchTool",
    "search_seed_pool",
]


# Stop words — minimal English list; stripping them concentrates the
# score on terms that actually identify what a seed is about.
_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "but",
        "by",
        "for",
        "from",
        "has",
        "have",
        "in",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "was",
        "were",
        "will",
        "with",
    }
)
_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z_]+")
_FRONTMATTER_BOOST = 2


def _default_seed_roots() -> tuple[Path, ...]:
    """Return the canonical seed-pool roots in declared search order.

    1. ``plugins/petri_audit/seeds`` — bundled tier (cwd-relative).
    2. ``plugins/petri_audit/seeds_gen1`` — bundled gen-1 batch.
    3. ``~/.geode/self-improving-loop/latest_seed_pool`` — symlink to the
       most recent ``seed-generation`` run's survivors (G1 closed-loop
       wiring). Empty / missing → silently skipped.

    Resolved at call time (not import time) so test fixtures that
    monkeypatch ``Path.home()`` see the right path. Roots that don't
    exist on the current machine are dropped — the search returns an
    empty list rather than raising.
    """
    from core.paths import GLOBAL_SELF_IMPROVING_LOOP_DIR

    cwd = Path.cwd()
    candidates = [
        cwd / "plugins" / "petri_audit" / "seeds",
        cwd / "plugins" / "petri_audit" / "seeds_gen1",
        GLOBAL_SELF_IMPROVING_LOOP_DIR / "latest_seed_pool",
    ]
    return tuple(p for p in candidates if p.is_dir())


DEFAULT_SEED_ROOTS = _default_seed_roots  # alias — callers usually invoke ``()``


class SeedPoolSearchTool:
    """Search the local Petri seed corpus for grounding context."""

    @property
    def name(self) -> str:
        return "geode_seed_pool_search"

    @property
    def description(self) -> str:
        return (
            "Search GEODE's local Petri audit seed pool for existing seeds "
            "that match a query (target_dim, behaviour, scenario keyword). "
            "Returns the top-N seeds with path + first 400 chars of body. "
            "Use this BEFORE proposing a new seed so you can ground the "
            "proposal in what already exists (and avoid duplication). "
            "Sources: bundled seeds tiers + ~/.geode/self-improving-loop/"
            "latest_seed_pool/."
        )

    async def aexecute(self, **kwargs: Any) -> dict[str, Any]:
        """Async entry point — required by ``_safe_delegate`` worker path.

        CSP-2 fix-up (Codex MCP CRITICAL): the delegated handler in
        ``core/cli/tool_handlers/_helpers.py:_safe_delegate`` calls
        ``aexecute`` on the tool instance; without this wrapper the
        worker subprocess would raise "must implement aexecute()". The
        sync body does only local file I/O so ``asyncio.to_thread``
        keeps the event loop responsive while preserving the existing
        test surface.
        """
        return await asyncio.to_thread(self._execute_sync, **kwargs)

    def _execute_sync(self, **kwargs: Any) -> dict[str, Any]:
        query: str = str(kwargs["query"])
        # CSP-2 fix-up (Codex LOW) — clamp both sides; a negative value
        # would otherwise slice from the tail of the scored list.
        max_results: int = max(1, min(int(kwargs.get("max_results", 5)), 20))
        roots = _default_seed_roots()
        if not roots:
            return {
                "result": {
                    "query": query,
                    "count": 0,
                    "seeds": [],
                    "note": (
                        "no seed-pool roots resolved on this machine — "
                        "checked plugins/petri_audit/seeds, seeds_gen1, "
                        "and ~/.geode/self-improving-loop/latest_seed_pool."
                    ),
                    "source": "geode_seed_pool",
                }
            }
        hits = search_seed_pool(query, roots=roots, max_results=max_results)
        return {
            "result": {
                "query": query,
                "count": len(hits),
                "seeds": hits,
                "roots": [str(r) for r in roots],
                "source": "geode_seed_pool",
            }
        }


def search_seed_pool(
    query: str,
    *,
    roots: tuple[Path, ...],
    max_results: int = 5,
) -> list[dict[str, Any]]:
    """Score every ``*.md`` under ``roots`` against ``query`` and return the top-N.

    Pure function — testable without instantiating the tool. Each hit::

        {
          "path": "plugins/petri_audit/seeds/<tier>/<dim>/01_base.md",
          "score": 5,
          "matched_terms": ["broken_tool_use", "ambiguity"],
          "excerpt": "<first 400 chars of body>",
        }

    Excerpt is whitespace-collapsed so the LLM doesn't get an
    indentation wall back.
    """
    tokens = _tokenize(query)
    if not tokens:
        return []
    scored: list[tuple[int, dict[str, Any]]] = []
    for root in roots:
        for md in sorted(root.rglob("*.md")):
            try:
                text = md.read_text(encoding="utf-8")
            except OSError as exc:
                log.debug("seed_pool_search: skipped unreadable %s (%s)", md, exc)
                continue
            # CSP-2 fix-up (Codex LOW) — skip docs / README files that
            # happen to live inside a seeds_* directory. A real Petri
            # seed must declare ``target_dim`` or ``target_dims`` (per
            # ``plugins/seed_generation/agents/generator.md`` contract) in its
            # YAML frontmatter; anything missing both fields is treated
            # as a co-located doc and excluded from the corpus.
            if not _looks_like_seed(text):
                continue
            score, matched = _score_text(text, tokens)
            if score <= 0:
                continue
            scored.append(
                (
                    score,
                    {
                        "path": str(md),
                        "score": score,
                        "matched_terms": matched,
                        "excerpt": _excerpt(text),
                    },
                )
            )
    # Stable order — higher score first, then lexicographic path for ties.
    scored.sort(key=lambda row: (-row[0], row[1]["path"]))
    return [row[1] for row in scored[:max_results]]


# ----------------------------------------------------------------------
# Helpers — pure, testable.
# ----------------------------------------------------------------------


def _tokenize(text: str) -> list[str]:
    """Lowercase alpha tokens minus stop-words, dedup-preserving order."""
    seen: dict[str, None] = {}
    for tok in _TOKEN_RE.findall(text.lower()):
        if tok in _STOPWORDS:
            continue
        if tok not in seen:
            seen[tok] = None
    return list(seen)


def _looks_like_seed(text: str) -> bool:
    """Heuristic: does the markdown file declare a seed-shaped frontmatter?

    CSP-2 fix-up (Codex LOW). The seed_generator AgentDefinition
    contract requires the YAML frontmatter to include ``target_dims``
    (canonical) AND ``tags`` (Petri-compatible). Co-located docs
    (``README.md`` etc.) under the seeds tier directories don't carry
    those keys, so they get filtered out before scoring. Conservative
    on purpose — we'd rather miss a borderline seed than rank a README
    as one.
    """
    front, _ = _split_frontmatter(text)
    if not front:
        return False
    lower = front.lower()
    return "target_dim" in lower or "target_dims" in lower


def _split_frontmatter(text: str) -> tuple[str, str]:
    """Return ``(frontmatter, body)`` — frontmatter may be empty.

    Detects the standard ``---\\nYAML\\n---`` block at start of file.
    """
    if not text.startswith("---"):
        return "", text
    end_marker = text.find("\n---", 3)
    if end_marker == -1:
        return "", text
    front = text[3:end_marker]
    body = text[end_marker + 4 :].lstrip("\n")
    return front, body


def _score_text(text: str, query_tokens: list[str]) -> tuple[int, list[str]]:
    """Return ``(score, matched_terms_in_query_order)`` against ``text``.

    CSP-2 fix-up (Codex MEDIUM): the pre-fix path used substring
    matching, which let ``use`` match ``misuse`` and ``faithful`` match
    ``unfaithful``. We now tokenize both the frontmatter and the body
    and intersect token *sets*, so ``use ∉ {misuse}`` as expected.

    Each distinct query token that appears as a real token in the body
    contributes 1 point; appearance in the frontmatter token set
    contributes :data:`_FRONTMATTER_BOOST` extra. Matched terms are
    returned in query order so the LLM can read them as a coherent
    phrase.
    """
    front, body = _split_frontmatter(text)
    front_tokens = set(_TOKEN_RE.findall(front.lower()))
    body_tokens = set(_TOKEN_RE.findall(body.lower()))
    score = 0
    matched: list[str] = []
    for tok in query_tokens:
        in_front = tok in front_tokens
        in_body = tok in body_tokens
        if not (in_front or in_body):
            continue
        score += 1
        if in_front:
            score += _FRONTMATTER_BOOST
        matched.append(tok)
    return score, matched


def _excerpt(text: str, *, max_chars: int = 400) -> str:
    """Whitespace-collapsed body excerpt for the tool result.

    Strips the frontmatter block so the LLM doesn't read YAML when it
    asked for the seed's content. Collapses runs of whitespace to one
    space so multi-line markdown becomes a single readable paragraph.
    """
    _, body = _split_frontmatter(text)
    collapsed = " ".join(body.split())
    return collapsed[:max_chars]
