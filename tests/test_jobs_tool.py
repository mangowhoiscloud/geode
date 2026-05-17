"""Tests for ``core.tools.jobs.WantedJobsSearchTool`` — Wanted.co.kr API client.

Mock-based — no live HTTP calls. Live testing is the user's responsibility
since it costs nothing and the API may evolve.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import patch

import httpx
import pytest
from core.tools.jobs import WantedJobsSearchTool


def _mock_response(
    status_code: int = 200,
    json_data: Any | None = None,
    raise_json: bool = False,
) -> httpx.Response:
    """Build an ``httpx.Response`` suitable for mock returns."""
    request = httpx.Request("GET", "https://www.wanted.co.kr/api/v4/jobs")
    if raise_json:
        # Body that triggers JSONDecodeError on .json()
        return httpx.Response(status_code, content=b"<html>maintenance</html>", request=request)
    return httpx.Response(status_code, json=(json_data or {}), request=request)


class TestSchema:
    def test_name(self) -> None:
        assert WantedJobsSearchTool().name == "wanted_jobs_search"

    def test_required_query(self) -> None:
        params = WantedJobsSearchTool().parameters
        assert "query" in params["required"]
        assert params["additionalProperties"] is False

    def test_description_mentions_linkedin_alternative(self) -> None:
        """The agent should know to switch here when LinkedIn fails."""
        desc = WantedJobsSearchTool().description.lower()
        assert "wanted" in desc
        assert "linkedin" in desc


class TestExecute:
    def test_empty_query_rejected(self) -> None:
        result = asyncio.run(WantedJobsSearchTool().aexecute(query="   "))
        assert "error" in result
        assert result["error_type"] == "validation"

    def test_happy_path_shape(self) -> None:
        """Wanted-style payload flattens to {job_id, position, company, location, url, …}."""
        wanted_payload = {
            "data": [
                {
                    "id": 12345,
                    "position": "AI Engineer",
                    "company": {"name": "Krafton"},
                    "address": {"full_location": "Seoul, South Korea"},
                    "created_at": "2026-05-10T09:00:00Z",
                },
                {
                    "id": 67890,
                    "position": "LLM Platform Engineer",
                    "company": {"name": "Naver"},
                    "address": {"full_location": "Seongnam, South Korea"},
                    "created_at": "2026-05-08T11:30:00Z",
                },
            ]
        }
        with patch.object(
            httpx.Client, "get", return_value=_mock_response(json_data=wanted_payload)
        ):
            result = asyncio.run(WantedJobsSearchTool().aexecute(query="AI Engineer"))

        assert "result" in result
        inner = result["result"]
        assert inner["query"] == "AI Engineer"
        assert inner["source"] == "wanted.co.kr"
        assert inner["total_returned"] == 2
        assert inner["jobs"][0]["job_id"] == 12345
        assert inner["jobs"][0]["company"] == "Krafton"
        assert inner["jobs"][0]["location"] == "Seoul, South Korea"
        assert inner["jobs"][0]["url"] == "https://www.wanted.co.kr/wd/12345"
        assert inner["jobs"][1]["position"] == "LLM Platform Engineer"

    def test_aexecute_happy_path_shape(self) -> None:
        payload = {
            "data": [
                {
                    "id": 12345,
                    "position": "AI Engineer",
                    "company": {"name": "Krafton"},
                    "address": {"full_location": "Seoul, South Korea"},
                }
            ]
        }
        with patch.object(httpx.Client, "get", return_value=_mock_response(json_data=payload)):
            result = asyncio.run(WantedJobsSearchTool().aexecute(query="AI Engineer"))

        assert result["result"]["total_returned"] == 1
        assert result["result"]["jobs"][0]["job_id"] == 12345

    def test_missing_company_or_address_tolerated(self) -> None:
        """Partial Wanted response shouldn't hard-fail — emit best-effort entries."""
        payload = {
            "data": [
                {"id": 1, "position": "Junior ML", "company": None, "address": None},
                {"id": 2, "position": "MLOps"},  # no company / address at all
            ]
        }
        with patch.object(httpx.Client, "get", return_value=_mock_response(json_data=payload)):
            result = asyncio.run(WantedJobsSearchTool().aexecute(query="ML"))

        jobs = result["result"]["jobs"]
        assert len(jobs) == 2
        assert jobs[0]["company"] == ""
        assert jobs[0]["location"] == ""
        assert jobs[1]["position"] == "MLOps"

    def test_alt_jobs_field(self) -> None:
        """Wanted has sometimes nested under ``jobs`` instead of ``data``."""
        payload = {"jobs": [{"id": 99, "position": "X", "company": "Co"}]}
        with patch.object(httpx.Client, "get", return_value=_mock_response(json_data=payload)):
            result = asyncio.run(WantedJobsSearchTool().aexecute(query="X"))
        assert result["result"]["total_returned"] == 1

    def test_non_200_returns_tool_error(self) -> None:
        with patch.object(httpx.Client, "get", return_value=_mock_response(status_code=429)):
            result = asyncio.run(WantedJobsSearchTool().aexecute(query="X"))
        assert "error" in result
        assert "429" in result["error"]
        assert result["error_type"] == "dependency"

    def test_timeout_returns_tool_error(self) -> None:
        with patch.object(
            httpx.Client,
            "get",
            side_effect=httpx.TimeoutException("read timeout"),
        ):
            result = asyncio.run(WantedJobsSearchTool().aexecute(query="X"))
        assert result["error_type"] == "timeout"

    def test_non_json_body_returns_tool_error(self) -> None:
        with patch.object(httpx.Client, "get", return_value=_mock_response(raise_json=True)):
            result = asyncio.run(WantedJobsSearchTool().aexecute(query="X"))
        assert "error" in result
        assert result["error_type"] == "dependency"

    def test_limit_capped(self) -> None:
        """User-supplied limit above MAX_LIMIT (50) is clamped silently."""
        captured: dict[str, Any] = {}

        def _capture(self: Any, url: str, params: dict[str, Any] | None = None, **_: Any) -> Any:
            captured["params"] = params or {}
            return _mock_response(json_data={"data": []})

        with patch.object(httpx.Client, "get", _capture):
            asyncio.run(WantedJobsSearchTool().aexecute(query="X", limit=500))

        assert int(captured["params"]["limit"]) == 50

    def test_default_query_params_have_kr_country(self) -> None:
        captured: dict[str, Any] = {}

        def _capture(self: Any, url: str, params: dict[str, Any] | None = None, **_: Any) -> Any:
            captured["params"] = params or {}
            return _mock_response(json_data={"data": []})

        with patch.object(httpx.Client, "get", _capture):
            asyncio.run(WantedJobsSearchTool().aexecute(query="AI Engineer", years=3))

        assert captured["params"]["country"] == "kr"
        assert captured["params"]["years"] == "3"
        assert captured["params"]["query"] == "AI Engineer"


class TestSafetyClassification:
    """Read-only HTTP call — must be in SAFE_TOOLS for sub-agent auto-approval."""

    def test_listed_in_safe_tools(self) -> None:
        from core.agent.safety import SAFE_TOOLS

        assert "wanted_jobs_search" in SAFE_TOOLS


@pytest.fixture(autouse=True)
def _no_real_http(monkeypatch: pytest.MonkeyPatch) -> None:
    """Belt-and-braces — guarantee no test ever opens a real socket."""

    def _refuse(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("Real HTTP attempt in test (should be mocked)")

    monkeypatch.setattr("httpx.Client.send", _refuse)
