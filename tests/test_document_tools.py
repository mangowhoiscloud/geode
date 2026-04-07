"""Tests for ReadDocumentTool — offset/limit + file size guards."""

from __future__ import annotations

from pathlib import Path

import core.paths as paths_mod
import pytest
from core.tools import sandbox
from core.tools.document_tools import ReadDocumentTool


@pytest.fixture(autouse=True)
def _sandbox_to_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Redirect sandbox root to tmp_path for all tests."""
    def _root() -> Path:
        return tmp_path

    monkeypatch.setattr(paths_mod, "get_project_root", _root)
    monkeypatch.setattr("core.tools.sandbox.get_project_root", _root)
    sandbox._additional_dirs.clear()
    sandbox._resolve_symlink_cached.cache_clear()


class TestReadBasic:
    def test_reads_file(self, tmp_path: Path):
        f = tmp_path / "hello.txt"
        f.write_text("line1\nline2\nline3")

        tool = ReadDocumentTool()
        result = tool.execute(file_path=str(f))
        assert "result" in result
        assert result["result"]["total_lines"] == 3
        assert "line1" in result["result"]["content"]

    def test_file_not_found(self, tmp_path: Path):
        tool = ReadDocumentTool()
        result = tool.execute(file_path=str(tmp_path / "missing.txt"))
        assert "error" in result
        assert result["error_type"] == "not_found"

    def test_not_a_file(self, tmp_path: Path):
        tool = ReadDocumentTool()
        result = tool.execute(file_path=str(tmp_path))
        assert "error" in result
        assert result["error_type"] == "validation"


class TestOffsetLimit:
    def test_default_reads_all(self, tmp_path: Path):
        f = tmp_path / "data.txt"
        f.write_text("\n".join(f"line{i}" for i in range(50)))

        tool = ReadDocumentTool()
        result = tool.execute(file_path=str(f))
        assert result["result"]["total_lines"] == 50
        assert result["result"]["start_line"] == 1
        assert result["result"]["num_lines"] == 50

    def test_offset_and_limit(self, tmp_path: Path):
        f = tmp_path / "data.txt"
        f.write_text("\n".join(f"line{i}" for i in range(100)))

        tool = ReadDocumentTool()
        result = tool.execute(file_path=str(f), offset=10, limit=5)
        r = result["result"]
        assert r["start_line"] == 10
        assert r["num_lines"] == 5
        assert r["total_lines"] == 100
        assert "line9" in r["content"]  # 0-indexed line9 = 1-indexed line10
        assert "line13" in r["content"]

    def test_offset_beyond_file(self, tmp_path: Path):
        f = tmp_path / "short.txt"
        f.write_text("one\ntwo\nthree")

        tool = ReadDocumentTool()
        result = tool.execute(file_path=str(f), offset=100, limit=10)
        assert result["result"]["num_lines"] == 0
        assert result["result"]["content"] == ""

    def test_max_lines_backward_compat(self, tmp_path: Path):
        f = tmp_path / "data.txt"
        f.write_text("\n".join(f"line{i}" for i in range(50)))

        tool = ReadDocumentTool()
        result = tool.execute(file_path=str(f), max_lines=10)
        assert result["result"]["num_lines"] == 10
        assert result["result"]["truncated"] is True


class TestFileSizeGuard:
    def test_rejects_large_file_without_limit(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        from core.config import settings

        monkeypatch.setattr(settings, "sandbox_max_file_size_bytes", 100)

        f = tmp_path / "large.txt"
        f.write_text("x" * 200)

        tool = ReadDocumentTool()
        result = tool.execute(file_path=str(f))
        assert "error" in result
        assert "too large" in result["error"].lower()
        assert result["recoverable"] is True

    def test_allows_large_file_with_limit(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        from core.config import settings

        monkeypatch.setattr(settings, "sandbox_max_file_size_bytes", 100)

        f = tmp_path / "large.txt"
        f.write_text("\n".join(f"line{i}" for i in range(1000)))

        tool = ReadDocumentTool()
        result = tool.execute(file_path=str(f), offset=1, limit=5)
        assert "result" in result
        assert result["result"]["num_lines"] == 5


class TestTokenGuard:
    def test_truncates_on_token_overflow(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        from core.config import settings

        monkeypatch.setattr(settings, "sandbox_max_read_tokens", 10)  # very low
        monkeypatch.setattr(settings, "sandbox_max_file_size_bytes", 10_000_000)

        f = tmp_path / "verbose.txt"
        f.write_text("x" * 500)

        tool = ReadDocumentTool()
        result = tool.execute(file_path=str(f))
        assert "result" in result
        assert result["result"]["truncated"] is True
        # Content should be truncated to ~40 chars (10 tokens * 4 chars/token)
        assert len(result["result"]["content"]) <= 50
