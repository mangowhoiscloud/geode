"""Document Tools — local file reading as LLM-callable tool.

Provides:
- ReadDocumentTool: Read a local file (markdown, text, JSON)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from core.paths import get_project_root

log = logging.getLogger(__name__)


class ReadDocumentTool:
    """Read a local file (markdown, text, JSON)."""

    @property
    def name(self) -> str:
        return "read_document"

    @property
    def description(self) -> str:
        return "Read a local file (markdown, text, JSON)."

    def execute(self, **kwargs: Any) -> dict[str, Any]:
        file_path_str: str = kwargs["file_path"]
        max_lines: int = kwargs.get("max_lines", 200)

        raw_path = Path(file_path_str)

        from core.tools.base import tool_error

        # Security: reject symlinks before resolve (prevents traversal)
        if raw_path.is_symlink():
            return tool_error(
                f"Symlinks not allowed: {file_path_str}",
                error_type="permission",
                recoverable=False,
                context={"file_path": file_path_str},
            )

        file_path = raw_path.resolve()

        # Security: ensure path is within project directory
        try:
            file_path.relative_to(get_project_root())
        except ValueError:
            return tool_error(
                f"Access denied: path outside project directory ({get_project_root()})",
                error_type="permission",
                recoverable=False,
                hint=(
                    "All file tools are sandboxed to the project directory. "
                    "Use a relative path or omit the path parameter."
                ),
                context={"file_path": str(file_path)},
            )

        if not file_path.exists():
            return tool_error(
                f"File not found: {file_path}",
                error_type="not_found",
                hint="Check the file path or use a different file.",
                context={"file_path": str(file_path)},
            )

        if not file_path.is_file():
            return tool_error(
                f"Not a file: {file_path}",
                error_type="validation",
                hint="Provide a path to a file, not a directory.",
                context={"file_path": str(file_path)},
            )

        try:
            lines = file_path.read_text(encoding="utf-8").splitlines()
            truncated = len(lines) > max_lines
            content = "\n".join(lines[:max_lines])
            return {
                "result": {
                    "file_path": str(file_path),
                    "content": content,
                    "total_lines": len(lines),
                    "truncated": truncated,
                }
            }
        except Exception as exc:
            return tool_error(
                f"Failed to read {file_path}: {exc}",
                error_type="internal",
                context={"file_path": str(file_path)},
            )
