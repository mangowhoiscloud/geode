"""Process-neutral execution mode shared by session composition callers."""

from enum import StrEnum


class SessionMode(StrEnum):
    """Behavior profile for one agent session."""

    REPL = "repl"
    IPC = "ipc"
    DAEMON = "daemon"
    SCHEDULER = "scheduler"
