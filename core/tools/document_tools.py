"""Document Tools — local file reading as LLM-callable tool.

Provides:
- ReadDocumentTool: Read a local file (markdown, text, JSON)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# Security: restrict file access to project directory
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


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

        file_path = Path(file_path_str).resolve()

        # Security: ensure path is within project directory
        try:
            file_path.relative_to(_PROJECT_ROOT)
        except ValueError:
            return {"error": f"Access denied: path outside project directory ({_PROJECT_ROOT})"}

        if not file_path.exists():
            return {"error": f"File not found: {file_path}"}

        if not file_path.is_file():
            return {"error": f"Not a file: {file_path}"}

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
            return {"error": f"Failed to read {file_path}: {exc}"}
