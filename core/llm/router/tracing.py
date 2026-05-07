"""LangSmith tracing integration (Phase 5-A): LangChain standard env vars.

Activated when both ``LANGCHAIN_TRACING_V2=true`` and an API key are set.
``maybe_traceable`` returns the LangSmith ``@traceable`` decorator when active,
otherwise an identity passthrough so the call_llm* path stays free of
langsmith imports at module load time.
"""

from __future__ import annotations

import os as _os
from typing import Any


def is_langsmith_enabled() -> bool:
    """Check if LangSmith tracing is active (both gate + key required).

    Reads env vars at call time for testability.
    """
    tracing = _os.environ.get("LANGCHAIN_TRACING_V2", "").lower() == "true"
    api_key = _os.environ.get("LANGCHAIN_API_KEY") or _os.environ.get("LANGSMITH_API_KEY")
    return tracing and api_key is not None


def maybe_traceable(
    *,
    run_type: str = "llm",
    name: str | None = None,
) -> Any:
    """Return @traceable decorator if LangSmith is configured, else passthrough.

    Public API — used by domain/verification layers for LangSmith integration.
    """
    if is_langsmith_enabled():
        try:
            from langsmith import traceable

            return traceable(run_type=run_type, name=name)  # type: ignore[call-overload]
        except ImportError:
            pass

    def _identity(fn: Any) -> Any:
        return fn

    return _identity
