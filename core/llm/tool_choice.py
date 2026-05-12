"""Tool choice normalization across providers (GAP-T1).

Different LLM providers expect different ``tool_choice`` shapes:

- **Anthropic Messages API**: always a dict.
  ``{"type": "auto"|"any"|"tool"|"none", "name"?: "..."}``
- **OpenAI Responses API**: string or flat dict.
  ``"auto" | "none" | "required" | {"type": "function", "name": "..."}``
- **GLM Chat Completions** (OpenAI-compat): string or nested dict.
  ``"auto" | "none" | "required" | {"type": "function", "function": {"name": "..."}}``

Prior to v0.93, each adapter inlined its own conversion (anthropic.py:482-484,
openai.py:507, glm.py:190), which (a) duplicated logic 3× and (b) failed
to translate cross-provider concepts such as ``required`` ↔ ``any`` or
named-tool forcing (``{"name": "X"}``).  This module centralizes the
mapping so callers can pass a single canonical form and each adapter
renders it natively.

Canonical inputs accepted:
- ``"auto"`` / ``"none"`` / ``"required"`` / ``"any"`` (string)
- ``{"type": "..."}`` (dict; same keywords as above)
- ``{"type": "tool"|"function", "name": "X"}`` (force named tool)
- ``{"name": "X"}`` (shorthand for forced named tool)
- ``{"function": {"name": "X"}}`` (OpenAI-style nested name)
- ``None`` (pass through)
"""

from __future__ import annotations

from typing import Any

ToolChoice = str | dict[str, Any]

# ``required`` ↔ ``any`` is the only cross-provider keyword that differs
# in spelling.  ``auto`` / ``none`` / function-name forcing are conceptually
# identical across the three providers; only the wrapping shape changes.
_REQUIRED_ALIASES = frozenset({"required", "any"})


def _extract_name(choice: dict[str, Any]) -> str | None:
    """Return the forced-tool name from any common dict shape, or None."""
    direct = choice.get("name")
    if isinstance(direct, str) and direct:
        return direct
    fn = choice.get("function")
    if isinstance(fn, dict):
        nested = fn.get("name")
        if isinstance(nested, str) and nested:
            return nested
    return None


def _to_anthropic(choice: ToolChoice | None) -> dict[str, Any] | None:
    if choice is None:
        return None
    if isinstance(choice, str):
        if choice in _REQUIRED_ALIASES:
            return {"type": "any"}
        return {"type": choice}
    name = _extract_name(choice)
    if name is not None:
        return {"type": "tool", "name": name}
    t = choice.get("type", "auto")
    if isinstance(t, str) and t in _REQUIRED_ALIASES:
        return {"type": "any"}
    return {"type": t}


def _to_openai(choice: ToolChoice | None) -> str | dict[str, Any] | None:
    """Responses API flat shape: string or ``{"type": "function", "name": "X"}``."""
    if choice is None:
        return None
    if isinstance(choice, str):
        return "required" if choice in _REQUIRED_ALIASES else choice
    name = _extract_name(choice)
    if name is not None:
        return {"type": "function", "name": name}
    t = choice.get("type", "auto")
    if isinstance(t, str) and t in _REQUIRED_ALIASES:
        return "required"
    return t if isinstance(t, str) else "auto"


def _to_glm(choice: ToolChoice | None) -> str | dict[str, Any] | None:
    """Chat Completions nested shape: string or
    ``{"type": "function", "function": {"name": "X"}}``.
    """
    if choice is None:
        return None
    if isinstance(choice, str):
        return "required" if choice in _REQUIRED_ALIASES else choice
    name = _extract_name(choice)
    if name is not None:
        return {"type": "function", "function": {"name": name}}
    t = choice.get("type", "auto")
    if isinstance(t, str) and t in _REQUIRED_ALIASES:
        return "required"
    return t if isinstance(t, str) else "auto"


def normalize(provider: str, choice: ToolChoice | None) -> str | dict[str, Any] | None:
    """Convert a tool_choice into the provider-native shape.

    ``provider`` is matched case-insensitively against ``anthropic`` /
    ``openai`` / ``codex`` / ``glm``.  Unknown providers receive the
    input back unchanged so callers do not crash when extending to new
    backends — log + add a branch when the new provider lands.
    """
    p = provider.lower()
    if p == "anthropic":
        return _to_anthropic(choice)
    if p in ("openai", "codex"):
        return _to_openai(choice)
    if p == "glm":
        return _to_glm(choice)
    return choice
