"""Simple Vector Store — NumPy-based in-memory vector search with disk persistence.

No external vector DB dependency.  Uses cosine similarity for search.
Stores embeddings as ``.npz`` files and metadata as ``.json`` at
``.geode/vectors/{collection}/``.

Designed for small-to-medium corpora (up to ~50K entries) typical of
project memory, rules, and past analyses.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

log = logging.getLogger(__name__)

_vector_store_ctx: ContextVar[SimpleVectorStore | None] = ContextVar(
    "vector_store", default=None
)


def set_vector_store(store: SimpleVectorStore | None) -> None:
    """Inject the vector store into the current context."""
    _vector_store_ctx.set(store)


def get_vector_store() -> SimpleVectorStore | None:
    """Retrieve the vector store from the current context."""
    return _vector_store_ctx.get()


@dataclass
class SearchResult:
    """A single search result with text, similarity score, and metadata."""

    text: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)


class SimpleVectorStore:
    """NumPy-based vector store with cosine similarity search.

    Supports incremental ``add``, ``search``, ``clear``, and disk persistence.
    Thread-safe for reads; writes should be serialized by the caller.
    """

    def __init__(
        self,
        collection: str,
        *,
        engine: Any = None,  # EmbeddingEngine
        persist_dir: Path | None = None,
    ) -> None:
        self._collection = collection
        self._engine = engine
        self._persist_dir = persist_dir or Path(".geode/vectors")
        self._collection_dir = self._persist_dir / collection

        self._texts: list[str] = []
        self._metadata: list[dict[str, Any]] = []
        self._embeddings: np.ndarray | None = None  # (N, dim)

        self._load_from_disk()

    @property
    def size(self) -> int:
        """Number of entries in the store."""
        return len(self._texts)

    def add(
        self,
        texts: list[str],
        metadata: list[dict[str, Any]] | None = None,
    ) -> int:
        """Add texts to the store.  Returns number of entries added.

        Computes embeddings via the engine and appends to the index.
        If no engine is set, texts are stored but search will return empty results.
        """
        if not texts:
            return 0

        meta_list = metadata or [{} for _ in texts]
        if len(meta_list) != len(texts):
            meta_list = [{} for _ in texts]

        # Compute embeddings
        if self._engine is not None:
            new_embeddings = self._engine.embed(texts)
        else:
            new_embeddings = np.zeros((len(texts), 1), dtype=np.float32)

        # Append
        self._texts.extend(texts)
        self._metadata.extend(meta_list)

        if self._embeddings is None or self._embeddings.shape[0] == 0:
            self._embeddings = new_embeddings
        else:
            self._embeddings = np.vstack([self._embeddings, new_embeddings])

        self._persist_to_disk()
        return len(texts)

    def search(
        self,
        query: str,
        k: int = 5,
        filter_fn: Callable[[dict[str, Any]], bool] | None = None,
    ) -> list[SearchResult]:
        """Search for the top-k most similar texts.

        Args:
            query: Natural language query.
            k: Number of results to return.
            filter_fn: Optional metadata filter.  Only entries where
                ``filter_fn(metadata)`` returns True are considered.

        Returns list of SearchResult sorted by descending similarity.
        """
        if self._engine is None or self._embeddings is None or self._embeddings.shape[0] == 0:
            return []

        query_vec = self._engine.embed_single(query)
        if np.linalg.norm(query_vec) == 0:
            return []

        # Cosine similarity
        norms = np.linalg.norm(self._embeddings, axis=1, keepdims=True)
        # Avoid division by zero
        safe_norms = np.where(norms == 0, 1.0, norms)
        normalized = self._embeddings / safe_norms
        query_normalized = query_vec / np.linalg.norm(query_vec)
        scores = normalized @ query_normalized

        # Build candidate list with optional filtering
        candidates: list[tuple[int, float]] = []
        for i, score in enumerate(scores):
            if filter_fn and not filter_fn(self._metadata[i]):
                continue
            candidates.append((i, float(score)))

        # Sort by score descending, take top-k
        candidates.sort(key=lambda x: x[1], reverse=True)
        top_k = candidates[:k]

        return [
            SearchResult(
                text=self._texts[idx],
                score=score,
                metadata=self._metadata[idx],
            )
            for idx, score in top_k
        ]

    def clear(self) -> None:
        """Remove all entries from the store."""
        self._texts.clear()
        self._metadata.clear()
        self._embeddings = None

        # Remove persisted files
        if self._collection_dir.exists():
            for f in self._collection_dir.glob("*"):
                f.unlink(missing_ok=True)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _persist_to_disk(self) -> None:
        """Save embeddings and metadata to disk."""
        try:
            self._collection_dir.mkdir(parents=True, exist_ok=True)
            if self._embeddings is not None and self._embeddings.shape[0] > 0:
                np.savez_compressed(
                    self._collection_dir / "embeddings.npz",
                    embeddings=self._embeddings,
                )
            meta_path = self._collection_dir / "metadata.json"
            meta_path.write_text(
                json.dumps(
                    {"texts": self._texts, "metadata": self._metadata},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        except Exception:
            log.debug("Failed to persist vector store", exc_info=True)

    def _load_from_disk(self) -> None:
        """Load embeddings and metadata from disk if available."""
        meta_path = self._collection_dir / "metadata.json"
        emb_path = self._collection_dir / "embeddings.npz"

        if not meta_path.exists():
            return

        try:
            data = json.loads(meta_path.read_text(encoding="utf-8"))
            self._texts = data.get("texts", [])
            self._metadata = data.get("metadata", [])

            if emb_path.exists():
                loaded = np.load(emb_path)
                self._embeddings = loaded["embeddings"].astype(np.float32)

                # Sanity check
                if self._embeddings.shape[0] != len(self._texts):
                    log.warning(
                        "Vector store %s: embedding count mismatch (%d vs %d) — clearing",
                        self._collection,
                        self._embeddings.shape[0],
                        len(self._texts),
                    )
                    self.clear()
        except Exception:
            log.debug("Failed to load vector store from disk", exc_info=True)
            self._texts = []
            self._metadata = []
            self._embeddings = None
