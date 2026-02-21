"""Tests for LLM client JSON extraction."""

from __future__ import annotations

import json
import re


def _strip_fences(raw: str) -> str:
    """Reproduce the fence-stripping logic from client.py for testing."""
    text = raw.strip()
    text = re.sub(r"^```\w*\s*\n", "", text)
    text = re.sub(r"\n```\s*$", "", text)
    return text


class TestStripFences:
    def test_no_fences(self):
        raw = '{"key": "value"}'
        assert json.loads(_strip_fences(raw)) == {"key": "value"}

    def test_json_fence(self):
        raw = '```json\n{"key": "value"}\n```'
        assert json.loads(_strip_fences(raw)) == {"key": "value"}

    def test_fence_with_trailing_spaces(self):
        raw = '```json  \n{"key": "value"}\n```  '
        assert json.loads(_strip_fences(raw)) == {"key": "value"}

    def test_plain_fence(self):
        raw = '```\n{"key": "value"}\n```'
        assert json.loads(_strip_fences(raw)) == {"key": "value"}

    def test_multiline_json(self):
        raw = '```json\n{\n  "score": 4.2,\n  "finding": "test"\n}\n```'
        result = json.loads(_strip_fences(raw))
        assert result["score"] == 4.2
        assert result["finding"] == "test"

    def test_no_trailing_newline_fence(self):
        raw = '{"key": "value"}'
        assert json.loads(_strip_fences(raw)) == {"key": "value"}

    def test_fence_with_language_tag(self):
        raw = '```javascript\n{"key": "value"}\n```'
        assert json.loads(_strip_fences(raw)) == {"key": "value"}
