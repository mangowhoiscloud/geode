"""Embedding Engine — pluggable text embedding with caching.

Backends:
- ``"openai"``: Uses ``text-embedding-3-small`` via the existing OpenAI dependency.
  Cost: $0.02 / 1M tokens.  No additional dependency.
- ``"local"``: Uses ``sentence-transformers`` (optional ``[rag]`` extra).
  Free, but requires ~500 MB model download on first use.
- ``"none"``: No-op — returns empty vectors.  Graceful degradation fallback.

Embeddings are cached to ``.geode/embedding-cache/`` by content hash to avoid
recomputing identical texts.
"""

from __future__ import annotations

import hashlib
import logging
from contextvars import ContextVar
from pathlib import Path
from typing import Any

import numpy as np

log = logging.getLogger(__name__)

_embedding_engine_ctx: ContextVar[EmbeddingEngine | None] = ContextVar(
    "embedding_engine", default=None
)


def set_embedding_engine(engine: EmbeddingEngine | None) -> None:
    """Inject the embedding engine into the current context."""
    _embedding_engine_ctx.set(engine)


def get_embedding_engine() -> EmbeddingEngine | None:
    """Retrieve the embedding engine from the current context."""
    return _embedding_engine_ctx.get()


class EmbeddingEngine:
    """Generate and cache text embeddings with pluggable backends."""

    def __init__(
        self,
        backend: str = "openai",
        model: str = "text-embedding-3-small",
        cache_dir: Path | None = None,
        dimension: int = 1536,
    ) -> None:
        self._backend = backend
        self._model = model
        self._cache_dir = cache_dir or Path(".geode/embedding-cache")
        self._dimension = dimension
        self._local_model: Any = None
        self._warned = False

        if backend == "openai":
            self._dimension = 1536  # text-embedding-3-small default
        elif backend == "local":
            self._dimension = 384  # all-MiniLM-L6-v2 default
        # "none" uses dimension as-is (default 1536)

    @property
    def dimension(self) -> int:
        """Embedding vector dimension."""
        return self._dimension

    @property
    def backend(self) -> str:
        """Active backend name."""
        return self._backend

    def embed(self, texts: list[str]) -> np.ndarray:
        """Embed multiple texts.  Returns (N, dimension) float32 array.

        Uses cache for previously seen texts.  Falls back to zero vectors
        on error.
        """
        if not texts:
            return np.empty((0, self._dimension), dtype=np.float32)

        results: list[np.ndarray] = []
        uncached_indices: list[int] = []
        uncached_texts: list[str] = []

        # Check cache
        for i, text in enumerate(texts):
            cached = self._load_cache(text)
            if cached is not None:
                results.append(cached)
            else:
                results.append(np.zeros(self._dimension, dtype=np.float32))
                uncached_indices.append(i)
                uncached_texts.append(text)

        # Compute uncached embeddings
        if uncached_texts:
            vectors = self._compute(uncached_texts)
            for idx, vec in zip(uncached_indices, vectors, strict=True):
                results[idx] = vec
                self._save_cache(texts[idx], vec)

        return np.array(results, dtype=np.float32)

    def embed_single(self, text: str) -> np.ndarray:
        """Embed a single text.  Returns (dimension,) float32 array."""
        result = self.embed([text])
        vec: np.ndarray = result[0]
        return vec

    # ------------------------------------------------------------------
    # Backend implementations
    # ------------------------------------------------------------------

    def _compute(self, texts: list[str]) -> list[np.ndarray]:
        """Dispatch to the appropriate backend."""
        if self._backend == "openai":
            return self._compute_openai(texts)
        elif self._backend == "local":
            return self._compute_local(texts)
        else:
            return [np.zeros(self._dimension, dtype=np.float32) for _ in texts]

    def _compute_openai(self, texts: list[str]) -> list[np.ndarray]:
        """Compute embeddings via OpenAI API."""
        try:
            from openai import OpenAI

            client = OpenAI()
            response = client.embeddings.create(
                model=self._model,
                input=texts,
            )
            vectors = [
                np.array(item.embedding, dtype=np.float32)
                for item in sorted(response.data, key=lambda x: x.index)
            ]
            self._dimension = len(vectors[0]) if vectors else self._dimension
            return vectors
        except Exception:
            if not self._warned:
                log.warning("OpenAI embedding failed — falling back to zero vectors")
                self._warned = True
            return [np.zeros(self._dimension, dtype=np.float32) for _ in texts]

    def _compute_local(self, texts: list[str]) -> list[np.ndarray]:
        """Compute embeddings via sentence-transformers (optional dep)."""
        try:
            if self._local_model is None:
                from sentence_transformers import SentenceTransformer

                self._local_model = SentenceTransformer("all-MiniLM-L6-v2")
                self._dimension = self._local_model.get_sentence_embedding_dimension()
            embeddings = self._local_model.encode(texts, convert_to_numpy=True)
            return [np.array(e, dtype=np.float32) for e in embeddings]
        except ImportError:
            if not self._warned:
                log.warning(
                    "sentence-transformers not installed — "
                    "install with: uv pip install 'geode[rag]'"
                )
                self._warned = True
            return [np.zeros(self._dimension, dtype=np.float32) for _ in texts]
        except Exception:
            if not self._warned:
                log.warning("Local embedding failed — falling back to zero vectors")
                self._warned = True
            return [np.zeros(self._dimension, dtype=np.float32) for _ in texts]

    # ------------------------------------------------------------------
    # Cache
    # ------------------------------------------------------------------

    def _cache_key(self, text: str) -> str:
        """SHA-256 hash of text for cache filename."""
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]

    def _load_cache(self, text: str) -> np.ndarray | None:
        """Load cached embedding if available."""
        key = self._cache_key(text)
        path = self._cache_dir / f"{key}.npy"
        if path.exists():
            try:
                arr: np.ndarray = np.load(path)
                return arr.astype(np.float32)
            except Exception:
                path.unlink(missing_ok=True)
        return None

    def _save_cache(self, text: str, vector: np.ndarray) -> None:
        """Persist embedding to disk cache."""
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            key = self._cache_key(text)
            np.save(self._cache_dir / f"{key}.npy", vector)
        except Exception:
            log.debug("Failed to cache embedding", exc_info=True)
