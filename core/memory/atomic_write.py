"""Atomic file I/O — crash-safe write via tmp+rename.

Prevents data corruption when the process is interrupted mid-write.
Pattern extracted from ``core/memory/session.py:_persist()``.

Usage::

    from core.memory.atomic_write import atomic_write_text, atomic_write_json

    atomic_write_text(path, content)
    atomic_write_json(path, data, indent=2)
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from collections.abc import Callable, Iterator
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


def read_json_or_none(path: Path) -> dict[str, Any] | None:
    """Return the parsed JSON dict at *path*, or ``None``.

    Read companion to :func:`atomic_write_json`. Returns ``None`` for a
    missing / unreadable / malformed / non-dict file and NEVER raises — the
    read counterpart to the crash-safe write, for callers (slash status,
    eval export) that must tolerate a file being concurrently rewritten.
    """
    path = Path(path)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def iter_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    """Yield each valid JSON-object row from a JSONL file.

    The read companion to the append/write side. A missing or unreadable file
    yields nothing; blank lines and rows that fail to parse or aren't dicts are
    skipped silently. NEVER raises — JSONL logs are appended live and read
    concurrently, so a partial last line during a write must not break a reader.
    Callers layer their own filtering / projection / tail / counting on top.
    """
    path = Path(path)
    if not path.is_file():
        return  # missing file is the expected common case (fresh repo) — silent
    try:
        handle = path.open(encoding="utf-8")
    except OSError as exc:
        # An existing-but-unreadable file is unexpected — degrade to empty (callers
        # treat "no rows" uniformly) but surface it so a real I/O fault isn't hidden.
        log.warning("iter_jsonl: %s unreadable: %s", path, exc)
        return
    # Stream line-by-line (genuinely lazy) so early-exit callers — ``any(... for
    # row in iter_jsonl(...))`` — stop reading the file, not just parsing.
    with handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                row = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                yield row


def read_jsonl(path: Path, *, tail: int | None = None) -> list[dict[str, Any]]:
    """Materialise :func:`iter_jsonl` to a list, optionally keeping the last ``tail``.

    ``tail=None`` (default) returns every row; ``tail=N`` (N>0) returns the last
    N; ``tail<=0`` returns ``[]`` (matches the prior ``_tail_jsonl(limit<=0)``
    helpers). Same never-raises contract as :func:`iter_jsonl`.
    """
    rows = list(iter_jsonl(path))
    if tail is None:
        return rows
    return rows[-tail:] if tail > 0 else []
