"""ADR-012 M4.1 — DPO canonical pack JSONL writer invariants.

Pins:
- ``build_dpo_pack`` reads ``eval_response_recorded`` events (M4.0
  output) and writes one JSONL row per ``(prompt, chosen, rejected)``
  tuple.
- Pairing: top-fitness chosen × bottom-fitness rejected — clearest
  margin per prompt.
- Idempotency: re-running over the same journals + pack file appends
  zero new rows (signature-keyed dedup).
- Graceful: missing journals → empty pack, no exception. Malformed
  JSONL lines silently dropped.
- ``fitness_delta = fitness_chosen - fitness_rejected``.
- Prompts with chosen-only or rejected-only piles counted as
  ``prompts_unpaired`` — no row written.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from core.observability.session_journal import (
    SessionJournal,
    session_journal_scope,
)
from core.self_improving_loop.dpo_pack import (
    BuildResult,
    build_dpo_pack,
    pair_signature,
)
from core.self_improving_loop.eval_journaling import emit_eval_response_recorded


@pytest.fixture
def journal_path(tmp_path: Path) -> Iterator[Path]:
    yield tmp_path / "session-A" / "transcript.jsonl"


@pytest.fixture
def pack_path(tmp_path: Path) -> Iterator[Path]:
    yield tmp_path / "dpo" / "pack.jsonl"


def _journal(path: Path, session_id: str = "test") -> SessionJournal:
    return SessionJournal(
        session_id=session_id,
        gen_tag="auto",
        component="test",
        path=path,
    )


def _read_pack(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


# Signature ------------------------------------------------------------------


def test_pair_signature_is_deterministic() -> None:
    sig1 = pair_signature("p", "good", "bad")
    sig2 = pair_signature("p", "good", "bad")
    assert sig1 == sig2
    assert len(sig1) == 16


def test_pair_signature_differs_on_any_field() -> None:
    base = pair_signature("p", "good", "bad")
    assert pair_signature("p2", "good", "bad") != base
    assert pair_signature("p", "good2", "bad") != base
    assert pair_signature("p", "good", "bad2") != base
    # Field-order can't collide with separator collapse — pin via empty fields.
    assert pair_signature("a", "", "b") != pair_signature("", "a", "b")


# Empty / missing inputs -----------------------------------------------------


def test_build_with_no_journals_returns_zero(pack_path: Path) -> None:
    result = build_dpo_pack(journal_paths=[], pack_path=pack_path)
    assert result == BuildResult(
        pairs_appended=0,
        pairs_skipped_duplicate=0,
        events_seen=0,
        prompts_unpaired=0,
    )
    assert not pack_path.exists()


def test_build_with_missing_journal_file_graceful(tmp_path: Path, pack_path: Path) -> None:
    """Missing journal file is treated as empty — no exception, no pack file."""
    missing = tmp_path / "nope.jsonl"
    result = build_dpo_pack(journal_paths=[missing], pack_path=pack_path)
    assert result.events_seen == 0
    assert result.pairs_appended == 0


# Pairing rule ---------------------------------------------------------------


def test_pairs_chosen_with_rejected_for_same_prompt(journal_path: Path, pack_path: Path) -> None:
    with session_journal_scope(_journal(journal_path)):
        emit_eval_response_recorded(prompt="explain DPO", response="good answer", fitness_score=0.9)
        emit_eval_response_recorded(
            prompt="explain DPO",
            response="bad answer",
            fitness_score=0.2,
            rollback_flag=True,
        )
    result = build_dpo_pack(journal_paths=[journal_path], pack_path=pack_path)
    assert result.pairs_appended == 1
    assert result.prompts_unpaired == 0
    rows = _read_pack(pack_path)
    assert len(rows) == 1
    assert rows[0]["prompt"] == "explain DPO"
    assert rows[0]["chosen"] == "good answer"
    assert rows[0]["rejected"] == "bad answer"
    assert rows[0]["fitness_chosen"] == 0.9
    assert rows[0]["fitness_rejected"] == 0.2
    assert rows[0]["fitness_delta"] == pytest.approx(0.7)


def test_picks_highest_chosen_and_lowest_rejected(journal_path: Path, pack_path: Path) -> None:
    """Three chosen + three rejected → top × bottom (steepest margin)."""
    with session_journal_scope(_journal(journal_path)):
        for resp, fit in [("good_low", 0.5), ("good_top", 0.95), ("good_mid", 0.7)]:
            emit_eval_response_recorded(prompt="q", response=resp, fitness_score=fit)
        for resp, fit in [("bad_high", 0.4), ("bad_bottom", 0.05), ("bad_mid", 0.2)]:
            emit_eval_response_recorded(
                prompt="q", response=resp, fitness_score=fit, rollback_flag=True
            )
    build_dpo_pack(journal_paths=[journal_path], pack_path=pack_path)
    rows = _read_pack(pack_path)
    assert len(rows) == 1
    assert rows[0]["chosen"] == "good_top"
    assert rows[0]["rejected"] == "bad_bottom"
    assert rows[0]["fitness_delta"] == pytest.approx(0.95 - 0.05)


def test_chosen_only_prompt_counted_as_unpaired(journal_path: Path, pack_path: Path) -> None:
    """No rollback → no rejected → no pair, but events still counted."""
    with session_journal_scope(_journal(journal_path)):
        emit_eval_response_recorded(prompt="q", response="a", fitness_score=0.8)
    result = build_dpo_pack(journal_paths=[journal_path], pack_path=pack_path)
    assert result.events_seen == 1
    assert result.pairs_appended == 0
    assert result.prompts_unpaired == 1
    assert not pack_path.exists()  # no rows = no file


def test_rejected_only_prompt_counted_as_unpaired(journal_path: Path, pack_path: Path) -> None:
    with session_journal_scope(_journal(journal_path)):
        emit_eval_response_recorded(prompt="q", response="a", fitness_score=0.1, rollback_flag=True)
    result = build_dpo_pack(journal_paths=[journal_path], pack_path=pack_path)
    assert result.prompts_unpaired == 1
    assert result.pairs_appended == 0


# Idempotency ----------------------------------------------------------------


def test_rerun_skips_duplicates(journal_path: Path, pack_path: Path) -> None:
    """Re-running the builder over the same journal appends zero new rows."""
    with session_journal_scope(_journal(journal_path)):
        emit_eval_response_recorded(prompt="q", response="good", fitness_score=0.9)
        emit_eval_response_recorded(
            prompt="q", response="bad", fitness_score=0.1, rollback_flag=True
        )
    first = build_dpo_pack(journal_paths=[journal_path], pack_path=pack_path)
    second = build_dpo_pack(journal_paths=[journal_path], pack_path=pack_path)
    assert first.pairs_appended == 1
    assert second.pairs_appended == 0
    assert second.pairs_skipped_duplicate == 1
    assert len(_read_pack(pack_path)) == 1


def test_new_pair_appended_on_rerun(journal_path: Path, pack_path: Path) -> None:
    """Fresh prompt added to journal → second invocation appends just that pair."""
    journal = _journal(journal_path)
    with session_journal_scope(journal):
        emit_eval_response_recorded(prompt="q1", response="g", fitness_score=0.9)
        emit_eval_response_recorded(
            prompt="q1", response="b", fitness_score=0.1, rollback_flag=True
        )
    build_dpo_pack(journal_paths=[journal_path], pack_path=pack_path)
    with session_journal_scope(journal):
        emit_eval_response_recorded(prompt="q2", response="g2", fitness_score=0.8)
        emit_eval_response_recorded(
            prompt="q2", response="b2", fitness_score=0.2, rollback_flag=True
        )
    second = build_dpo_pack(journal_paths=[journal_path], pack_path=pack_path)
    assert second.pairs_appended == 1
    assert second.pairs_skipped_duplicate == 1
    rows = _read_pack(pack_path)
    prompts = sorted(r["prompt"] for r in rows)
    assert prompts == ["q1", "q2"]


# Multi-journal --------------------------------------------------------------


def test_multi_journal_merge(tmp_path: Path, pack_path: Path) -> None:
    """Two journals (different sessions) feed the same prompt → cross-session pair."""
    j1 = tmp_path / "s1" / "transcript.jsonl"
    j2 = tmp_path / "s2" / "transcript.jsonl"
    with session_journal_scope(_journal(j1, session_id="s1")):
        emit_eval_response_recorded(
            prompt="shared", response="great", fitness_score=0.95, source="petri_audit"
        )
    with session_journal_scope(_journal(j2, session_id="s2")):
        emit_eval_response_recorded(
            prompt="shared",
            response="awful",
            fitness_score=0.05,
            rollback_flag=True,
            source="live_session",
        )
    result = build_dpo_pack(journal_paths=[j1, j2], pack_path=pack_path)
    assert result.pairs_appended == 1
    row = _read_pack(pack_path)[0]
    assert row["session_id_chosen"] == "s1"
    assert row["session_id_rejected"] == "s2"
    assert row["source_chosen"] == "petri_audit"
    assert row["source_rejected"] == "live_session"


# Malformed input ------------------------------------------------------------


def test_malformed_lines_silently_dropped(tmp_path: Path, pack_path: Path) -> None:
    """Bad JSON / wrong event / missing payload fields → skipped, no crash."""
    journal_p = tmp_path / "j.jsonl"
    journal_p.parent.mkdir(parents=True, exist_ok=True)
    valid_chosen = json.dumps(
        {
            "ts": 1.0,
            "session_id": "s",
            "gen_tag": "g",
            "component": "c",
            "level": "info",
            "event": "eval_response_recorded",
            "payload": {
                "prompt": "q",
                "response": "good",
                "fitness_score": 0.9,
                "rollback_flag": False,
                "source": "",
            },
        }
    )
    valid_rejected = json.dumps(
        {
            "ts": 2.0,
            "session_id": "s",
            "gen_tag": "g",
            "component": "c",
            "level": "info",
            "event": "eval_response_recorded",
            "payload": {
                "prompt": "q",
                "response": "bad",
                "fitness_score": 0.1,
                "rollback_flag": True,
                "source": "",
            },
        }
    )
    journal_p.write_text(
        "\n".join(
            [
                "not json at all",
                "{}",  # missing event
                json.dumps({"event": "different_event", "payload": {}}),
                json.dumps(
                    {
                        "event": "eval_response_recorded",
                        "payload": {"prompt": "x"},  # missing response/fitness
                    }
                ),
                json.dumps(
                    {
                        "event": "eval_response_recorded",
                        "payload": {
                            "prompt": "y",
                            "response": "r",
                            "fitness_score": "not_a_number",
                        },
                    }
                ),
                valid_chosen,
                valid_rejected,
                "",  # empty line
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    result = build_dpo_pack(journal_paths=[journal_p], pack_path=pack_path)
    assert result.events_seen == 2  # only the two valid rows
    assert result.pairs_appended == 1
