"""Tests for P0 tool result offloading and observation masking."""

from __future__ import annotations

import json
import time
from pathlib import Path

from core.orchestration.context_monitor import mask_stale_observations
from core.orchestration.tool_offload import (
    ToolResultOffloadStore,
    extract_result_summary,
    get_offload_store,
    set_offload_store,
)

# ---------------------------------------------------------------------------
# ToolResultOffloadStore
# ---------------------------------------------------------------------------


class TestToolResultOffloadStore:
    def test_offload_and_recall(self, tmp_path: Path):
        store = ToolResultOffloadStore(
            session_id="test-session",
            threshold=100,
            base_dir=tmp_path / "offload",
        )
        result = {"data": "x" * 1000, "summary": "big result"}
        ref = store.offload("ref_001", result)
        assert ref == "ref_001"

        recalled = store.recall("ref_001")
        assert recalled["data"] == "x" * 1000
        assert recalled["summary"] == "big result"

    def test_recall_nonexistent(self, tmp_path: Path):
        store = ToolResultOffloadStore(
            session_id="test-session",
            threshold=100,
            base_dir=tmp_path / "offload",
        )
        result = store.recall("missing")
        assert "error" in result

    def test_ttl_expiry(self, tmp_path: Path):
        store = ToolResultOffloadStore(
            session_id="test-session",
            threshold=100,
            ttl_hours=0.0,  # immediate expiry
            base_dir=tmp_path / "offload",
        )
        store.offload("ref_exp", {"data": "will expire"})
        # TTL is 0 hours = 0 seconds, so it expires immediately
        time.sleep(0.01)
        result = store.recall("ref_exp")
        assert "error" in result
        assert "expired" in result["error"]

    def test_cleanup_expired(self, tmp_path: Path):
        store = ToolResultOffloadStore(
            session_id="test-session",
            threshold=100,
            ttl_hours=0.0,
            base_dir=tmp_path / "offload",
        )
        store.offload("ref_1", {"a": 1})
        store.offload("ref_2", {"b": 2})
        time.sleep(0.01)
        removed = store.cleanup_expired()
        assert removed == 2

    def test_cleanup_session(self, tmp_path: Path):
        store = ToolResultOffloadStore(
            session_id="test-session",
            threshold=100,
            ttl_hours=24.0,
            base_dir=tmp_path / "offload",
        )
        store.offload("ref_a", {"a": 1})
        store.offload("ref_b", {"b": 2})
        removed = store.cleanup_session()
        assert removed == 2
        # Directory should be removed
        assert not (tmp_path / "offload" / "test-session").exists()

    def test_offload_creates_directory(self, tmp_path: Path):
        store = ToolResultOffloadStore(
            session_id="new-session",
            threshold=100,
            base_dir=tmp_path / "offload",
        )
        store.offload("ref_dir", {"test": True})
        assert (tmp_path / "offload" / "new-session" / "ref_dir.json").exists()


# ---------------------------------------------------------------------------
# extract_result_summary
# ---------------------------------------------------------------------------


class TestExtractResultSummary:
    def test_summary_field_preferred(self):
        result = {"summary": "This is the summary", "data": "x" * 10000}
        assert extract_result_summary(result) == "This is the summary"

    def test_text_field_fallback(self):
        result = {"text": "Some text content", "other": "data"}
        assert extract_result_summary(result) == "Some text content"

    def test_content_field_fallback(self):
        result = {"content": "Content here"}
        assert extract_result_summary(result) == "Content here"

    def test_json_preview_fallback(self):
        result = {"alpha": 1, "beta": 2, "gamma": 3}
        summary = extract_result_summary(result, max_chars=100)
        assert "keys=" in summary
        assert "preview=" in summary

    def test_max_chars_truncation(self):
        result = {"summary": "a" * 1000}
        summary = extract_result_summary(result, max_chars=50)
        assert len(summary) == 50

    def test_non_dict_result(self):
        assert extract_result_summary("plain string") == "plain string"
        assert extract_result_summary(42) == "42"

    def test_empty_dict(self):
        summary = extract_result_summary({})
        assert "keys=" in summary


# ---------------------------------------------------------------------------
# ContextVar DI
# ---------------------------------------------------------------------------


class TestOffloadContextVar:
    def test_set_and_get(self, tmp_path: Path):
        prev = get_offload_store()
        try:
            store = ToolResultOffloadStore(
                session_id="ctx-test",
                threshold=100,
                base_dir=tmp_path / "offload",
            )
            set_offload_store(store)
            assert get_offload_store() is store
        finally:
            set_offload_store(prev)  # restore

    def test_set_none_clears(self, tmp_path: Path):
        prev = get_offload_store()
        try:
            store = ToolResultOffloadStore(
                session_id="ctx-test",
                threshold=100,
                base_dir=tmp_path / "offload",
            )
            set_offload_store(store)
            set_offload_store(None)
            assert get_offload_store() is None
        finally:
            set_offload_store(prev)  # restore


# ---------------------------------------------------------------------------
# mask_stale_observations
# ---------------------------------------------------------------------------


def _make_round(turn: int, tool_content_size: int = 500) -> list[dict]:
    """Create a typical assistant→user(tool_result) round pair."""
    return [
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": f"Turn {turn} response"},
                {"type": "tool_use", "id": f"tu_{turn}", "name": "search", "input": {}},
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": f"tu_{turn}",
                    "content": json.dumps({"data": "x" * tool_content_size}),
                }
            ],
        },
    ]


class TestMaskStaleObservations:
    def test_no_masking_when_few_rounds(self):
        """Should not mask when fewer rounds than keep_recent."""
        messages = [
            {"role": "user", "content": "initial query"},
        ]
        for i in range(2):
            messages.extend(_make_round(i))
        masked = mask_stale_observations(messages, keep_recent_rounds=3)
        assert masked == 0

    def test_masks_old_rounds(self):
        """Should mask tool results in rounds older than keep_recent."""
        messages = [{"role": "user", "content": "initial query"}]
        for i in range(6):
            messages.extend(_make_round(i, tool_content_size=500))
        # 6 rounds, keep 3 → should mask rounds 0, 1, 2
        masked = mask_stale_observations(messages, keep_recent_rounds=3)
        assert masked == 3

    def test_preserves_recent_rounds(self):
        """Recent tool results should be untouched."""
        messages = [{"role": "user", "content": "initial query"}]
        for i in range(6):
            messages.extend(_make_round(i, tool_content_size=500))
        mask_stale_observations(messages, keep_recent_rounds=3)

        # Check last 3 rounds are untouched
        for i in range(3, 6):
            # Find the tool_result for round i
            for msg in messages:
                if msg.get("role") != "user":
                    continue
                content = msg.get("content")
                if not isinstance(content, list):
                    continue
                for block in content:
                    if (
                        isinstance(block, dict)
                        and block.get("type") == "tool_result"
                        and block.get("tool_use_id") == f"tu_{i}"
                    ):
                        assert not block["content"].startswith("[masked:")

    def test_skips_small_results(self):
        """Tool results < 200 chars should not be masked."""
        messages = [{"role": "user", "content": "query"}]
        for i in range(5):
            messages.extend(_make_round(i, tool_content_size=10))  # small results
        masked = mask_stale_observations(messages, keep_recent_rounds=2)
        assert masked == 0  # all results < 200 chars

    def test_skips_already_masked(self):
        """Already-masked results should not be re-masked."""
        messages = [{"role": "user", "content": "query"}]
        for i in range(5):
            messages.extend(_make_round(i, tool_content_size=500))
        # First mask pass
        masked1 = mask_stale_observations(messages, keep_recent_rounds=2)
        assert masked1 > 0
        # Second mask pass — should find nothing new
        masked2 = mask_stale_observations(messages, keep_recent_rounds=2)
        assert masked2 == 0

    def test_mutates_in_place(self):
        """Should modify the messages list in place."""
        messages = [{"role": "user", "content": "query"}]
        for i in range(5):
            messages.extend(_make_round(i, tool_content_size=500))
        original_len = len(messages)
        mask_stale_observations(messages, keep_recent_rounds=2)
        assert len(messages) == original_len  # same length, content changed
