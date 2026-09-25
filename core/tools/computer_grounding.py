"""Source-aware failure for unsupported automatic visual grounding.

No current public Z.AI model establishes the previous GLM-5V coordinate
contract. Native computer actions remain owned by the provider adapters.
"""

from __future__ import annotations

from typing import Any

from core.tools.computer_use import TARGET_HEIGHT, TARGET_WIDTH


class VisualGroundingUnavailableError(RuntimeError):
    """Raised when no source-safe grounding backend exists for this turn."""

    def __init__(self, message: str, *, provider: str = "", source: str = "") -> None:
        super().__init__(message)
        self.provider = provider
        self.source = source


def _context_provider_source(tool_context: Any | None) -> tuple[str, str]:
    provider = str(getattr(tool_context, "provider", "") or "").strip().lower()
    source = str(getattr(tool_context, "source", "") or "").strip().lower()
    if provider == "openai-codex":
        provider = "openai"
    if provider == "zhipuai":
        provider = "glm"
    return provider, source


async def locate_with_active_provider(
    screenshot_b64: str,
    instruction: str,
    *,
    target_width: int = TARGET_WIDTH,
    target_height: int = TARGET_HEIGHT,
    tool_context: Any | None = None,
) -> tuple[int, int] | None:
    """Reject automatic grounding until a model and coordinate contract is verified."""
    provider, source = _context_provider_source(tool_context)
    raise VisualGroundingUnavailableError(
        (
            "visual grounding is not configured for "
            f"provider={provider or '<unknown>'} source={source or '<unknown>'}; "
            "implicit GLM fallback is disabled; no verified model and coordinate contract exists"
        ),
        provider=provider,
        source=source,
    )
