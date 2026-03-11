"""Tests for OpenAI Adapter (P1-4)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from core.config import OPENAI_PRIMARY
from core.infrastructure.adapters.llm.openai_adapter import OpenAIAdapter
from core.infrastructure.ports.llm_port import LLMClientPort


class TestOpenAIAdapterInterface:
    def test_implements_port(self):
        adapter = OpenAIAdapter()
        assert isinstance(adapter, LLMClientPort)

    def test_default_model(self):
        adapter = OpenAIAdapter()
        assert adapter._default_model == OPENAI_PRIMARY

    def test_custom_model(self):
        adapter = OpenAIAdapter(default_model="gpt-4o")
        assert adapter._default_model == "gpt-4o"

    @patch("core.infrastructure.adapters.llm.openai_adapter._get_openai_client")
    def test_generate(self, mock_client_fn):
        mock_client = MagicMock()
        mock_client_fn.return_value = mock_client

        mock_response = MagicMock()
        mock_response.usage.prompt_tokens = 10
        mock_response.usage.completion_tokens = 20
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Hello from GPT"
        mock_client.chat.completions.create.return_value = mock_response

        adapter = OpenAIAdapter()
        result = adapter.generate("system prompt", "user prompt")
        assert result == "Hello from GPT"

    @patch("core.infrastructure.adapters.llm.openai_adapter._get_openai_client")
    def test_generate_structured(self, mock_client_fn):
        mock_client = MagicMock()
        mock_client_fn.return_value = mock_client

        mock_response = MagicMock()
        mock_response.usage.prompt_tokens = 10
        mock_response.usage.completion_tokens = 20
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '{"key": "value"}'
        mock_client.chat.completions.create.return_value = mock_response

        adapter = OpenAIAdapter()
        result = adapter.generate_structured("system", "user")
        assert result == {"key": "value"}

    @patch("core.infrastructure.adapters.llm.openai_adapter._get_openai_client")
    def test_generate_stream(self, mock_client_fn):
        mock_client = MagicMock()
        mock_client_fn.return_value = mock_client

        # Simulate streaming chunks
        chunk1 = MagicMock()
        chunk1.choices = [MagicMock()]
        chunk1.choices[0].delta.content = "Hello"
        chunk2 = MagicMock()
        chunk2.choices = [MagicMock()]
        chunk2.choices[0].delta.content = " World"
        mock_client.chat.completions.create.return_value = iter([chunk1, chunk2])

        adapter = OpenAIAdapter()
        result = list(adapter.generate_stream("system", "user"))
        assert result == ["Hello", " World"]
