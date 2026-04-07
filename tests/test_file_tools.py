"""Tests for file operation tools — Glob, Grep, Edit, Write."""

from __future__ import annotations

from pathlib import Path

import pytest
from core.tools.file_tools import EditFileTool, GlobTool, GrepTool, WriteFileTool


@pytest.fixture(autouse=True)
def _sandbox_to_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Redirect sandbox root to tmp_path for all tests."""
    monkeypatch.setattr("core.tools.file_tools.get_project_root", lambda: tmp_path)


class TestGlobTool:
    def test_find_python_files(self, tmp_path: Path):
        (tmp_path / "a.py").write_text("print(1)")
        (tmp_path / "b.txt").write_text("hello")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "c.py").write_text("print(2)")

        tool = GlobTool()
        result = tool.execute(pattern="**/*.py", path=str(tmp_path))
        assert "result" in result
        files = result["result"]["files"]
        py_files = [f for f in files if f.endswith(".py")]
        assert len(py_files) >= 2

    def test_no_matches(self, tmp_path: Path):
        tool = GlobTool()
        result = tool.execute(pattern="*.xyz", path=str(tmp_path))
        assert result["result"]["total_matches"] == 0

    def test_rejects_symlink_dir(self, tmp_path: Path):
        real = tmp_path / "real"
        real.mkdir()
        link = tmp_path / "link"
        link.symlink_to(real)

        tool = GlobTool()
        result = tool.execute(pattern="*", path=str(link))
        assert "error" in result


class TestGrepTool:
    def test_find_pattern(self, tmp_path: Path):
        (tmp_path / "a.py").write_text("def hello():\n    pass\n")
        (tmp_path / "b.py").write_text("x = 42\n")

        tool = GrepTool()
        result = tool.execute(pattern="def hello", path=str(tmp_path))
        assert result["result"]["total_files"] == 1

    def test_include_content(self, tmp_path: Path):
        (tmp_path / "f.txt").write_text("line1\nfoo bar\nline3\n")

        tool = GrepTool()
        result = tool.execute(pattern="foo", path=str(tmp_path), include_content=True)
        matches = result["result"]["results"][0]["matches"]
        assert matches[0]["line"] == 2
        assert "foo bar" in matches[0]["text"]

    def test_invalid_regex(self):
        tool = GrepTool()
        result = tool.execute(pattern="[invalid")
        assert "error" in result
        assert result["error_type"] == "validation"

    def test_glob_filter(self, tmp_path: Path):
        (tmp_path / "a.py").write_text("target")
        (tmp_path / "b.txt").write_text("target")

        tool = GrepTool()
        result = tool.execute(pattern="target", path=str(tmp_path), glob="*.py")
        assert result["result"]["total_files"] == 1


class TestEditFileTool:
    def test_replace_string(self, tmp_path: Path):
        f = tmp_path / "test.txt"
        f.write_text("hello world")

        tool = EditFileTool()
        result = tool.execute(file_path=str(f), old_string="hello", new_string="goodbye")
        assert result["result"]["success"]
        assert f.read_text() == "goodbye world"

    def test_old_string_not_found(self, tmp_path: Path):
        f = tmp_path / "test.txt"
        f.write_text("hello")

        tool = EditFileTool()
        result = tool.execute(file_path=str(f), old_string="xyz", new_string="abc")
        assert "error" in result

    def test_ambiguous_match_rejected(self, tmp_path: Path):
        f = tmp_path / "test.txt"
        f.write_text("aaa bbb aaa")

        tool = EditFileTool()
        result = tool.execute(file_path=str(f), old_string="aaa", new_string="ccc")
        assert "error" in result
        assert result["context"]["occurrences"] == 2

    def test_replace_all(self, tmp_path: Path):
        f = tmp_path / "test.txt"
        f.write_text("aaa bbb aaa")

        tool = EditFileTool()
        result = tool.execute(
            file_path=str(f),
            old_string="aaa",
            new_string="ccc",
            replace_all=True,
        )
        assert result["result"]["replacements"] == 2
        assert f.read_text() == "ccc bbb ccc"

    def test_rejects_symlink(self, tmp_path: Path):
        real = tmp_path / "real.txt"
        real.write_text("content")
        link = tmp_path / "link.txt"
        link.symlink_to(real)

        tool = EditFileTool()
        result = tool.execute(file_path=str(link), old_string="content", new_string="new")
        assert "error" in result


class TestWriteFileTool:
    def test_create_new_file(self, tmp_path: Path):
        f = tmp_path / "new.txt"

        tool = WriteFileTool()
        result = tool.execute(file_path=str(f), content="hello world")
        assert result["result"]["created"]
        assert f.read_text() == "hello world"

    def test_creates_parent_dirs(self, tmp_path: Path):
        f = tmp_path / "sub" / "deep" / "file.txt"

        tool = WriteFileTool()
        result = tool.execute(file_path=str(f), content="nested")
        assert result["result"]["created"]
        assert f.read_text() == "nested"

    def test_overwrites_existing(self, tmp_path: Path):
        f = tmp_path / "existing.txt"
        f.write_text("old content")

        tool = WriteFileTool()
        result = tool.execute(file_path=str(f), content="new content")
        assert result["result"]["created"]
        assert f.read_text() == "new content"

    def test_rejects_symlink(self, tmp_path: Path):
        real = tmp_path / "real.txt"
        real.write_text("original")
        link = tmp_path / "link.txt"
        link.symlink_to(real)

        tool = WriteFileTool()
        result = tool.execute(file_path=str(link), content="hacked")
        assert "error" in result
        assert real.read_text() == "original"  # unchanged
