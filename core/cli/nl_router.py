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

import difflib
import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from core.config import settings
from core.llm.client import (
    LLMAuthenticationError,
    LLMBadRequestError,
    get_anthropic_client,
)
from core.llm.prompts import ROUTER_SYSTEM

if TYPE_CHECKING:
    from core.cli.conversation import ConversationContext
    from core.tools.registry import ToolRegistry

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Intent data model
# ---------------------------------------------------------------------------

_STATIC_VALID_ACTIONS = {
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
    "decompose",  # compound goal decomposition
}

# Backward-compatible alias
VALID_ACTIONS = _STATIC_VALID_ACTIONS


def get_valid_actions(registry: ToolRegistry | None = None) -> set[str]:
    """Static actions + dynamic from ToolRegistry."""
    actions = set(_STATIC_VALID_ACTIONS)
    if registry:
        for tool_name in registry.list_tools():
            action = _TOOL_ACTION_MAP.get(tool_name, tool_name)
            actions.add(action)
    return actions


LLM_ROUTER_MODEL = settings.router_model


@dataclass
class NLIntent:
    """Classified intent from natural language input."""

    action: str  # analyze, search, list, help, compare, chat
    args: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0  # 1.0 = exact match, <1.0 = fuzzy
    ambiguous: bool = False
    alternatives: list[NLIntent] | None = None


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
    "schedule_job": {
        "sub_action": "sub_action",
        "target_id": "target_id",
        "expression": "expression",
    },
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
_OFFLINE_BATCH = re.compile(
    r"(?:배치|전체\s*(?:ip\s*)?분석|모든\s*(?:ip\s*)?분석|순위|rank|batch|all\s*ip|top\s*\d+)",
    re.IGNORECASE,
)
_OFFLINE_STATUS = re.compile(
    r"(?:상태|건강|health|status|설정|config|모델\s*뭐|mcp\s*(?:리스트|목록|상태|서버|연결|list|server|status))",
    re.IGNORECASE,
)
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


def _fuzzy_match_ip(text: str, cutoff: float = 0.7) -> str | None:
    """Fuzzy-match user input against known IP names."""
    known = list(_get_known_ips())
    lower = text.lower()

    # 1. Exact substring (existing behavior)
    for ip in known:
        if ip in lower:
            return ip

    # 2. Fuzzy: n-gram phrases against known IPs
    words = lower.split()
    for n in range(min(len(words), 4), 0, -1):
        for i in range(len(words) - n + 1):
            phrase = " ".join(words[i : i + n])
            matches = difflib.get_close_matches(phrase, known, n=1, cutoff=cutoff)
            if matches:
                return matches[0]

    return None


_COMPOUND_SPLITTERS = re.compile(r"(?:\s+(?:그리고|and|then|다음에|후에)\s+|하고\s+|\s*[,;]\s*)")


def _offline_multi_intent(text: str, *, error: str = "") -> list[NLIntent]:
    """Split compound input into multiple intents for offline mode."""
    parts = _COMPOUND_SPLITTERS.split(text)
    parts = [p.strip() for p in parts if p.strip()]

    if len(parts) <= 1:
        return []

    intents = []
    for part in parts:
        intent = _offline_fallback(part, error=error)
        if intent.action != "help":
            intents.append(intent)

    return intents if len(intents) > 1 else []


# ---------------------------------------------------------------------------
# Args builders for scored matching
# ---------------------------------------------------------------------------


def _args_compare(text: str, error: str) -> dict[str, Any]:
    return {"_offline": True, "_error": error}


def _args_delegate(text: str, error: str) -> dict[str, Any]:
    return {"_offline": True, "_error": error}


def _args_ip_name(text: str, error: str) -> dict[str, Any]:
    return {"ip_name": text.strip(), "_error": error}


def _args_query(text: str, error: str) -> dict[str, Any]:
    return {"query": text.strip(), "_error": error}


def _args_error_only(_text: str, error: str) -> dict[str, Any]:
    return {"_error": error}


# ---------------------------------------------------------------------------
# Offline pattern registry — scored matching (Phase 4C)
# ---------------------------------------------------------------------------


@dataclass
class _OfflinePattern:
    """Single offline pattern with priority for scored matching."""

    action: str
    regex: re.Pattern[str]
    confidence: float
    priority: int  # lower = higher priority (tie-breaker)
    args_builder: Callable[[str, str], dict[str, Any]]


_OFFLINE_PATTERNS: list[_OfflinePattern] = [
    _OfflinePattern("compare", _OFFLINE_COMPARE, 0.8, 1, _args_compare),
    _OfflinePattern("report", _OFFLINE_REPORT, 0.7, 2, _args_ip_name),
    _OfflinePattern("plan", _OFFLINE_PLAN, 0.7, 3, _args_ip_name),
    _OfflinePattern("delegate", _OFFLINE_DELEGATE, 0.5, 4, _args_delegate),
    _OfflinePattern("list", _OFFLINE_LIST, 0.7, 5, _args_error_only),
    _OfflinePattern("batch", _OFFLINE_BATCH, 0.7, 6, _args_error_only),
    _OfflinePattern("status", _OFFLINE_STATUS, 0.7, 7, _args_error_only),
    _OfflinePattern("model", _OFFLINE_MODEL, 0.7, 8, _args_error_only),
    _OfflinePattern("memory", _OFFLINE_MEMORY, 0.7, 9, _args_query),
    _OfflinePattern("help", _OFFLINE_HELP, 1.0, 10, _args_error_only),
    _OfflinePattern("analyze", _OFFLINE_ANALYZE, 0.7, 11, _args_ip_name),
    _OfflinePattern("search", _OFFLINE_SEARCH, 0.7, 12, _args_query),
]


def _offline_fallback(text: str, *, error: str = "") -> NLIntent:
    """Scored pattern matching when LLM is unavailable.

    Uses a pattern registry with priority-based scoring:
    1. Known IP exact match → analyze (bypasses scored matching)
    2. All regex patterns evaluated → collect matches
    3. Single match → return directly
    4. Multiple matches → best by priority + ambiguous=True with alternatives
    5. No match → fuzzy IP → help fallback
    """
    lower = text.lower().strip()

    # Phase 1: High-specificity patterns first (compare, report, plan, delegate)
    # These override known IP because "Berserk vs X" = compare, not analyze.
    _HIGH_PRIORITY_ACTIONS = {"compare", "report", "plan", "delegate"}
    for pat in _OFFLINE_PATTERNS:
        if pat.action in _HIGH_PRIORITY_ACTIONS and pat.regex.search(lower):
            return NLIntent(
                action=pat.action,
                args=pat.args_builder(text, error),
                confidence=pat.confidence,
            )

    # Phase 2: Known IP exact match — before scored matching
    for ip in _get_known_ips():
        if ip in lower:
            name_map = get_ip_name_map()
            canonical = name_map.get(ip, ip)
            return NLIntent(
                action="analyze",
                args={"ip_name": canonical, "_error": error},
                confidence=0.7,
            )

    # Phase 3: Scored matching — evaluate remaining patterns
    matched: list[_OfflinePattern] = [
        pat
        for pat in _OFFLINE_PATTERNS
        if pat.action not in _HIGH_PRIORITY_ACTIONS and pat.regex.search(lower)
    ]

    if matched:
        matched.sort(key=lambda p: p.priority)
        best = matched[0]

        if len(matched) == 1:
            return NLIntent(
                action=best.action,
                args=best.args_builder(text, error),
                confidence=best.confidence,
            )

        # Multiple matches → ambiguous
        alternatives = [
            NLIntent(
                action=p.action,
                args=p.args_builder(text, error),
                confidence=p.confidence,
            )
            for p in matched[1:4]  # up to 3 alternatives
        ]
        return NLIntent(
            action=best.action,
            args=best.args_builder(text, error),
            confidence=best.confidence,
            ambiguous=True,
            alternatives=alternatives,
        )

    # Phase 4: Fuzzy IP name matching
    ip_match = _fuzzy_match_ip(lower)
    if ip_match:
        name_map = get_ip_name_map()
        canonical = name_map.get(ip_match, ip_match)
        return NLIntent(
            action="analyze",
            args={"ip_name": canonical, "_error": error},
            confidence=0.5,
        )

    # Phase 5: Nothing matched — help with error context
    return NLIntent(action="help", args={"_error": error}, confidence=0.3)


# ---------------------------------------------------------------------------
# LLM Tool Use call
# ---------------------------------------------------------------------------


def _call_tool_use_router(
    text: str,
    *,
    context: ConversationContext | None = None,
) -> NLIntent:
    """Route user input via Claude Opus 4.6 Tool Use.

    The LLM sees tool definitions and autonomously decides:
    - Call a tool → mapped to NLIntent action
    - Respond with text → chat intent
    """
    try:
        if not settings.anthropic_api_key:
            log.debug("No Anthropic API key — LLM router unavailable")
            return _offline_fallback(text, error="no_api_key")

        client = get_anthropic_client()

        # Build messages with conversation history for context-aware routing
        if context is not None and not context.is_empty:
            recent = context.get_messages()[-6:]  # last 3 turns
            # Ensure first message is user role
            while recent and recent[0]["role"] != "user":
                recent.pop(0)
            # Append current input if not already last
            if not recent or recent[-1].get("content") != text:
                recent.append({"role": "user", "content": text})
            messages: list[dict[str, Any]] = recent
        else:
            messages = [{"role": "user", "content": text}]

        response = client.messages.create(  # type: ignore[call-overload]
            model=LLM_ROUTER_MODEL,
            system=_build_system_prompt(),
            messages=messages,
            tools=_TOOLS,
            tool_choice={"type": "auto"},
            max_tokens=1024,
            temperature=0.0,
            timeout=15.0,
        )

        # Track token usage
        if response.usage:
            from core.llm.token_tracker import get_tracker

            in_tok = response.usage.input_tokens
            out_tok = response.usage.output_tokens
            usage = get_tracker().record(LLM_ROUTER_MODEL, in_tok, out_tok)
            log.debug(
                "NLRouter tool_use: model=%s in=%d out=%d cost=$%.6f",
                LLM_ROUTER_MODEL,
                in_tok,
                out_tok,
                usage.cost_usd,
            )

        # Parse response: tool_use or text
        if response.stop_reason == "tool_use":
            return _parse_tool_use(response)

        # Text-only response → chat
        return _parse_text_response(response)

    except LLMAuthenticationError:
        log.warning("Anthropic API key is invalid or expired")
        return _offline_fallback(text, error="auth_error")

    except LLMBadRequestError as exc:
        error_msg = str(exc)
        if "credit balance" in error_msg.lower() or "billing" in error_msg.lower():
            log.warning("Anthropic API credit balance too low")
            return _offline_fallback(text, error="billing")
        log.warning("Anthropic BadRequest: %s", error_msg)
        return _offline_fallback(text, error="api_error")

    except Exception:
        log.warning("NLRouter Tool Use call failed", exc_info=True)
        return _offline_fallback(text, error="api_error")


def _parse_tool_use(response: Any) -> NLIntent:
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


def _parse_text_response(response: Any) -> NLIntent:
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

    def classify(
        self,
        text: str,
        *,
        context: ConversationContext | None = None,
    ) -> NLIntent:
        """Classify user input via LLM Tool Use."""
        text = text.strip()
        if not text:
            return NLIntent(action="help")

        if self._llm_enabled:
            return _call_tool_use_router(text, context=context)

        # LLM disabled — fallback
        return NLIntent(action="help", confidence=0.3)
