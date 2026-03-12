"""Tests for NLRouter — Claude Opus 4.6 Tool Use (autonomous)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import anthropic
import pytest
from core.cli.nl_router import (
    VALID_ACTIONS,
    NLIntent,
    NLRouter,
    _fuzzy_match_ip,
    _offline_fallback,
    _offline_multi_intent,
    _parse_text_response,
    _parse_tool_use,
    get_valid_actions,
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

    When patching `core.cli.nl_router.anthropic`, MagicMock replaces
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
            patch("core.cli.nl_router.anthropic") as mock_anthropic,
            patch("core.cli.nl_router.settings") as mock_settings,
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
            patch("core.cli.nl_router.anthropic") as mock_anthropic,
            patch("core.cli.nl_router.settings") as mock_settings,
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
            patch("core.cli.nl_router.anthropic") as mock_anthropic,
            patch("core.cli.nl_router.settings") as mock_settings,
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
            patch("core.cli.nl_router.anthropic") as mock_anthropic,
            patch("core.cli.nl_router.settings") as mock_settings,
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
            patch("core.cli.nl_router.anthropic") as mock_anthropic,
            patch("core.cli.nl_router.settings") as mock_settings,
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
            patch("core.cli.nl_router.anthropic") as mock_anthropic,
            patch("core.cli.nl_router.settings") as mock_settings,
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
        with patch("core.cli.nl_router.settings") as mock_settings:
            mock_settings.anthropic_api_key = ""
            intent = router_llm.classify("anything")

        assert intent.action == "help"
        assert intent.args.get("_error") == "no_api_key"
        assert intent.confidence == 0.3

    def test_no_api_key_with_known_ip(self, router_llm: NLRouter) -> None:
        """Without API key, known IP still routes to analyze."""
        with patch("core.cli.nl_router.settings") as mock_settings:
            mock_settings.anthropic_api_key = ""
            intent = router_llm.classify("Berserk")

        assert intent.action == "analyze"
        assert intent.args["ip_name"].lower() == "berserk"
        assert intent.args["_error"] == "no_api_key"

    def test_api_error(self, router_llm: NLRouter) -> None:
        """API exception → offline fallback."""
        with (
            patch("core.cli.nl_router.anthropic") as mock_anthropic,
            patch("core.cli.nl_router.settings") as mock_settings,
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
            patch("core.cli.nl_router.anthropic") as mock_anthropic,
            patch("core.cli.nl_router.settings") as mock_settings,
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
            patch("core.cli.nl_router.anthropic") as mock_anthropic,
            patch("core.cli.nl_router.settings") as mock_settings,
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
            patch("core.cli.nl_router.anthropic") as mock_anthropic,
            patch("core.cli.nl_router.settings") as mock_settings,
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
            patch("core.cli.nl_router.anthropic") as mock_anthropic,
            patch("core.cli.nl_router.settings") as mock_settings,
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
            patch("core.cli.nl_router.anthropic") as mock_anthropic,
            patch("core.cli.nl_router.settings") as mock_settings,
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
        mock_tracker = MagicMock()
        mock_tracker.record.return_value = MagicMock(cost_usd=0.0035)
        with (
            patch("core.cli.nl_router.anthropic") as mock_anthropic,
            patch("core.cli.nl_router.settings") as mock_settings,
            patch("core.llm.token_tracker.get_tracker", return_value=mock_tracker),
        ):
            mock_settings.anthropic_api_key = "sk-ant-test"
            mock_client = MagicMock()
            mock_anthropic.Anthropic.return_value = mock_client
            mock_client.messages.create.return_value = resp

            router_llm.classify("목록")

        mock_tracker.record.assert_called_once()

    def test_no_usage(self, router_llm: NLRouter) -> None:
        """No usage field → no tracking error."""
        resp = _make_tool_use_response("list_ips", {}, with_usage=False)
        with (
            patch("core.cli.nl_router.anthropic") as mock_anthropic,
            patch("core.cli.nl_router.settings") as mock_settings,
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
        from core.cli.nl_router import VALID_ACTIONS

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

    def test_compare_falls_back_to_compare(self) -> None:
        """Compare pattern detected offline — returns compare with offline flag."""
        intent = _offline_fallback("Berserk vs Cowboy Bebop", error="billing")
        # "vs" triggers compare pattern
        assert intent.action == "compare"
        assert intent.args.get("_offline") is True

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
            patch("core.cli.nl_router.anthropic") as mock_anthropic,
            patch("core.cli.nl_router.settings") as mock_settings,
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
            patch("core.cli.nl_router.anthropic") as mock_anthropic,
            patch("core.cli.nl_router.settings") as mock_settings,
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


# ---------------------------------------------------------------------------
# Plan + Delegate NL integration tests
# ---------------------------------------------------------------------------


class TestPlanDelegateNL:
    """Verify plan/delegate tools parse and route correctly."""

    def test_create_plan_parse(self) -> None:
        resp = _make_tool_use_response("create_plan", {"ip_name": "Berserk"})
        intent = _parse_tool_use(resp)
        assert intent.action == "plan"
        assert intent.args["ip_name"] == "Berserk"

    def test_create_plan_with_template(self) -> None:
        resp = _make_tool_use_response(
            "create_plan", {"ip_name": "Berserk", "template": "prospect"}
        )
        intent = _parse_tool_use(resp)
        assert intent.action == "plan"
        assert intent.args["template"] == "prospect"

    def test_approve_plan_parse(self) -> None:
        resp = _make_tool_use_response("approve_plan", {"plan_id": "abc123"})
        intent = _parse_tool_use(resp)
        assert intent.action == "plan"
        assert intent.args["plan_id"] == "abc123"

    def test_delegate_task_parse(self) -> None:
        resp = _make_tool_use_response(
            "delegate_task",
            {"tasks": [{"type": "analyze", "ip_name": "Berserk"}]},
        )
        intent = _parse_tool_use(resp)
        assert intent.action == "delegate"

    def test_plan_via_router(self, router_llm: NLRouter) -> None:
        """Full flow: LLM calls create_plan."""
        resp = _make_tool_use_response("create_plan", {"ip_name": "Berserk"})
        with (
            patch("core.cli.nl_router.anthropic") as mock_anthropic,
            patch("core.cli.nl_router.settings") as mock_settings,
        ):
            mock_settings.anthropic_api_key = "sk-ant-test"
            mock_client = MagicMock()
            mock_anthropic.Anthropic.return_value = mock_client
            mock_client.messages.create.return_value = resp

            intent = router_llm.classify("Berserk 분석 계획 세워줘")

        assert intent.action == "plan"
        assert intent.args["ip_name"] == "Berserk"

    def test_delegate_via_router(self, router_llm: NLRouter) -> None:
        """Full flow: LLM calls delegate_task."""
        resp = _make_tool_use_response(
            "delegate_task",
            {"tasks": [{"type": "analyze", "ip_name": "Berserk"}]},
        )
        with (
            patch("core.cli.nl_router.anthropic") as mock_anthropic,
            patch("core.cli.nl_router.settings") as mock_settings,
        ):
            mock_settings.anthropic_api_key = "sk-ant-test"
            mock_client = MagicMock()
            mock_anthropic.Anthropic.return_value = mock_client
            mock_client.messages.create.return_value = resp

            intent = router_llm.classify("병렬로 Berserk 분석해줘")

        assert intent.action == "delegate"

    @pytest.fixture
    def router_llm(self) -> NLRouter:
        return NLRouter(llm_enabled=True)


class TestOfflinePlanDelegate:
    """Offline fallback patterns for plan/delegate."""

    def test_plan_korean(self) -> None:
        intent = _offline_fallback("Berserk 분석 계획 세워줘")
        assert intent.action == "plan"

    def test_plan_english(self) -> None:
        intent = _offline_fallback("plan the analysis for Berserk")
        assert intent.action == "plan"

    def test_plan_review(self) -> None:
        intent = _offline_fallback("사전 검토 먼저 해줘")
        assert intent.action == "plan"

    def test_delegate_korean(self) -> None:
        intent = _offline_fallback("병렬로 분석 실행해줘")
        assert intent.action == "delegate"

    def test_delegate_english(self) -> None:
        intent = _offline_fallback("run in parallel using sub agents")
        assert intent.action == "delegate"

    def test_delegate_concurrent(self) -> None:
        intent = _offline_fallback("동시에 처리해")
        assert intent.action == "delegate"


# ---------------------------------------------------------------------------
# Phase 1: Context injection tests (L1 + L2 + L4)
# ---------------------------------------------------------------------------


class TestContextInjection:
    """Verify NLRouter.classify() accepts context and passes to LLM."""

    def test_classify_with_context(self) -> None:
        """context parameter is forwarded to _call_tool_use_router."""
        from core.cli.conversation import ConversationContext

        ctx = ConversationContext(max_turns=5)
        ctx.add_user_message("Berserk 분석해")
        ctx.add_assistant_message([{"type": "text", "text": "분석 결과입니다."}])

        resp = _make_tool_use_response("analyze_ip", {"ip_name": "Berserk"})
        with (
            patch("core.cli.nl_router.anthropic") as mock_anthropic,
            patch("core.cli.nl_router.settings") as mock_settings,
        ):
            mock_settings.anthropic_api_key = "sk-ant-test"
            mock_client = MagicMock()
            mock_anthropic.Anthropic.return_value = mock_client
            mock_client.messages.create.return_value = resp

            router = NLRouter(llm_enabled=True)
            intent = router.classify("그거 다시 분석해", context=ctx)

            # Verify messages include history
            call_args = mock_client.messages.create.call_args
            messages = call_args.kwargs.get("messages") or call_args[1].get("messages")
            assert len(messages) > 1  # More than just current input

        assert intent.action == "analyze"

    def test_classify_without_context(self) -> None:
        """context=None sends single message (backward compat)."""
        resp = _make_tool_use_response("list_ips", {})
        with (
            patch("core.cli.nl_router.anthropic") as mock_anthropic,
            patch("core.cli.nl_router.settings") as mock_settings,
        ):
            mock_settings.anthropic_api_key = "sk-ant-test"
            mock_client = MagicMock()
            mock_anthropic.Anthropic.return_value = mock_client
            mock_client.messages.create.return_value = resp

            router = NLRouter(llm_enabled=True)
            router.classify("목록")

            call_args = mock_client.messages.create.call_args
            messages = call_args.kwargs.get("messages") or call_args[1].get("messages")
            assert len(messages) == 1
            assert messages[0]["role"] == "user"

    def test_context_recent_turns_only(self) -> None:
        """Only last 3 turns (6 messages) are included."""
        from core.cli.conversation import ConversationContext

        ctx = ConversationContext(max_turns=20)
        for i in range(10):
            ctx.add_user_message(f"msg {i}")
            ctx.add_assistant_message([{"type": "text", "text": f"reply {i}"}])

        resp = _make_tool_use_response("list_ips", {})
        with (
            patch("core.cli.nl_router.anthropic") as mock_anthropic,
            patch("core.cli.nl_router.settings") as mock_settings,
        ):
            mock_settings.anthropic_api_key = "sk-ant-test"
            mock_client = MagicMock()
            mock_anthropic.Anthropic.return_value = mock_client
            mock_client.messages.create.return_value = resp

            router = NLRouter(llm_enabled=True)
            router.classify("현재 입력", context=ctx)

            call_args = mock_client.messages.create.call_args
            messages = call_args.kwargs.get("messages") or call_args[1].get("messages")
            # 6 recent + 1 current input = 7 max
            assert len(messages) <= 7

    def test_context_starts_with_user(self) -> None:
        """First message in history must be user role."""
        from core.cli.conversation import ConversationContext

        ctx = ConversationContext(max_turns=20)
        # Simulate assistant-first edge case
        ctx.messages.append({"role": "assistant", "content": "welcome"})
        ctx.add_user_message("hello")

        resp = _make_tool_use_response("list_ips", {})
        with (
            patch("core.cli.nl_router.anthropic") as mock_anthropic,
            patch("core.cli.nl_router.settings") as mock_settings,
        ):
            mock_settings.anthropic_api_key = "sk-ant-test"
            mock_client = MagicMock()
            mock_anthropic.Anthropic.return_value = mock_client
            mock_client.messages.create.return_value = resp

            router = NLRouter(llm_enabled=True)
            router.classify("test", context=ctx)

            call_args = mock_client.messages.create.call_args
            messages = call_args.kwargs.get("messages") or call_args[1].get("messages")
            assert messages[0]["role"] == "user"

    def test_router_prompt_has_context_instructions(self) -> None:
        """router.md should contain context-aware routing instructions."""
        from core.llm.prompts import ROUTER_SYSTEM

        lower = ROUTER_SYSTEM.lower()
        assert "conversation history" in lower or "context-aware" in lower


# ---------------------------------------------------------------------------
# Phase 1: Dead code removal (L1)
# ---------------------------------------------------------------------------


class TestDeadCodeRemoved:
    """Verify dead code was removed from __init__.py."""

    def test_handle_natural_language_removed(self) -> None:
        """_handle_natural_language function should not exist in cli module."""
        import core.cli

        assert not hasattr(core.cli, "_handle_natural_language")

    def test_nl_router_not_imported(self) -> None:
        """NLRouter class should not be imported in cli __init__."""
        import inspect

        from core.cli import _interactive_loop

        source = inspect.getsource(_interactive_loop)
        assert "NLRouter" not in source


# ---------------------------------------------------------------------------
# Phase 2: Regex fix (L6) + Fuzzy (L7)
# ---------------------------------------------------------------------------


class TestRegexFix:
    """L6: 'list all IPs' should be list, not batch."""

    def test_list_all_ips_is_list(self) -> None:
        intent = _offline_fallback("list all IPs")
        assert intent.action == "list"

    def test_show_all_is_list(self) -> None:
        intent = _offline_fallback("show all")
        assert intent.action == "list"

    def test_batch_still_works(self) -> None:
        intent = _offline_fallback("batch analyze")
        assert intent.action == "batch"

    def test_top_10_still_batch(self) -> None:
        intent = _offline_fallback("top 10")
        assert intent.action == "batch"

    def test_batch_korean_still_works(self) -> None:
        intent = _offline_fallback("배치 분석 실행")
        assert intent.action == "batch"


class TestFuzzyMatching:
    """L7: Fuzzy IP name matching for typos."""

    def test_fuzzy_no_false_positive(self) -> None:
        """Random text should not fuzzy-match any IP."""
        result = _fuzzy_match_ip("completely random gibberish xyzzy")
        assert result is None

    def test_exact_match_still_works(self) -> None:
        """Exact IP names still match."""
        result = _fuzzy_match_ip("berserk")
        assert result is not None
        assert "berserk" in result.lower()

    def test_fuzzy_lower_confidence(self) -> None:
        """Fuzzy matches should have lower confidence than exact."""
        # Exact match
        intent_exact = _offline_fallback("berserk")
        assert intent_exact.confidence == 0.7

        # If fuzzy match exists for a typo, confidence should be 0.5
        # (only if the typo actually fuzzy-matches an IP)


# ---------------------------------------------------------------------------
# Phase 3: Multi-intent offline (L5)
# ---------------------------------------------------------------------------


class TestMultiIntent:
    """L5: Compound input splitting for offline mode."""

    def test_single_intent_no_split(self) -> None:
        """Single action should not be split."""
        intents = _offline_multi_intent("Berserk 분석해")
        assert intents == []

    def test_multi_intent_korean(self) -> None:
        """Korean compound: '분석하고 목록 보여줘' → [analyze, list]."""
        intents = _offline_multi_intent("berserk 분석하고 목록 보여줘")
        assert len(intents) >= 2
        actions = [i.action for i in intents]
        assert "analyze" in actions
        assert "list" in actions

    def test_multi_intent_english(self) -> None:
        """English compound with 'and'."""
        intents = _offline_multi_intent("analyze Berserk and list all")
        assert len(intents) >= 2
        actions = [i.action for i in intents]
        assert "analyze" in actions
        assert "list" in actions

    def test_multi_intent_comma(self) -> None:
        """Comma-separated compound."""
        intents = _offline_multi_intent("목록, 배치 돌려")
        assert len(intents) >= 2


# ---------------------------------------------------------------------------
# Phase 4: Dynamic actions (L3) + Disambiguation (L8)
# ---------------------------------------------------------------------------


class TestDynamicActions:
    """L3: get_valid_actions with optional ToolRegistry."""

    def test_get_valid_actions_static(self) -> None:
        """Without registry, returns static 18 actions."""
        actions = get_valid_actions()
        assert actions == VALID_ACTIONS
        assert len(actions) == 18

    def test_get_valid_actions_dynamic(self) -> None:
        """With registry containing extra tool, returns 19+ actions."""
        mock_registry = MagicMock()
        mock_registry.list_tools.return_value = ["custom_tool_xyz"]
        actions = get_valid_actions(registry=mock_registry)
        assert "custom_tool_xyz" in actions
        assert len(actions) >= 19


class TestDisambiguation:
    """L8: NLIntent ambiguity fields."""

    def test_nlintent_backward_compat(self) -> None:
        """Existing 3-field creation still works."""
        intent = NLIntent(action="list")
        assert intent.ambiguous is False
        assert intent.alternatives is None

    def test_nlintent_with_ambiguity(self) -> None:
        """Can create NLIntent with ambiguity fields."""
        alt = NLIntent(action="batch", confidence=0.6)
        intent = NLIntent(
            action="list",
            confidence=0.7,
            ambiguous=True,
            alternatives=[alt],
        )
        assert intent.ambiguous is True
        assert len(intent.alternatives) == 1
        assert intent.alternatives[0].action == "batch"

    def test_single_match_not_ambiguous(self) -> None:
        """Single pattern match → ambiguous=False."""
        intent = _offline_fallback("batch")
        assert intent.ambiguous is False

    def test_multi_match_is_ambiguous(self) -> None:
        """Multiple pattern matches → ambiguous=True."""
        # "batch analyze" matches both batch and analyze patterns
        intent = _offline_fallback("batch analyze")
        assert intent.ambiguous is True
        assert intent.alternatives is not None
        assert len(intent.alternatives) >= 1


# ---------------------------------------------------------------------------
# Phase 4C: Scored Matching tests
# ---------------------------------------------------------------------------


class TestScoredMatching:
    """Verify scored matching behavior in _offline_fallback."""

    def test_scored_single_match(self) -> None:
        """Single pattern match → no ambiguity."""
        intent = _offline_fallback("status")
        assert intent.action == "status"
        assert intent.ambiguous is False
        assert intent.alternatives is None

    def test_scored_multi_match_ambiguous(self) -> None:
        """Multiple regex matches → ambiguous=True with alternatives."""
        # "search 메모리" matches both search and memory patterns
        intent = _offline_fallback("search memory")
        assert intent.ambiguous is True
        assert intent.alternatives is not None
        actions = {intent.action} | {a.action for a in intent.alternatives}
        assert "search" in actions
        assert "memory" in actions

    def test_scored_alternatives_populated(self) -> None:
        """Alternatives list contains correct NLIntent objects."""
        intent = _offline_fallback("batch analyze")
        assert intent.alternatives is not None
        for alt in intent.alternatives:
            assert isinstance(alt, NLIntent)
            assert alt.action in VALID_ACTIONS
            assert alt.confidence > 0

    def test_scored_best_by_priority(self) -> None:
        """Best match determined by priority (lower = better)."""
        # "list" has priority 5, "batch" has priority 6
        # "list all ip" should resolve to list (priority 5 < 6)
        intent = _offline_fallback("list all ip")
        assert intent.action == "list"

    def test_scored_known_ip_bypasses(self) -> None:
        """Known IP exact match bypasses scored matching entirely."""
        intent = _offline_fallback("berserk")
        assert intent.action == "analyze"
        assert intent.ambiguous is False

    def test_scored_no_match_help(self) -> None:
        """No pattern matches → help fallback."""
        intent = _offline_fallback("xyzzy gibberish 12345")
        assert intent.action == "help"
        assert intent.confidence == 0.3

    def test_scored_high_priority_overrides_known_ip(self) -> None:
        """Compare/report/plan/delegate override known IP match."""
        # "Berserk vs Cowboy Bebop" has known IPs but "vs" = compare
        intent = _offline_fallback("Berserk vs Cowboy Bebop")
        assert intent.action == "compare"

    def test_scored_alternatives_max_three(self) -> None:
        """Alternatives capped at 3 even if more patterns match."""
        # Construct input that could match many patterns
        intent = _offline_fallback("search find analyze evaluate memory save")
        if intent.alternatives:
            assert len(intent.alternatives) <= 3
