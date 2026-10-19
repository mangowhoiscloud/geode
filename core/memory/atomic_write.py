"""Atomic file I/O — crash-safe write via tmp+rename.

Prevents data corruption when the process is interrupted mid-write.
Pattern extracted from ``core/memory/session.py:_persist()``.

Usage::

    from core.memory.atomic_write import atomic_write_text, atomic_write_json

    atomic_write_text(path, content)
    atomic_write_json(path, data, indent=2)
"""

from __future__ import annotations

import fcntl
import json
import logging
import os
import tempfile
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)
_JSONL_APPEND_LOCK = threading.Lock()


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


@contextmanager
def exclusive_file_lock(lock_path: Path, *, timeout_s: float = 10.0) -> Iterator[None]:
    """Hold an exclusive ``flock`` on *lock_path* for one read-modify-write.

    The lock lives on its own inode next to the data: ``atomic_write_text``
    replaces the data file, so a lock on the data file itself would be lost
    by the very write it protects. Separate descriptors exclude each other,
    so this serializes threads as well as processes, and the kernel drops the
    lock when its holder dies. The lock file is opened without following a
    symlink and created owner-only.

    Raises:
        TimeoutError: The lock was not acquired within *timeout_s*.
    """
    lock_path = Path(lock_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        deadline = time.monotonic() + timeout_s
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"Could not acquire lock: {lock_path}") from None
                time.sleep(0.02)
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


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


def append_jsonl(
    path: Path,
    record: dict[str, Any],
    *,
    ensure_ascii: bool = False,
    default: Callable[..., Any] | None = None,
    encoding: str = "utf-8",
) -> None:
    """Append one JSON object as one newline-terminated JSONL row.

    This is the L0 write companion to :func:`iter_jsonl` /
    :func:`read_jsonl`: callers get a shared, lock-serialised append
    primitive instead of open-coded ``open("a")`` writers. Higher-level
    append-only sinks still own pruning and layout policy.
    """
    path = Path(path)
    line = json.dumps(
        record,
        ensure_ascii=ensure_ascii,
        default=default or str,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with _JSONL_APPEND_LOCK, path.open("a", encoding=encoding) as handle:
        handle.write(line + "\n")


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
