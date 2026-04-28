"""RAPTOR — Recursive Abstractive Processing for Tree-Organized Retrieval.

Builds a hierarchical tree of summaries over the vector store:
- Level 0: Original text chunks (leaf nodes)
- Level 1: Cluster summaries (~cluster_size chunks each)
- Level 2+: Theme summaries (~cluster_size clusters each)

Search traverses from root (global themes) down to leaves (details),
returning the right abstraction level for the query.

Reference: Sarthi et al., "RAPTOR: Recursive Abstractive Processing
for Tree-Organized Retrieval" (ICLR 2024).
"""

from __future__ import annotations

import json
import logging
import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from experimental.memory.embeddings import EmbeddingEngine
from experimental.memory.vector_store import SimpleVectorStore

log = logging.getLogger(__name__)

_raptor_index_ctx: ContextVar[RAPTORIndex | None] = ContextVar(
    "raptor_index", default=None
)


def set_raptor_index(index: RAPTORIndex | None) -> None:
    """Inject the RAPTOR index into the current context."""
    _raptor_index_ctx.set(index)


def get_raptor_index() -> RAPTORIndex | None:
    """Retrieve the RAPTOR index from the current context."""
    return _raptor_index_ctx.get()


@dataclass
class RAPTORResult:
    """A single RAPTOR search result."""

    text: str
    score: float
    level: int  # 0=leaf, 1=cluster, 2=theme, ...
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class _TreeNode:
    """Internal tree node holding text + embedding + children."""

    text: str
    level: int
    embedding: np.ndarray
    metadata: dict[str, Any] = field(default_factory=dict)
    children: list[int] = field(default_factory=list)  # indices into flat list


class RAPTORIndex:
    """Recursive tree-structured retrieval index.

    Leaf nodes are original text chunks.  Internal nodes are LLM-generated
    summaries of their children.  Search can target any level of abstraction.
    """

    def __init__(
        self,
        collection: str,
        vector_store: SimpleVectorStore,
        engine: EmbeddingEngine,
        *,
        cluster_size: int = 5,
        max_levels: int = 3,
        persist_dir: Path | None = None,
    ) -> None:
        self._collection = collection
        self._store = vector_store
        self._engine = engine
        self._cluster_size = cluster_size
        self._max_levels = max_levels
        self._persist_dir = persist_dir or Path(".geode/raptor")
        self._collection_dir = self._persist_dir / collection

        # Flat list of all nodes across all levels
        self._nodes: list[_TreeNode] = []
        self._max_level_built = -1

        self._load_from_disk()

    @property
    def is_built(self) -> bool:
        """Whether the tree has been built."""
        return self._max_level_built >= 0

    @property
    def level_count(self) -> int:
        """Number of levels in the tree (0 if not built)."""
        return self._max_level_built + 1 if self.is_built else 0

    @property
    def node_count(self) -> int:
        """Total number of nodes across all levels."""
        return len(self._nodes)

    def build(self, texts: list[str]) -> None:
        """Build the tree from leaf texts.

        Uses k-means clustering (NumPy only) and budget LLM for summarization.
        If LLM is unavailable, uses extractive fallback summaries.
        """
        if not texts:
            return

        self._nodes.clear()
        self._max_level_built = -1

        # Level 0: leaf nodes
        embeddings = self._engine.embed(texts)
        for i, (text, emb) in enumerate(zip(texts, embeddings, strict=True)):
            self._nodes.append(_TreeNode(
                text=text,
                level=0,
                embedding=emb,
                metadata={"leaf_index": i},
            ))
        self._max_level_built = 0

        # Build higher levels by clustering
        current_level_indices = list(range(len(self._nodes)))

        for level in range(1, self._max_levels + 1):
            if len(current_level_indices) <= self._cluster_size:
                break  # too few nodes to cluster further

            clusters = self._cluster_nodes(current_level_indices)
            next_level_indices: list[int] = []

            for cluster_indices in clusters:
                if not cluster_indices:
                    continue
                # Summarize cluster
                cluster_texts = [self._nodes[i].text for i in cluster_indices]
                summary = self._summarize_cluster(cluster_texts, level)
                summary_emb = self._engine.embed_single(summary)

                node_idx = len(self._nodes)
                self._nodes.append(_TreeNode(
                    text=summary,
                    level=level,
                    embedding=summary_emb,
                    metadata={"cluster_size": len(cluster_indices), "level": level},
                    children=cluster_indices,
                ))
                next_level_indices.append(node_idx)

            current_level_indices = next_level_indices
            self._max_level_built = level

        self._persist_to_disk()
        log.info(
            "RAPTOR tree built: %d nodes across %d levels (from %d leaves)",
            len(self._nodes),
            self._max_level_built + 1,
            len(texts),
        )

    def search(
        self,
        query: str,
        *,
        detail_level: str = "auto",
        k: int = 5,
    ) -> list[RAPTORResult]:
        """Search the tree at the specified abstraction level.

        Args:
            query: Natural language query.
            detail_level: ``"detail"`` (level 0), ``"theme"`` (level 1),
                ``"global"`` (highest level), or ``"auto"`` (search all levels).
            k: Number of results.

        Returns list of RAPTORResult sorted by descending similarity.
        """
        if not self._nodes:
            return []

        query_emb = self._engine.embed_single(query)
        if np.linalg.norm(query_emb) == 0:
            return []

        # Determine which levels to search
        target_levels = self._resolve_levels(detail_level)

        # Collect candidates from target levels
        candidates: list[tuple[int, float]] = []
        for i, node in enumerate(self._nodes):
            if node.level not in target_levels:
                continue
            norm = np.linalg.norm(node.embedding)
            if norm == 0:
                continue
            score = float(np.dot(node.embedding, query_emb) / (norm * np.linalg.norm(query_emb)))
            candidates.append((i, score))

        candidates.sort(key=lambda x: x[1], reverse=True)

        return [
            RAPTORResult(
                text=self._nodes[idx].text,
                score=score,
                level=self._nodes[idx].level,
                metadata=self._nodes[idx].metadata,
            )
            for idx, score in candidates[:k]
        ]

    def update_incremental(self, new_texts: list[str]) -> None:
        """Add new leaf nodes and rebuild affected branches.

        For simplicity, currently rebuilds the entire tree.
        Incremental branch rebuild is a future optimization.
        """
        if not new_texts:
            return
        existing_leaves = [n.text for n in self._nodes if n.level == 0]
        self.build(existing_leaves + new_texts)

    def cleanup(self) -> int:
        """Remove all persisted tree data."""
        if not self._collection_dir.exists():
            return 0
        removed = 0
        for f in self._collection_dir.glob("*"):
            f.unlink(missing_ok=True)
            removed += 1
        if self._collection_dir.exists() and not any(self._collection_dir.iterdir()):
            self._collection_dir.rmdir()
        return removed

    # ------------------------------------------------------------------
    # Internal: Clustering
    # ------------------------------------------------------------------

    def _cluster_nodes(self, indices: list[int]) -> list[list[int]]:
        """K-means clustering using NumPy only (no sklearn)."""
        embeddings = np.array([self._nodes[i].embedding for i in indices])
        n = len(indices)
        k = max(2, n // self._cluster_size)
        k = min(k, n)  # can't have more clusters than data points

        if k <= 1:
            return [indices]

        # K-means++ initialization
        rng = np.random.default_rng(42)
        centroids = np.empty((k, embeddings.shape[1]), dtype=np.float32)
        first = rng.integers(0, n)
        centroids[0] = embeddings[first]

        for c in range(1, k):
            dists = np.min(
                np.linalg.norm(embeddings[:, np.newaxis] - centroids[:c], axis=2),
                axis=1,
            )
            probs = dists ** 2
            total = probs.sum()
            if total == 0:
                centroids[c] = embeddings[rng.integers(0, n)]
            else:
                probs /= total
                chosen = rng.choice(n, p=probs)
                centroids[c] = embeddings[chosen]

        # Iterate
        for _ in range(50):
            dists = np.linalg.norm(
                embeddings[:, np.newaxis] - centroids[np.newaxis, :], axis=2
            )
            assignments = np.argmin(dists, axis=1)
            new_centroids = np.empty_like(centroids)
            for c in range(k):
                mask = assignments == c
                if mask.any():
                    new_centroids[c] = embeddings[mask].mean(axis=0)
                else:
                    new_centroids[c] = centroids[c]
            if np.allclose(centroids, new_centroids):
                break
            centroids = new_centroids

        # Build cluster lists
        clusters: list[list[int]] = [[] for _ in range(k)]
        for i, assignment in enumerate(assignments):
            clusters[int(assignment)].append(indices[i])

        return [c for c in clusters if c]  # remove empty

    # ------------------------------------------------------------------
    # Internal: Summarization
    # ------------------------------------------------------------------

    def _summarize_cluster(self, texts: list[str], level: int) -> str:
        """Summarize cluster texts using budget LLM or fallback."""
        combined = "\n---\n".join(t[:500] for t in texts)
        level_name = "cluster" if level == 1 else "theme"

        # Try Anthropic Haiku
        try:
            from anthropic import Anthropic

            client = Anthropic()
            prompt = (
                f"Summarize these {len(texts)} related text chunks into a "
                f"cohesive {level_name} summary.\n"
                "Preserve: key entities, relationships, quantitative data, "
                "temporal markers.\n"
                "Output: 100-150 words.\n\n"
                f"{combined}"
            )
            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=256,
                messages=[{"role": "user", "content": prompt}],
            )
            if response.content and response.content[0].type == "text":
                return response.content[0].text
        except Exception:
            log.debug("RAPTOR Haiku summarization failed, trying fallback", exc_info=True)

        # Try OpenAI mini
        try:
            from core.llm.providers.openai import _get_openai_client

            client = _get_openai_client()
            if client is not None:
                response = client.chat.completions.create(
                    model="gpt-4.1-mini",
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                f"Summarize the following {len(texts)} text chunks "
                                f"into a cohesive {level_name} summary. "
                                "Preserve key entities and data. 100-150 words."
                            ),
                        },
                        {"role": "user", "content": combined},
                    ],
                    max_tokens=256,
                    temperature=0.0,
                )
                choice = response.choices[0] if response.choices else None
                if choice and choice.message and choice.message.content:
                    content: str = choice.message.content
                    return content
        except Exception:
            log.debug("RAPTOR OpenAI summarization failed, using extractive", exc_info=True)

        # Extractive fallback: first sentence of each text
        parts = []
        for t in texts:
            first_line = t.split("\n")[0].strip()[:100]
            if first_line:
                parts.append(first_line)
        return f"[{level_name.title()} summary] " + " | ".join(parts[:5])

    # ------------------------------------------------------------------
    # Internal: Level resolution
    # ------------------------------------------------------------------

    def _resolve_levels(self, detail_level: str) -> set[int]:
        """Resolve detail_level string to set of level integers."""
        if detail_level == "detail":
            return {0}
        if detail_level == "theme":
            return {1} if self._max_level_built >= 1 else {0}
        if detail_level == "global":
            return {self._max_level_built} if self._max_level_built >= 0 else {0}
        # "auto": search all levels
        return set(range(self._max_level_built + 1)) if self._max_level_built >= 0 else {0}

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _persist_to_disk(self) -> None:
        """Save tree structure to disk."""
        if not self._nodes:
            return
        try:
            self._collection_dir.mkdir(parents=True, exist_ok=True)

            # Save embeddings
            embeddings = np.array([n.embedding for n in self._nodes], dtype=np.float32)
            np.savez_compressed(self._collection_dir / "tree_embeddings.npz", embeddings=embeddings)

            # Save metadata
            meta = {
                "max_level": self._max_level_built,
                "node_count": len(self._nodes),
                "built_at": time.time(),
                "nodes": [
                    {
                        "text": n.text,
                        "level": n.level,
                        "metadata": n.metadata,
                        "children": n.children,
                    }
                    for n in self._nodes
                ],
            }
            (self._collection_dir / "tree_meta.json").write_text(
                json.dumps(meta, ensure_ascii=False), encoding="utf-8"
            )
        except Exception:
            log.debug("Failed to persist RAPTOR tree", exc_info=True)

    def _load_from_disk(self) -> None:
        """Load tree from disk if available."""
        meta_path = self._collection_dir / "tree_meta.json"
        emb_path = self._collection_dir / "tree_embeddings.npz"

        if not meta_path.exists() or not emb_path.exists():
            return

        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            loaded = np.load(emb_path)
            embeddings = loaded["embeddings"].astype(np.float32)

            nodes_data = meta.get("nodes", [])
            if len(nodes_data) != embeddings.shape[0]:
                log.warning("RAPTOR tree data mismatch — ignoring persisted tree")
                return

            self._nodes = [
                _TreeNode(
                    text=nd["text"],
                    level=nd["level"],
                    embedding=embeddings[i],
                    metadata=nd.get("metadata", {}),
                    children=nd.get("children", []),
                )
                for i, nd in enumerate(nodes_data)
            ]
            self._max_level_built = meta.get("max_level", -1)
            log.debug(
                "Loaded RAPTOR tree: %d nodes, %d levels",
                len(self._nodes),
                self._max_level_built + 1,
            )
        except Exception:
            log.debug("Failed to load RAPTOR tree", exc_info=True)
