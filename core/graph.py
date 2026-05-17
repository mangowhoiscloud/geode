"""Domain graph compatibility boundary.

The fixed Game IP LangGraph pipeline moved out of GEODE core for v1.0.0.
Core still exposes this module with clear failures so stale integrations fail
with an actionable message instead of importing a removed plugin path.
"""

from __future__ import annotations

from typing import Any


def _removed_graph_error() -> RuntimeError:
    return RuntimeError(
        "GEODE core no longer includes the Game IP LangGraph pipeline. "
        "Use an external domain plugin that owns its graph/nodes."
    )


def build_graph(*args: Any, **kwargs: Any) -> Any:
    raise _removed_graph_error()


def compile_graph(*args: Any, **kwargs: Any) -> Any:
    raise _removed_graph_error()
