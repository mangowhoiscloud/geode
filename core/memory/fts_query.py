"""FTS5 query sanitisation + capability detection.

PR-Hermes-1c (2026-05-22) absorbs the Hermes ``_sanitize_fts5_query``
pattern (``hermes_state.py:1796``) for the per-project SQLite text
indices added in ``core/memory/session_manager.py``.

**Why sanitisation matters**: FTS5's query syntax reserves a handful
of metacharacters — ``-`` is the NOT operator, ``.`` is a token
separator, ``"`` opens a phrase. Operator queries that come in as
"file-not-found" or "v3.34" get parsed as boolean expressions and
either error or return zero rows. Hermes' fix is to detect
non-alphanumeric tokens and wrap them in escaped double quotes so
they're treated as literal phrase tokens.

**Capability detection**: SQLite ships ``unicode61`` (case+diacritic
fold) in every FTS5 build but ``trigram`` only landed in 3.34 (2020).
GEODE's minimum runtime can't assume 3.34+, so the session_manager
guards trigram table creation with :func:`has_trigram_support`. The
unicode61 index covers most full-word recall; the trigram index is the
substring-recall booster (Korean / Japanese partial-word search,
identifier-fragment matching). Missing trigram = graceful degradation,
not a hard failure.
"""

from __future__ import annotations

import contextlib
import logging
import re
import sqlite3
from collections.abc import Iterable

log = logging.getLogger(__name__)

__all__ = [
    "FTS5_META_CHARS",
    "has_trigram_support",
    "sanitize_fts5_query",
]

# FTS5 metacharacters that break a query when they appear unquoted. We
# don't try to support FTS5's full operator grammar (the operator-side
# caller doesn't write FTS5 by hand) — instead we treat any token
# containing these as a literal phrase.
FTS5_META_CHARS: frozenset[str] = frozenset({"-", ".", ":", "(", ")", "*", "^", "+"})

# Whitelist for "this token is safe as a bare FTS5 word": ASCII alnum +
# the underscore + any non-ASCII letter / digit (Unicode). Anything else
# triggers double-quote wrapping.
_BARE_TOKEN_RE = re.compile(r"\A[A-Za-z0-9_À-￿]+\Z")


def sanitize_fts5_query(raw: str) -> str:
    """Escape ``raw`` so it can be passed to ``SELECT ... MATCH ?``.

    Algorithm (Hermes parity):

    1. Split ``raw`` on whitespace into tokens.
    2. Drop empty tokens and tokens that are *purely* FTS5 metacharacters
       (e.g. a bare ``"-"`` left over from a hyphen-split query).
    3. For each remaining token:

       * If it matches :data:`_BARE_TOKEN_RE` (pure alnum / underscore /
         Unicode letter), keep it bare.
       * Otherwise wrap it in double quotes, escaping any literal ``"``
         to ``""`` (FTS5 phrase-escape convention).

    4. Join tokens with single spaces. Empty input → ``""``.

    Returns a string the caller can pass directly to ``MATCH ?`` without
    risking an FTS5 syntax error.
    """
    if not raw:
        return ""
    tokens = raw.split()
    cleaned: list[str] = []
    for tok in tokens:
        if not tok:
            continue
        if all(ch in FTS5_META_CHARS for ch in tok):
            # Pure metacharacter token (e.g. "-") — drop entirely. Keeping
            # it would yield "" inside the wrapped quotes or, worse, a
            # bare hyphen that FTS5 reads as NOT.
            continue
        if _BARE_TOKEN_RE.match(tok):
            cleaned.append(tok)
        else:
            escaped = tok.replace('"', '""')
            cleaned.append(f'"{escaped}"')
    return " ".join(cleaned)


def has_trigram_support(conn: sqlite3.Connection) -> bool:
    """Probe whether the underlying SQLite build supports ``tokenize='trigram'``.

    Runs a one-shot ``CREATE VIRTUAL TABLE ... USING fts5(... tokenize='trigram')``
    on a throwaway name and drops it. SQLite ≥ 3.34 has trigram baked
    in; older builds raise ``sqlite3.OperationalError``. Returns
    ``False`` on any exception so the caller can downgrade gracefully
    rather than crash the whole DB init.
    """
    probe_name = "_geode_trigram_probe"
    try:
        conn.execute(f"CREATE VIRTUAL TABLE {probe_name} USING fts5(c, tokenize='trigram')")
    except sqlite3.OperationalError as exc:
        log.debug("trigram capability probe failed: %s", exc)
        return False
    except Exception as exc:  # pragma: no cover — defensive
        log.debug("trigram capability probe unexpected error: %s", exc)
        return False
    with contextlib.suppress(Exception):
        # Best-effort cleanup; leaving the probe table behind is harmless.
        conn.execute(f"DROP TABLE {probe_name}")
    return True


def fts_index_columns(_columns: Iterable[str]) -> str:
    """Render an FTS5 column spec (no rowid / control args).

    Tiny helper so the session_manager's schema strings stay readable
    when adding/removing indexed columns. Kept here so future storage
    adapters reuse the same convention.
    """
    return ", ".join(_columns)
