"""Small durable-file helpers shared by Crucible command surfaces."""

from __future__ import annotations

import json
import os
import stat
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .contract import ContractError

DEFAULT_JSON_LIMIT_BYTES = 16 * 1024 * 1024


def load_json_object(
    path: Path,
    field: str,
    *,
    max_bytes: int = DEFAULT_JSON_LIMIT_BYTES,
) -> dict[str, Any]:
    """Load one JSON object with a stable Crucible error."""

    try:
        info = path.lstat()
    except OSError as exc:
        raise ContractError(f"cannot read {field} {path}: {exc}") from exc
    if not stat.S_ISREG(info.st_mode):
        raise ContractError(f"{field} must be a regular file: {path}")
    if info.st_size > max_bytes:
        raise ContractError(f"{field} exceeds {max_bytes} bytes: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read {field} {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ContractError(f"{field} must be a JSON object")
    return value


def write_exclusive_json(path: Path, payload: Mapping[str, Any]) -> None:
    """Create one immutable JSON artifact and refuse replacement."""

    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (
        json.dumps(
            payload,
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n"
    )
    descriptor, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=path.parent,
        text=True,
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temp_path, path)
        except FileExistsError as exc:
            raise ContractError(f"refusing to overwrite immutable artifact: {path}") from exc
    finally:
        temp_path.unlink(missing_ok=True)


def atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    """Replace a mutable state snapshot atomically."""

    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (
        json.dumps(
            payload,
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n"
    )
    descriptor, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=path.parent,
        text=True,
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def append_jsonl(path: Path, payload: Mapping[str, Any]) -> None:
    """Append one bounded record with one write and an fsync."""

    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode("utf-8")
    descriptor = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        view = memoryview(encoded)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:  # pragma: no cover - defensive OS contract
                raise OSError("short JSONL append")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def contained_path(root: Path, relative: str, field: str) -> Path:
    """Resolve an artifact path without allowing traversal outside ``root``."""

    candidate = Path(relative)
    if candidate.is_absolute():
        raise ContractError(f"{field} must be relative to the attempt directory")
    resolved_root = root.resolve()
    resolved = (resolved_root / candidate).resolve()
    if not resolved.is_relative_to(resolved_root):
        raise ContractError(f"{field} escapes the attempt directory")
    return resolved
