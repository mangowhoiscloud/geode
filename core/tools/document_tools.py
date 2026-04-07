"""Document Tools — local file reading as LLM-callable tool.

Provides:
- ReadDocumentTool: Read a local file (markdown, text, JSON)
  with offset/limit support and file size guards.
"""

from __future__ import annotations

import logging
from typing import Any

from core.tools.sandbox import validate_path

log = logging.getLogger(__name__)

# File size guard defaults (Claude Code parity)
_MAX_FILE_SIZE_BYTES = 262_144  # 256 KB — pre-read check
_MAX_READ_TOKENS = 25_000  # post-read token estimate check
_CHARS_PER_TOKEN = 4  # rough estimate for token counting


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

        # offset/limit with max_lines backward compat
        offset: int = kwargs.get("offset", 1)
        limit: int | None = kwargs.get("limit") or kwargs.get("max_lines")

        from core.tools.base import tool_error

        result = validate_path(file_path_str, write=False)
        if isinstance(result, dict):
            return result
        file_path = result

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

        # Pre-read file size guard: only when no explicit limit (full-file read)
        if limit is None:
            try:
                size = file_path.stat().st_size
            except OSError:
                size = 0
            if size > _MAX_FILE_SIZE_BYTES:
                return tool_error(
                    f"File too large: {size:,} bytes (limit {_MAX_FILE_SIZE_BYTES:,})",
                    error_type="validation",
                    recoverable=True,
                    hint=(
                        "Use offset and limit to read a range.  "
                        "Example: offset=1, limit=200 for the first 200 lines."
                    ),
                    context={
                        "file_path": str(file_path),
                        "file_size": size,
                        "max_size": _MAX_FILE_SIZE_BYTES,
                    },
                )

        try:
            all_lines = file_path.read_text(encoding="utf-8").splitlines()
        except Exception as exc:
            return tool_error(
                f"Failed to read {file_path}: {exc}",
                error_type="internal",
                context={"file_path": str(file_path)},
            )

        total_lines = len(all_lines)

        # Apply offset (1-indexed) and limit
        start_idx = max(0, offset - 1)
        end_idx = start_idx + limit if limit is not None else total_lines

        selected = all_lines[start_idx:end_idx]
        content = "\n".join(selected)

        # Post-read token guard: estimate tokens and truncate if needed
        truncated = end_idx < total_lines
        estimated_tokens = len(content) // _CHARS_PER_TOKEN
        if estimated_tokens > _MAX_READ_TOKENS:
            # Truncate to approximate token limit
            max_chars = _MAX_READ_TOKENS * _CHARS_PER_TOKEN
            content = content[:max_chars]
            truncated = True

        return {
            "result": {
                "file_path": str(file_path),
                "content": content,
                "total_lines": total_lines,
                "start_line": start_idx + 1,
                "num_lines": len(selected),
                "truncated": truncated,
            }
        }
