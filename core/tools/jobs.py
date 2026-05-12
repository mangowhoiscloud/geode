"""Korean job board search tool — alternative to LinkedIn when bot detection blocks.

Hits Wanted.co.kr's public job-search REST endpoint. Returns structured job
listings without OAuth, scraping, or third-party proxies. Used by the agent
when ``search_jobs`` (linkedin-scraper-mcp) hits the 403 / empty-body
PerimeterX challenge that LinkedIn deploys on bot-shaped sessions.

Why an internal tool rather than an MCP server:

* Wanted's endpoint is a single GET with JSON response — running a separate
  subprocess for that is pure overhead.
* GEODE already has ``httpx`` as a runtime dep.
* The MCP layer adds ``mcp__<server>__<tool>`` naming + per-call permission
  overhead the user does not want for a low-risk read-only HTTP call.

Frontier reference: Manus / Devin lean on paid scraping providers (Apify,
Bright Data) for LinkedIn parity; we follow the lighter path of switching
source when one source becomes hostile.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

_WANTED_JOBS_URL = "https://www.wanted.co.kr/api/v4/jobs"
_WANTED_JOB_DETAIL_URL = "https://www.wanted.co.kr/wd/{job_id}"
_DEFAULT_TIMEOUT_S = 10.0
_MAX_LIMIT = 50

# Browser-like UA — Wanted's API ignores it for unauthenticated read but
# sending one keeps the request indistinguishable from a vanilla web client.
_DEFAULT_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/17.0 Safari/605.1.15"
    ),
    "Accept": "application/json",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
}

_WANTED_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": (
                "Free-text search keyword (e.g., 'AI Engineer', 'LLM agent', "
                "'MLOps'). Wanted matches against position title + skills + "
                "company description."
            ),
        },
        "limit": {
            "type": "integer",
            "description": f"Max results (default 20, max {_MAX_LIMIT}).",
        },
        "offset": {
            "type": "integer",
            "description": "Pagination offset (default 0).",
        },
        "years": {
            "type": "integer",
            "description": (
                "Years of experience filter. -1 = all, 0 = entry/junior, "
                "1 = 1+ years, 3 = 3+ years, 5 = 5+ years. Default -1."
            ),
        },
    },
    "required": ["query"],
    "additionalProperties": False,
}


class WantedJobsSearchTool:
    """Search Korean tech jobs on Wanted.co.kr (LinkedIn alternative).

    Returns up to ``limit`` job listings matching ``query``. Each job is a
    minimal flat dict — ``{job_id, position, company, location, url,
    posted_at?}`` — so the LLM can render or filter without re-parsing
    nested JSON.
    """

    @property
    def name(self) -> str:
        return "wanted_jobs_search"

    @property
    def description(self) -> str:
        return (
            "Search Korean tech jobs on Wanted.co.kr by free-text query. "
            "Read-only public API (no OAuth). Use when LinkedIn search_jobs "
            "hits 403/timeout (bot detection) or when the user specifically "
            "wants Korean job-market data. Returns job_id, position, "
            "company, location, and direct apply URL."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return _WANTED_PARAMETERS

    def execute(self, **kwargs: Any) -> dict[str, Any]:
        from core.tools.base import tool_error

        query: str = str(kwargs.get("query") or "").strip()
        if not query:
            return tool_error(
                "query is required and must be non-empty",
                error_type="validation",
            )
        limit = min(int(kwargs.get("limit") or 20), _MAX_LIMIT)
        offset = max(int(kwargs.get("offset") or 0), 0)
        years = int(kwargs.get("years", -1))

        try:
            import httpx
        except ImportError:
            return tool_error("httpx is not installed", error_type="internal")

        params = {
            "query": query,
            "country": "kr",
            "job_sort": "job.latest_order",
            "years": str(years),
            "locations": "all",
            "limit": str(limit),
            "offset": str(offset),
        }

        try:
            with httpx.Client(timeout=_DEFAULT_TIMEOUT_S, headers=_DEFAULT_HEADERS) as client:
                resp = client.get(_WANTED_JOBS_URL, params=params)
        except httpx.TimeoutException:
            return tool_error(
                f"Wanted API timeout after {_DEFAULT_TIMEOUT_S}s",
                error_type="timeout",
                hint="Retry or try a narrower query.",
            )
        except httpx.HTTPError as exc:
            return tool_error(
                f"Wanted API request failed: {exc}",
                error_type="internal",
            )

        if resp.status_code != 200:
            return tool_error(
                f"Wanted API returned status {resp.status_code}",
                error_type="dependency",
                hint=(
                    "Wanted may have rate-limited or changed its API; "
                    "fall back to general_web_search with a 'site:wanted.co.kr' filter."
                ),
            )

        try:
            payload = resp.json()
        except ValueError:
            return tool_error(
                "Wanted API returned non-JSON body",
                error_type="dependency",
                hint="API contract may have changed; report to maintainer.",
            )

        if not isinstance(payload, dict):
            return {
                "result": {
                    "query": query,
                    "limit": limit,
                    "offset": offset,
                    "years": years,
                    "total_returned": 0,
                    "jobs": [],
                    "source": "wanted.co.kr",
                }
            }
        return {
            "result": _shape_response(payload, query=query, limit=limit, offset=offset, years=years)
        }


def _shape_response(
    payload: dict[str, Any],
    *,
    query: str,
    limit: int,
    offset: int,
    years: int,
) -> dict[str, Any]:
    """Flatten Wanted's nested ``data`` array into the tool result shape.

    Defensive — Wanted has historically nested job data under ``data``
    (list) or occasionally ``jobs``. We accept both and tolerate missing
    sub-fields so a partial response still returns *something* useful
    rather than a hard error.
    """
    raw_jobs_obj = payload.get("data")
    if not isinstance(raw_jobs_obj, list):
        raw_jobs_obj = payload.get("jobs")
    raw_jobs: list[Any] = raw_jobs_obj if isinstance(raw_jobs_obj, list) else []

    jobs: list[dict[str, Any]] = []
    for entry in raw_jobs:
        if not isinstance(entry, dict):
            continue
        job_id = entry.get("id") or entry.get("job_id")
        company_field = entry.get("company")
        company_name = (
            company_field.get("name") if isinstance(company_field, dict) else company_field
        )
        address_field = entry.get("address")
        location = (
            address_field.get("full_location") if isinstance(address_field, dict) else address_field
        )
        position = entry.get("position") or entry.get("title") or ""
        posted_at = entry.get("created_at") or entry.get("posted_at")

        jobs.append(
            {
                "job_id": job_id,
                "position": str(position),
                "company": str(company_name or ""),
                "location": str(location or ""),
                "url": _WANTED_JOB_DETAIL_URL.format(job_id=job_id) if job_id else "",
                "posted_at": posted_at,
            }
        )

    return {
        "query": query,
        "limit": limit,
        "offset": offset,
        "years": years,
        "total_returned": len(jobs),
        "jobs": jobs,
        "source": "wanted.co.kr",
    }
