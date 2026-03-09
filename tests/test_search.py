"""Tests for IP Search Engine — keyword-based search."""

import pytest

from geode.cli.search import IPSearchEngine


@pytest.fixture
def engine():
    return IPSearchEngine()


class TestBasicSearch:
    def test_genre_search_dark_fantasy(self, engine):
        results = engine.search("dark fantasy")
        assert len(results) >= 1
        assert results[0].ip_name == "Berserk"

    def test_genre_search_cyberpunk(self, engine):
        results = engine.search("cyberpunk")
        assert len(results) >= 1
        # Ghost in the Shell has cyberpunk genre_fit_keywords
        names = [r.ip_name for r in results]
        assert "Ghost in the Shell" in names

    def test_genre_search_noir(self, engine):
        results = engine.search("noir")
        assert len(results) >= 1
        names = [r.ip_name for r in results]
        assert "Cowboy Bebop" in names

    def test_genre_search_action(self, engine):
        """Action is common — should match multiple IPs."""
        results = engine.search("action")
        assert len(results) >= 2

    def test_empty_query(self, engine):
        results = engine.search("")
        assert results == []


class TestKoreanSearch:
    def test_soulslike_korean(self, engine):
        results = engine.search("소울라이크")
        assert len(results) >= 1
        assert results[0].ip_name == "Berserk"

    def test_dark_fantasy_korean(self, engine):
        results = engine.search("다크 판타지")
        assert len(results) >= 1
        assert results[0].ip_name == "Berserk"

    def test_cyberpunk_korean(self, engine):
        results = engine.search("사이버펑크")
        assert len(results) >= 1
        names = [r.ip_name for r in results]
        assert "Ghost in the Shell" in names

    def test_noir_korean(self, engine):
        results = engine.search("느와르")
        assert len(results) >= 1
        names = [r.ip_name for r in results]
        assert "Cowboy Bebop" in names


class TestKeywordSearch:
    def test_souls_like_hyphenated(self, engine):
        results = engine.search("souls-like")
        assert len(results) >= 1
        assert results[0].ip_name == "Berserk"

    def test_bounty_hunter(self, engine):
        results = engine.search("bounty hunter")
        assert len(results) >= 1
        names = [r.ip_name for r in results]
        assert "Cowboy Bebop" in names

    def test_stealth_hacking(self, engine):
        results = engine.search("stealth hacking")
        assert len(results) >= 1
        names = [r.ip_name for r in results]
        assert "Ghost in the Shell" in names


class TestSearchResultOrdering:
    def test_results_sorted_by_score(self, engine):
        results = engine.search("action RPG")
        if len(results) > 1:
            for i in range(len(results) - 1):
                assert results[i].score >= results[i + 1].score

    def test_score_range(self, engine):
        results = engine.search("dark fantasy")
        for r in results:
            assert 0.0 <= r.score <= 1.0

    def test_matches_not_empty(self, engine):
        results = engine.search("dark fantasy")
        for r in results:
            assert len(r.matches) > 0


class TestSearchCommands:
    def test_search_ip_by_name(self, engine):
        """Searching by IP name should find it."""
        results = engine.search("berserk")
        assert len(results) >= 1
        assert results[0].ip_name == "Berserk"

    def test_media_type_manga(self, engine):
        results = engine.search("manga")
        names = [r.ip_name for r in results]
        assert "Berserk" in names

    def test_media_type_anime(self, engine):
        results = engine.search("anime")
        names = [r.ip_name for r in results]
        assert "Cowboy Bebop" in names
