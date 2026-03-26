"""Language detection utility — deterministic, Unicode-range based.

No LLM calls. Used to set output_language in pipeline state so that
analyst / synthesizer prompts respond in the user's language.
"""

from __future__ import annotations


def detect_language(text: str) -> str:
    """Detect the dominant language of *text* from Unicode character ranges.

    Returns a human-readable language name suitable for injection into LLM
    prompts (e.g. "Korean", "Japanese", "Chinese", "English").

    Decision order: Korean > Japanese kana > CJK (Chinese) > English (default).
    A single Korean/Japanese character is sufficient; CJK requires 4+ chars
    to avoid false-positives from mixed-script titles.
    """
    korean = sum(
        1
        for c in text
        if "\uac00" <= c <= "\ud7a3"  # Hangul syllables
        or "\u3131" <= c <= "\u314e"  # Hangul compatibility jamo
    )
    japanese_kana = sum(
        1
        for c in text
        if "\u3040" <= c <= "\u309f"  # Hiragana
        or "\u30a0" <= c <= "\u30ff"  # Katakana
    )
    cjk = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")

    if korean > 0:
        return "Korean"
    if japanese_kana > 0:
        return "Japanese"
    if cjk >= 4:
        return "Chinese"
    return "English"
