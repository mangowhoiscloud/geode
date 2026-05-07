"""Runtime state — cross-layer session state primitives.

Provides session checkpoint persistence and conversation transcript logging
that can be consumed by any layer (cli, agent, server) without creating
a layer violation.

Modules:
- :mod:`session_checkpoint` — `SessionState`, `SessionCheckpoint` (atomic JSON store)
- :mod:`transcript` — `SessionTranscript`, `cleanup_old_transcripts`
"""
