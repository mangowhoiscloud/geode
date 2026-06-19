"""Tests for atomic file I/O utility.

Covers:
- Basic text write + overwrite
- Original preserved on error
- Temp file cleaned up on failure
- Parent directory auto-created
- JSON round-trip
- Concurrent write safety
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from unittest.mock import patch

import pytest
from core.memory.atomic_write import (
    atomic_write_json,
    atomic_write_text,
    iter_jsonl,
    read_jsonl,
)


class TestAtomicWriteText:
    def test_basic_write(self, tmp_path: Path) -> None:
        target = tmp_path / "hello.txt"
        atomic_write_text(target, "hello world")
        assert target.read_text() == "hello world"

    def test_overwrite_existing(self, tmp_path: Path) -> None:
        target = tmp_path / "data.txt"
        target.write_text("old", encoding="utf-8")
        atomic_write_text(target, "new")
        assert target.read_text() == "new"

    def test_original_preserved_on_write_error(self, tmp_path: Path) -> None:
        target = tmp_path / "keep.txt"
        target.write_text("original", encoding="utf-8")

        with (
            patch("core.memory.atomic_write.os.fdopen", side_effect=OSError("disk full")),
            pytest.raises(OSError, match="disk full"),
        ):
            atomic_write_text(target, "bad data")

        assert target.read_text() == "original"

    def test_temp_file_cleaned_on_failure(self, tmp_path: Path) -> None:
        target = tmp_path / "clean.txt"

        with (
            patch("core.memory.atomic_write.os.replace", side_effect=OSError("rename failed")),
            pytest.raises(OSError, match="rename failed"),
        ):
            atomic_write_text(target, "data")

        # No .tmp files should remain
        tmps = list(tmp_path.glob("*.tmp"))
        assert tmps == []

    def test_creates_parent_directory(self, tmp_path: Path) -> None:
        target = tmp_path / "deep" / "nested" / "file.txt"
        atomic_write_text(target, "nested content")
        assert target.read_text() == "nested content"

    def test_encoding_parameter(self, tmp_path: Path) -> None:
        target = tmp_path / "utf8.txt"
        atomic_write_text(target, "한글 테스트", encoding="utf-8")
        assert target.read_text(encoding="utf-8") == "한글 테스트"

    def test_empty_content(self, tmp_path: Path) -> None:
        target = tmp_path / "empty.txt"
        atomic_write_text(target, "")
        assert target.read_text() == ""


class TestAtomicWriteJson:
    def test_json_roundtrip(self, tmp_path: Path) -> None:
        target = tmp_path / "data.json"
        data = {"key": "value", "number": 42, "nested": {"a": [1, 2]}}
        atomic_write_json(target, data, indent=2)
        loaded = json.loads(target.read_text())
        assert loaded == data

    def test_json_ensure_ascii_false(self, tmp_path: Path) -> None:
        target = tmp_path / "unicode.json"
        data = {"name": "한글"}
        atomic_write_json(target, data)
        raw = target.read_text()
        assert "한글" in raw  # not escaped

    def test_json_custom_default(self, tmp_path: Path) -> None:
        target = tmp_path / "custom.json"

        class Custom:
            def __repr__(self) -> str:
                return "custom-repr"

        data = {"obj": Custom()}
        atomic_write_json(target, data, default=repr)
        loaded = json.loads(target.read_text())
        assert loaded["obj"] == "custom-repr"

    def test_json_original_preserved_on_error(self, tmp_path: Path) -> None:
        target = tmp_path / "safe.json"
        target.write_text('{"old": true}', encoding="utf-8")

        with (
            patch("core.memory.atomic_write.os.replace", side_effect=OSError("fail")),
            pytest.raises(OSError),
        ):
            atomic_write_json(target, {"new": True})

        assert json.loads(target.read_text()) == {"old": True}


class TestConcurrentWrites:
    def test_concurrent_writers_no_corruption(self, tmp_path: Path) -> None:
        target = tmp_path / "concurrent.txt"
        errors: list[Exception] = []

        def writer(content: str) -> None:
            try:
                for _ in range(20):
                    atomic_write_text(target, content)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(f"thread-{i}\n" * 100,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        # File should contain content from exactly one writer (no mixed content)
        final = target.read_text()
        assert final.startswith("thread-")
        lines = final.strip().split("\n")
        assert len(set(lines)) == 1  # all lines from same thread


class TestIterReadJsonl:
    """The shared JSONL read+parse+skip helper (PR-DEDUP-JSONL)."""

    def _write(self, path: Path, lines: list[str]) -> None:
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def test_reads_valid_rows(self, tmp_path: Path) -> None:
        f = tmp_path / "log.jsonl"
        self._write(f, ['{"a": 1}', '{"b": 2}'])
        assert read_jsonl(f) == [{"a": 1}, {"b": 2}]

    def test_skips_blank_and_malformed_and_non_dict(self, tmp_path: Path) -> None:
        f = tmp_path / "log.jsonl"
        self._write(f, ['{"a": 1}', "", "  ", "not json", "[1, 2]", '{"b": 2}'])
        assert read_jsonl(f) == [{"a": 1}, {"b": 2}]  # array row + garbage skipped

    def test_missing_file_is_empty(self, tmp_path: Path) -> None:
        assert read_jsonl(tmp_path / "absent.jsonl") == []
        assert list(iter_jsonl(tmp_path / "absent.jsonl")) == []

    def test_tail_keeps_last_n(self, tmp_path: Path) -> None:
        f = tmp_path / "log.jsonl"
        self._write(f, [f'{{"i": {i}}}' for i in range(5)])
        assert read_jsonl(f, tail=2) == [{"i": 3}, {"i": 4}]
        assert read_jsonl(f, tail=0) == []  # tail<=0 → empty (matches old _tail_jsonl)
        assert read_jsonl(f) == [{"i": i} for i in range(5)]  # tail=None → all

    def test_iter_supports_early_exit(self, tmp_path: Path) -> None:
        f = tmp_path / "log.jsonl"
        self._write(f, ['{"k": "x"}', '{"k": "y"}', '{"k": "z"}'])
        found = next((r for r in iter_jsonl(f) if r.get("k") == "y"), None)
        assert found == {"k": "y"}

    def test_unreadable_file_warns_and_returns_empty(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        # An existing-but-unreadable file degrades to empty but is LOGGED (not
        # silently swallowed) — observable fail-soft (Codex HIGH).
        f = tmp_path / "log.jsonl"
        self._write(f, ['{"a": 1}'])
        with (
            patch.object(Path, "read_text", side_effect=OSError("boom")),
            caplog.at_level("WARNING"),
        ):
            assert read_jsonl(f) == []
        assert any("unreadable" in r.message for r in caplog.records)
