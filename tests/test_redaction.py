"""Tests for secret redaction — API key pattern matching and replacement."""

from __future__ import annotations

from core.cli.redaction import redact_secrets


class TestRedactSecrets:
    """Test redact_secrets() with various API key formats."""

    def test_anthropic_key(self) -> None:
        text = "key=sk-ant-api03-abcdef1234567890abcdef1234567890"
        result = redact_secrets(text)
        assert "sk-ant-" not in result
        assert "[REDACTED]" in result

    def test_openai_project_key(self) -> None:
        text = "OPENAI_API_KEY=sk-proj-abc123def456ghi789jkl012mno345"
        result = redact_secrets(text)
        assert "sk-proj-" not in result
        assert "[REDACTED]" in result

    def test_openai_generic_key(self) -> None:
        text = "export OPENAI_API_KEY=sk-abcdefghijklmnopqrstuvwxyz1234"
        result = redact_secrets(text)
        assert "sk-abcdefghij" not in result
        assert "[REDACTED]" in result

    def test_zhipuai_key(self) -> None:
        text = "GLM_KEY=a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4.abcdefghijklmnop"
        result = redact_secrets(text)
        assert "a1b2c3d4e5f6" not in result
        assert "[REDACTED]" in result

    def test_github_pat(self) -> None:
        text = "GITHUB_TOKEN=ghp_abcdefghijklmnopqrstuvwxyz1234567890"
        result = redact_secrets(text)
        assert "ghp_" not in result
        assert "[REDACTED]" in result

    def test_slack_bot_token(self) -> None:
        text = "SLACK_TOKEN=xoxb-123456-abcdef-ghijkl"
        result = redact_secrets(text)
        assert "xoxb-" not in result
        assert "[REDACTED]" in result

    def test_plain_text_unchanged(self) -> None:
        text = "Hello world, this is normal text without any secrets."
        assert redact_secrets(text) == text

    def test_multiple_keys_in_same_text(self) -> None:
        text = (
            "ANTHROPIC=sk-ant-api03-aaaabbbbccccddddeeeeffffgggg "
            "OPENAI=sk-proj-aaaabbbbccccddddeeeeffffgggg "
            "normal text"
        )
        result = redact_secrets(text)
        assert result.count("[REDACTED]") == 2
        assert "normal text" in result

    def test_custom_placeholder(self) -> None:
        text = "key=sk-ant-api03-abcdef1234567890abcdef1234567890"
        result = redact_secrets(text, placeholder="***")
        assert "***" in result
        assert "sk-ant-" not in result

    def test_empty_string(self) -> None:
        assert redact_secrets("") == ""

    def test_short_sk_prefix_not_matched(self) -> None:
        """sk- followed by fewer than 20 chars should not be redacted."""
        text = "sk-short"
        assert redact_secrets(text) == text


class TestRedactionIntegration:
    """Test redaction wired into BashTool.to_tool_result."""

    def test_bash_tool_result_redacts_stdout(self) -> None:
        from core.cli.bash_tool import BashResult, BashTool

        bash = BashTool()
        result = BashResult(
            stdout="ANTHROPIC_API_KEY=sk-ant-api03-aaaabbbbccccddddeeeeffffgggg",
            returncode=0,
            command="env",
        )
        tool_result = bash.to_tool_result(result)
        assert "sk-ant-" not in tool_result["stdout"]
        assert "[REDACTED]" in tool_result["stdout"]

    def test_bash_tool_result_redacts_stderr(self) -> None:
        from core.cli.bash_tool import BashResult, BashTool

        bash = BashTool()
        result = BashResult(
            stderr="error: key=sk-proj-aaaabbbbccccddddeeeeffffgggg invalid",
            returncode=1,
            command="test",
        )
        tool_result = bash.to_tool_result(result)
        assert "sk-proj-" not in tool_result["stderr"]
        assert "[REDACTED]" in tool_result["stderr"]

    def test_bash_tool_result_no_secrets_unchanged(self) -> None:
        from core.cli.bash_tool import BashResult, BashTool

        bash = BashTool()
        result = BashResult(
            stdout="hello world",
            returncode=0,
            command="echo hello world",
        )
        tool_result = bash.to_tool_result(result)
        assert tool_result["stdout"] == "hello world"
