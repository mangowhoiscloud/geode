"""Tests for ``core.text.similarity`` — Jaccard / shingles primitives."""

from __future__ import annotations

import pytest
from core.text.similarity import (
    DEFAULT_NGRAM_SIZE,
    jaccard_similarity,
    shingles,
    text_jaccard,
)


class TestShingles:
    def test_basic_split(self) -> None:
        text = "the quick brown fox jumps over the lazy dog"
        result = shingles(text, n=5)
        assert "the quick brown fox jumps" in result
        assert "quick brown fox jumps over" in result
        assert len(result) == 5  # 9 tokens, 5-gram → 5 windows

    def test_lowercased(self) -> None:
        result = shingles("The Quick Brown Fox Jumps", n=5)
        assert "the quick brown fox jumps" in result

    def test_shorter_than_ngram(self) -> None:
        # 3 tokens, default n=5 → whole text is the only shingle.
        result = shingles("a b c", n=5)
        assert result == {"a b c"}

    def test_empty(self) -> None:
        assert shingles("", n=5) == set()

    def test_default_n(self) -> None:
        assert DEFAULT_NGRAM_SIZE == 5
        text = "one two three four five six"
        # 6 tokens, n=5 → 2 windows.
        assert len(shingles(text)) == 2


class TestJaccardSimilarity:
    def test_identical(self) -> None:
        assert jaccard_similarity({"a", "b"}, {"a", "b"}) == 1.0

    def test_disjoint(self) -> None:
        assert jaccard_similarity({"a"}, {"b"}) == 0.0

    def test_partial(self) -> None:
        # |{a,b} ∩ {b,c}| = 1, |union| = 3 → 1/3.
        assert jaccard_similarity({"a", "b"}, {"b", "c"}) == pytest.approx(1 / 3)

    def test_both_empty(self) -> None:
        assert jaccard_similarity(set(), set()) == 0.0

    def test_one_empty(self) -> None:
        assert jaccard_similarity({"a"}, set()) == 0.0
        assert jaccard_similarity(set(), {"a"}) == 0.0


class TestTextJaccard:
    def test_identical_text(self) -> None:
        assert text_jaccard("one two three four five", "one two three four five") == 1.0

    def test_disjoint_text(self) -> None:
        assert text_jaccard("a b c d e", "x y z w v") == 0.0

    def test_near_duplicate(self) -> None:
        # Same 5-token preamble, divergent tails.
        left = "the model misuses tool error to escalate without reflection"
        right = "the model misuses tool error during escalate but recovers properly"
        score = text_jaccard(left, right, n=5)
        assert 0.0 < score < 1.0  # some shingles shared, not all


class TestProximityReexports:
    """Pin that proximity.py still exposes ``_shingles`` and ``_jaccard``
    as compatibility shims so external importers (tests, third-party
    plugins) don't break after the hoist."""

    def test_proximity_reexports_jaccard(self) -> None:
        from plugins.seed_generation.agents.proximity import _jaccard

        assert _jaccard({"a"}, {"a"}) == 1.0

    def test_proximity_reexports_shingles(self) -> None:
        from plugins.seed_generation.agents.proximity import _shingles

        assert _shingles("a b c d e f g") == shingles("a b c d e f g")
