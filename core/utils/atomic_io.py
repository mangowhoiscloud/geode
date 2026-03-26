"""Atomic file I/O — crash-safe write via tmp+rename.

Prevents data corruption when the process is interrupted mid-write.
Pattern extracted from ``core/memory/session.py:_persist()``.

Usage::

    from core.utils.atomic_io import atomic_write_text, atomic_write_json

    atomic_write_text(path, content)
    atomic_write_json(path, data, indent=2)
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


def atomic_write_text(
    path: Path,
    content: str,
    *,
    encoding: str = "utf-8",
) -> None:
    """Write *content* to *path* atomically via tmp+rename.

    The temporary file is created in the same directory as *path* so that
    ``os.replace`` is guaranteed to be an atomic rename (same filesystem).

    Raises:
        OSError: If the write or rename fails.  On error, any leftover
            temporary file is cleaned up so the original file is untouched.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, str(path))
    except BaseException:
        # Clean up temp file on any failure (including KeyboardInterrupt)
        import contextlib

        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise


def atomic_write_json(
    path: Path,
    data: Any,
    *,
    indent: int | None = None,
    ensure_ascii: bool = False,
    default: Callable[..., Any] | None = None,
    encoding: str = "utf-8",
) -> None:
    """Serialize *data* to JSON and write atomically to *path*.

    Equivalent to ``atomic_write_text(path, json.dumps(data, ...))``.
    """
    content = json.dumps(
        data,
        indent=indent,
        ensure_ascii=ensure_ascii,
        default=default or str,
    )
    atomic_write_text(path, content, encoding=encoding)
