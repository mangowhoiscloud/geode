"""DPO pack PII + secret redaction — ADR-012 M4.3.

The M4.1 canonical pack (``~/.geode/self-improving-loop/dpo/pack.jsonl``)
ships user prompts + assistant responses *verbatim*. Before that data
crosses the operator-machine boundary (M4.2 publish to OpenAI / Bedrock
/ HuggingFace, or shared with teammates), it must be scrubbed of
**operator-private** content:

* API keys — Anthropic / OpenAI / GitHub / Slack / ZhipuAI (re-uses
  ``core.utils.redaction._SECRET_PATTERNS``, the same patterns used for
  shell tool output sanitisation, so we stay consistent across the
  codebase).
* Bearer tokens — ``Authorization: Bearer <opaque>`` headers that LLM
  agents sometimes echo into completions.
* AWS access keys — ``AKIA…`` / ``ASIA…`` prefixes.
* Email addresses — RFC-light pattern.
* Phone numbers — E.164 / dashed / parenthesised variants, 8+ digits.
* URL credentials — ``https://user:password@host`` form.
* POSIX home paths — ``/Users/<name>/`` and ``/home/<name>/`` (collapsed
  to a placeholder so the user's local layout doesn't leak).

Redaction is **per-row, per-field**: only the textual fields (``prompt``,
``chosen``, ``rejected``, ``source_chosen``, ``source_rejected``) are
scrubbed. Numeric fields (``fitness_*``, ``ts_*``) and the row signature
are untouched — they carry no PII but are essential for audit + dedup
downstream.

The redaction is *idempotent and lossy*. We never store the original
text; the redacted pack is a separate file (M4.2's publisher consumes
either the raw or the redacted pack, operator's choice).
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from core.utils.redaction import redact_secrets

log = logging.getLogger(__name__)

__all__ = [
    "PII_PATTERNS",
    "redact_pack",
    "redact_pack_row",
    "redact_text",
]

# PII patterns ordered most-specific-first so an email isn't partially
# eaten by a phone-number regex etc. Each entry is ``(pattern, placeholder)``.
PII_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # URL credentials FIRST so they aren't shredded by the email pattern.
    (
        re.compile(r"\b(https?|ftp)://[^/:\s]+:[^@/\s]+@", re.IGNORECASE),
        r"\1://[REDACTED:url_credentials]@",
    ),
    # AWS access keys — distinct prefix + fixed length.
    (re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b"), "[REDACTED:aws_key]"),
    # Bearer tokens — caller convention ``Authorization: Bearer …``.
    (
        re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{16,}\b"),
        "Bearer [REDACTED:bearer]",
    ),
    # Email — single-pass; RFC-light but practical.
    (
        re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"),
        "[REDACTED:email]",
    ),
    # POSIX user home paths (macOS + Linux). Capture group keeps the
    # trailing slash so ``/Users/x/foo`` → ``[REDACTED:home]/foo``.
    (
        re.compile(r"(/Users/|/home/)[A-Za-z0-9_.\-]+/"),
        "[REDACTED:home]/",
    ),
    # Phone numbers — leading optional ``+``, 10-15 digits with common
    # separators. Required digit-density check avoids matching arbitrary
    # numeric strings. We require at least 9 digits in total.
    (
        re.compile(
            r"(?<![\w])"  # not preceded by a word char
            r"\+?\d[\d\-\s().]{8,17}\d"
            r"(?![\w])"  # not followed by a word char
        ),
        "[REDACTED:phone]",
    ),
]


def redact_text(text: str) -> str:
    """Scrub secrets + PII from ``text``.

    Composition order: API-key patterns first (re-using
    ``core.utils.redaction``), then DPO-specific PII patterns. Returning
    the original string unchanged when nothing matches is a deliberate
    contract — callers can chain without paying a copy.
    """
    if not text:
        return text
    cleaned = redact_secrets(text, placeholder="[REDACTED:secret]")
    for pattern, placeholder in PII_PATTERNS:
        cleaned = pattern.sub(placeholder, cleaned)
    return cleaned


_TEXT_FIELDS = ("prompt", "chosen", "rejected", "source_chosen", "source_rejected")


def redact_pack_row(row: dict[str, Any]) -> dict[str, Any]:
    """Return a new pack-row dict with all text fields redacted.

    Numeric fields, signature, timestamps, and session ids are passed
    through unchanged — they carry no PII and are needed for audit /
    dedup. Missing text fields are tolerated (graceful for partial rows
    that may appear during M4.1 → M4.3 migration).
    """
    cleaned: dict[str, Any] = dict(row)
    for field in _TEXT_FIELDS:
        value = cleaned.get(field)
        if isinstance(value, str):
            cleaned[field] = redact_text(value)
    return cleaned


def redact_pack(src_pack_path: Path, dst_pack_path: Path) -> int:
    """Read every row from ``src``, scrub, write to ``dst``. Returns row count.

    Both inputs and outputs are JSONL. The destination is OVERWRITTEN —
    re-running over the same input produces a byte-equal output (the
    redaction patterns are deterministic). Malformed input lines are
    silently dropped (per-line graceful — one bad row should not block
    the rest of the pack from being redacted).
    """
    if not src_pack_path.is_file():
        dst_pack_path.parent.mkdir(parents=True, exist_ok=True)
        dst_pack_path.write_text("", encoding="utf-8")
        return 0
    try:
        text = src_pack_path.read_text(encoding="utf-8")
    except OSError as exc:
        log.warning("dpo_redaction: failed to read pack %s: %s", src_pack_path, exc)
        return 0
    dst_pack_path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with dst_pack_path.open("w", encoding="utf-8") as fh:
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            scrubbed = redact_pack_row(row)
            fh.write(json.dumps(scrubbed, ensure_ascii=False) + "\n")
            written += 1
    return written
