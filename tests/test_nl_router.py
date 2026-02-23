"""Tests for NL Router — intent classification from natural language."""

import pytest

from geode.cli.nl_router import NLRouter


@pytest.fixture
def router():
    return NLRouter()


class TestSearchIntent:
    def test_korean_search_with_찾아줘(self, router):
        intent = router.classify("다크 판타지 게임 찾아줘")
        assert intent.action == "search"
        assert "다크 판타지 게임" in intent.args["query"]

    def test_korean_search_with_검색(self, router):
        intent = router.classify("소울라이크 검색")
        assert intent.action == "search"

    def test_english_search(self, router):
        intent = router.classify("search dark fantasy")
        assert intent.action == "search"
        assert "dark fantasy" in intent.args["query"]

    def test_english_find(self, router):
        intent = router.classify("find action RPG games")
        assert intent.action == "search"

    def test_genre_keyword_detection(self, router):
        """Genre keywords should trigger search even without explicit search verbs."""
        intent = router.classify("소울라이크")
        assert intent.action == "search"

    def test_genre_keyword_english(self, router):
        intent = router.classify("cyberpunk stealth")
        assert intent.action == "search"

    def test_genre_keyword_mixed(self, router):
        intent = router.classify("다크 판타지")
        assert intent.action == "search"


class TestAnalyzeIntent:
    def test_korean_analyze(self, router):
        intent = router.classify("Berserk 분석해")
        assert intent.action == "analyze"
        assert intent.args["ip_name"] == "Berserk"

    def test_korean_evaluate(self, router):
        intent = router.classify("Cowboy Bebop 평가해")
        assert intent.action == "analyze"

    def test_english_analyze(self, router):
        intent = router.classify("analyze Ghost in the Shell")
        assert intent.action == "analyze"
        assert "Ghost in the Shell" in intent.args["ip_name"]

    def test_bare_ip_name(self, router):
        """Bare IP name defaults to analyze."""
        intent = router.classify("Berserk")
        assert intent.action == "analyze"
        assert intent.args["ip_name"] == "Berserk"
        assert intent.confidence < 1.0  # lower confidence for default


class TestCompareIntent:
    def test_korean_vs(self, router):
        intent = router.classify("Berserk vs Cowboy Bebop")
        assert intent.action == "compare"
        assert intent.args["ip_a"] == "Berserk"
        assert intent.args["ip_b"] == "Cowboy Bebop"

    def test_korean_비교(self, router):
        intent = router.classify("Berserk하고 Cowboy Bebop 비교")
        assert intent.action == "compare"


class TestListIntent:
    def test_korean_목록(self, router):
        intent = router.classify("IP 목록")
        assert intent.action == "list"

    def test_korean_뭐가있어(self, router):
        intent = router.classify("뭐가 있어?")
        assert intent.action == "list"

    def test_english_list(self, router):
        intent = router.classify("list all")
        assert intent.action == "list"


class TestHelpIntent:
    def test_korean_도움(self, router):
        intent = router.classify("도움")
        assert intent.action == "help"

    def test_english_help(self, router):
        intent = router.classify("help")
        assert intent.action == "help"

    def test_empty_input(self, router):
        intent = router.classify("")
        assert intent.action == "help"
