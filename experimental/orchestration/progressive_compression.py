"""Progressive Context Compression — 3-zone graduated compression.

Divides conversation history into three zones by recency:
- Zone A (Recent 20%): Verbatim — no compression
- Zone B (Middle 60%): LLM-summarized (groups of 3-5 messages → ~200 tokens)
- Zone C (Oldest 20%): Archived to filesystem, replaced with marker

Triggered at 60% context usage (before WARNING at 80%), converting
quadratic token cost to linear.

OpenHands pattern (2025.11): 50%+ API cost reduction with linear scaling.
"""

from __future__ import annotations

import json
import logging
import time
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from core.utils.atomic_io import atomic_write_json

log = logging.getLogger(__name__)

# ContextVar DI
_compressor_ctx: ContextVar[ProgressiveCompressor | None] = ContextVar(
    "progressive_compressor", default=None
)


def set_compressor(compressor: ProgressiveCompressor | None) -> None:
    """Inject the progressive compressor into the current context."""
    _compressor_ctx.set(compressor)


def get_compressor() -> ProgressiveCompressor | None:
    """Retrieve the progressive compressor from the current context."""
    return _compressor_ctx.get()


# Group summarization prompt (Haiku-optimized: concise, factual)
_GROUP_SUMMARY_PROMPT = (
    "Summarize this conversation segment concisely, preserving:\n"
    "1. Tools called and their key results\n"
    "2. Decisions made\n"
    "3. Errors encountered\n"
    "4. Data references (file paths, URLs, IDs)\n"
    "Format: 2-3 bullet points. Max 200 tokens."
)


class ProgressiveCompressor:
    """3-zone context compression: verbatim / summarized / archived.

    Zone boundaries are computed as percentages of the total message count.
    Compression is applied in-place when context usage crosses the trigger
    threshold (default 60%).
    """

    def __init__(
        self,
        *,
        session_id: str = "",
        recent_pct: float = 0.20,
        middle_pct: float = 0.60,
        archive_dir: Path | None = None,
        group_size: int = 4,
    ) -> None:
        self._session_id = session_id
        self._recent_pct = recent_pct
        self._middle_pct = middle_pct
        self._archive_dir = archive_dir or Path(".geode/progressive-archive")
        self._session_dir = self._archive_dir / session_id if session_id else self._archive_dir
        self._group_size = group_size
        self._archive_counter = 0
        self._already_compressed = False

    def compress(
        self,
        messages: list[dict[str, Any]],
        provider: str,
    ) -> list[dict[str, Any]]:
        """Apply 3-zone compression.  Returns new message list.

        Does NOT mutate the input list.  The caller should replace
        their messages with the returned list.

        Zone B summarization uses a synchronous LLM call (budget model).
        If the LLM call fails, Zone B messages are kept verbatim.
        """
        n = len(messages)
        if n < 8:
            return list(messages)  # too few to compress

        # Compute zone boundaries
        zone_c_end = max(1, int(n * (1.0 - self._recent_pct - self._middle_pct)))
        zone_b_end = max(zone_c_end + 1, int(n * (1.0 - self._recent_pct)))

        zone_c = messages[:zone_c_end]
        zone_b = messages[zone_c_end:zone_b_end]
        zone_a = messages[zone_b_end:]

        result: list[dict[str, Any]] = []

        # Zone C: archive to disk
        if zone_c:
            archive_ref = self._archive_messages(zone_c)
            from core.orchestration.context_monitor import estimate_message_tokens

            archived_tokens = estimate_message_tokens(zone_c)
            result.append({
                "role": "user",
                "content": (
                    f"[Archived: {len(zone_c)} messages, ~{archived_tokens:,} tokens. "
                    f"ref={archive_ref}]"
                ),
            })
            result.append({
                "role": "assistant",
                "content": [{"type": "text", "text": "(acknowledged archived context)"}],
            })

        # Zone B: summarize in groups
        if zone_b:
            summaries = self._summarize_zone_b(zone_b, provider)
            if summaries:
                for summary in summaries:
                    result.append({
                        "role": "user",
                        "content": f"[Summary of earlier rounds]\n{summary}",
                    })
                    result.append({
                        "role": "assistant",
                        "content": [{"type": "text", "text": "(acknowledged summary)"}],
                    })
            else:
                # Summarization failed — fall back to keeping verbatim
                result.extend(zone_b)

        # Zone A: verbatim
        result.extend(zone_a)

        self._already_compressed = True
        log.info(
            "Progressive compression: %d → %d messages "
            "(archived=%d, summarized=%d, verbatim=%d)",
            n, len(result), len(zone_c), len(zone_b), len(zone_a),
        )
        return result

    @property
    def already_compressed(self) -> bool:
        """Whether compression has already been applied in this session."""
        return self._already_compressed

    def recall_archived(self, archive_ref: str) -> dict[str, Any]:
        """Retrieve archived messages by reference."""
        path = self._session_dir / f"{archive_ref}.json"
        if not path.exists():
            return {"error": f"Archive not found: {archive_ref}"}
        try:
            data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
            return data
        except (json.JSONDecodeError, OSError) as exc:
            return {"error": f"Failed to read archive {archive_ref}: {exc}"}

    def cleanup(self) -> int:
        """Remove all archive files for this session."""
        if not self._session_dir.exists():
            return 0
        removed = 0
        for path in self._session_dir.glob("*.json"):
            path.unlink(missing_ok=True)
            removed += 1
        if self._session_dir.exists() and not any(self._session_dir.iterdir()):
            self._session_dir.rmdir()
        return removed

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _archive_messages(self, messages: list[dict[str, Any]]) -> str:
        """Persist messages to disk, return archive reference."""
        self._session_dir.mkdir(parents=True, exist_ok=True)
        ref = f"archive_{self._archive_counter}"
        self._archive_counter += 1
        payload = {
            "ref": ref,
            "message_count": len(messages),
            "messages": messages,
            "archived_at": time.time(),
        }
        atomic_write_json(self._session_dir / f"{ref}.json", payload, indent=None)
        log.debug("Archived %d messages as %s", len(messages), ref)
        return ref

    def _summarize_zone_b(
        self,
        messages: list[dict[str, Any]],
        provider: str,
    ) -> list[str]:
        """Summarize Zone B messages in groups.

        Returns a list of summary strings (one per group).
        Uses synchronous LLM calls with budget model.
        """
        from core.orchestration.compaction import _build_summary_input

        groups = self._split_into_groups(messages)
        summaries: list[str] = []

        for group in groups:
            text = _build_summary_input(group)
            if not text.strip():
                continue
            summary = self._call_budget_summarize(text, provider)
            if summary:
                summaries.append(summary)
            else:
                # Fall back to a simple extraction
                summary = self._extract_summary_fallback(group)
                if summary:
                    summaries.append(summary)

        return summaries

    def _split_into_groups(
        self, messages: list[dict[str, Any]]
    ) -> list[list[dict[str, Any]]]:
        """Split messages into groups of self._group_size."""
        groups: list[list[dict[str, Any]]] = []
        for i in range(0, len(messages), self._group_size):
            groups.append(messages[i : i + self._group_size])
        return groups

    def _call_budget_summarize(self, text: str, provider: str) -> str | None:
        """Call budget LLM for summarization (sync)."""
        try:
            if provider == "anthropic":
                return self._summarize_anthropic(text)
            elif provider == "openai":
                return self._summarize_openai(text)
            else:
                return None
        except Exception:
            log.debug("Budget summarization failed", exc_info=True)
            return None

    def _summarize_anthropic(self, text: str) -> str | None:
        """Summarize using Anthropic Haiku (cheapest)."""
        try:
            from anthropic import Anthropic

            client = Anthropic()
            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=256,
                messages=[{"role": "user", "content": f"{_GROUP_SUMMARY_PROMPT}\n\n{text}"}],
            )
            if response.content and response.content[0].type == "text":
                return response.content[0].text
        except Exception:
            log.debug("Anthropic budget summarization failed", exc_info=True)
        return None

    def _summarize_openai(self, text: str) -> str | None:
        """Summarize using OpenAI budget model."""
        try:
            from core.llm.providers.openai import _get_openai_client

            client = _get_openai_client()
            if client is None:
                return None
            response = client.chat.completions.create(
                model="gpt-4.1-mini",
                messages=[
                    {"role": "system", "content": _GROUP_SUMMARY_PROMPT},
                    {"role": "user", "content": text},
                ],
                max_tokens=256,
                temperature=0.0,
            )
            choice = response.choices[0] if response.choices else None
            if choice and choice.message and choice.message.content:
                content: str = choice.message.content
                return content
        except Exception:
            log.debug("OpenAI budget summarization failed", exc_info=True)
        return None

    def _extract_summary_fallback(self, messages: list[dict[str, Any]]) -> str | None:
        """Extract a simple summary without LLM (last resort)."""
        parts: list[str] = []
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if isinstance(content, str):
                text = content[:100]
            elif isinstance(content, list):
                texts = []
                for block in content:
                    if isinstance(block, dict):
                        t = block.get("text", "") or ""
                        name = block.get("name", "")
                        if name:
                            texts.append(f"tool:{name}")
                        elif t:
                            texts.append(t[:50])
                text = ", ".join(texts)[:100]
            else:
                text = str(content)[:100]
            if text.strip():
                parts.append(f"{role}: {text}")
        if not parts:
            return None
        return "[Fallback summary] " + " | ".join(parts[:5])
