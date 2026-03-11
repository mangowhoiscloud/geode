"""Natural Language Router — Claude Opus 4.6 Tool Use (autonomous).

LLM-autonomous routing via Anthropic Tool Use API:
  - LLM receives user input + tool definitions
  - LLM autonomously decides: call a tool (action) OR respond with text (chat)

Graceful degradation (3-stage):
  1. LLM Tool Use (primary) — full autonomous routing
  2. Offline pattern matching (fallback) — when LLM unavailable
  3. Help with error context — when nothing matches

Tools exposed to LLM (20):
  1-17. Core tools (list, analyze, search, compare, help, report, batch,
        status, model, memory_search/save, rule, key, auth, data, schedule, trigger)
  18. delegate_task  — 서브에이전트 병렬 실행
  19. create_plan    — 분석 계획 생성
  20. approve_plan   — 계획 승인 및 실행

Excluded: run_bash (requires explicit HITL gate, not exposed to NL router)

If the LLM responds with text (no tool call) → chat intent.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import anthropic

from core.config import settings
from core.llm.prompts import ROUTER_SYSTEM

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Intent data model
# ---------------------------------------------------------------------------

VALID_ACTIONS = {
    "analyze",
    "search",
    "list",
    "help",
    "compare",
    "chat",
    "report",
    "batch",
    "status",
    "model",
    "memory",
    "key",
    "auth",
    "generate",
    "schedule",
    "trigger",
    "plan",
    "delegate",
}

LLM_ROUTER_MODEL = settings.router_model


@dataclass
class NLIntent:
    """Classified intent from natural language input."""

    action: str  # analyze, search, list, help, compare, chat
    args: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0  # 1.0 = exact match, <1.0 = fuzzy


# ---------------------------------------------------------------------------
# IP name registry — canonical names from fixtures
# ---------------------------------------------------------------------------


def _load_ip_names() -> dict[str, str]:
    """Load canonical IP names from fixtures.

    Returns a mapping of lowercased canonical name → fixture key.
    Example: {"ghost in the shell": "ghost in shell", "berserk": "berserk"}
    """
    from core.fixtures import FIXTURE_MAP, load_fixture

    name_to_key: dict[str, str] = {}
    for fk in FIXTURE_MAP:
        try:
            fixture = load_fixture(fk)
            canonical = fixture["ip_info"]["ip_name"]
            name_to_key[canonical.lower()] = fk
        except Exception:
            # Fixture without ip_info — use key as-is
            name_to_key[fk] = fk
    return name_to_key


# Lazy-loaded cache
_ip_name_cache: dict[str, str] | None = None


def get_ip_name_map() -> dict[str, str]:
    """Get the canonical name → fixture key map (cached)."""
    global _ip_name_cache
    if _ip_name_cache is None:
        _ip_name_cache = _load_ip_names()
    return _ip_name_cache


# ---------------------------------------------------------------------------
# System prompt — dynamically built with all available IP names
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT_TEMPLATE = ROUTER_SYSTEM

# Well-known IPs to include as examples (recognizable across languages)
_NOTABLE_IPS = {
    "berserk",
    "cowboy bebop",
    "ghost in shell",
    "hollow knight",
    "disco elysium",
    "hades",
    "celeste",
    "cult of the lamb",
    "dead cells",
    "slay the spire",
    "vampire survivors",
    "factorio",
    "stardew valley",
    "cuphead",
    "balatro",
    "rimworld",
}


def _build_system_prompt() -> str:
    """Build system prompt with notable IP examples and memory context (P1-C)."""
    from core.fixtures import FIXTURE_MAP, load_fixture

    name_map = get_ip_name_map()
    ip_count = len(name_map)

    # Prefer notable IPs as examples, then fill with others
    examples: list[str] = []
    for fk in _NOTABLE_IPS:
        if fk in FIXTURE_MAP:
            try:
                canonical = load_fixture(fk)["ip_info"]["ip_name"]
                examples.append(canonical)
            except Exception:
                examples.append(fk.title())

    base = _SYSTEM_PROMPT_TEMPLATE.format(
        ip_count=ip_count,
        ip_examples=", ".join(sorted(examples)),
    )

    # P1-C: Inject memory context (recent insights + active rules)
    memory_ctx = _build_memory_context()
    if memory_ctx:
        base += "\n\n" + memory_ctx

    return base


def _build_memory_context() -> str:
    """Build memory context string from ProjectMemory (recent insights + rules)."""
    try:
        from core.memory.project import ProjectMemory

        mem = ProjectMemory()
        if not mem.exists():
            return ""

        parts: list[str] = []

        # Recent insights (last 5 lines from MEMORY.md's 최근 인사이트 section)
        content = mem.load_memory()
        if "## 최근 인사이트" in content:
            section = content.split("## 최근 인사이트")[1]
            lines = [ln.strip() for ln in section.split("\n") if ln.strip().startswith("- ")]
            if lines:
                parts.append("Recent insights:\n" + "\n".join(lines[:5]))

        # Active rules summary
        rules = mem.list_rules()
        if rules:
            rule_summaries = [
                f"- {r['name']} (paths: {', '.join(r.get('paths', []))})" for r in rules[:5]
            ]
            parts.append("Active analysis rules:\n" + "\n".join(rule_summaries))

        return "\n\n".join(parts)
    except Exception:
        log.debug("Failed to build memory context for system prompt", exc_info=True)
        return ""


# ---------------------------------------------------------------------------
# Tool definitions — loaded from core/tools/definitions.json
# ---------------------------------------------------------------------------

_TOOLS_JSON_PATH = Path(__file__).resolve().parent.parent / "tools" / "definitions.json"


def _load_tools() -> list[dict[str, Any]]:
    """Load tool definitions from JSON file (NL router tools, excluding run_bash)."""
    all_tools: list[dict[str, Any]] = json.loads(_TOOLS_JSON_PATH.read_text(encoding="utf-8"))
    # NL router exposes all tools except run_bash (requires explicit HITL)
    excluded = {"run_bash"}
    return [t for t in all_tools if t["name"] not in excluded]


_TOOLS: list[dict[str, Any]] = _load_tools()

# Legacy compatibility marker — the full 400-line inline definition has been
# moved to core/tools/definitions.json.  See that file for all tool schemas.
_LEGACY_TOOLS_REMOVED = True

# Tool name → NLIntent action mapping
_TOOL_ACTION_MAP: dict[str, str] = {
    "list_ips": "list",
    "analyze_ip": "analyze",
    "search_ips": "search",
    "compare_ips": "compare",
    "show_help": "help",
    "generate_report": "report",
    "batch_analyze": "batch",
    "check_status": "status",
    "switch_model": "model",
    "memory_search": "memory",
    "memory_save": "memory",
    "manage_rule": "memory",
    "set_api_key": "key",
    "manage_auth": "auth",
    "generate_data": "generate",
    "schedule_job": "schedule",
    "trigger_event": "trigger",
    "create_plan": "plan",
    "approve_plan": "plan",
    "delegate_task": "delegate",
}

# Tool name → args key mapping (passthrough all tool input keys)
_TOOL_ARGS_MAP: dict[str, dict[str, str]] = {
    "analyze_ip": {"ip_name": "ip_name"},
    "search_ips": {"query": "query"},
    "compare_ips": {"ip_a": "ip_a", "ip_b": "ip_b"},
    "generate_report": {"ip_name": "ip_name"},
    "batch_analyze": {"top": "top", "genre": "genre", "stream": "stream"},
    "switch_model": {"model_hint": "model_hint"},
    "memory_search": {"query": "query", "tier": "tier"},
    "memory_save": {"key": "key", "content": "content"},
    "manage_rule": {
        "action": "rule_action",
        "name": "name",
        "paths": "paths",
        "content": "content",
    },
    "set_api_key": {"key_value": "key_value"},
    "manage_auth": {"sub_action": "sub_action"},
    "generate_data": {"count": "count", "genre": "genre"},
    "schedule_job": {"sub_action": "sub_action", "target_id": "target_id"},
    "trigger_event": {"sub_action": "sub_action", "event_name": "event_name"},
    "create_plan": {"ip_name": "ip_name", "template": "template"},
    "approve_plan": {"plan_id": "plan_id"},
    "delegate_task": {"tasks": "tasks"},
}


# ---------------------------------------------------------------------------
# Offline fallback patterns (used when LLM is unavailable)
# ---------------------------------------------------------------------------


def _get_known_ips() -> set[str]:
    """Get all known IP names for offline fallback (lowercased)."""
    name_map = get_ip_name_map()
    ips: set[str] = set()
    for canonical, fk in name_map.items():
        ips.add(canonical)
        ips.add(fk)
    return ips


_OFFLINE_LIST = re.compile(r"(?:목록|리스트|list|show\s*all|display)", re.IGNORECASE)
_OFFLINE_HELP = re.compile(r"(?:도움|help|사용법|가이드|어떻게|how\s*to)", re.IGNORECASE)
_OFFLINE_SEARCH = re.compile(r"(?:찾아|검색|search|find)", re.IGNORECASE)
_OFFLINE_COMPARE = re.compile(r"(?:비교|compare|\bvs\b)", re.IGNORECASE)
_OFFLINE_ANALYZE = re.compile(r"(?:분석|평가|analyze|evaluate)", re.IGNORECASE)
_OFFLINE_REPORT = re.compile(r"(?:리포트|보고서|report|레포트)", re.IGNORECASE)
_OFFLINE_BATCH = re.compile(r"(?:배치|전체|모든|순위|rank|batch|all\s*ip|top\s*\d+)", re.IGNORECASE)
_OFFLINE_STATUS = re.compile(r"(?:상태|건강|health|status|설정|config|모델\s*뭐)", re.IGNORECASE)
_OFFLINE_MODEL = re.compile(
    r"(?:모델\s*바꿔|switch\s*model|앙상블|ensemble|cross\s*모드)", re.IGNORECASE
)
_OFFLINE_MEMORY = re.compile(
    r"(?:기억|메모리|memory|규칙|rule|인사이트|insight|저장|save|remember)", re.IGNORECASE
)
_OFFLINE_PLAN = re.compile(
    r"(?:계획|플랜|plan|먼저|before\s*execut|사전\s*검토|순서)", re.IGNORECASE
)
_OFFLINE_DELEGATE = re.compile(
    r"(?:병렬|동시|parallel|서브\s*에이전트|sub\s*agent|delegate|concurrent)", re.IGNORECASE
)


def _offline_fallback(text: str, *, error: str = "") -> NLIntent:
    """Minimal pattern matching when LLM is unavailable.

    Only activated on API failure — not part of the normal routing path.
    """
    lower = text.lower().strip()

    # Compare check first (more specific — "vs", "비교" are unambiguous)
    if _OFFLINE_COMPARE.search(lower):
        return NLIntent(
            action="compare",
            args={"_offline": True, "_error": error},
            confidence=0.3,
        )
    # Report check before known IP names (more specific — "리포트", "report")
    if _OFFLINE_REPORT.search(lower):
        return NLIntent(
            action="report",
            args={"ip_name": text.strip(), "_error": error},
            confidence=0.7,
        )
    # Plan mode check (before known IP — more specific intent)
    if _OFFLINE_PLAN.search(lower):
        return NLIntent(
            action="plan",
            args={"ip_name": text.strip(), "_error": error},
            confidence=0.7,
        )
    # Delegate check (parallel sub-agent dispatch)
    if _OFFLINE_DELEGATE.search(lower):
        return NLIntent(
            action="delegate",
            args={"_offline": True, "_error": error},
            confidence=0.5,
        )
    # Known IP names → analyze
    for ip in _get_known_ips():
        if ip in lower:
            return NLIntent(
                action="analyze",
                args={"ip_name": text.strip(), "_error": error},
                confidence=0.7,
            )

    # Pattern checks (ordered by specificity)
    if _OFFLINE_BATCH.search(lower):
        return NLIntent(action="batch", args={"_error": error}, confidence=0.7)
    if _OFFLINE_STATUS.search(lower):
        return NLIntent(action="status", args={"_error": error}, confidence=0.7)
    if _OFFLINE_MODEL.search(lower):
        return NLIntent(action="model", args={"_error": error}, confidence=0.7)
    if _OFFLINE_MEMORY.search(lower):
        return NLIntent(
            action="memory",
            args={"query": text.strip(), "_error": error},
            confidence=0.7,
        )
    if _OFFLINE_LIST.search(lower):
        return NLIntent(action="list", args={"_error": error}, confidence=0.7)
    if _OFFLINE_HELP.search(lower):
        return NLIntent(action="help", args={"_error": error})
    if _OFFLINE_ANALYZE.search(lower):
        return NLIntent(
            action="analyze",
            args={"ip_name": text.strip(), "_error": error},
            confidence=0.7,
        )
    if _OFFLINE_SEARCH.search(lower):
        return NLIntent(
            action="search",
            args={"query": text.strip(), "_error": error},
            confidence=0.7,
        )

    # Nothing matched — help with error context
    return NLIntent(action="help", args={"_error": error}, confidence=0.3)


# ---------------------------------------------------------------------------
# LLM Tool Use call
# ---------------------------------------------------------------------------


def _call_tool_use_router(text: str) -> NLIntent:
    """Route user input via Claude Opus 4.6 Tool Use.

    The LLM sees tool definitions and autonomously decides:
    - Call a tool → mapped to NLIntent action
    - Respond with text → chat intent
    """
    try:
        if not settings.anthropic_api_key:
            log.debug("No Anthropic API key — LLM router unavailable")
            return _offline_fallback(text, error="no_api_key")

        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

        response = client.messages.create(  # type: ignore[call-overload]
            model=LLM_ROUTER_MODEL,
            system=_build_system_prompt(),
            messages=[{"role": "user", "content": text}],
            tools=_TOOLS,
            tool_choice={"type": "auto"},
            max_tokens=1024,
            temperature=0.0,
            timeout=15.0,
        )

        # Track token usage
        if response.usage:
            from core.llm.client import (
                LLMUsage,
                calculate_cost,
                get_usage_accumulator,
            )

            in_tok = response.usage.input_tokens
            out_tok = response.usage.output_tokens
            cost = calculate_cost(LLM_ROUTER_MODEL, in_tok, out_tok)
            get_usage_accumulator().record(
                LLMUsage(
                    model=LLM_ROUTER_MODEL,
                    input_tokens=in_tok,
                    output_tokens=out_tok,
                    cost_usd=cost,
                )
            )
            log.debug(
                "NLRouter tool_use: model=%s in=%d out=%d cost=$%.6f",
                LLM_ROUTER_MODEL,
                in_tok,
                out_tok,
                cost,
            )

        # Parse response: tool_use or text
        if response.stop_reason == "tool_use":
            return _parse_tool_use(response)

        # Text-only response → chat
        return _parse_text_response(response)

    except anthropic.AuthenticationError:
        log.warning("Anthropic API key is invalid or expired")
        return _offline_fallback(text, error="auth_error")

    except anthropic.BadRequestError as exc:
        error_msg = str(exc)
        if "credit balance" in error_msg.lower() or "billing" in error_msg.lower():
            log.warning("Anthropic API credit balance too low")
            return _offline_fallback(text, error="billing")
        log.warning("Anthropic BadRequest: %s", error_msg)
        return _offline_fallback(text, error="api_error")

    except Exception:
        log.warning("NLRouter Tool Use call failed", exc_info=True)
        return _offline_fallback(text, error="api_error")


def _parse_tool_use(response: anthropic.types.Message) -> NLIntent:
    """Extract intent from a tool_use response."""
    for block in response.content:
        if block.type == "tool_use":
            tool_name = block.name
            tool_input: dict[str, Any] = block.input

            action = _TOOL_ACTION_MAP.get(tool_name, "chat")
            args: dict[str, Any] = {}

            # Map tool input args to NLIntent args
            if tool_name in _TOOL_ARGS_MAP:
                for tool_key, intent_key in _TOOL_ARGS_MAP[tool_name].items():
                    if tool_key in tool_input:
                        args[intent_key] = tool_input[tool_key]

            return NLIntent(action=action, args=args, confidence=0.95)

    # No tool_use block found (shouldn't happen)
    return NLIntent(action="help", confidence=0.5)


def _parse_text_response(response: anthropic.types.Message) -> NLIntent:
    """Extract chat response from a text-only response."""
    parts: list[str] = []
    for block in response.content:
        if block.type == "text":
            parts.append(block.text)

    text = "\n".join(parts).strip()
    if text:
        return NLIntent(action="chat", args={"response": text}, confidence=0.9)

    return NLIntent(action="help", confidence=0.5)


# ---------------------------------------------------------------------------
# Router class
# ---------------------------------------------------------------------------


class NLRouter:
    """LLM-Autonomous NL Router via Claude Opus 4.6 Tool Use.

    The LLM receives tool definitions and decides:
    - Which tool to call (→ action intent), or
    - Respond directly with text (→ chat intent).

    No regex patterns — all routing decisions are made by the LLM.
    Graceful degradation: no API key → help fallback.
    """

    def __init__(self, *, llm_enabled: bool = True) -> None:
        self._llm_enabled = llm_enabled

    def classify(self, text: str) -> NLIntent:
        """Classify user input via LLM Tool Use."""
        text = text.strip()
        if not text:
            return NLIntent(action="help")

        if self._llm_enabled:
            return _call_tool_use_router(text)

        # LLM disabled — fallback
        return NLIntent(action="help", confidence=0.3)
