"""Tests for NLRouter — Claude Opus 4.6 Tool Use (autonomous)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import anthropic
import pytest

from geode.cli.nl_router import (
    NLIntent,
    NLRouter,
    _offline_fallback,
    _parse_text_response,
    _parse_tool_use,
)


@pytest.fixture
def router() -> NLRouter:
    """Router with LLM disabled."""
    return NLRouter(llm_enabled=False)


@pytest.fixture
def router_llm() -> NLRouter:
    """Router with LLM enabled."""
    return NLRouter(llm_enabled=True)


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


def _preserve_exceptions(mock_anthropic: MagicMock) -> None:
    """Preserve real exception classes on mocked anthropic module.

    When patching `geode.cli.nl_router.anthropic`, MagicMock replaces
    exception classes too. The `except` chain needs real BaseException
    subclasses to evaluate, so we restore them on the mock.
    """
    mock_anthropic.AuthenticationError = anthropic.AuthenticationError
    mock_anthropic.BadRequestError = anthropic.BadRequestError


def _make_tool_use_response(
    tool_name: str,
    tool_input: dict,
    *,
    with_usage: bool = True,
) -> MagicMock:
    """Create a mock Anthropic response with a tool_use block."""
    mock = MagicMock()
    mock.stop_reason = "tool_use"

    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.name = tool_name
    tool_block.input = tool_input

    mock.content = [tool_block]

    if with_usage:
        mock.usage = MagicMock(input_tokens=200, output_tokens=50)
    else:
        mock.usage = None

    return mock


def _make_text_response(
    text: str,
    *,
    with_usage: bool = True,
) -> MagicMock:
    """Create a mock Anthropic response with a text block (chat)."""
    mock = MagicMock()
    mock.stop_reason = "end_turn"

    text_block = MagicMock()
    text_block.type = "text"
    text_block.text = text

    mock.content = [text_block]

    if with_usage:
        mock.usage = MagicMock(input_tokens=200, output_tokens=50)
    else:
        mock.usage = None

    return mock


# ---------------------------------------------------------------------------
# Edge cases (no LLM call)
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Empty/whitespace input and LLM-disabled fallback."""

    def test_empty_input(self, router_llm: NLRouter) -> None:
        intent = router_llm.classify("")
        assert intent.action == "help"

    def test_whitespace_input(self, router_llm: NLRouter) -> None:
        intent = router_llm.classify("   ")
        assert intent.action == "help"

    def test_llm_disabled_fallback(self, router: NLRouter) -> None:
        intent = router.classify("anything")
        assert intent.action == "help"
        assert intent.confidence == 0.3


# ---------------------------------------------------------------------------
# _parse_tool_use unit tests
# ---------------------------------------------------------------------------


class TestParseToolUse:
    """Verify _parse_tool_use maps each tool correctly."""

    def test_list_ips(self) -> None:
        resp = _make_tool_use_response("list_ips", {})
        intent = _parse_tool_use(resp)
        assert intent.action == "list"
        assert intent.args == {}
        assert intent.confidence == 0.95

    def test_analyze_ip(self) -> None:
        resp = _make_tool_use_response("analyze_ip", {"ip_name": "Berserk"})
        intent = _parse_tool_use(resp)
        assert intent.action == "analyze"
        assert intent.args == {"ip_name": "Berserk"}
        assert intent.confidence == 0.95

    def test_search_ips(self) -> None:
        resp = _make_tool_use_response("search_ips", {"query": "dark fantasy"})
        intent = _parse_tool_use(resp)
        assert intent.action == "search"
        assert intent.args == {"query": "dark fantasy"}

    def test_compare_ips(self) -> None:
        resp = _make_tool_use_response(
            "compare_ips",
            {"ip_a": "Berserk", "ip_b": "Cowboy Bebop"},
        )
        intent = _parse_tool_use(resp)
        assert intent.action == "compare"
        assert intent.args["ip_a"] == "Berserk"
        assert intent.args["ip_b"] == "Cowboy Bebop"

    def test_show_help(self) -> None:
        resp = _make_tool_use_response("show_help", {})
        intent = _parse_tool_use(resp)
        assert intent.action == "help"
        assert intent.confidence == 0.95

    def test_unknown_tool_falls_back_to_chat(self) -> None:
        resp = _make_tool_use_response("unknown_tool", {})
        intent = _parse_tool_use(resp)
        assert intent.action == "chat"

    def test_no_tool_use_block(self) -> None:
        """Response with stop_reason=tool_use but no ToolUseBlock."""
        mock = MagicMock()
        mock.stop_reason = "tool_use"
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "some text"
        mock.content = [text_block]

        intent = _parse_tool_use(mock)
        assert intent.action == "help"
        assert intent.confidence == 0.5


# ---------------------------------------------------------------------------
# _parse_text_response unit tests
# ---------------------------------------------------------------------------


class TestParseTextResponse:
    """Verify _parse_text_response extracts chat text."""

    def test_text_response(self) -> None:
        resp = _make_text_response("게임 퍼블리싱은 계약을 통해 진행됩니다.")
        intent = _parse_text_response(resp)
        assert intent.action == "chat"
        assert intent.args["response"] == ("게임 퍼블리싱은 계약을 통해 진행됩니다.")
        assert intent.confidence == 0.9

    def test_empty_text_response(self) -> None:
        resp = _make_text_response("")
        intent = _parse_text_response(resp)
        assert intent.action == "help"
        assert intent.confidence == 0.5

    def test_multi_block_text(self) -> None:
        """Multiple text blocks are joined."""
        mock = MagicMock()
        mock.stop_reason = "end_turn"

        b1 = MagicMock()
        b1.type = "text"
        b1.text = "First part."
        b2 = MagicMock()
        b2.type = "text"
        b2.text = "Second part."
        mock.content = [b1, b2]

        intent = _parse_text_response(mock)
        assert intent.action == "chat"
        assert "First part." in intent.args["response"]
        assert "Second part." in intent.args["response"]


# ---------------------------------------------------------------------------
# Tool Use router integration (mocked API calls)
# ---------------------------------------------------------------------------


class TestToolUseRouter:
    """Full _call_tool_use_router flow with mocked Anthropic API."""

    def test_tool_use_list(self, router_llm: NLRouter) -> None:
        """LLM calls list_ips tool."""
        resp = _make_tool_use_response("list_ips", {})
        with (
            patch("geode.cli.nl_router.anthropic") as mock_anthropic,
            patch("geode.cli.nl_router.settings") as mock_settings,
        ):
            mock_settings.anthropic_api_key = "sk-ant-test"
            mock_client = MagicMock()
            mock_anthropic.Anthropic.return_value = mock_client
            mock_client.messages.create.return_value = resp

            intent = router_llm.classify("IP 목록 보여줘")

        assert intent.action == "list"
        assert intent.confidence == 0.95

    def test_tool_use_analyze(self, router_llm: NLRouter) -> None:
        """LLM calls analyze_ip tool with ip_name."""
        resp = _make_tool_use_response("analyze_ip", {"ip_name": "Cowboy Bebop"})
        with (
            patch("geode.cli.nl_router.anthropic") as mock_anthropic,
            patch("geode.cli.nl_router.settings") as mock_settings,
        ):
            mock_settings.anthropic_api_key = "sk-ant-test"
            mock_client = MagicMock()
            mock_anthropic.Anthropic.return_value = mock_client
            mock_client.messages.create.return_value = resp

            intent = router_llm.classify("Cowboy Bebop 분석해")

        assert intent.action == "analyze"
        assert intent.args["ip_name"] == "Cowboy Bebop"

    def test_tool_use_search(self, router_llm: NLRouter) -> None:
        """LLM calls search_ips tool."""
        resp = _make_tool_use_response("search_ips", {"query": "소울라이크"})
        with (
            patch("geode.cli.nl_router.anthropic") as mock_anthropic,
            patch("geode.cli.nl_router.settings") as mock_settings,
        ):
            mock_settings.anthropic_api_key = "sk-ant-test"
            mock_client = MagicMock()
            mock_anthropic.Anthropic.return_value = mock_client
            mock_client.messages.create.return_value = resp

            intent = router_llm.classify("소울라이크 검색")

        assert intent.action == "search"
        assert intent.args["query"] == "소울라이크"

    def test_tool_use_compare(self, router_llm: NLRouter) -> None:
        """LLM calls compare_ips tool."""
        resp = _make_tool_use_response(
            "compare_ips",
            {"ip_a": "Berserk", "ip_b": "Ghost In The Shell"},
        )
        with (
            patch("geode.cli.nl_router.anthropic") as mock_anthropic,
            patch("geode.cli.nl_router.settings") as mock_settings,
        ):
            mock_settings.anthropic_api_key = "sk-ant-test"
            mock_client = MagicMock()
            mock_anthropic.Anthropic.return_value = mock_client
            mock_client.messages.create.return_value = resp

            intent = router_llm.classify("Berserk vs Ghost In The Shell")

        assert intent.action == "compare"
        assert intent.args["ip_a"] == "Berserk"
        assert intent.args["ip_b"] == "Ghost In The Shell"

    def test_tool_use_help(self, router_llm: NLRouter) -> None:
        """LLM calls show_help tool."""
        resp = _make_tool_use_response("show_help", {})
        with (
            patch("geode.cli.nl_router.anthropic") as mock_anthropic,
            patch("geode.cli.nl_router.settings") as mock_settings,
        ):
            mock_settings.anthropic_api_key = "sk-ant-test"
            mock_client = MagicMock()
            mock_anthropic.Anthropic.return_value = mock_client
            mock_client.messages.create.return_value = resp

            intent = router_llm.classify("도움말")

        assert intent.action == "help"
        assert intent.confidence == 0.95

    def test_text_response_chat(self, router_llm: NLRouter) -> None:
        """LLM responds with text → chat intent."""
        resp = _make_text_response("게임 퍼블리싱은 계약을 통해 진행됩니다.")
        with (
            patch("geode.cli.nl_router.anthropic") as mock_anthropic,
            patch("geode.cli.nl_router.settings") as mock_settings,
        ):
            mock_settings.anthropic_api_key = "sk-ant-test"
            mock_client = MagicMock()
            mock_anthropic.Anthropic.return_value = mock_client
            mock_client.messages.create.return_value = resp

            intent = router_llm.classify("게임 퍼블리싱이 뭐야?")

        assert intent.action == "chat"
        assert "response" in intent.args
        assert intent.confidence == 0.9


# ---------------------------------------------------------------------------
# Graceful degradation
# ---------------------------------------------------------------------------


class TestGracefulDegradation:
    """No API key, API errors, empty responses."""

    def test_no_api_key(self, router_llm: NLRouter) -> None:
        """Without API key → offline fallback with error context."""
        with patch("geode.cli.nl_router.settings") as mock_settings:
            mock_settings.anthropic_api_key = ""
            intent = router_llm.classify("anything")

        assert intent.action == "help"
        assert intent.args.get("_error") == "no_api_key"
        assert intent.confidence == 0.3

    def test_no_api_key_with_known_ip(self, router_llm: NLRouter) -> None:
        """Without API key, known IP still routes to analyze."""
        with patch("geode.cli.nl_router.settings") as mock_settings:
            mock_settings.anthropic_api_key = ""
            intent = router_llm.classify("Berserk")

        assert intent.action == "analyze"
        assert intent.args["ip_name"] == "Berserk"
        assert intent.args["_error"] == "no_api_key"

    def test_api_error(self, router_llm: NLRouter) -> None:
        """API exception → offline fallback."""
        with (
            patch("geode.cli.nl_router.anthropic") as mock_anthropic,
            patch("geode.cli.nl_router.settings") as mock_settings,
        ):
            mock_settings.anthropic_api_key = "sk-ant-test"
            _preserve_exceptions(mock_anthropic)
            mock_anthropic.Anthropic.side_effect = Exception("API down")

            intent = router_llm.classify("이상한 입력")

        assert intent.action == "help"
        assert intent.args.get("_error") == "api_error"
        assert intent.confidence == 0.3

    def test_api_timeout(self, router_llm: NLRouter) -> None:
        """Timeout → offline fallback."""
        with (
            patch("geode.cli.nl_router.anthropic") as mock_anthropic,
            patch("geode.cli.nl_router.settings") as mock_settings,
        ):
            mock_settings.anthropic_api_key = "sk-ant-test"
            _preserve_exceptions(mock_anthropic)
            mock_client = MagicMock()
            mock_anthropic.Anthropic.return_value = mock_client
            mock_client.messages.create.side_effect = TimeoutError("Request timed out")

            intent = router_llm.classify("타임아웃 테스트")

        assert intent.action == "help"
        assert intent.args.get("_error") == "api_error"
        assert intent.confidence == 0.3

    def test_auth_error(self, router_llm: NLRouter) -> None:
        """Invalid API key → offline fallback with auth_error."""
        with (
            patch("geode.cli.nl_router.anthropic") as mock_anthropic,
            patch("geode.cli.nl_router.settings") as mock_settings,
        ):
            mock_settings.anthropic_api_key = "sk-ant-invalid"
            _preserve_exceptions(mock_anthropic)
            mock_client = MagicMock()
            mock_anthropic.Anthropic.return_value = mock_client
            mock_client.messages.create.side_effect = anthropic.AuthenticationError(
                message="invalid x-api-key",
                response=MagicMock(status_code=401),
                body={"type": "error"},
            )

            intent = router_llm.classify("안녕")

        assert intent.action == "help"
        assert intent.args.get("_error") == "auth_error"

    def test_billing_error(self, router_llm: NLRouter) -> None:
        """Credit balance error → offline fallback with billing error."""
        with (
            patch("geode.cli.nl_router.anthropic") as mock_anthropic,
            patch("geode.cli.nl_router.settings") as mock_settings,
        ):
            mock_settings.anthropic_api_key = "sk-ant-test"
            _preserve_exceptions(mock_anthropic)
            mock_client = MagicMock()
            mock_anthropic.Anthropic.return_value = mock_client
            mock_client.messages.create.side_effect = anthropic.BadRequestError(
                message="Your credit balance is too low",
                response=MagicMock(status_code=400),
                body={"type": "error"},
            )

            intent = router_llm.classify("목록 보여줘")

        assert intent.action == "list"
        assert intent.args.get("_error") == "billing"

    def test_billing_error_unknown_input(self, router_llm: NLRouter) -> None:
        """Billing error on unrecognized input → help with billing."""
        with (
            patch("geode.cli.nl_router.anthropic") as mock_anthropic,
            patch("geode.cli.nl_router.settings") as mock_settings,
        ):
            mock_settings.anthropic_api_key = "sk-ant-test"
            _preserve_exceptions(mock_anthropic)
            mock_client = MagicMock()
            mock_anthropic.Anthropic.return_value = mock_client
            mock_client.messages.create.side_effect = anthropic.BadRequestError(
                message="Your credit balance is too low",
                response=MagicMock(status_code=400),
                body={"type": "error"},
            )

            intent = router_llm.classify("안녕")

        assert intent.action == "help"
        assert intent.args.get("_error") == "billing"

    def test_empty_text_response(self, router_llm: NLRouter) -> None:
        """LLM returns empty text → help fallback."""
        resp = _make_text_response("", with_usage=False)
        with (
            patch("geode.cli.nl_router.anthropic") as mock_anthropic,
            patch("geode.cli.nl_router.settings") as mock_settings,
        ):
            mock_settings.anthropic_api_key = "sk-ant-test"
            mock_client = MagicMock()
            mock_anthropic.Anthropic.return_value = mock_client
            mock_client.messages.create.return_value = resp

            intent = router_llm.classify("빈 응답 테스트")

        assert intent.action == "help"
        assert intent.confidence == 0.5


# ---------------------------------------------------------------------------
# Token usage tracking
# ---------------------------------------------------------------------------


class TestTokenUsageTracking:
    """Verify token usage is recorded when response has usage."""

    def test_usage_recorded(self, router_llm: NLRouter) -> None:
        """Token usage from tool_use response is tracked."""
        resp = _make_tool_use_response("list_ips", {}, with_usage=True)
        with (
            patch("geode.cli.nl_router.anthropic") as mock_anthropic,
            patch("geode.cli.nl_router.settings") as mock_settings,
            patch("geode.llm.client.calculate_cost", return_value=0.0035) as mock_cost,
            patch("geode.llm.client.get_usage_accumulator") as mock_acc_fn,
        ):
            mock_settings.anthropic_api_key = "sk-ant-test"
            mock_client = MagicMock()
            mock_anthropic.Anthropic.return_value = mock_client
            mock_client.messages.create.return_value = resp

            mock_acc = MagicMock()
            mock_acc_fn.return_value = mock_acc

            router_llm.classify("목록")

        mock_cost.assert_called_once()
        mock_acc.record.assert_called_once()

    def test_no_usage(self, router_llm: NLRouter) -> None:
        """No usage field → no tracking error."""
        resp = _make_tool_use_response("list_ips", {}, with_usage=False)
        with (
            patch("geode.cli.nl_router.anthropic") as mock_anthropic,
            patch("geode.cli.nl_router.settings") as mock_settings,
        ):
            mock_settings.anthropic_api_key = "sk-ant-test"
            mock_client = MagicMock()
            mock_anthropic.Anthropic.return_value = mock_client
            mock_client.messages.create.return_value = resp

            intent = router_llm.classify("목록")

        assert intent.action == "list"


# ---------------------------------------------------------------------------
# NLIntent data model
# ---------------------------------------------------------------------------


class TestNLIntent:
    """NLIntent dataclass behavior."""

    def test_defaults(self) -> None:
        intent = NLIntent(action="list")
        assert intent.action == "list"
        assert intent.args == {}
        assert intent.confidence == 1.0

    def test_with_args(self) -> None:
        intent = NLIntent(
            action="analyze",
            args={"ip_name": "Berserk"},
            confidence=0.95,
        )
        assert intent.args["ip_name"] == "Berserk"
        assert intent.confidence == 0.95

    def test_valid_actions(self) -> None:
        from geode.cli.nl_router import VALID_ACTIONS

        for action in VALID_ACTIONS:
            intent = NLIntent(action=action)
            assert intent.action == action


# ---------------------------------------------------------------------------
# Offline fallback tests
# ---------------------------------------------------------------------------


class TestOfflineFallback:
    """_offline_fallback pattern matching when LLM is unavailable."""

    @pytest.mark.parametrize(
        "text",
        [
            "목록",
            "리스트",
            "list",
            "show all",
            "display",
            "IP 목록",
        ],
    )
    def test_list_patterns(self, text: str) -> None:
        intent = _offline_fallback(text, error="billing")
        assert intent.action == "list"
        assert intent.args["_error"] == "billing"

    @pytest.mark.parametrize(
        "text",
        [
            "도움",
            "도움말",
            "help",
            "사용법",
            "가이드",
            "어떻게",
            "how to use",
        ],
    )
    def test_help_patterns(self, text: str) -> None:
        intent = _offline_fallback(text, error="api_error")
        assert intent.action == "help"

    @pytest.mark.parametrize(
        "text",
        [
            "Berserk",
            "cowboy bebop",
            "Ghost In The Shell",
            "berserk 분석해",
        ],
    )
    def test_known_ip_analyze(self, text: str) -> None:
        intent = _offline_fallback(text, error="billing")
        assert intent.action == "analyze"
        assert intent.confidence == 0.7

    @pytest.mark.parametrize(
        "text",
        [
            "분석해줘 테스트",
            "analyze something",
            "평가해줘",
        ],
    )
    def test_analyze_patterns(self, text: str) -> None:
        intent = _offline_fallback(text, error="billing")
        assert intent.action == "analyze"

    @pytest.mark.parametrize(
        "text",
        [
            "다크 판타지 찾아줘",
            "검색",
            "search soulslike",
            "find me something",
        ],
    )
    def test_search_patterns(self, text: str) -> None:
        intent = _offline_fallback(text, error="billing")
        assert intent.action == "search"

    def test_unknown_text_returns_help(self) -> None:
        intent = _offline_fallback("안녕", error="billing")
        assert intent.action == "help"
        assert intent.args["_error"] == "billing"
        assert intent.confidence == 0.3

    def test_compare_falls_back_to_help(self) -> None:
        """Compare requires LLM for arg parsing — offline returns help."""
        intent = _offline_fallback("Berserk vs Cowboy Bebop", error="billing")
        # "vs" triggers compare pattern but offline can't parse args
        assert intent.action == "help"

    def test_error_context_preserved(self) -> None:
        intent = _offline_fallback("anything", error="no_api_key")
        assert intent.args["_error"] == "no_api_key"

    @pytest.mark.parametrize(
        "text",
        [
            "배치 돌려",
            "전체 IP 분석해줘",
            "모든 IP 순위",
            "rank all",
            "batch",
            "top 10",
        ],
    )
    def test_batch_patterns(self, text: str) -> None:
        intent = _offline_fallback(text, error="billing")
        assert intent.action == "batch"

    @pytest.mark.parametrize(
        "text",
        [
            "상태 확인",
            "시스템 건강",
            "health check",
            "status",
            "설정 보여줘",
        ],
    )
    def test_status_patterns(self, text: str) -> None:
        intent = _offline_fallback(text, error="billing")
        assert intent.action == "status"

    @pytest.mark.parametrize(
        "text",
        [
            "모델 바꿔",
            "switch model",
            "앙상블 모드로",
            "cross 모드 켜줘",
        ],
    )
    def test_model_patterns(self, text: str) -> None:
        intent = _offline_fallback(text, error="billing")
        assert intent.action == "model"


# ---------------------------------------------------------------------------
# New tool parsing tests
# ---------------------------------------------------------------------------


class TestNewToolParsing:
    """Verify new tools (batch, status, model) parse correctly."""

    def test_batch_analyze(self) -> None:
        resp = _make_tool_use_response("batch_analyze", {"top": 5, "genre": "Dark Fantasy"})
        intent = _parse_tool_use(resp)
        assert intent.action == "batch"
        assert intent.args["top"] == 5
        assert intent.args["genre"] == "Dark Fantasy"

    def test_batch_analyze_no_args(self) -> None:
        resp = _make_tool_use_response("batch_analyze", {})
        intent = _parse_tool_use(resp)
        assert intent.action == "batch"
        assert intent.args == {}

    def test_check_status(self) -> None:
        resp = _make_tool_use_response("check_status", {})
        intent = _parse_tool_use(resp)
        assert intent.action == "status"
        assert intent.confidence == 0.95

    def test_switch_model_with_hint(self) -> None:
        resp = _make_tool_use_response("switch_model", {"model_hint": "haiku"})
        intent = _parse_tool_use(resp)
        assert intent.action == "model"
        assert intent.args["model_hint"] == "haiku"

    def test_switch_model_no_hint(self) -> None:
        resp = _make_tool_use_response("switch_model", {})
        intent = _parse_tool_use(resp)
        assert intent.action == "model"

    def test_tool_use_batch_via_router(self, router_llm: NLRouter) -> None:
        """Full flow: LLM calls batch_analyze."""
        resp = _make_tool_use_response("batch_analyze", {"top": 10})
        with (
            patch("geode.cli.nl_router.anthropic") as mock_anthropic,
            patch("geode.cli.nl_router.settings") as mock_settings,
        ):
            mock_settings.anthropic_api_key = "sk-ant-test"
            mock_client = MagicMock()
            mock_anthropic.Anthropic.return_value = mock_client
            mock_client.messages.create.return_value = resp

            intent = router_llm.classify("전체 IP 배치 분석해줘")

        assert intent.action == "batch"
        assert intent.args["top"] == 10

    def test_tool_use_status_via_router(self, router_llm: NLRouter) -> None:
        """Full flow: LLM calls check_status."""
        resp = _make_tool_use_response("check_status", {})
        with (
            patch("geode.cli.nl_router.anthropic") as mock_anthropic,
            patch("geode.cli.nl_router.settings") as mock_settings,
        ):
            mock_settings.anthropic_api_key = "sk-ant-test"
            mock_client = MagicMock()
            mock_anthropic.Anthropic.return_value = mock_client
            mock_client.messages.create.return_value = resp

            intent = router_llm.classify("시스템 상태 보여줘")

        assert intent.action == "status"

    @pytest.fixture
    def router_llm(self) -> NLRouter:
        return NLRouter(llm_enabled=True)
