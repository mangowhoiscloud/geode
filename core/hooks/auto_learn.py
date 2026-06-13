"""Auto-learn hook — detects user patterns from turn data and persists to profile.

Runs on TURN_COMPLETE. Deterministic regex detectors extract self-introductions,
explicit preferences, language preferences, domain interests, and tool-usage
frequency. Writes directly to FileBasedUserProfile.add_learned_pattern(),
bypassing the WRITE tool gate.

Noise control: min input length, slash-command exclusion, 60s cooldown,
10-pattern-per-session cap, built-in dedup in FileBasedUserProfile.
"""

from __future__ import annotations

import logging
import re
import time
from collections import Counter
from collections.abc import Callable
from typing import Any

from core.hooks.system import HookEvent

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MIN_INPUT_LEN = 15
_COOLDOWN_S = 60.0
_MAX_PER_SESSION = 10
_TOOL_USAGE_THRESHOLD = 5

# ---------------------------------------------------------------------------
# Detectors — each returns (pattern_text, category) or None
# ---------------------------------------------------------------------------

_RE_SELF_INTRO = re.compile(
    r"(?i)\b(i\s+am|i'm|my\s+name\s+is|call\s+me|i\s+work\b|나는|저는|제\s*이름은)",
)

_RE_EXPLICIT_PREF = re.compile(
    r"(?i)\b(i\s+prefer|i\s+like\s+to|always\s+use|don't\s+use|never\s+use"
    r"|i\s+hate|please\s+always|from\s+now\s+on|앞으로|항상)",
)

_RE_LANG_PREF = re.compile(
    r"(?i)(korean|english|japanese|chinese|한국어|영어|일본어|중국어)"
    r"\s*"
    r"(로|으로|in\s+|으로\s*)"
    r"\s*"
    r"(답변|응답|대답|respond|answer|reply|write)",
)

_RE_LANG_PREF_REV = re.compile(
    r"(?i)(답변|응답|대답|respond|answer|reply|write)"
    r".{0,20}"
    r"(in\s+|using\s+)"
    r"(korean|english|japanese|chinese|한국어|영어|일본어|중국어)",
)

_RE_DOMAIN_INTEREST = re.compile(
    r"(?i)\b(interested\s+in|working\s+on|researching|studying"
    r"|focused\s+on|specializ\w+\s+in|관심\s*분야|연구\s*중)",
)

# Validation detector: user confirms a non-obvious approach
# Claude Code pattern: "confirmations are quieter — watch for them"
_RE_VALIDATION = re.compile(
    r"(?i)\b(exactly|perfect|that'?s? (?:right|correct|it)|keep doing"
    r"|good (?:call|approach|choice)|nice|잘했|맞아|좋아|그대로|딱 맞|괜찮)"
    r"(?!.*\b(but|however|except|다만|근데)\b)",
)

# Correction detector: user corrects approach
_RE_CORRECTION = re.compile(
    r"(?i)\b(don'?t|stop doing|not like that|wrong|하지\s*마"
    r"|그렇게\s*말고|아니야|잘못|틀렸)"
    r"(?!.*\bjust\s+kidding\b)",
)


def _detect_self_intro(user_input: str) -> tuple[str, str] | None:
    if _RE_SELF_INTRO.search(user_input):
        return (f"User self-intro: {user_input[:120]}", "preference")
    return None


def _detect_explicit_pref(user_input: str) -> tuple[str, str] | None:
    if _RE_EXPLICIT_PREF.search(user_input):
        return (f"User preference: {user_input[:120]}", "preference")
    return None


def _detect_language_pref(user_input: str) -> tuple[str, str] | None:
    m = _RE_LANG_PREF.search(user_input) or _RE_LANG_PREF_REV.search(user_input)
    if m:
        return (f"Language preference: {user_input[:120]}", "preference")
    return None


def _detect_domain_interest(user_input: str) -> tuple[str, str] | None:
    if _RE_DOMAIN_INTEREST.search(user_input):
        return (f"Domain interest: {user_input[:120]}", "domain")
    return None


def _detect_validation(user_input: str) -> tuple[str, str] | None:
    if _RE_VALIDATION.search(user_input):
        return (f"Validated: {user_input[:120]}", "validation")
    return None


def _detect_correction(user_input: str) -> tuple[str, str] | None:
    if _RE_CORRECTION.search(user_input):
        return (f"Corrected: {user_input[:120]}", "correction")
    return None


_INPUT_DETECTORS: list[Callable[[str], tuple[str, str] | None]] = [
    _detect_language_pref,  # highest priority — short inputs like "한국어로 답변해줘"
    _detect_correction,  # bidirectional: corrections first (stronger signal)
    _detect_validation,  # bidirectional: then validations (quieter signal)
    _detect_self_intro,
    _detect_explicit_pref,
    _detect_domain_interest,
]


def detect_patterns(
    user_input: str,
    tool_calls: list[str],
    tool_counter: Counter[str],
) -> list[tuple[str, str]]:
    """Run all detectors and return matched (pattern_text, category) pairs.

    At most one input-based pattern and one tool-usage pattern per call.
    """
    results: list[tuple[str, str]] = []

    # Input-based detectors (first match wins)
    stripped = user_input.strip()
    if stripped and not stripped.startswith("/"):
        for detector in _INPUT_DETECTORS:
            # Language preference can be short ("한국어로 답변해줘"); others need more context
            min_len = 8 if detector is _detect_language_pref else _MIN_INPUT_LEN
            if len(stripped) < min_len:
                continue
            hit = detector(stripped)
            if hit is not None:
                results.append(hit)
                break  # first match only

    # Tool-usage frequency detector
    tool_counter.update(tool_calls)
    for tool_name, count in tool_counter.items():
        if count == _TOOL_USAGE_THRESHOLD:  # emit exactly once at threshold
            results.append(
                (f"Frequently uses {tool_name}", "tool_usage"),
            )

    return results


# ---------------------------------------------------------------------------
# Hook handler factory
# ---------------------------------------------------------------------------


def make_auto_learn_handler(
    profile_provider: Callable[[], Any] | None = None,
) -> tuple[str, Callable[..., None]]:
    """Create a TURN_COMPLETE handler that auto-learns user patterns.

    Args:
        profile_provider: Callable returning the current user profile.
            Injected at registration to avoid L6→L5 layer violation.
            Falls back to lazy import if not provided (backwards compat).

    Returns (handler_name, handler_fn) for hook registration.
    """
    # Per-session state (resets on process restart).
    #
    # ``last_learn_ts = float("-inf")`` so the first call always passes the
    # cooldown gate, regardless of how recently the process started. The
    # previous init ``0.0`` assumed ``time.monotonic()`` was already past
    # ``_COOLDOWN_S`` — true for long-lived servers, false for short-lived
    # pytest-xdist worker processes that the ``load`` distribution strategy
    # spins up fresh. That mismatch produced flaky failures in
    # ``tests/core/hooks/test_auto_learn.py::TestAutoLearnHandler`` on PR #1220
    # (2026-05-17, same commit, two CI runs — one PASS, one FAIL).
    session_count = 0
    last_learn_ts: float = float("-inf")
    tool_counter: Counter[str] = Counter()

    def _get_profile() -> Any:
        if profile_provider is not None:
            return profile_provider()
        # Fallback for backwards compat (tests that don't inject)
        from core.tools.profile_tools import get_user_profile

        return get_user_profile()

    def _on_turn_complete(event: HookEvent, data: dict[str, Any]) -> None:
        nonlocal session_count, last_learn_ts

        if session_count >= _MAX_PER_SESSION:
            return

        profile = _get_profile()
        if profile is None:
            return

        user_input: str = data.get("user_input", "")
        tool_calls: list[str] = data.get("tool_calls", [])

        patterns = detect_patterns(user_input, tool_calls, tool_counter)
        if not patterns:
            return

        now = time.monotonic()
        if now - last_learn_ts < _COOLDOWN_S:
            return

        # P2: Include conversation context for "Why" reasoning
        assistant_text: str = data.get("text", "")[:200]

        for pattern_text, category in patterns:
            if session_count >= _MAX_PER_SESSION:
                break
            # Append context so future recall includes "why"
            if assistant_text and category in ("validation", "correction"):
                pattern_with_why = f"{pattern_text} [context: {assistant_text[:100]}]"
            else:
                pattern_with_why = pattern_text
            try:
                saved = profile.add_learned_pattern(pattern_with_why, category)
                if saved:
                    session_count += 1
                    last_learn_ts = now
                    log.debug("auto-learn: saved [%s] %s", category, pattern_text[:60])
            except Exception:
                # PR-OBS-CONTRACT — losing a learned pattern is a user-
                # visible feature failure; surface it once at WARNING.
                log.warning("auto-learn: failed to save pattern", exc_info=True)

    return ("turn_auto_learn", _on_turn_complete)
