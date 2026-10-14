"""HTTP API-key adapter for OpenAI — GEODE-owned inspect_ai provider.

Maps the manifest binding ``[petri.adapter.openai.api_key]`` to
``openai-platform/<model>``: inspect_ai's stock ``OpenAIAPI`` whose model
family questions are answered from GEODE's verified ``OpenAIModelSpec``
rows. inspect_ai 0.3.252 classifies reasoning models by name
(``"gpt-5" in name``), so GPT-6 ids get Chat Completions and lose their
reasoning options. Unknown models and custom gateways keep stock behavior.
The endpoint is resolved once at construction and passed explicitly, so a
later environment change cannot reclassify a provider whose client stays
bound. The ``openai-codex`` provider shares :class:`CatalogOpenAIFamily`.

Raw ``openai/<model>`` ids remain inspect_ai's stock provider: an explicit
escape hatch that bypasses these GEODE contracts.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from core.llm.adapters._openai_common import OpenAIModelSpec

__all__ = [
    "INSPECT_PREFIX",
    "CatalogOpenAIFamily",
    "admit_openai_reasoning_effort",
    "is_available",
    "register",
]

INSPECT_PREFIX = "openai-platform"
OPENAI_PLATFORM_URL = "https://api.openai.com/v1"


class CatalogOpenAIFamily:
    """Mixin for inspect_ai ``OpenAIAPI`` subclasses (place before the base)."""

    def _geode_official_endpoint(self) -> bool:
        # ``base_url`` is final: subclasses pass the resolved endpoint explicitly.
        base = getattr(self, "base_url", None)
        return base is not None and urlsplit(base).hostname == "api.openai.com"

    def _geode_spec(self) -> OpenAIModelSpec | None:
        if getattr(self, "service", None) is not None or not self._geode_official_endpoint():
            return None
        from core.llm.adapters._openai_common import find_openai_model_spec

        return find_openai_model_spec(str(getattr(self, "model_name", "")))

    def is_gpt_5(self) -> bool:
        spec = self._geode_spec()
        if spec is None:
            return bool(cast(Any, super()).is_gpt_5())
        return spec.reasoning_effort_values is not None

    def is_gpt_5_plus(self) -> bool:
        # inspect_ai's "plus" means reasoning can be switched off with ``none``.
        spec = self._geode_spec()
        if spec is None:
            return bool(cast(Any, super()).is_gpt_5_plus())
        return "none" in (spec.reasoning_effort_values or ())

    def supports_max_reasoning_effort(self) -> bool:
        spec = self._geode_spec()
        if spec is None:
            return bool(cast(Any, super()).supports_max_reasoning_effort())
        return "max" in (spec.reasoning_effort_values or ())


def admit_openai_reasoning_effort(api: CatalogOpenAIFamily, effort: str | None) -> None:
    """Reject an explicit effort the verified model does not accept, before any request."""
    spec = api._geode_spec()
    if spec is None or effort is None:
        return
    if effort not in (spec.reasoning_effort_values or ()):
        raise ValueError(
            f"{spec.model_id} does not accept reasoning_effort={effort!r}; "
            f"supported: {list(spec.reasoning_effort_values or ())}"
        )


def register() -> None:
    """Register ``openai-platform`` with inspect_ai (requires the ``[audit]`` extra)."""
    from inspect_ai.model import modelapi
    from inspect_ai.model._providers.openai import OpenAIAPI as _StockOpenAIAPI

    @modelapi(name=INSPECT_PREFIX)
    class OpenAIPlatformAPI(CatalogOpenAIFamily, _StockOpenAIAPI):  # type: ignore[misc, unused-ignore]
        def __init__(self, model_name: str, base_url: str | None = None, **kwargs: Any) -> None:
            if "/" not in model_name:  # no azure/bedrock service prefix
                base_url = base_url or os.environ.get("OPENAI_BASE_URL") or OPENAI_PLATFORM_URL
                from core.llm.model_catalog import require_model_source_available

                require_model_source_available(
                    model_name, provider="openai", source="payg", base_url=base_url
                )
            super().__init__(model_name, base_url=base_url, **kwargs)

        async def generate(self, input: Any, tools: Any, tool_choice: Any, config: Any) -> Any:
            admit_openai_reasoning_effort(self, config.reasoning_effort)
            return await super().generate(input, tools, tool_choice, config)


def is_available() -> bool:
    """True when ``OPENAI_API_KEY`` is set in the environment."""
    return bool(os.environ.get("OPENAI_API_KEY"))
