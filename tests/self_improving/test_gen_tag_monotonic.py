"""PR-GEN-COUNTER (2026-05-26) — monotonic gen_tag counter pin.

Closes the silent leak surfaced in the 2026-05-26 autoresearch
attribution sprint Phase A audit (§5.6):

* Pre-PR ``_resolve_gen_tag(commit)`` returned ``autoresearch-{commit}``
  deterministically — same commit + repeated audits = same gen_tag.
* Attribution rows at that commit collapsed into one synthetic
  generation; outer-loop diagnostics couldn't decompose cross-cycle
  signal.

Post-PR ``_resolve_gen_tag`` returns ``autoresearch-{commit}-gen{N}``
where N is read from sessions.jsonl history and incremented. This
file pins:

1. Fresh history (no sessions.jsonl) → first call returns ``gen1``.
2. History with ``gen3`` for this commit → next call returns ``gen4``.
3. Legacy history (no ``-gen{N}`` suffix) → treated as ``gen0``,
   next call returns ``gen1``.
4. ``AUTORESEARCH_GEN_TAG`` operator override still wins (counter
   ignored).
5. Different commit's prior history doesn't bleed (per-commit
   isolation).
6. Malformed JSONL rows are skipped gracefully (one bad row
   doesn't abort).
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest


def _write_session(
    path: Path,
    *,
    gen_tag: str,
    session_id: str = "session-x",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "session_id": session_id,
        "gen_tag": gen_tag,
        "component": "autoresearch",
        "started_at": 0.0,
        "ended_at": 1.0,
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")


def test_fresh_history_returns_gen1(tmp_path: Path) -> None:
    """No sessions.jsonl yet → first gen_tag emission is gen1."""
    from core.self_improving.train import _next_gen_counter_for_commit

    n = _next_gen_counter_for_commit("abc1234", sessions_path=tmp_path / "missing.jsonl")
    assert n == 1


def test_history_with_existing_gen_n_increments(tmp_path: Path) -> None:
    """history has gen1 + gen3 for this commit → next is gen4."""
    from core.self_improving.train import _next_gen_counter_for_commit

    sessions = tmp_path / "sessions.jsonl"
    _write_session(sessions, gen_tag="autoresearch-abc1234-gen1")
    _write_session(sessions, gen_tag="autoresearch-abc1234-gen3")

    n = _next_gen_counter_for_commit("abc1234", sessions_path=sessions)
    assert n == 4


def test_legacy_no_suffix_treated_as_gen0_so_next_is_gen1(tmp_path: Path) -> None:
    """Pre-PR rows had ``autoresearch-{commit}`` with no ``-gen{N}``
    suffix — those count as gen0; next emission is gen1."""
    from core.self_improving.train import _next_gen_counter_for_commit

    sessions = tmp_path / "sessions.jsonl"
    _write_session(sessions, gen_tag="autoresearch-abc1234")  # legacy
    _write_session(sessions, gen_tag="autoresearch-abc1234")  # legacy dup

    n = _next_gen_counter_for_commit("abc1234", sessions_path=sessions)
    assert n == 1


def test_legacy_mixed_with_gen_n(tmp_path: Path) -> None:
    """Mix of legacy (no suffix) + ``-gen{N}`` rows → max(N) + 1
    ignores the legacy ones."""
    from core.self_improving.train import _next_gen_counter_for_commit

    sessions = tmp_path / "sessions.jsonl"
    _write_session(sessions, gen_tag="autoresearch-abc1234")  # legacy → gen0
    _write_session(sessions, gen_tag="autoresearch-abc1234-gen2")
    _write_session(sessions, gen_tag="autoresearch-abc1234-gen5")

    n = _next_gen_counter_for_commit("abc1234", sessions_path=sessions)
    assert n == 6


def test_other_commit_does_not_bleed(tmp_path: Path) -> None:
    """sessions.jsonl has gen5 for *other* commit → our commit's
    counter stays at gen1 (per-commit isolation)."""
    from core.self_improving.train import _next_gen_counter_for_commit

    sessions = tmp_path / "sessions.jsonl"
    _write_session(sessions, gen_tag="autoresearch-other7890-gen5")

    n = _next_gen_counter_for_commit("abc1234", sessions_path=sessions)
    assert n == 1


def test_operator_override_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    """AUTORESEARCH_GEN_TAG env override skips the counter entirely —
    operator pins the tag for cross-process consistency."""
    from core.self_improving.train import _resolve_gen_tag

    monkeypatch.setenv("AUTORESEARCH_GEN_TAG", "custom-pinned-tag-v3")

    assert _resolve_gen_tag("abc1234") == "custom-pinned-tag-v3"


def test_resolve_emits_gen_n_format_by_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Without override and with empty history → emits
    ``autoresearch-{commit}-gen1`` (post-PR shape)."""
    from core.self_improving import train as train_mod

    monkeypatch.delenv("AUTORESEARCH_GEN_TAG", raising=False)
    monkeypatch.setattr(train_mod, "SESSIONS_INDEX_PATH", tmp_path / "missing.jsonl")

    tag = train_mod._resolve_gen_tag("abc1234")
    assert tag == "autoresearch-abc1234-gen1"


def test_resolve_increments_with_real_history(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """End-to-end pin: writing one gen1 row + calling _resolve_gen_tag
    returns gen2 — the SESSIONS_INDEX_PATH lookup actually wires the
    counter into the resolver, not just into the private helper."""
    from core.self_improving import train as train_mod

    monkeypatch.delenv("AUTORESEARCH_GEN_TAG", raising=False)
    sessions = tmp_path / "sessions.jsonl"
    _write_session(sessions, gen_tag="autoresearch-abc1234-gen1")
    monkeypatch.setattr(train_mod, "SESSIONS_INDEX_PATH", sessions)

    tag = train_mod._resolve_gen_tag("abc1234")
    assert tag == "autoresearch-abc1234-gen2"


def test_malformed_json_row_skipped_gracefully(tmp_path: Path) -> None:
    """One malformed JSON line in the middle of sessions.jsonl must
    not abort the scan — the good rows around it should still be
    parsed."""
    from core.self_improving.train import _next_gen_counter_for_commit

    sessions = tmp_path / "sessions.jsonl"
    _write_session(sessions, gen_tag="autoresearch-abc1234-gen1")
    with sessions.open("a", encoding="utf-8") as fh:
        fh.write("{ this is not valid JSON\n")
        fh.write("\n")  # blank line
    _write_session(sessions, gen_tag="autoresearch-abc1234-gen3")

    n = _next_gen_counter_for_commit("abc1234", sessions_path=sessions)
    assert n == 4


def test_non_dict_row_skipped(tmp_path: Path) -> None:
    """JSON arrays / scalars in sessions.jsonl (shouldn't happen, but
    defensive) are skipped without aborting."""
    from core.self_improving.train import _next_gen_counter_for_commit

    sessions = tmp_path / "sessions.jsonl"
    sessions.write_text('[1, 2, 3]\n"just a string"\n', encoding="utf-8")
    _write_session(sessions, gen_tag="autoresearch-abc1234-gen2")

    n = _next_gen_counter_for_commit("abc1234", sessions_path=sessions)
    assert n == 3


def test_oserror_during_read_returns_gen1(tmp_path: Path) -> None:
    """Permission error / IO failure during read → fall through to
    gen1 (best-effort). The audit cycle should never crash because
    sessions.jsonl is unreadable."""
    from core.self_improving.train import _next_gen_counter_for_commit

    sessions = tmp_path / "sessions.jsonl"
    sessions.write_text("dummy\n", encoding="utf-8")

    with patch.object(Path, "open", side_effect=OSError("disk full")):
        n = _next_gen_counter_for_commit("abc1234", sessions_path=sessions)
    assert n == 1
