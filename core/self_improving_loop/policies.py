"""Policy SoT files for non-prompt mutation targets.

PR-6 C-5 of the cognitive-loop-uplift sprint
(``docs/plans/2026-05-21-cognitive-loop-uplift.md``).

Pre-PR-6 the self-improving loop's mutation target was *only* the
wrapper prompt — `wrapper-sections.json`. Tool selection policy,
decomposition policy, retrieval policy, and reflection policy were
hard-coded in Python and never participated in the
self-improvement loop.

This module introduces four sibling SoT files alongside
``wrapper-sections.json``:

  ============  ==============================================
  target_kind   SoT file
  ============  ==============================================
  prompt        wrapper-sections.json   (legacy — unchanged)
  tool_policy   tool-policy.json
  decomposition decomposition.json
  retrieval     retrieval.json
  reflection    reflection.json
  ============  ==============================================

Each file is a ``dict[str, str]`` (same schema as wrapper-sections so
operators learn one format). A mutation row carries ``target_kind``
plus ``target_section``; the runner dispatches to the matching file.

PR-6 stops at the *file format + dispatcher*. The Voyager-style
learning loops that actually exercise the new SoTs (curriculum +
skill library + critic) land as follow-ups; PR-6 just makes sure
the four files exist with stable read/write paths so the
infrastructure is committed before the policies that consume them.

Why no Voyager-style execution yet — Q4 simplicity: this PR ships
*one PR worth of expansion*, not a full curriculum loop. The
existing wrapper-prompt mutation path now goes through the same
dispatcher so a single ``apply_mutation`` call handles all five
kinds.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from core.paths import (
    GLOBAL_DECOMPOSITION_POLICY_PATH,
    GLOBAL_REFLECTION_POLICY_PATH,
    GLOBAL_RETRIEVAL_POLICY_PATH,
    GLOBAL_TOOL_POLICY_PATH,
    GLOBAL_WRAPPER_SECTIONS_PATH,
    LEGACY_SOT_DIR,
)

log = logging.getLogger(__name__)

# PR-RATCHET-1 (2026-05-21) — when the in-repo SoT path doesn't
# exist yet, fall back to the pre-RATCHET-1 ``~/.geode/self-improving-loop/``
# location. Operators upgrading an existing install have their last
# mutation state there; copying it forward on first read keeps the
# loop continuous across the migration without a manual step. The
# legacy file is preserved (not deleted) so an operator can roll back
# manually if needed.
_LEGACY_FILE_NAMES: dict[str, str] = {
    "prompt": "wrapper-sections.json",
    "tool_policy": "tool-policy.json",
    "decomposition": "decomposition.json",
    "retrieval": "retrieval.json",
    "reflection": "reflection.json",
}


def _maybe_migrate_legacy_sot(kind: str, new_path: Path) -> None:
    """Copy the pre-RATCHET-1 policy file to ``new_path`` if it
    exists and the new in-repo path doesn't yet. Idempotent — once
    the in-repo file is present the legacy copy is ignored on
    subsequent calls.

    Failures are logged but never raise — the caller's
    ``FileNotFoundError`` fallback (returning ``{}``) still produces
    a usable state. The catch is intentionally broad (``Exception``)
    because the migration is best-effort observability glue: a
    decode failure (e.g. non-UTF-8 legacy JSON, ``UnicodeDecodeError``)
    or any other unexpected condition should leave the caller free
    to fall through to the empty-policy state rather than crash the
    self-improving loop. Codex MCP review of PR-RATCHET-1 caught
    the original ``except OSError`` scope being too narrow.
    """
    if new_path.exists():
        return
    legacy_name = _LEGACY_FILE_NAMES.get(kind)
    if legacy_name is None:
        return
    legacy_path = LEGACY_SOT_DIR / legacy_name
    if not legacy_path.is_file():
        return
    try:
        new_path.parent.mkdir(parents=True, exist_ok=True)
        new_path.write_text(legacy_path.read_text(encoding="utf-8"), encoding="utf-8")
        log.info(
            "PR-RATCHET-1 migration: copied %s → %s (legacy preserved)",
            legacy_path,
            new_path,
        )
    except Exception:
        log.warning(
            "PR-RATCHET-1 migration: failed to copy %s → %s",
            legacy_path,
            new_path,
            exc_info=True,
        )


# Canonical list of target kinds. Order matters for the type-hint enum
# only — apply dispatch is by string key.
TARGET_KINDS: tuple[str, ...] = (
    "prompt",
    "tool_policy",
    "decomposition",
    "retrieval",
    "reflection",
)

# Each kind maps to the SoT file. ``prompt`` re-points to the legacy
# wrapper-sections SoT so older mutations replay unchanged.
_KIND_TO_PATH: dict[str, Path] = {
    "prompt": GLOBAL_WRAPPER_SECTIONS_PATH,
    "tool_policy": GLOBAL_TOOL_POLICY_PATH,
    "decomposition": GLOBAL_DECOMPOSITION_POLICY_PATH,
    "retrieval": GLOBAL_RETRIEVAL_POLICY_PATH,
    "reflection": GLOBAL_REFLECTION_POLICY_PATH,
}


def is_valid_target_kind(kind: str) -> bool:
    """Return True iff ``kind`` is one of the registered targets."""
    return kind in _KIND_TO_PATH


def policy_path(kind: str) -> Path:
    """Return the SoT file path for ``kind``.

    Raises :class:`ValueError` on unknown kinds so the runner can
    fail closed rather than silently writing to an unexpected file.
    """
    try:
        return _KIND_TO_PATH[kind]
    except KeyError as exc:
        raise ValueError(f"unknown target_kind {kind!r}; expected one of {TARGET_KINDS!r}") from exc


def load_policy(kind: str) -> dict[str, str]:
    """Read the ``dict[str, str]`` policy for ``kind``.

    Missing file returns ``{}`` so a freshly-installed GEODE behaves
    like an empty policy — the runner's mutation step populates it
    over time. Malformed JSON also returns ``{}`` with a WARN, never
    raises; the readers downstream (PR-5 attribution) must remain
    robust to incomplete state.

    PR-RATCHET-1 (2026-05-21) — lazy migration from the pre-PR
    ``~/.geode/self-improving-loop/`` location to the in-repo
    ``autoresearch/state/policies/`` location runs before the read.
    """
    path = policy_path(kind)
    _maybe_migrate_legacy_sot(kind, path)
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        log.warning(
            "policy file %s is not valid JSON; returning empty dict",
            path,
            exc_info=True,
        )
        return {}
    if not isinstance(payload, dict):
        log.warning(
            "policy file %s is %s, expected dict; returning empty",
            path,
            type(payload).__name__,
        )
        return {}
    # Coerce values to strings — same schema as wrapper-sections so
    # the contract is "string-keyed dict of string sections".
    return {k: str(v) for k, v in payload.items() if isinstance(k, str)}


def write_policy(kind: str, sections: dict[str, str]) -> Path:
    """Write the policy for ``kind`` to its SoT file, returning the
    written path. The dir is created if missing; the file is rewritten
    atomically (temp + rename) so concurrent readers never see a
    partial file.

    PR-RATCHET-1 (2026-05-21) — runs the lazy legacy-SoT migration
    before the write so a pre-PR-RATCHET-1 operator state at
    ``~/.geode/self-improving-loop/`` is captured in the in-repo
    location as the *previous* value of this kind, rather than being
    overwritten on the first mutation after upgrade.
    """
    path = policy_path(kind)
    _maybe_migrate_legacy_sot(kind, path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        {k: v for k, v in sections.items() if isinstance(k, str)},
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(payload + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


__all__ = [
    "TARGET_KINDS",
    "is_valid_target_kind",
    "load_policy",
    "policy_path",
    "write_policy",
]
