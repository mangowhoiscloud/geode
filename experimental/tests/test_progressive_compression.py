"""Tests for P1 progressive context compression."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from experimental.orchestration.progressive_compression import (
    ProgressiveCompressor,
    get_compressor,
    set_compressor,
)


def _make_messages(n: int, content_size: int = 200) -> list[dict[str, Any]]:
    """Create n pairs of user→assistant messages."""
    messages: list[dict[str, Any]] = []
    for i in range(n):
        messages.append({
            "role": "user",
            "content": f"Question {i}: {'x' * content_size}",
        })
        messages.append({
            "role": "assistant",
            "content": [{"type": "text", "text": f"Answer {i}: {'y' * content_size}"}],
        })
    return messages


# ---------------------------------------------------------------------------
# Zone boundary calculation
# ---------------------------------------------------------------------------


class TestZoneBoundaries:
    def test_too_few_messages_returns_copy(self, tmp_path: Path) -> None:
        compressor = ProgressiveCompressor(
            session_id="test", archive_dir=tmp_path / "archive"
        )
        messages = _make_messages(3)  # 6 messages total
        result = compressor.compress(messages, "anthropic")
        # < 8 messages → returned as-is
        assert len(result) == 6

    def test_zones_split_correctly(self, tmp_path: Path) -> None:
        compressor = ProgressiveCompressor(
            session_id="test", archive_dir=tmp_path / "archive"
        )
        messages = _make_messages(10)  # 20 messages
        # With defaults (20% recent, 60% middle):
        # Zone C: 0..4 (oldest 20% = 4 messages)
        # Zone B: 4..16 (middle 60% = 12 messages)
        # Zone A: 16..20 (recent 20% = 4 messages)

        # Compress — Zone B summarization will use fallback (no LLM)
        result = compressor.compress(messages, "none")

        # Zone C → 2 messages (archive marker + ack)
        # Zone B → fallback summaries + acks (varies by group size)
        # Zone A → 4 messages (verbatim)
        # Total should be less than 20
        assert len(result) < 20
        assert len(result) >= 6  # at minimum: 2 (archive) + 2 (summary) + 4 (recent) - 2 (ack overlap)


# ---------------------------------------------------------------------------
# Zone C: Archiving
# ---------------------------------------------------------------------------


class TestZoneCArchive:
    def test_archive_creates_file(self, tmp_path: Path) -> None:
        compressor = ProgressiveCompressor(
            session_id="arch-test", archive_dir=tmp_path / "archive"
        )
        messages = _make_messages(10)
        compressor.compress(messages, "none")

        # Archive file should exist
        archive_dir = tmp_path / "archive" / "arch-test"
        assert archive_dir.exists()
        files = list(archive_dir.glob("*.json"))
        assert len(files) >= 1

    def test_recall_archived(self, tmp_path: Path) -> None:
        compressor = ProgressiveCompressor(
            session_id="recall-test", archive_dir=tmp_path / "archive"
        )
        messages = _make_messages(10)
        compressor.compress(messages, "none")

        # Recall the archive
        result = compressor.recall_archived("archive_0")
        assert "messages" in result
        assert result["message_count"] > 0

    def test_recall_nonexistent(self, tmp_path: Path) -> None:
        compressor = ProgressiveCompressor(
            session_id="no-test", archive_dir=tmp_path / "archive"
        )
        result = compressor.recall_archived("missing_archive")
        assert "error" in result

    def test_archive_marker_in_result(self, tmp_path: Path) -> None:
        compressor = ProgressiveCompressor(
            session_id="marker-test", archive_dir=tmp_path / "archive"
        )
        messages = _make_messages(10)
        result = compressor.compress(messages, "none")

        # First message should be the archive marker
        assert "[Archived:" in result[0]["content"]


# ---------------------------------------------------------------------------
# Zone B: Summarization fallback
# ---------------------------------------------------------------------------


class TestZoneBSummary:
    def test_fallback_summary_when_no_llm(self, tmp_path: Path) -> None:
        compressor = ProgressiveCompressor(
            session_id="fb-test", archive_dir=tmp_path / "archive"
        )
        messages = _make_messages(10)
        result = compressor.compress(messages, "none")

        # Should contain summary markers from fallback
        has_summary = any(
            "[Summary" in str(m.get("content", "")) or "[Fallback" in str(m.get("content", ""))
            for m in result
        )
        assert has_summary

    def test_group_splitting(self, tmp_path: Path) -> None:
        compressor = ProgressiveCompressor(
            session_id="grp-test",
            archive_dir=tmp_path / "archive",
            group_size=3,
        )
        # 12 messages with group_size=3 → 4 groups
        groups = compressor._split_into_groups(_make_messages(6))  # 12 msgs
        assert len(groups) == 4  # 12 / 3 = 4


# ---------------------------------------------------------------------------
# Zone A: Verbatim preservation
# ---------------------------------------------------------------------------


class TestZoneAVerbatim:
    def test_recent_messages_preserved(self, tmp_path: Path) -> None:
        compressor = ProgressiveCompressor(
            session_id="verb-test", archive_dir=tmp_path / "archive"
        )
        messages = _make_messages(10)
        last_msg = messages[-1]
        result = compressor.compress(messages, "none")

        # Last message should be preserved verbatim
        assert result[-1] == last_msg


# ---------------------------------------------------------------------------
# State management
# ---------------------------------------------------------------------------


class TestCompressorState:
    def test_already_compressed_flag(self, tmp_path: Path) -> None:
        compressor = ProgressiveCompressor(
            session_id="flag-test", archive_dir=tmp_path / "archive"
        )
        assert not compressor.already_compressed
        messages = _make_messages(10)
        compressor.compress(messages, "none")
        assert compressor.already_compressed

    def test_cleanup(self, tmp_path: Path) -> None:
        compressor = ProgressiveCompressor(
            session_id="clean-test", archive_dir=tmp_path / "archive"
        )
        messages = _make_messages(10)
        compressor.compress(messages, "none")
        removed = compressor.cleanup()
        assert removed >= 1
        assert not (tmp_path / "archive" / "clean-test").exists()

    def test_does_not_mutate_input(self, tmp_path: Path) -> None:
        compressor = ProgressiveCompressor(
            session_id="mut-test", archive_dir=tmp_path / "archive"
        )
        messages = _make_messages(10)
        original_len = len(messages)
        compressor.compress(messages, "none")
        assert len(messages) == original_len  # input not mutated


# ---------------------------------------------------------------------------
# ContextVar DI
# ---------------------------------------------------------------------------


class TestCompressorContextVar:
    def test_set_and_get(self, tmp_path: Path) -> None:
        prev = get_compressor()
        try:
            compressor = ProgressiveCompressor(
                session_id="ctx-test", archive_dir=tmp_path / "archive"
            )
            set_compressor(compressor)
            assert get_compressor() is compressor
        finally:
            set_compressor(prev)

    def test_set_none_clears(self, tmp_path: Path) -> None:
        prev = get_compressor()
        try:
            compressor = ProgressiveCompressor(
                session_id="ctx-test", archive_dir=tmp_path / "archive"
            )
            set_compressor(compressor)
            set_compressor(None)
            assert get_compressor() is None
        finally:
            set_compressor(prev)
