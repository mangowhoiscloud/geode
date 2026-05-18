"""Unit tests for ``core.tools.text_embed``."""

from __future__ import annotations

import asyncio
import math
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from core.tools.text_embed import (
    DEFAULT_EMBED_MODEL,
    EmbeddingError,
    cosine_similarity,
    embed_texts_async,
)

# ─────────────────────────── cosine_similarity ───────────────────────────


def test_cosine_identical_vectors_returns_one() -> None:
    v = [1.0, 0.0, 0.5]
    assert cosine_similarity(v, v) == pytest.approx(1.0)


def test_cosine_orthogonal_vectors_returns_zero() -> None:
    a = [1.0, 0.0]
    b = [0.0, 1.0]
    assert cosine_similarity(a, b) == pytest.approx(0.0)


def test_cosine_opposite_vectors_returns_negative_one() -> None:
    a = [1.0, 0.0]
    b = [-1.0, 0.0]
    assert cosine_similarity(a, b) == pytest.approx(-1.0)


def test_cosine_zero_vector_returns_zero() -> None:
    a = [0.0, 0.0]
    b = [1.0, 1.0]
    assert cosine_similarity(a, b) == 0.0


def test_cosine_dim_mismatch_raises() -> None:
    with pytest.raises(ValueError, match="dim mismatch"):
        cosine_similarity([1.0], [1.0, 0.0])


def test_cosine_known_pair() -> None:
    a = [1.0, 1.0]
    b = [1.0, 0.0]
    # cos = 1 / sqrt(2)
    expected = 1 / math.sqrt(2)
    assert cosine_similarity(a, b) == pytest.approx(expected)


# ─────────────────────────── embed_texts_async ───────────────────────────


def _fake_response(num_inputs: int, dim: int = 4) -> Any:
    """Construct a fake OpenAI-like response object."""
    response = MagicMock()
    response.data = [MagicMock(embedding=[float(i + 1)] * dim) for i in range(num_inputs)]
    return response


def test_embed_async_empty_returns_empty() -> None:
    out = asyncio.run(embed_texts_async([]))
    assert out == []


def test_embed_async_aligns_with_input_order() -> None:
    fake_client = MagicMock()
    fake_client.embeddings.create = AsyncMock(return_value=_fake_response(3))
    result = asyncio.run(embed_texts_async(["a", "b", "c"], client=fake_client))
    assert len(result) == 3
    assert result[0] == [1.0, 1.0, 1.0, 1.0]
    assert result[1] == [2.0, 2.0, 2.0, 2.0]
    assert result[2] == [3.0, 3.0, 3.0, 3.0]


def test_embed_async_count_mismatch_raises() -> None:
    fake_client = MagicMock()
    fake_client.embeddings.create = AsyncMock(return_value=_fake_response(2))
    with pytest.raises(EmbeddingError, match="count mismatch"):
        asyncio.run(embed_texts_async(["a", "b", "c"], client=fake_client))


def test_embed_async_api_failure_translates_to_embedding_error() -> None:
    fake_client = MagicMock()
    fake_client.embeddings.create = AsyncMock(side_effect=RuntimeError("API down"))
    with pytest.raises(EmbeddingError, match="API down"):
        asyncio.run(embed_texts_async(["a"], client=fake_client))


def test_embed_async_uses_default_model() -> None:
    fake_client = MagicMock()
    fake_client.embeddings.create = AsyncMock(return_value=_fake_response(1))
    asyncio.run(embed_texts_async(["a"], client=fake_client))
    fake_client.embeddings.create.assert_awaited_once()
    args = fake_client.embeddings.create.call_args
    assert args.kwargs["model"] == DEFAULT_EMBED_MODEL
