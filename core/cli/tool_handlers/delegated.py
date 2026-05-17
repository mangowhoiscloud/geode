"""Delegated tool handlers — registry-based lazy-import wrappers.

Maps tool name → (module_path, class_name) for lazy-import delegation.
Adding a new delegated tool requires only one line in ``_DELEGATED_TOOLS``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from core.cli.tool_handlers._helpers import _safe_delegate

_DELEGATED_TOOLS: dict[str, tuple[str, str]] = {
    # web / document / note
    "web_fetch": ("core.tools.web_tools", "WebFetchTool"),
    "general_web_search": ("core.tools.web_tools", "GeneralWebSearchTool"),
    "read_document": ("core.tools.document_tools", "ReadDocumentTool"),
    "glob_files": ("core.tools.file_tools", "GlobTool"),
    "grep_files": ("core.tools.file_tools", "GrepTool"),
    "edit_file": ("core.tools.file_tools", "EditFileTool"),
    "write_file": ("core.tools.file_tools", "WriteFileTool"),
    "note_save": ("core.tools.memory_tools", "NoteSaveTool"),
    "note_read": ("core.tools.memory_tools", "NoteReadTool"),
    # profile
    "profile_show": ("core.tools.profile_tools", "ProfileShowTool"),
    "profile_update": ("core.tools.profile_tools", "ProfileUpdateTool"),
    "profile_preference": ("core.tools.profile_tools", "ProfilePreferenceTool"),
    "profile_learn": ("core.tools.profile_tools", "ProfileLearnTool"),
}


def _make_delegate_handler(
    module_path: str,
    class_name: str,
) -> Callable[..., dict[str, Any]]:
    """Return a handler that lazily imports *class_name* from *module_path* and delegates."""

    def _handler(**kwargs: Any) -> dict[str, Any]:
        import importlib

        mod = importlib.import_module(module_path)
        tool_cls = getattr(mod, class_name)
        return _safe_delegate(tool_cls, kwargs)

    return _handler


def _build_delegated_handlers() -> dict[str, Any]:
    """Build all delegated tool handlers from ``_DELEGATED_TOOLS`` registry."""
    return {name: _make_delegate_handler(mod, cls) for name, (mod, cls) in _DELEGATED_TOOLS.items()}
