"""Public-safe env helpers for benchmark harnesses."""

from __future__ import annotations

import os
from pathlib import Path


def read_dotenv_status(path: Path) -> dict[str, bool]:
    if not path.exists():
        return {}
    status: dict[str, bool] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        status[key.strip()] = bool(value.strip())
    return status


def env_status(names: tuple[str, ...], *, dotenv_path: Path | None = None) -> dict[str, bool]:
    file_status = read_dotenv_status(dotenv_path) if dotenv_path else {}
    return {name: bool(os.environ.get(name)) or file_status.get(name, False) for name in names}


def missing_required(names: tuple[str, ...], *, dotenv_path: Path | None = None) -> list[str]:
    status = env_status(names, dotenv_path=dotenv_path)
    return [name for name, present in status.items() if not present]
