"""Unified entry-point logging configuration.

S-6 observability audit (2026-06-11): each entry point configured logging
independently — ``serve`` had a RotatingFileHandler to
``~/.geode/logs/serve.log`` while ``geode-mcp`` / worker / campaign logged
to stderr only, so their diagnostics vanished with the process. This
module is the single switchboard: every entry point calls
:func:`configure_logging` with its mode and gets the same
formatter + stderr stream + per-mode rotating file under
``~/.geode/logs/``.

Mode notes:
- ``serve`` keeps its pre-existing contract — ``SERVE_LOG_PATH`` location
  and 10MB x5 rotation (``cmd_lifecycle`` status reads that path).
- ``campaign`` keeps its bare ``%(message)s`` console format (the phase
  digest is operator-facing console output) but gains the file handler
  with the full format.
- ``cli`` (thin REPL) intentionally has no file handler — it is a short-
  lived client whose runtime lives in the serve daemon.
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from core.paths import GEODE_HOME, SERVE_LOG_PATH

LOGS_DIR: Path = GEODE_HOME / "logs"

_FILE_FORMAT = "%(asctime)s %(name)s %(levelname)s %(message)s"
_DEFAULT_MAX_BYTES = 10 * 1024 * 1024
_DEFAULT_BACKUP_COUNT = 5

#: mode -> (log file path or None, console format)
_MODE_SPECS: dict[str, tuple[Path | None, str]] = {
    "serve": (SERVE_LOG_PATH, _FILE_FORMAT),
    "mcp": (LOGS_DIR / "mcp.log", _FILE_FORMAT),
    "worker": (LOGS_DIR / "worker.log", _FILE_FORMAT),
    "campaign": (LOGS_DIR / "campaign.log", "%(message)s"),
    "cli": (None, _FILE_FORMAT),
}


def configure_logging(mode: str, *, level: int = logging.INFO) -> None:
    """Install the unified handler set for a GEODE entry point.

    Replaces any pre-existing root handlers (an imported module may have
    called ``basicConfig`` already) so handlers never double-log — same
    discipline the serve entry point established.
    """
    if mode not in _MODE_SPECS:
        raise ValueError(f"unknown logging mode {mode!r} (known: {sorted(_MODE_SPECS)})")
    log_file, console_format = _MODE_SPECS[mode]

    root = logging.getLogger()
    root.setLevel(level)
    for handler in list(root.handlers):
        root.removeHandler(handler)

    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setLevel(level)
    stream_handler.setFormatter(logging.Formatter(console_format))
    root.addHandler(stream_handler)

    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=_DEFAULT_MAX_BYTES,
            backupCount=_DEFAULT_BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(logging.Formatter(_FILE_FORMAT))
        root.addHandler(file_handler)
        logging.getLogger(__name__).info(
            "%s log opened: %s (10MB x%d rotation)", mode, log_file, _DEFAULT_BACKUP_COUNT
        )
