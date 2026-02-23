"""Data Retrieval Tools — wraps fixture/cortex system as LLM-callable tools.

Layer 5 tools for data access:
- QueryMonoLakeTool: Query MonoLake game metrics (fixture-based)
- CortexAnalystTool: Placeholder for Snowflake Cortex Analyst SQL
- CortexSearchTool: Placeholder for Cortex Search semantic retrieval
"""

from __future__ import annotations

from typing import Any

from geode.fixtures import FIXTURE_MAP, load_fixture


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


class CortexAnalystTool:
    """Placeholder tool for Snowflake Cortex Analyst SQL queries.

    In production, translates natural-language questions into
    SQL via Cortex Analyst and executes against Snowflake.
    Demo returns a stub acknowledgment.
    """

    @property
    def name(self) -> str:
        return "cortex_analyst"

    @property
    def description(self) -> str:
        return (
            "Run a natural-language query against Snowflake via Cortex Analyst. "
            "Translates question to SQL, executes, and returns tabular results."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "Natural-language question to answer via SQL.",
                },
                "database": {
                    "type": "string",
                    "description": "Target database name.",
                    "default": "GEODE_DB",
                },
            },
            "required": ["question"],
        }

    def execute(self, **kwargs: Any) -> dict[str, Any]:
        question: str = kwargs["question"]
        database: str = kwargs.get("database", "GEODE_DB")
        return {
            "result": {
                "status": "stub",
                "message": (
                    f"Cortex Analyst query against {database} "
                    f"would execute: '{question}'"
                ),
                "rows": [],
                "columns": [],
            }
        }


class CortexSearchTool:
    """Placeholder tool for Cortex Search semantic retrieval.

    In production, performs vector-based semantic search over
    IP documents, reviews, and community content.
    Demo returns a stub result.
    """

    @property
    def name(self) -> str:
        return "cortex_search"

    @property
    def description(self) -> str:
        return (
            "Semantic search across IP documents, reviews, and community content "
            "using Cortex Search vector retrieval."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Semantic search query.",
                },
                "top_k": {
                    "type": "integer",
                    "description": "Number of results to return.",
                    "default": 5,
                },
                "filters": {
                    "type": "object",
                    "description": "Optional metadata filters (e.g., genre, year).",
                },
            },
            "required": ["query"],
        }

    def execute(self, **kwargs: Any) -> dict[str, Any]:
        query: str = kwargs["query"]
        top_k: int = kwargs.get("top_k", 5)
        return {
            "result": {
                "status": "stub",
                "message": (
                    f"Cortex Search would return top-{top_k} "
                    f"results for: '{query}'"
                ),
                "documents": [],
                "scores": [],
            }
        }
