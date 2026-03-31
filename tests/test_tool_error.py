"""Tests for tool_error() helper and classify_tool_exception()."""

from __future__ import annotations

import pytest
from core.tools.base import classify_tool_exception, tool_error


class TestToolError:
    """Test the standardized tool_error() helper."""

    def test_minimal_error(self):
        result = tool_error("Something went wrong")
        assert result["error"] == "Something went wrong"
        assert result["error_type"] == "internal"
        assert result["recoverable"] is True
        assert "hint" not in result
        assert "context" not in result

    def test_with_all_fields(self):
        result = tool_error(
            "File not found: foo.txt",
            error_type="not_found",
            recoverable=False,
            hint="Check the path.",
            context={"file_path": "foo.txt"},
        )
        assert result["error"] == "File not found: foo.txt"
        assert result["error_type"] == "not_found"
        assert result["recoverable"] is False
        assert result["hint"] == "Check the path."
        assert result["context"]["file_path"] == "foo.txt"

    def test_validation_error(self):
        result = tool_error(
            "Unknown analyst_type: foo",
            error_type="validation",
            hint="Valid types: a, b, c",
        )
        assert result["error_type"] == "validation"
        assert result["hint"] == "Valid types: a, b, c"

    def test_connection_error(self):
        result = tool_error(
            "Server unavailable",
            error_type="connection",
            recoverable=True,
        )
        assert result["error_type"] == "connection"
        assert result["recoverable"] is True

    @pytest.mark.parametrize(
        "error_type",
        ["validation", "not_found", "permission", "connection", "timeout", "dependency", "internal"],
    )
    def test_all_error_types_accepted(self, error_type: str):
        result = tool_error("test", error_type=error_type)
        assert result["error_type"] == error_type

    def test_backward_compat_error_key(self):
        """The 'error' key must always be a string for backward compatibility."""
        result = tool_error("msg")
        assert isinstance(result["error"], str)


class TestClassifyToolException:
    """Test classify_tool_exception() for automatic exception classification."""

    def test_connection_error(self):
        result = classify_tool_exception(ConnectionError("refused"))
        assert result["error_type"] == "connection"

    def test_os_error(self):
        result = classify_tool_exception(OSError("disk full"))
        assert result["error_type"] == "connection"

    def test_timeout_error(self):
        result = classify_tool_exception(TimeoutError("timed out"))
        assert result["error_type"] == "timeout"

    def test_value_error(self):
        result = classify_tool_exception(ValueError("bad input"))
        assert result["error_type"] == "validation"

    def test_type_error(self):
        result = classify_tool_exception(TypeError("wrong type"))
        assert result["error_type"] == "validation"

    def test_key_error(self):
        result = classify_tool_exception(KeyError("missing"))
        assert result["error_type"] == "validation"

    def test_permission_error(self):
        result = classify_tool_exception(PermissionError("denied"))
        assert result["error_type"] == "permission"
        assert result["recoverable"] is False

    def test_file_not_found_error(self):
        result = classify_tool_exception(FileNotFoundError("no such file"))
        assert result["error_type"] == "not_found"

    def test_import_error(self):
        result = classify_tool_exception(ImportError("no module"))
        assert result["error_type"] == "dependency"
        assert result["recoverable"] is False

    def test_generic_exception(self):
        result = classify_tool_exception(RuntimeError("unexpected"))
        assert result["error_type"] == "internal"

    def test_tool_name_in_hint(self):
        result = classify_tool_exception(RuntimeError("boom"), tool_name="web_fetch")
        assert "web_fetch" in result.get("hint", "")

    def test_backward_compat(self):
        """All classified errors must have 'error' key as string."""
        result = classify_tool_exception(ValueError("bad"))
        assert isinstance(result["error"], str)
        assert "error_type" in result
