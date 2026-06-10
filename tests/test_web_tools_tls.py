"""PR-AUDIT-AB — fetch_url TLS-downgrade visibility.

The ConnectError → ``verify=False`` retry is a kept fallback (Python 3.14
+ macOS certifi issue), but it must be observable: warn + ``tls_verified``
tag on the result instead of a silent security downgrade.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from unittest.mock import patch

import httpx
import pytest
from core.tools.web_tools import WebFetchTool


class _FakeResponse:
    status_code = 200
    headers: dict[str, str] = {"content-type": "text/plain"}
    text = "hello"

    def raise_for_status(self) -> None:
        return None


def _get(tool: WebFetchTool, **kwargs: Any) -> dict[str, Any]:
    return asyncio.run(tool.aexecute(url="https://example.test/x", **kwargs))


def test_fetch_url_normal_path_reports_tls_verified() -> None:
    with patch.object(httpx, "get", return_value=_FakeResponse()) as mock_get:
        result = _get(WebFetchTool())
    assert result["result"]["tls_verified"] is True
    assert mock_get.call_count == 1


def test_fetch_url_downgrade_is_tagged_and_logged(caplog: pytest.LogCaptureFixture) -> None:
    calls: list[dict[str, Any]] = []

    def _fake_get(url: str, **kwargs: Any) -> _FakeResponse:
        calls.append(kwargs)
        if "verify" not in kwargs:
            raise httpx.ConnectError("boom")
        return _FakeResponse()

    with (
        patch.object(httpx, "get", side_effect=_fake_get),
        caplog.at_level(logging.WARNING, logger="core.tools.web_tools"),
    ):
        result = _get(WebFetchTool())

    assert result["result"]["tls_verified"] is False
    assert calls[1]["verify"] is False
    assert any("TLS verification DISABLED" in r.message for r in caplog.records)
