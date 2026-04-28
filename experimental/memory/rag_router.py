"""Adaptive RAG Router — classify queries and route to appropriate retrieval.

Inspired by A-RAG (arXiv:2602.03442) hierarchical retrieval interfaces
and Adaptive RAG's query complexity classification.

Query types:
- ``"simple"``: Direct factual lookup → lexical search (fast, no embeddings)
- ``"focused"``: Single-concept semantic query → vector search
- ``"complex"``: Multi-concept / comparative → hybrid (lexical + vector)
"""

from __future__ import annotations

import logging
import re
from typing import Any

from experimental.memory.vector_store import SearchResult, SimpleVectorStore, get_vector_store

log = logging.getLogger(__name__)

# Patterns that suggest complex queries (multi-concept, comparative)
_COMPLEX_PATTERNS = [
    r"\b(compare|comparison|versus|vs\.?|differ|common|pattern|trend)\b",
    r"\b(across|between|among|all|every|each)\b",
    r"\band\b.*\band\b",  # multiple "and" conjunctions
]
_COMPLEX_RE = re.compile("|".join(_COMPLEX_PATTERNS), re.IGNORECASE)

# Patterns that suggest simple lookups (specific facts)
_SIMPLE_PATTERNS = [
    r"\b(what is|who is|when did|how many|how much|define|definition)\b",
    r"\b(score|tier|price|cost|count|number|version)\b",
]
_SIMPLE_RE = re.compile("|".join(_SIMPLE_PATTERNS), re.IGNORECASE)


class RAGRouter:
    """Classify queries and route to appropriate retrieval strategy.

    Uses heuristic classification (no LLM call) to keep routing overhead
    at zero.  Falls back gracefully when vector store is unavailable.
    """

    def __init__(
        self,
        *,
        vector_store: SimpleVectorStore | None = None,
        similarity_threshold: float = 0.7,
    ) -> None:
        self._store = vector_store
        self._threshold = similarity_threshold

    def classify(self, query: str) -> str:
        """Classify query complexity.

        Returns ``"simple"``, ``"focused"``, or ``"complex"``.
        """
        if _COMPLEX_RE.search(query):
            return "complex"
        if _SIMPLE_RE.search(query):
            return "simple"
        # Default: focused (single-concept semantic search)
        if len(query.split()) >= 5:
            return "focused"
        return "simple"

    def retrieve(
        self,
        query: str,
        k: int = 5,
        *,
        lexical_results: list[dict[str, Any]] | None = None,
    ) -> list[SearchResult]:
        """Retrieve results using the appropriate strategy.

        Args:
            query: Natural language query.
            k: Number of results to return.
            lexical_results: Pre-computed lexical search results (from MemorySearchTool).
                If provided, used in hybrid mode for ``"complex"`` queries.

        Returns list of SearchResult sorted by relevance.
        """
        query_type = self.classify(query)
        store = self._store or get_vector_store()

        if query_type == "simple":
            # Pure lexical — caller should use existing MemorySearchTool
            return []

        if store is None or store.size == 0:
            return []

        if query_type == "focused":
            return self._vector_search(store, query, k)

        # "complex" — hybrid: vector search + boost from lexical matches
        return self._hybrid_search(store, query, k, lexical_results or [])

    def _vector_search(
        self, store: SimpleVectorStore, query: str, k: int
    ) -> list[SearchResult]:
        """Pure semantic search."""
        results = store.search(query, k=k)
        return [r for r in results if r.score >= self._threshold]

    def _hybrid_search(
        self,
        store: SimpleVectorStore,
        query: str,
        k: int,
        lexical_results: list[dict[str, Any]],
    ) -> list[SearchResult]:
        """Combine semantic and lexical results.

        Lexical matches get a score boost of 0.1 to prefer results
        that match both semantically and lexically.
        """
        semantic = store.search(query, k=k * 2)  # fetch more for re-ranking

        # Build set of lexical-matched texts for boosting
        lexical_texts: set[str] = set()
        for lr in lexical_results:
            for line in lr.get("matching_lines", []):
                lexical_texts.add(line.lower().strip())
            preview = lr.get("preview", "")
            if preview:
                lexical_texts.add(preview.lower().strip()[:100])

        # Boost semantic results that also appear in lexical
        boosted: list[SearchResult] = []
        for r in semantic:
            boost = 0.1 if any(lt in r.text.lower() for lt in lexical_texts if lt) else 0.0
            boosted.append(
                SearchResult(
                    text=r.text,
                    score=min(r.score + boost, 1.0),
                    metadata={**r.metadata, "hybrid_boost": boost > 0},
                )
            )

        boosted.sort(key=lambda x: x.score, reverse=True)
        return [r for r in boosted[:k] if r.score >= self._threshold]
