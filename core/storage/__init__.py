"""Storage primitives — SQLite helpers shared across memory backends.

PR-Hermes-1c (2026-05-22) introduced this package with
``fts_helpers.py``: FTS5 query sanitisation + trigram capability
detection used by ``core/memory/session_manager.py``'s text-search
indices. Future storage adapters (sled / DuckDB / Postgres) would land
sibling modules here.
"""

from __future__ import annotations
