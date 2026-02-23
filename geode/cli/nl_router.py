"""Natural Language Router — OpenClaw Binding pattern for free-form input.

Classifies user intent from natural language text and routes to the
appropriate handler. Works without LLM (keyword-based matching).

Intent hierarchy (most-specific wins, like OpenClaw Binding priority):
  1. search  — genre/keyword queries ("다크 판타지 게임 찾아줘")
  2. compare — comparison queries ("Berserk vs Cowboy Bebop")
  3. analyze — explicit analysis request ("Berserk 분석해")
  4. list    — list request ("IP 목록", "뭐가 있어?")
  5. help    — help request ("도움", "어떻게 써?")
  6. default — treat as IP name (direct analyze)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class NLIntent:
    """Classified intent from natural language input."""

    action: str  # analyze, search, list, help, compare
    args: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0  # 1.0 = exact match, <1.0 = fuzzy


# ---------------------------------------------------------------------------
# Pattern bindings (OpenClaw: most-specific wins)
# ---------------------------------------------------------------------------

_SEARCH_PATTERNS: list[re.Pattern[str]] = [
    # Korean search patterns
    re.compile(r"(?P<query>.+?)\s*(?:찾아줘|검색|찾아|찾기|서치)", re.IGNORECASE),
    re.compile(r"(?:어떤|무슨)\s*(?:게임|IP|아이피).*?(?P<query>.+)", re.IGNORECASE),
    re.compile(r"(?P<query>.+?)\s*(?:장르|종류|타입).*?(?:있|뭐|알려)", re.IGNORECASE),
    re.compile(r"(?P<query>.+?)\s*(?:게임|IP|아이피)\s*(?:있|뭐|알려|추천)", re.IGNORECASE),
    # English search patterns
    re.compile(r"(?:search|find|look\s*for|show me)\s+(?P<query>.+)", re.IGNORECASE),
    re.compile(
        r"(?:what|which)\s+(?:games?|IPs?)\s+(?:are|have|match)\s+(?P<query>.+)", re.IGNORECASE
    ),
]

_COMPARE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(?P<ip_a>.+?)\s*(?:vs\.?|versus|대|비교)\s*(?P<ip_b>.+)", re.IGNORECASE),
    re.compile(r"(?P<ip_a>.+?)(?:하고|랑|와|과)\s*(?P<ip_b>.+?)\s*비교", re.IGNORECASE),
]

_ANALYZE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(?P<ip_name>.+?)\s*(?:분석해|분석|평가해|평가|돌려)", re.IGNORECASE),
    re.compile(r"(?:analyze|evaluate|assess|run)\s+(?P<ip_name>.+)", re.IGNORECASE),
]

_LIST_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(?:IP|아이피|게임)\s*(?:목록|리스트|list)", re.IGNORECASE),
    re.compile(r"(?:뭐가|뭐)\s*있", re.IGNORECASE),
    re.compile(r"(?:list|show)\s*(?:all|ips|games)?$", re.IGNORECASE),
]

_HELP_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^(?:도움|도움말|help|어떻게|사용법)$", re.IGNORECASE),
    re.compile(r"(?:어떻게|how)\s*(?:써|쓰|use)", re.IGNORECASE),
]

# Genre/keyword vocabulary for search intent detection
_GENRE_KEYWORDS: set[str] = {
    # English
    "action",
    "rpg",
    "souls",
    "soulslike",
    "souls-like",
    "cyberpunk",
    "stealth",
    "noir",
    "sci-fi",
    "scifi",
    "fantasy",
    "dark fantasy",
    "horror",
    "adventure",
    "shooter",
    "mmo",
    "mmorpg",
    "fighting",
    "platformer",
    # Korean
    "액션",
    "소울라이크",
    "소울",
    "사이버펑크",
    "스텔스",
    "느와르",
    "SF",
    "판타지",
    "다크",
    "호러",
    "어드벤처",
    "슈터",
    "격투",
    "플랫포머",
    "RPG",
    "알피지",
    # Specific to GEODE IPs
    "바운티",
    "헌터",
    "bounty",
    "hunter",
    "해킹",
    "hacking",
    "드래곤슬레이어",
    "dragonslayer",
    "우주",
    "space",
    "로봇",
    "robot",
    "mecha",
    "메카",
    "검",
    "sword",
    "대검",
    "greatsword",
}


class NLRouter:
    """OpenClaw-inspired Binding Router for natural language input.

    Routes free-form text to intents using pattern matching.
    Most-specific binding wins (like OpenClaw's peer > guildId > channel).
    """

    def classify(self, text: str) -> NLIntent:
        """Classify natural language text into an intent."""
        text = text.strip()
        if not text:
            return NLIntent(action="help")

        # Priority 1: Search patterns (most specific)
        for pattern in _SEARCH_PATTERNS:
            m = pattern.match(text)
            if m:
                query = m.group("query").strip()
                if query:
                    return NLIntent(action="search", args={"query": query})

        # Priority 2: Compare patterns
        for pattern in _COMPARE_PATTERNS:
            m = pattern.match(text)
            if m:
                return NLIntent(
                    action="compare",
                    args={
                        "ip_a": m.group("ip_a").strip(),
                        "ip_b": m.group("ip_b").strip(),
                    },
                )

        # Priority 3: Analyze patterns (explicit)
        for pattern in _ANALYZE_PATTERNS:
            m = pattern.match(text)
            if m:
                return NLIntent(action="analyze", args={"ip_name": m.group("ip_name").strip()})

        # Priority 4: List patterns
        for pattern in _LIST_PATTERNS:
            if pattern.match(text):
                return NLIntent(action="list")

        # Priority 5: Help patterns
        for pattern in _HELP_PATTERNS:
            if pattern.match(text):
                return NLIntent(action="help")

        # Priority 6: Genre keyword detection → search
        words = set(re.split(r"\s+", text.lower()))
        if words & _GENRE_KEYWORDS:
            return NLIntent(action="search", args={"query": text}, confidence=0.8)

        # Default: treat as IP name → analyze
        return NLIntent(action="analyze", args={"ip_name": text}, confidence=0.6)
