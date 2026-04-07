"""File Operation Tools — Glob, Grep, Edit, Write for LLM-callable use.

Claude Code-inspired tools that provide structured file operations
without requiring run_bash. Safety-gated by the Tool Protocol:
- Glob, Grep: SAFE (read-only, auto-approved)
- Edit, Write: WRITE (requires HITL approval)

All paths are validated through ``core.tools.sandbox.validate_path()``.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from core.paths import get_project_root
from core.tools.sandbox import validate_path

log = logging.getLogger(__name__)


class GlobTool:
    """Find files by glob pattern within the project directory."""

    @property
    def name(self) -> str:
        return "glob_files"

    @property
    def description(self) -> str:
        return (
            "Find files whose paths match a glob pattern (e.g. '**/*.py', 'src/**/*.ts'). "
            "Results sorted by modification time (newest first). Max 100 results."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Glob pattern (e.g. '**/*.py', 'core/**/*.json')",
                },
                "path": {
                    "type": "string",
                    "description": (
                        "Directory to search in (default: project root). "
                        "Symlinks allowed if they resolve within the project directory."
                    ),
                },
            },
            "required": ["pattern"],
        }

    def execute(self, **kwargs: Any) -> dict[str, Any]:
        from core.tools.base import tool_error

        pattern: str = kwargs["pattern"]
        path_str: str = kwargs.get("path", ".")

        result = validate_path(path_str, write=False)
        if isinstance(result, dict):
            return result
        search_dir = result

        if not search_dir.is_dir():
            return tool_error(
                f"Not a directory: {search_dir}",
                error_type="not_found",
                hint="Provide a valid directory path.",
            )

        project_root = get_project_root()
        matches: list[tuple[float, str]] = []
        for path in search_dir.rglob(pattern) if "**" in pattern else search_dir.glob(pattern):
            if not path.is_file():
                continue
            try:
                resolved = path.resolve()
                rel = resolved.relative_to(project_root)
                mtime = path.stat().st_mtime
                matches.append((mtime, str(rel)))
            except (ValueError, OSError):
                continue

        matches.sort(reverse=True)  # newest first
        files = [f for _, f in matches[:100]]

        return {
            "result": {
                "pattern": pattern,
                "total_matches": len(matches),
                "files": files,
                "truncated": len(matches) > 100,
            }
        }


class GrepTool:
    """Search file contents using regex patterns."""

    @property
    def name(self) -> str:
        return "grep_files"

    @property
    def description(self) -> str:
        return (
            "Search file contents using regex patterns. "
            "Returns matching file paths and optionally matching lines with context."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Regex pattern to search for",
                },
                "path": {
                    "type": "string",
                    "description": (
                        "File or directory to search (default: project root). "
                        "Symlinks allowed if they resolve within the project directory."
                    ),
                },
                "glob": {
                    "type": "string",
                    "description": "File pattern filter (e.g. '*.py', '*.ts')",
                },
                "include_content": {
                    "type": "boolean",
                    "description": "Include matching lines in output (default: false)",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Max files to return (default: 50)",
                },
            },
            "required": ["pattern"],
        }

    def execute(self, **kwargs: Any) -> dict[str, Any]:
        from core.tools.base import tool_error

        pattern_str: str = kwargs["pattern"]
        path_str: str = kwargs.get("path", ".")
        file_glob: str = kwargs.get("glob", "")
        include_content: bool = kwargs.get("include_content", False)
        max_results: int = min(kwargs.get("max_results", 50), 100)

        result = validate_path(path_str, write=False)
        if isinstance(result, dict):
            return result
        search_path = result

        try:
            regex = re.compile(pattern_str)
        except re.error as exc:
            return tool_error(
                f"Invalid regex: {exc}",
                error_type="validation",
                hint="Check regex syntax.",
            )

        results: list[dict[str, Any]] = []
        files_to_search: list[Path] = []

        if search_path.is_file():
            files_to_search = [search_path]
        elif search_path.is_dir():
            glob_pattern = file_glob or "*"
            files_to_search = sorted(search_path.rglob(glob_pattern))
        else:
            return tool_error(
                f"Path not found: {search_path}",
                error_type="not_found",
            )

        _SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".mypy_cache"}
        project_root = get_project_root()

        for fpath in files_to_search:
            if not fpath.is_file():
                continue
            if any(part in _SKIP_DIRS for part in fpath.parts):
                continue
            if len(results) >= max_results:
                break

            try:
                text = fpath.read_text(encoding="utf-8", errors="replace")
            except (OSError, UnicodeDecodeError):
                continue

            matches_in_file: list[dict[str, Any]] = []
            for i, line in enumerate(text.splitlines(), 1):
                if regex.search(line):
                    if include_content:
                        matches_in_file.append({"line": i, "text": line.rstrip()[:200]})
                    else:
                        matches_in_file.append({"line": i})

            if matches_in_file:
                try:
                    rel = str(fpath.resolve().relative_to(project_root))
                except ValueError:
                    continue
                entry: dict[str, Any] = {"file": rel, "match_count": len(matches_in_file)}
                if include_content:
                    entry["matches"] = matches_in_file[:20]
                results.append(entry)

        return {
            "result": {
                "pattern": pattern_str,
                "total_files": len(results),
                "results": results,
                "truncated": len(results) >= max_results,
            }
        }


class EditFileTool:
    """Edit a file by exact string replacement."""

    @property
    def name(self) -> str:
        return "edit_file"

    @property
    def description(self) -> str:
        return (
            "Edit an existing file by replacing an exact string match. "
            "Provide the old text and new text. The old text must appear exactly once "
            "in the file (or use replace_all=true for all occurrences)."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": (
                        "Path to the file to edit. "
                        "Symlinks allowed if they resolve within the project directory."
                    ),
                },
                "old_string": {
                    "type": "string",
                    "description": "Exact string to find and replace",
                },
                "new_string": {
                    "type": "string",
                    "description": "Replacement text",
                },
                "replace_all": {
                    "type": "boolean",
                    "description": "Replace all occurrences (default: false)",
                },
            },
            "required": ["file_path", "old_string", "new_string"],
        }

    def execute(self, **kwargs: Any) -> dict[str, Any]:
        from core.tools.base import tool_error

        path_str: str = kwargs["file_path"]
        old_string: str = kwargs["old_string"]
        new_string: str = kwargs["new_string"]
        replace_all: bool = kwargs.get("replace_all", False)

        result = validate_path(path_str, write=True)
        if isinstance(result, dict):
            return result
        file_path = result

        if not file_path.exists():
            return tool_error(
                f"File not found: {file_path}",
                error_type="not_found",
                hint="Check the file path.",
            )

        if not file_path.is_file():
            return tool_error(
                f"Not a file: {file_path}",
                error_type="validation",
            )

        try:
            content = file_path.read_text(encoding="utf-8")
        except Exception as exc:
            return tool_error(f"Failed to read: {exc}", error_type="internal")

        count = content.count(old_string)
        if count == 0:
            return tool_error(
                "old_string not found in file",
                error_type="validation",
                hint="Ensure the old_string matches exactly (including whitespace).",
                context={"file_path": str(file_path)},
            )

        if count > 1 and not replace_all:
            return tool_error(
                f"old_string found {count} times — use replace_all=true or provide more context",
                error_type="validation",
                context={"file_path": str(file_path), "occurrences": count},
            )

        if replace_all:
            new_content = content.replace(old_string, new_string)
        else:
            new_content = content.replace(old_string, new_string, 1)
        file_path.write_text(new_content, encoding="utf-8")

        return {
            "result": {
                "file_path": str(file_path),
                "replacements": count if replace_all else 1,
                "success": True,
            }
        }


class WriteFileTool:
    """Create a new file or overwrite an existing file."""

    @property
    def name(self) -> str:
        return "write_file"

    @property
    def description(self) -> str:
        return (
            "Create a new file or completely overwrite an existing file. "
            "Parent directories are created automatically. "
            "Use edit_file for partial modifications."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": (
                        "Path to the file to create or overwrite. "
                        "Symlinks allowed if they resolve within the project directory."
                    ),
                },
                "content": {
                    "type": "string",
                    "description": "Complete file content",
                },
            },
            "required": ["file_path", "content"],
        }

    def execute(self, **kwargs: Any) -> dict[str, Any]:
        from core.tools.base import tool_error

        path_str: str = kwargs["file_path"]
        content: str = kwargs["content"]

        result = validate_path(path_str, write=True)
        if isinstance(result, dict):
            return result
        file_path = result

        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")
        except Exception as exc:
            return tool_error(f"Failed to write: {exc}", error_type="internal")

        return {
            "result": {
                "file_path": str(file_path),
                "bytes_written": len(content.encode("utf-8")),
                "created": True,
            }
        }
