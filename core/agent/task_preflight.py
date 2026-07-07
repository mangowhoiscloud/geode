"""Task preflight routing based on GEODE's capability graph."""

from __future__ import annotations

import re
from typing import Literal, TypedDict

from core.agent.capability_graph import CapabilityGraph

TaskKind = Literal["pdf", "gui", "research", "code", "general"]


class TaskPreflight(TypedDict):
    schema_version: int
    task_kinds: list[TaskKind]
    recommended_tools: list[str]
    required_evidence: list[str]
    route_notes: list[str]
    warnings: list[str]


_PDF_RE = re.compile(r"(\.pdf\b|pdf\b|document\b|문서|논문|자료)", re.IGNORECASE)
_GUI_RE = re.compile(
    r"(screen|screenshot|desktop|computer use|gui|click|browser|window|화면|클릭|브라우저|창)",
    re.IGNORECASE,
)
_RESEARCH_RE = re.compile(
    r"(latest|recent|trend|research|paper|web|source|citation|최신|최근|조사|출처|논문)",
    re.IGNORECASE,
)
_CODE_RE = re.compile(
    r"(\bcode\b|\brepo\b|\btest\b|\bbug\b|\bimplement\b|\brefactor\b|\bgit\b|파일|코드|테스트|구현|수정|브랜치)",
    re.IGNORECASE,
)


def classify_task(user_input: str) -> list[TaskKind]:
    kinds: list[TaskKind] = []
    if _PDF_RE.search(user_input):
        kinds.append("pdf")
    if _GUI_RE.search(user_input):
        kinds.append("gui")
    if _RESEARCH_RE.search(user_input):
        kinds.append("research")
    if _CODE_RE.search(user_input):
        kinds.append("code")
    return kinds or ["general"]


def _gui_fallback_tools(visible: set[str]) -> list[str]:
    """Return source-safe GUI helper tools visible in this loop."""
    fallbacks: list[str] = []
    if "ui_probe" in visible:
        fallbacks.append("ui_probe")

    # Playwright MCP and the bundled browser helpers expose DOM/snapshot
    # structure. Prefer exact names when present, then fall back to a compact
    # browser_* bucket so the hint still points at the available surface.
    for name in (
        "browser_snapshot",
        "browser_scan",
        "browser_execute_js",
        "browser_evaluate",
        "browser_click",
    ):
        if name in visible and name not in fallbacks:
            fallbacks.append(name)
    if not any(name.startswith("browser_") for name in fallbacks) and any(
        name.startswith("browser_") or name.startswith("playwright__browser_") for name in visible
    ):
        fallbacks.append("browser_dom_tools")

    if any(name == "playwriter" or name.startswith("playwriter") for name in visible):
        fallbacks.append("playwriter")
    return fallbacks


def plan_task_preflight(user_input: str, graph: CapabilityGraph) -> TaskPreflight:
    """Return a provider-aware execution preflight for a user request."""
    kinds = classify_task(user_input)
    features = graph["features"]
    visible = set(graph["visible_tools"])
    recommended: list[str] = []
    evidence: list[str] = ["preflight", "final_answer"]
    notes: list[str] = []
    warnings = list(graph["warnings"])

    if "pdf" in kinds:
        evidence.append("document_ingest")
        if features["pdf_tool_ingest"]["supported"]:
            recommended.append("ingest_pdf")
            notes.append("Use GEODE PDF ingest first so downstream provider limits are explicit.")
        elif features["pdf_direct"]["supported"]:
            notes.append("Provider direct PDF input is available; keep extracted evidence rows.")
        else:
            warnings.append("PDF requested but neither direct PDF nor ingest_pdf is visible.")

    if "gui" in kinds:
        evidence.extend(["screen_observation", "gui_trajectory"])
        if features["native_computer_use"]["supported"]:
            recommended.append("computer")
            notes.append("Prefer provider-native computer-use when the hosted tool is visible.")
        elif features["emulated_computer_use"]["supported"]:
            recommended.append("computer_use")
            fallback_tools = _gui_fallback_tools(visible)
            recommended.extend(fallback_tools)
            if features["visual_grounding"]["supported"]:
                notes.append("Use capture -> locate -> action -> verify for emulated computer-use.")
            else:
                notes.append(
                    "Emulated computer_use can capture and act, but visual locate is not "
                    "source-safe on this provider/source. Prefer ui_probe, browser DOM tools, "
                    "playwriter for login-required browser sessions, or keyboard navigation; "
                    "route through GLM explicitly when visual locate is required."
                )
        else:
            warnings.append("GUI task requested but no computer-use route is visible.")

    if "research" in kinds:
        evidence.append("source_url")
        for tool in ("llms_txt_index", "web_fetch", "general_web_search", "arxiv_search"):
            if tool in visible:
                recommended.append(tool)
        notes.append("Record source URLs and distinguish observed evidence from inference.")

    if "code" in kinds:
        evidence.append("local_diff")
        for tool in ("glob_files", "grep_files", "read_document", "edit_file"):
            if tool in visible:
                recommended.append(tool)
        notes.append("Prefer repo-local evidence before edits; verify with targeted tests.")

    deduped: list[str] = []
    for tool in recommended:
        if tool not in deduped:
            deduped.append(tool)
    return {
        "schema_version": 1,
        "task_kinds": kinds,
        "recommended_tools": deduped,
        "required_evidence": sorted(set(evidence)),
        "route_notes": notes,
        "warnings": warnings,
    }


def render_preflight_hint(preflight: TaskPreflight) -> str:
    """Render a short system-prompt hint. Empty when no routing signal exists."""
    if preflight["task_kinds"] == ["general"] and not preflight["warnings"]:
        return ""
    lines = ["<geode_task_preflight>"]
    lines.append(f"task_kinds: {', '.join(preflight['task_kinds'])}")
    if preflight["recommended_tools"]:
        lines.append(f"recommended_tools: {', '.join(preflight['recommended_tools'])}")
    if preflight["required_evidence"]:
        lines.append(f"required_evidence: {', '.join(preflight['required_evidence'])}")
    for note in preflight["route_notes"][:4]:
        lines.append(f"note: {note}")
    for warning in preflight["warnings"][:3]:
        lines.append(f"warning: {warning}")
    lines.append("</geode_task_preflight>")
    return "\n".join(lines)
