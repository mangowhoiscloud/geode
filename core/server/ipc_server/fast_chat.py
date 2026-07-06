"""Lightweight IPC fast-chat routing for simple conversational turns."""

from __future__ import annotations

import os
import re

_QUESTION_HINT_RE = re.compile(
    r"(뭐|무엇|누구|언제|어디|왜|어떻게|설명|소개|요약|번역|정의|meaning|what|who|when|where|why|how|explain|summari[sz]e|translate)",
    re.I,
)

_AGENTIC_VERB_RE = re.compile(
    r"(수정|고쳐|구현|만들|작성|실행|검색|찾아|조사|분석|파일|코드|테스트|커밋|빌드|설치|열어|클릭|캡처|계획.*진행|진행해|run|edit|fix|implement|create|write|search|find|analy[sz]e|file|code|test|commit|build|install|open|click|capture)",
    re.I,
)

_FAST_CHAT_SYSTEM = (
    "GEODE lightweight chat path. Identity: GEODE, a self-hosting autonomous "
    "agent harness built around an AgenticLoop. Answer directly and briefly. "
    "When asked for self-introduction, speak as GEODE, not as a generic API "
    "assistant or generic chatbot. "
    "Do not claim file inspection, tool execution, browsing, or local-state changes. "
    "For actions, planning, roadmaps, tools, code edits, research, or execution, "
    "say that the full agent path is required."
)


def fast_chat_enabled() -> bool:
    return os.environ.get("GEODE_FAST_CHAT", "0").lower() in {"1", "true", "on"}


def should_use_fast_chat(text: str) -> bool:
    """Return True for short non-action prompts that do not need GEODE's loop."""
    if not fast_chat_enabled():
        return False
    stripped = text.strip()
    if not stripped or "\n" in stripped:
        return False
    if len(stripped) > 160:
        return False
    if stripped.startswith(("/", "@", "!")):
        return False
    if _AGENTIC_VERB_RE.search(stripped):
        return False
    return bool(_QUESTION_HINT_RE.search(stripped)) or len(stripped) <= 40


def fast_chat_system_prompt() -> str:
    return _FAST_CHAT_SYSTEM


__all__ = ["fast_chat_enabled", "fast_chat_system_prompt", "should_use_fast_chat"]
