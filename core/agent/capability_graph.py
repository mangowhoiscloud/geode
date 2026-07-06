"""Provider/source capability graph for GEODE's agent runtime.

The graph is deliberately compact and runtime-shaped: it describes what this
session can safely *use*, not every theoretical feature a vendor page lists.
Callers use it for preflight routing, evidence rows, and model/tool mismatch
diagnostics.
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict

FeatureName = Literal[
    "function_calling",
    "native_computer_use",
    "emulated_computer_use",
    "pdf_direct",
    "pdf_tool_ingest",
    "visual_grounding",
    "evidence_ledger",
    "trajectory_eval",
]


class CapabilitySupport(TypedDict):
    supported: bool
    mode: str
    reason: str
    source_url: str


class CapabilityGraph(TypedDict):
    schema_version: int
    provider: str
    source: str
    model: str
    context_window_tokens: int | None
    features: dict[FeatureName, CapabilitySupport]
    visible_tools: list[str]
    warnings: list[str]


_DOCS = {
    "openai_function": "https://developers.openai.com/api/docs/guides/function-calling",
    "openai_computer": "https://developers.openai.com/api/docs/guides/tools-computer-use",
    "anthropic_tool": "https://platform.claude.com/docs/en/agents-and-tools/tool-use/overview",
    "anthropic_computer": (
        "https://platform.claude.com/docs/en/agents-and-tools/tool-use/computer-use-tool"
    ),
    "zai_function": "https://docs.z.ai/guides/capabilities/function-calling",
    "zai_glm": "https://docs.z.ai/guides/llm/glm-5.1",
    "geode": "GEODE runtime contract",
}


def _support(
    supported: bool,
    *,
    mode: str,
    reason: str,
    source_url: str,
) -> CapabilitySupport:
    return {
        "supported": supported,
        "mode": mode,
        "reason": reason,
        "source_url": source_url,
    }


def _context_window(model: str, provider: str) -> int | None:
    lower = model.lower()
    if provider == "glm":
        if "5.1" in lower or "glm-5" in lower:
            return 200_000
        return None
    if provider == "anthropic":
        if any(token in lower for token in ("fable-5", "opus-4-8", "opus-4-7", "opus-4-6")):
            return 1_000_000
        return None
    if provider in {"openai", "openai-codex"}:
        if any(token in lower for token in ("gpt-5.5", "gpt-5.4", "gpt-5.3")):
            return 1_000_000
        return None
    return None


def build_capability_graph(
    *,
    model: str,
    provider: str,
    source: str,
    visible_tool_names: set[str] | list[str] | tuple[str, ...] = (),
    computer_use_enabled: bool = False,
) -> CapabilityGraph:
    """Build a session-local capability graph.

    ``visible_tool_names`` is important: hosted tools can be provider-injected
    outside the declarative function list, while GEODE's subscription workaround
    appears as the normal ``computer_use`` function only on specific routes.
    """
    tools = sorted(set(visible_tool_names))
    tool_set = set(tools)
    effective_provider = "openai" if provider == "openai-codex" else provider

    function_docs = {
        "openai": _DOCS["openai_function"],
        "anthropic": _DOCS["anthropic_tool"],
        "glm": _DOCS["zai_function"],
    }.get(effective_provider, _DOCS["geode"])
    function_calling = effective_provider in {"openai", "anthropic", "glm"}

    native_computer = False
    native_reason = "No provider-native desktop computer tool is visible on this route."
    if "computer" in tool_set:
        native_computer = True
        native_reason = "The native computer tool is visible in the model tool surface."
    elif computer_use_enabled and effective_provider == "anthropic":
        native_computer = True
        native_reason = "Anthropic computer-use is enabled and injected by the provider path."
    elif computer_use_enabled and effective_provider == "openai" and source != "subscription":
        native_computer = True
        native_reason = "OpenAI Platform can use the native Responses computer tool."

    emulated_computer = "computer_use" in tool_set or (
        computer_use_enabled and effective_provider == "openai" and source == "subscription"
    )

    pdf_direct = effective_provider in {"openai", "anthropic"}
    pdf_reason = (
        "Provider route can carry first-party PDF/file/document input."
        if pdf_direct
        else "Use GEODE PDF ingest/OCR tools before sending compact context to this provider."
    )

    visual_grounding = effective_provider == "glm"
    visual_reason = (
        "GLM/Z.ai vision grounding can ground screenshots for this active provider."
        if visual_grounding
        else (
            "No source-safe visual grounding path is visible for this provider/source; "
            "use ui_probe, text extraction, keyboard navigation, or route through GLM explicitly."
        )
    )

    warnings: list[str] = []
    if effective_provider == "openai" and source == "subscription" and native_computer:
        warnings.append(
            "OpenAI subscription routes should prefer computer_use emulation over hosted computer."
        )
    if not function_calling:
        warnings.append(
            "Function calling is not known for this provider; tool use may be unavailable."
        )

    features: dict[FeatureName, CapabilitySupport] = {
        "function_calling": _support(
            function_calling,
            mode="json_schema_tool" if function_calling else "unavailable",
            reason="Provider supports application-executed tool/function calls."
            if function_calling
            else "Provider is not in GEODE's function-calling support matrix.",
            source_url=function_docs,
        ),
        "native_computer_use": _support(
            native_computer,
            mode="hosted_provider_tool" if native_computer else "unavailable",
            reason=native_reason,
            source_url=_DOCS["anthropic_computer"]
            if effective_provider == "anthropic"
            else _DOCS["openai_computer"],
        ),
        "emulated_computer_use": _support(
            emulated_computer,
            mode="geode_function_tool" if emulated_computer else "unavailable",
            reason="GEODE exposes computer_use as a normal function-call desktop control tool."
            if emulated_computer
            else "The emulated computer_use function is hidden for this provider/source.",
            source_url=_DOCS["geode"],
        ),
        "pdf_direct": _support(
            pdf_direct,
            mode="provider_document_input" if pdf_direct else "unavailable",
            reason=pdf_reason,
            source_url=function_docs,
        ),
        "pdf_tool_ingest": _support(
            "ingest_pdf" in tool_set,
            mode="geode_tool" if "ingest_pdf" in tool_set else "hidden",
            reason="GEODE PDF ingest is available in the tool surface."
            if "ingest_pdf" in tool_set
            else "GEODE PDF ingest is not visible to this loop.",
            source_url=_DOCS["geode"],
        ),
        "visual_grounding": _support(
            visual_grounding,
            mode="vision_grounding" if visual_grounding else "unavailable",
            reason=visual_reason,
            source_url=_DOCS["zai_glm"] if visual_grounding else _DOCS["geode"],
        ),
        "evidence_ledger": _support(
            True,
            mode="geode_jsonl",
            reason="GEODE records compact decision evidence rows independently of provider replay.",
            source_url=_DOCS["geode"],
        ),
        "trajectory_eval": _support(
            True,
            mode="geode_metrics",
            reason="GEODE can score GUI/tool trajectories from structured action rows.",
            source_url=_DOCS["geode"],
        ),
    }
    return {
        "schema_version": 1,
        "provider": provider,
        "source": source,
        "model": model,
        "context_window_tokens": _context_window(model, effective_provider),
        "features": features,
        "visible_tools": tools,
        "warnings": warnings,
    }


def supported_features(graph: CapabilityGraph) -> set[FeatureName]:
    """Return supported feature names for compact tests and diagnostics."""
    return {name for name, support in graph["features"].items() if support["supported"]}


def graph_summary(graph: CapabilityGraph) -> dict[str, Any]:
    """Small serialisable summary suitable for evidence rows and hooks."""
    return {
        "schema_version": graph["schema_version"],
        "provider": graph["provider"],
        "source": graph["source"],
        "model": graph["model"],
        "context_window_tokens": graph["context_window_tokens"],
        "supported": sorted(supported_features(graph)),
        "warnings": graph["warnings"],
    }
