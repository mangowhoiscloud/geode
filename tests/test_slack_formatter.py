"""Tests for core.gateway.slack_formatter — Markdown → Slack mrkdwn conversion."""

from __future__ import annotations

from core.gateway.slack_formatter import markdown_to_slack_mrkdwn

_ZWS = "\u200b"


class TestBoldConversion:
    def test_double_asterisk_to_single(self) -> None:
        assert markdown_to_slack_mrkdwn("**bold**") == "*bold*"

    def test_multiple_bold_segments(self) -> None:
        result = markdown_to_slack_mrkdwn("**a** and **b**")
        assert result == "*a* and *b*"

    def test_bold_inside_sentence(self) -> None:
        result = markdown_to_slack_mrkdwn("This is **important** text")
        assert result == "This is *important* text"


class TestSlackBoundaryFix:
    """Slack requires whitespace/punctuation around *bold* markers."""

    def test_bold_followed_by_korean(self) -> None:
        result = markdown_to_slack_mrkdwn("**LangGraph**가 좋다")
        assert f"*LangGraph*{_ZWS}가 좋다" == result

    def test_bold_followed_by_space(self) -> None:
        result = markdown_to_slack_mrkdwn("**bold** text")
        assert result == "*bold* text"
        assert _ZWS not in result

    def test_bold_followed_by_comma(self) -> None:
        result = markdown_to_slack_mrkdwn("**bold**, text")
        assert result == "*bold*, text"
        assert _ZWS not in result

    def test_bold_followed_by_period(self) -> None:
        assert markdown_to_slack_mrkdwn("**bold**.") == "*bold*."

    def test_bold_at_end_of_line(self) -> None:
        assert markdown_to_slack_mrkdwn("This is **bold**") == "This is *bold*"

    def test_korean_before_bold(self) -> None:
        result = markdown_to_slack_mrkdwn("프레임워크**LangGraph**가")
        assert f"프레임워크{_ZWS}*LangGraph*{_ZWS}가" == result

    def test_multiple_bold_with_korean(self) -> None:
        result = markdown_to_slack_mrkdwn("**LangGraph**가 성숙하고, **CrewAI**가 적합")
        assert f"*LangGraph*{_ZWS}가" in result
        assert f"*CrewAI*{_ZWS}가" in result


class TestHeadingConversion:
    def test_h1(self) -> None:
        assert markdown_to_slack_mrkdwn("# Title") == "*Title*"

    def test_h2(self) -> None:
        assert markdown_to_slack_mrkdwn("## Subtitle") == "*Subtitle*"

    def test_h3(self) -> None:
        assert markdown_to_slack_mrkdwn("### Section") == "*Section*"

    def test_multiline_headings(self) -> None:
        text = "# First\nsome text\n## Second"
        result = markdown_to_slack_mrkdwn(text)
        assert result == "*First*\nsome text\n*Second*"

    def test_heading_with_bold(self) -> None:
        result = markdown_to_slack_mrkdwn("# **Important** Update")
        assert "Important" in result
        assert "Update" in result
        assert "***" not in result


class TestLinkConversion:
    def test_basic_link(self) -> None:
        assert markdown_to_slack_mrkdwn("[Google](https://google.com)") == "<https://google.com|Google>"

    def test_link_in_sentence(self) -> None:
        result = markdown_to_slack_mrkdwn("Visit [docs](https://docs.example.com) for info")
        assert result == "Visit <https://docs.example.com|docs> for info"


class TestTableToSections:
    def test_two_column_to_bullets(self) -> None:
        text = "| Name | Score |\n| --- | --- |\n| Alice | 90 |"
        result = markdown_to_slack_mrkdwn(text)
        assert "• *Alice*: 90" in result
        assert "```" not in result

    def test_comparison_to_vertical(self) -> None:
        text = "| 항목 | LangGraph | CrewAI |\n| --- | --- | --- |\n| 개발사 | LangChain | CrewAI Inc. |"
        result = markdown_to_slack_mrkdwn(text)
        assert "*LangGraph*" in result
        assert "*CrewAI*" in result
        assert "개발사: LangChain" in result
        assert "|" not in result

    def test_bold_stripped_in_cells(self) -> None:
        text = "| 항목 | **LG** | **CR** |\n| --- | --- | --- |\n| **특징** | a | b |"
        result = markdown_to_slack_mrkdwn(text)
        assert "**" not in result

    def test_dash_values_omitted(self) -> None:
        text = "| 항목 | A | B |\n| --- | --- | --- |\n| 점수 | 90 | - |"
        result = markdown_to_slack_mrkdwn(text)
        assert "점수: 90" in result

    def test_table_surrounded_by_text(self) -> None:
        text = "Before\n| A | B |\n| - | - |\n| 1 | 2 |\nAfter"
        result = markdown_to_slack_mrkdwn(text)
        assert result.startswith("Before")
        assert result.rstrip().endswith("After")


class TestHorizontalRule:
    def test_triple_dash(self) -> None:
        result = markdown_to_slack_mrkdwn("Before\n---\nAfter")
        assert "---" not in result
        assert "Before" in result and "After" in result


class TestStrikethrough:
    def test_basic(self) -> None:
        assert markdown_to_slack_mrkdwn("~~removed~~") == "~removed~"


class TestMixedContent:
    def test_heading_bold_link(self) -> None:
        text = "# Report\n**Status**: [link](https://x.com)"
        result = markdown_to_slack_mrkdwn(text)
        assert "*Report*" in result
        assert "*Status*" in result
        assert "<https://x.com|link>" in result

    def test_realistic_response(self) -> None:
        text = "## 비교\n\n| 항목 | A | B |\n| --- | --- | --- |\n| 점수 | 90 | 80 |\n\n**A**가 높다."
        result = markdown_to_slack_mrkdwn(text)
        assert "**" not in result
        assert "##" not in result
        assert "|" not in result
        assert f"*A*{_ZWS}가" in result


class TestNoOp:
    def test_plain_text(self) -> None:
        assert markdown_to_slack_mrkdwn("Hello!") == "Hello!"

    def test_empty_string(self) -> None:
        assert markdown_to_slack_mrkdwn("") == ""


class TestCodeBlockPreserved:
    def test_inline_code(self) -> None:
        assert markdown_to_slack_mrkdwn("Use `pip install geode`") == "Use `pip install geode`"

    def test_fenced_code(self) -> None:
        assert "print('hello')" in markdown_to_slack_mrkdwn("```python\nprint('hello')\n```")

    def test_bold_inside_code_preserved(self) -> None:
        assert "**not bold**" in markdown_to_slack_mrkdwn("```\n**not bold**\n```")

    def test_heading_inside_code_preserved(self) -> None:
        assert "# not heading" in markdown_to_slack_mrkdwn("```\n# not heading\n```")

    def test_inline_kwargs_preserved(self) -> None:
        assert "`**kwargs`" in markdown_to_slack_mrkdwn("Use `**kwargs` in function")
