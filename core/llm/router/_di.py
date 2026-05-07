"""Thread-safe LLM callable injection via contextvars.

GeodeRuntime.create() calls ``set_llm_callable`` once per session;
analyst/evaluator nodes pull the right callable through the ``get_llm_*``
accessors which raise a clear error when injection is skipped (so we never
fall back to a silent default that would produce wrong-tier scores).
"""

from __future__ import annotations

from contextvars import ContextVar

from core.llm.adapters import (
    LLMJsonCallable,
    LLMParsedCallable,
    LLMTextCallable,
    LLMToolCallable,
)

_llm_json_ctx: ContextVar[LLMJsonCallable | None] = ContextVar("llm_json", default=None)
_llm_parsed_ctx: ContextVar[LLMParsedCallable | None] = ContextVar("llm_parsed", default=None)
_llm_tool_ctx: ContextVar[LLMToolCallable | None] = ContextVar("llm_tool", default=None)

# Secondary LLM contextvars for ensemble/cross-LLM mode
_secondary_llm_json_ctx: ContextVar[LLMJsonCallable | None] = ContextVar(
    "secondary_llm_json", default=None
)
_secondary_llm_parsed_ctx: ContextVar[LLMParsedCallable | None] = ContextVar(
    "secondary_llm_parsed", default=None
)


def set_llm_callable(
    json_fn: LLMJsonCallable,
    text_fn: LLMTextCallable,
    parsed_fn: LLMParsedCallable | None = None,
    tool_fn: LLMToolCallable | None = None,
    secondary_json_fn: LLMJsonCallable | None = None,
    secondary_parsed_fn: LLMParsedCallable | None = None,
) -> None:
    """Inject LLM callables (typically called by GeodeRuntime.create())."""
    _llm_json_ctx.set(json_fn)
    if parsed_fn is not None:
        _llm_parsed_ctx.set(parsed_fn)
    if tool_fn is not None:
        _llm_tool_ctx.set(tool_fn)
    # Always update secondary contextvars (set to None to clear if not provided)
    _secondary_llm_json_ctx.set(secondary_json_fn)
    _secondary_llm_parsed_ctx.set(secondary_parsed_fn)


def get_llm_json() -> LLMJsonCallable:
    """Return the injected JSON callable. Raises if not injected."""
    fn = _llm_json_ctx.get()
    if fn is None:
        raise RuntimeError(
            "LLM JSON callable not injected. "
            "Call set_llm_callable() first (done by GeodeRuntime.create())."
        )
    return fn


def get_llm_parsed() -> LLMParsedCallable:
    """Return the injected parsed callable. Raises if not injected."""
    fn = _llm_parsed_ctx.get()
    if fn is None:
        raise RuntimeError(
            "LLM parsed callable not injected. "
            "Call set_llm_callable(parsed_fn=...) first (done by GeodeRuntime.create())."
        )
    return fn


def get_llm_tool() -> LLMToolCallable:
    """Return the injected tool-use callable. Raises if not injected."""
    fn = _llm_tool_ctx.get()
    if fn is None:
        raise RuntimeError(
            "LLM tool callable not injected. "
            "Call set_llm_callable(tool_fn=...) first (done by GeodeRuntime.create())."
        )
    return fn


def get_secondary_llm_json() -> LLMJsonCallable | None:
    """Return the secondary JSON callable, or None if not configured."""
    return _secondary_llm_json_ctx.get()


def get_secondary_llm_parsed() -> LLMParsedCallable | None:
    """Return the secondary parsed callable, or None if not configured."""
    return _secondary_llm_parsed_ctx.get()
