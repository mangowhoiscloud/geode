"""Game IP data retrieval tools — MonoLake fixture-backed query tool.

Layer 5 tool exposing fixture data (DAU, revenue, retention, metacritic,
media type, genre, studio) as an LLM-callable tool. The domain-agnostic
Snowflake Cortex stubs live in ``core/tools/data_tools.py``.
"""

from __future__ import annotations

from typing import Any

from plugins.game_ip.fixtures import FIXTURE_MAP, load_fixture


class QueryMonoLakeTool:
    """Tool wrapper for MonoLake data retrieval (fixture-based)."""

    @property
    def name(self) -> str:
        return "query_monolake"

    @property
    def description(self) -> str:
        return (
            "Query MonoLake for game metrics (DAU, revenue, retention, metacritic) "
            "and IP info (media type, genre, studio) for a given IP name."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "ip_name": {
                    "type": "string",
                    "description": "IP name to query (e.g., 'Berserk', 'Cowboy Bebop').",
                },
                "fields": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Optional list of specific fields to return. "
                        "If empty, returns all available data."
                    ),
                },
            },
            "required": ["ip_name"],
        }

    def execute(self, **kwargs: Any) -> dict[str, Any]:
        ip_name: str = kwargs["ip_name"]
        fields: list[str] = kwargs.get("fields", [])

        try:
            fixture = load_fixture(ip_name)
        except ValueError:
            return {
                "error": f"No data found for '{ip_name}'",
                "available_ips": list(FIXTURE_MAP.keys()),
            }

        result: dict[str, Any] = {
            "ip_info": fixture["ip_info"],
            "monolake": fixture["monolake"],
        }

        # Filter to requested fields if specified
        if fields:
            filtered: dict[str, Any] = {}
            for field in fields:
                if field in result.get("ip_info", {}):
                    filtered[field] = result["ip_info"][field]
                elif field in result.get("monolake", {}):
                    filtered[field] = result["monolake"][field]
            return {"result": filtered, "ip_name": ip_name}

        return {"result": result, "ip_name": ip_name}
