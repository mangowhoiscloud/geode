"""Data Retrieval Tools.

Layer 5 tools for data access:
- GenerateDataTool: Deterministic synthetic records for tests/demo workflows

PR-V1-PRE-CLEANUP (2026-06-13): the CortexAnalyst/CortexSearch placeholder
stubs (Game-IP-era Snowflake surface, always returned status="stub") were
deleted — registered tools must do real work.

Specialized fixture/query tools live in external packages.
"""

from __future__ import annotations

import asyncio
from typing import Any


class _AsyncExecuteMixin:
    def _execute_sync(self, **kwargs: Any) -> dict[str, Any]:
        raise NotImplementedError

    async def aexecute(self, **kwargs: Any) -> dict[str, Any]:
        """Run sync data client work off the event loop."""
        return await asyncio.to_thread(self._execute_sync, **kwargs)


class GenerateDataTool(_AsyncExecuteMixin):
    """Generate deterministic generic sample records.

    The tool intentionally avoids domain-specific fixtures. It exists for
    demos, smoke tests, and workflows that need small structured input data.
    """

    @property
    def name(self) -> str:
        return "generate_data"

    @property
    def description(self) -> str:
        return "Generate deterministic synthetic records for testing and demo workflows."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "count": {
                    "type": "integer",
                    "description": "Number of records to generate. Default 5, maximum 20.",
                },
                "genre": {
                    "type": "string",
                    "description": "Optional label applied to every generated record.",
                },
            },
            "required": [],
        }

    def _execute_sync(self, **kwargs: Any) -> dict[str, Any]:
        raw_count = kwargs.get("count", 5)
        try:
            count = int(raw_count)
        except (TypeError, ValueError):
            return {"error": "count must be an integer", "status": "failure"}
        count = max(1, min(count, 20))
        genre = str(kwargs.get("genre") or "general")

        records = [
            {
                "id": f"sample-{index + 1:03d}",
                "label": f"{genre}-{index + 1}",
                "genre": genre,
                "score": round(100.0 - index * 3.7, 1),
            }
            for index in range(count)
        ]
        return {
            "result": {
                "status": "ok",
                "count": count,
                "genre": genre,
                "records": records,
            }
        }
