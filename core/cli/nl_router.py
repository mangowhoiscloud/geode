"""Natural Language Router — Claude Opus 4.6 Tool Use (autonomous).

LLM-autonomous routing via Anthropic Tool Use API:
  - LLM receives user input + tool definitions
  - LLM autonomously decides: call a tool (action) OR respond with text (chat)

Graceful degradation (3-stage):
  1. LLM Tool Use (primary) — full autonomous routing
  2. Offline pattern matching (fallback) — when LLM unavailable
  3. Help with error context — when nothing matches

Tools exposed to LLM (12):
  1. list_ips       — 사용 가능한 IP 목록 표시
  2. analyze_ip     — 특정 IP 분석 실행
  3. search_ips     — 키워드/장르로 IP 검색
  4. compare_ips    — 두 IP 비교 분석
  5. show_help      — 사용법 안내
  6. generate_report — 리포트 생성
  7. batch_analyze  — 배치 분석 (전체/다수 IP 동시)
  8. check_status   — 시스템 상태 확인
  9. switch_model   — 모델/앙상블 모드 변경
  10. memory_search  — 메모리 검색 (인사이트, 규칙, 세션)
  11. memory_save    — 메모리 저장 (세션 + persistent)
  12. manage_rule    — 규칙 생성/수정/삭제/조회

If the LLM responds with text (no tool call) → chat intent.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

import anthropic

from core.config import settings

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
}

LLM_ROUTER_MODEL = "claude-opus-4-6"


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

_SYSTEM_PROMPT_TEMPLATE = """\
You are GEODE, an undervalued IP discovery agent for game publishing.
You help users find, search, and analyze entertainment IPs \
(anime, manga, webtoon, etc.) for potential game adaptation.

{ip_count} IPs are available including: {ip_examples}.

IMPORTANT: When calling analyze_ip or compare_ips, ALWAYS use the \
English title of the IP, even if the user speaks Korean or another language. \
Examples: "고스트 인 더 쉘" → "Ghost in the Shell", "버서크" → "Berserk", \
"카우보이 비밥" → "Cowboy Bebop", "할로우 나이트" → "Hollow Knight".

Routing rules:
- Use tools ONLY for concrete actions (analyze, search, list, compare).
- For general/conversational questions, respond directly with text — do NOT \
call show_help. This includes questions about yourself, your analysis method, \
your role, how you work, or opinions about games/IPs.
- Only call show_help when the user explicitly asks for the command list \
(e.g. "/help", "도움말", "명령어 목록").
- When the user explicitly requests dry-run, no-LLM, or fixture-only mode \
(e.g. "dry-run으로 분석해", "LLM 호출 없이 분석해", "드라이런으로 해줘", \
"without LLM", "fixture 데이터로만"), set dry_run=true in the tool call. \
Otherwise do NOT set dry_run — the system will decide based on API key availability.

Keep direct responses concise (2-4 sentences), in the same language as the user.

You can call multiple tools in sequence to fulfill complex requests. \
For example, "분석하고 비교해줘" can be handled by calling analyze_ip \
followed by compare_ips.

You are knowledgeable about game publishing, IP licensing, \
market analysis, and entertainment media.\
"""

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
# Tool definitions (Anthropic Tool Use format)
# ---------------------------------------------------------------------------

_TOOLS: list[dict[str, Any]] = [
    {
        "name": "list_ips",
        "description": (
            "사용 가능한 IP 목록을 표시합니다. "
            "사용자가 어떤 IP가 있는지 물어볼 때 사용하세요. "
            "Examples: 'IP 목록', '리스트 보여줘', '뭐가 있어?', "
            "'show all', 'list available IPs'"
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "analyze_ip",
        "description": (
            "특정 IP를 분석합니다. "
            "사용자가 IP 이름을 말하거나 분석을 요청할 때 사용하세요. "
            "IP 이름만 단독으로 입력한 경우에도 이 도구를 사용하세요. "
            "사용자가 'dry-run', '드라이런', 'LLM 없이', 'fixture로만' 등을 "
            "명시하면 반드시 dry_run=true로 설정하세요. "
            "Examples: 'Berserk 분석해', 'analyze Cowboy Bebop', "
            "'Berserk', 'Berserk dry-run으로 분석해'"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ip_name": {
                    "type": "string",
                    "description": "IP name in English (e.g. 'Berserk', 'Ghost in the Shell')",
                },
                "dry_run": {
                    "type": "boolean",
                    "description": (
                        "MUST be true when user says: dry-run, 드라이런, "
                        "LLM 없이, LLM 호출 없이, fixture로만, without LLM, "
                        "no-LLM, 간단히. Otherwise omit or set false."
                    ),
                },
            },
            "required": ["ip_name"],
        },
    },
    {
        "name": "search_ips",
        "description": (
            "키워드나 장르로 IP를 검색합니다. "
            "사용자가 특정 장르나 키워드로 IP를 찾을 때 사용하세요. "
            "Examples: '다크 판타지 게임 찾아줘', 'search soulslike', "
            "'SF 장르 있어?', 'find cyberpunk games'"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "검색 키워드 또는 장르 (e.g. 'dark fantasy', '소울라이크')",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "compare_ips",
        "description": (
            "두 IP를 비교 분석합니다. "
            "사용자가 두 IP를 비교하고 싶을 때 사용하세요. "
            "사용자가 'dry-run', '드라이런', 'LLM 없이' 등을 명시하면 dry_run=true. "
            "Examples: 'Berserk vs Cowboy Bebop', "
            "'버서크랑 공각기동대 비교해줘', 'dry-run으로 비교해'"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ip_a": {
                    "type": "string",
                    "description": "첫 번째 IP 이름",
                },
                "ip_b": {
                    "type": "string",
                    "description": "두 번째 IP 이름",
                },
                "dry_run": {
                    "type": "boolean",
                    "description": (
                        "MUST be true when user says: dry-run, 드라이런, "
                        "LLM 없이, LLM 호출 없이, fixture로만, without LLM, "
                        "no-LLM, 간단히. Otherwise omit or set false."
                    ),
                },
            },
            "required": ["ip_a", "ip_b"],
        },
    },
    {
        "name": "show_help",
        "description": (
            "슬래시 명령어 목록을 표시합니다. "
            "사용자가 명령어 목록이나 도움말 메뉴를 명시적으로 요청할 때만 사용하세요. "
            "일반적인 질문(분석 방식, 역할, 의견 등)에는 이 도구를 사용하지 마세요 — "
            "그런 경우 텍스트로 직접 응답하세요. "
            "Examples: '도움말', 'help', '명령어 목록', 'show commands'"
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "generate_report",
        "description": (
            "IP 분석 결과를 리포트로 생성합니다. "
            "사용자가 리포트, 보고서, report 생성을 요청할 때 사용하세요. "
            "사용자가 'dry-run', '드라이런', 'LLM 없이' 등을 명시하면 dry_run=true. "
            "Examples: 'Berserk 리포트 생성해', 'generate a report for Cowboy Bebop', "
            "'보고서 만들어줘', 'dry-run 리포트 생성'"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ip_name": {
                    "type": "string",
                    "description": "IP name in English (e.g. 'Berserk', 'Ghost in the Shell')",
                },
                "dry_run": {
                    "type": "boolean",
                    "description": (
                        "MUST be true when user says: dry-run, 드라이런, "
                        "LLM 없이, LLM 호출 없이, fixture로만, without LLM, "
                        "no-LLM, 간단히. Otherwise omit or set false."
                    ),
                },
            },
            "required": ["ip_name"],
        },
    },
    {
        "name": "batch_analyze",
        "description": (
            "여러 IP를 동시에 배치 분석합니다. "
            "사용자가 전체/다수 IP를 한번에 분석하거나 순위를 보고 싶을 때 사용하세요. "
            "사용자가 'dry-run', '드라이런', 'LLM 없이' 등을 명시하면 dry_run=true. "
            "Examples: '전체 IP 분석해줘', '배치 돌려', 'batch analyze all', "
            "'모든 IP 점수 보여줘', '상위 5개 분석해', 'top 10 dry-run'"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "top": {
                    "type": "integer",
                    "description": "분석할 최대 IP 수 (기본값: 20)",
                },
                "genre": {
                    "type": "string",
                    "description": "장르 필터 (e.g. 'Dark Fantasy', 'Cyberpunk'). 없으면 전체.",
                },
                "stream": {
                    "type": "boolean",
                    "description": "스트리밍 모드 사용 여부 (기본값: false)",
                },
                "dry_run": {
                    "type": "boolean",
                    "description": (
                        "MUST be true when user says: dry-run, 드라이런, "
                        "LLM 없이, LLM 호출 없이, fixture로만, without LLM, "
                        "no-LLM, 간단히. Otherwise omit or set false."
                    ),
                },
            },
            "required": [],
        },
    },
    {
        "name": "check_status",
        "description": (
            "GEODE 시스템 상태를 확인합니다. "
            "사용자가 시스템 상태, 건강 체크, 모델 정보, 설정을 물어볼 때 사용하세요. "
            "Examples: '시스템 상태', 'health check', '지금 모델 뭐야?', "
            "'상태 확인', 'status', '설정 보여줘', 'what model are you using?'"
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "switch_model",
        "description": (
            "LLM 모델이나 앙상블 모드를 변경합니다. "
            "사용자가 모델 변경, 앙상블 모드 전환을 요청할 때 사용하세요. "
            "Examples: '모델 바꿔', 'switch to GPT', '앙상블 모드로', "
            "'cross 모드 켜줘', 'change model', 'use Haiku'"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "model_hint": {
                    "type": "string",
                    "description": (
                        "원하는 모델이나 모드 힌트 (e.g. 'opus', 'haiku', 'gpt', "
                        "'cross', 'ensemble'). 없으면 모델 선택 메뉴 표시."
                    ),
                },
            },
            "required": [],
        },
    },
    # --- Memory Tools (P0-A) ---
    {
        "name": "memory_search",
        "description": (
            "메모리에서 과거 분석 결과, 인사이트, 규칙을 검색합니다. "
            "사용자가 이전 분석 기록이나 학습된 패턴을 물어볼 때 사용하세요. "
            "Examples: '지난번 Berserk 결과 알려줘', '다크판타지 관련 규칙 있어?', "
            "'이전에 분석한 거 뭐 있어?', 'what did we learn about anime IPs?'"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "검색 키워드 (IP 이름, 장르, 패턴 등)",
                },
                "tier": {
                    "type": "string",
                    "enum": ["session", "project", "organization", "all"],
                    "description": "검색할 메모리 계층. 기본값: all",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "memory_save",
        "description": (
            "메모리에 정보를 저장합니다. "
            "사용자가 '이거 기억해', '저장해둬' 같은 요청을 할 때 사용하세요. "
            "Examples: '이 결과 기억해', 'remember this', "
            "'다음에 참고할 수 있게 저장해줘'"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "저장할 데이터의 식별 키 (e.g. 'berserk_insight')",
                },
                "content": {
                    "type": "string",
                    "description": "저장할 내용",
                },
            },
            "required": ["key", "content"],
        },
    },
    {
        "name": "manage_rule",
        "description": (
            "분석 규칙을 생성, 수정, 삭제, 조회합니다. "
            "사용자가 분석 규칙을 관리하거나, 패턴을 학습시키려 할 때 사용하세요. "
            "Examples: '애니메이션 IP 규칙 만들어', '규칙 목록 보여줘', "
            "'anime 규칙 수정해', 'create a rule for dark fantasy IPs', "
            "'delete the old rule', '규칙 삭제해'"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["create", "update", "delete", "list"],
                    "description": "수행할 작업",
                },
                "name": {
                    "type": "string",
                    "description": "규칙 이름 (create/update/delete 시 필수)",
                },
                "paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "규칙이 적용될 IP 패턴 (create 시, e.g. ['*anime*', '*cowboy*'])"
                    ),
                },
                "content": {
                    "type": "string",
                    "description": "규칙 내용 (create/update 시)",
                },
            },
            "required": ["action"],
        },
    },
    # --- Additional Intent Tools ---
    {
        "name": "set_api_key",
        "description": (
            "API 키를 설정합니다. "
            "사용자가 API 키 설정, 변경을 요청할 때 사용하세요. "
            "Examples: 'API 키 설정해', 'set my API key', "
            "'키 바꿔줘', '인증 키 입력'"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "key_value": {
                    "type": "string",
                    "description": "API 키 값 (없으면 현재 상태 표시)",
                },
            },
            "required": [],
        },
    },
    {
        "name": "manage_auth",
        "description": (
            "인증 프로필을 관리합니다. "
            "사용자가 인증, 프로필, 자격증명을 관리하려 할 때 사용하세요. "
            "Examples: '인증 프로필 보여줘', 'show auth profiles', "
            "'인증 추가해', 'manage credentials'"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sub_action": {
                    "type": "string",
                    "description": "수행할 작업 (add, remove, list). 없으면 상태 표시.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "generate_data",
        "description": (
            "테스트/데모용 합성 IP 데이터를 생성합니다. "
            "사용자가 테스트 데이터, 샘플 데이터, 데모 데이터 생성을 요청할 때 사용하세요. "
            "Examples: '테스트 데이터 생성해', 'generate sample data', "
            "'데모 데이터 만들어줘', '합성 IP 생성'"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "count": {
                    "type": "integer",
                    "description": "생성할 IP 수 (기본값: 5, 최대: 20)",
                },
                "genre": {
                    "type": "string",
                    "description": "장르 필터 (e.g. 'mecha', 'dark_fantasy')",
                },
            },
            "required": [],
        },
    },
    {
        "name": "schedule_job",
        "description": (
            "배치 분석 스케줄을 관리합니다. "
            "사용자가 자동 실행, 스케줄, 예약 분석을 요청할 때 사용하세요. "
            "Examples: '매주 월요일 배치 스케줄', 'schedule weekly analysis', "
            "'스케줄 목록 보여줘', '예약 작업 관리'"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sub_action": {
                    "type": "string",
                    "description": "수행할 작업 (list, enable, disable, run). 없으면 목록 표시.",
                },
                "target_id": {
                    "type": "string",
                    "description": "대상 스케줄 ID (enable/disable/run 시)",
                },
            },
            "required": [],
        },
    },
    {
        "name": "trigger_event",
        "description": (
            "이벤트 또는 크론 트리거를 관리하거나 수동 실행합니다. "
            "사용자가 트리거, 이벤트 발생, 수동 실행을 요청할 때 사용하세요. "
            "Examples: 'drift scan 트리거해', 'fire an event', "
            "'트리거 목록 보여줘', '수동으로 이벤트 발생'"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sub_action": {
                    "type": "string",
                    "description": "수행할 작업 (list, fire). 없으면 목록 표시.",
                },
                "event_name": {
                    "type": "string",
                    "description": "발생시킬 이벤트 이름 (fire 시)",
                },
            },
            "required": [],
        },
    },
]

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
