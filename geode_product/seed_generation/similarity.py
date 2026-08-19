"""Token-set similarity primitives (CSP-6, 2026-05-22).

Hoisted from ``plugins/seed_generation/agents/proximity.py`` so other
plugins (and the upcoming Evolver anti-convergence guard) can reuse the
same Jaccard semantics without importing into another plugin's
internals. The original module re-exports these names so its public
surface is unchanged.

Pure functions — testable without instantiating any agent or pipeline.
"""

from __future__ import annotations

DEFAULT_NGRAM_SIZE = 5

__all__ = [
    "DEFAULT_NGRAM_SIZE",
    "jaccard_similarity",
    "shingles",
    "text_jaccard",
]


def shingles(text: str, n: int = DEFAULT_NGRAM_SIZE) -> set[str]:
    """Split lowercase whitespace-tokenized text into n-gram shingles.

    A "shingle" is a length-``n`` window of consecutive tokens joined
    with spaces — the classic Broder-style fingerprint that powers
    near-duplicate detection in the seed-pool proximity track. Texts
    shorter than ``n`` tokens collapse to the whole text as a single
    shingle (so Jaccard against another short text still produces a
    meaningful 1.0 / 0.0 signal). Empty input → empty set.
    """
    tokens = text.lower().split()
    if len(tokens) < n:
        return {" ".join(tokens)} if tokens else set()
    return {" ".join(tokens[i : i + n]) for i in range(len(tokens) - n + 1)}


def jaccard_similarity(a: set[str], b: set[str]) -> float:
    """Return |a∩b| / |a∪b| in ``[0.0, 1.0]``.

    Both sets empty → 0.0 (no overlap to compute). One side empty →
    0.0 (no intersection). The pre-CSP-6 ``_jaccard`` in proximity.py
    had the same semantics; this hoisted version is the SoT, and
    proximity.py re-exports it.
    """
    if not a and not b:
        return 0.0
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def text_jaccard(left: str, right: str, *, n: int = DEFAULT_NGRAM_SIZE) -> float:
    """Convenience: shingle both texts and return their Jaccard.

    Used by Evolver's anti-convergence post-check (CSP-6) — given two
    candidate bodies, decide whether the evolved seed is too close to
    a sibling. The threshold lives at the call site, not here.
    """
    return jaccard_similarity(shingles(left, n=n), shingles(right, n=n))
