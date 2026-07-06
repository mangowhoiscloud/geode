"""UTF-8 boundary helpers for CLI/IPC text.

Terminal paste paths can occasionally deliver lone UTF-16 surrogate code
points. Python can carry them in ``str``, but UTF-8 history files and IPC
sockets cannot encode them. Replace only those invalid code points at the
boundary so the REPL stays alive and normal Unicode text is preserved.
"""

from __future__ import annotations

from typing import Any


def replace_lone_surrogates(text: str) -> str:
    """Return *text* with lone surrogate code points replaced.

    Fast-path valid UTF-8 strings unchanged. For invalid strings, encode with
    ``surrogatepass`` then decode with replacement so invalid surrogate bytes
    become U+FFFD instead of crashing the caller.
    """
    try:
        text.encode("utf-8")
        return text
    except UnicodeEncodeError:
        return text.encode("utf-8", "surrogatepass").decode("utf-8", "replace")


def sanitize_jsonable(value: Any) -> Any:
    """Recursively sanitize strings in a JSON-like payload."""
    if isinstance(value, str):
        return replace_lone_surrogates(value)
    if isinstance(value, list):
        return [sanitize_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {
            sanitize_jsonable(key) if isinstance(key, str) else key: sanitize_jsonable(item)
            for key, item in value.items()
        }
    return value
