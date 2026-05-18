"""text_embed — OpenAI text-embedding-3-small Python helper.

S4 deliverable per ADR-003. Provides a synchronous + async API for the
seed-pipeline Proximity agent (3-track dedup) to compute vector
embeddings for candidate-seed bodies and pool members.

NOT exposed as an LLM-dispatch tool (no entry in
``core/tools/definitions.json``). Proximity imports ``embed_texts``
directly because the Proximity phase is pure-Python — it does NOT
run an LLM completion that would dispatch tools by name. Other agents
have no use case for embeddings, so this stays internal.

Provider — OpenAI ``text-embedding-3-small`` (1536-dim, $0.02 per 1M
tokens). The ADR-003 settled decision: single-provider, PAYG only
(ChatGPT Plus OAuth does not expose embeddings API). Per ADR-001's
operational defaults the embedding call is a flat cost — embedded into
the seed-pipeline budget rollup via the caller's ``BudgetGuard``.

P-checklist application (cycle-skill SKILL.md):

- **P4 Environment Anchor** — API key read from
  ``settings.openai_api_key`` via ``plan_registry`` resolution at call
  time, NOT from a module-level constant. Production deploys can rotate
  via ``geode login set-key openai sk-…`` without restart.
- **P7 Caller-Callee Contract** — Proximity (S4) calls this with a list
  of strings and expects a list of vectors in the SAME order; the API
  guarantees ``len(input) == len(output)`` and per-index alignment.
  Errors raise ``EmbeddingError`` with a structured message so the
  caller can attribute failures to specific candidates.
"""

from __future__ import annotations

import logging
import math
from typing import Any

log = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_EMBED_MODEL",
    "EmbeddingError",
    "cosine_similarity",
    "embed_texts",
    "embed_texts_async",
]


DEFAULT_EMBED_MODEL = "text-embedding-3-small"


class EmbeddingError(RuntimeError):
    """Raised when the embeddings API fails or returns an inconsistent shape.

    Carries ``model`` + ``input_count`` so the caller (Proximity agent)
    can correlate the failure with specific candidates.
    """

    def __init__(self, message: str, *, model: str, input_count: int) -> None:
        self.model = model
        self.input_count = input_count
        super().__init__(
            f"embedding failure (model={model!r}, input_count={input_count}): {message}"
        )


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two equal-dim vectors.

    Returns 0.0 when either vector is the zero vector (avoids
    ZeroDivisionError; the seed-pipeline interprets 0.0 as "no
    similarity signal"). Raises ``ValueError`` on dim mismatch.

    Pure function — no I/O, suitable for use inside the Proximity
    agent's per-pair loop without extra dependency injection.
    """
    if len(a) != len(b):
        raise ValueError(f"cosine_similarity: vector dim mismatch {len(a)} != {len(b)}")
    if not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def _resolve_openai_api_key() -> str:
    """Resolve the OpenAI API key from settings (lazy).

    Raises ``EmbeddingError`` (with empty input_count) when the key is
    missing — the caller cannot proceed and must surface a clear error
    instead of silently producing wrong vectors.
    """
    try:
        from core.config import settings
    except Exception as exc:
        raise EmbeddingError(
            "core.config import failed — cannot resolve OPENAI_API_KEY",
            model=DEFAULT_EMBED_MODEL,
            input_count=0,
        ) from exc
    key = getattr(settings, "openai_api_key", "") or ""
    if not key:
        raise EmbeddingError(
            "OPENAI_API_KEY is empty — set it via `geode login set-key openai "
            "sk-…` or via the OPENAI_API_KEY env var",
            model=DEFAULT_EMBED_MODEL,
            input_count=0,
        )
    return str(key)


async def embed_texts_async(
    texts: list[str],
    *,
    model: str = DEFAULT_EMBED_MODEL,
    client: Any | None = None,
) -> list[list[float]]:
    """Compute embeddings for ``texts`` — async API.

    Returns vectors aligned 1:1 with ``texts``. ``client`` is an optional
    pre-built ``openai.AsyncOpenAI`` instance; when omitted a fresh one
    is constructed with the resolved API key. Tests inject a stub here.
    """
    if not texts:
        return []
    if client is None:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=_resolve_openai_api_key())
    try:
        response = await client.embeddings.create(model=model, input=texts)
    except Exception as exc:
        raise EmbeddingError(
            f"OpenAI embeddings API call failed: {exc}",
            model=model,
            input_count=len(texts),
        ) from exc
    vectors = [item.embedding for item in response.data]
    if len(vectors) != len(texts):
        raise EmbeddingError(
            f"input/output count mismatch: {len(texts)} input -> {len(vectors)} output",
            model=model,
            input_count=len(texts),
        )
    return [list(v) for v in vectors]


def embed_texts(
    texts: list[str],
    *,
    model: str = DEFAULT_EMBED_MODEL,
    client: Any | None = None,
) -> list[list[float]]:
    """Synchronous wrapper around :func:`embed_texts_async`.

    Convenience for callers in non-async contexts (Proximity agent's
    sequential dedup loop). Reuses :func:`asyncio.run`-like dispatch
    via ``core.async_runtime.run_process_coroutine`` so it interops
    with the worker subprocess's event loop.
    """
    import asyncio

    return asyncio.run(embed_texts_async(texts, model=model, client=client))
