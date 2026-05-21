"""OL-AUDIT-BURST-FIX — audit burst serialisation invariants.

Three fixes ship together (all addressing the same defect: 429 storm
when Anthropic Max OAuth subscription is shared between host Claude
Code + audit subprocess + inspect_ai's 10-default-connection burst):

FIX-1 — ``_build_audit_command`` argv pins ``--max-connections 1``
        (inspect_ai default is 10 per provider).

FIX-2 — same argv pins ``--max-samples 1`` (serialises inspect_ai's
        per-sample parallelism on top of per-connection).

FIX-3 — ``core/llm/audit_lane.py`` module-level Lane (max_concurrent=1,
        15-min timeout) wraps the ``subprocess.run`` call so cron +
        manual audit invocations can't overlap on the host.

Together these match Paperclip's empirical success pattern of "1 active
agent process at a time, serial-turn loop inside" which stays under
Max OAuth's ~5 req/sec soft limit. Pre-fix the audit fired 30 concurrent
requests, hit 429 instantly, retried with 769s backoff, hit 17-min
timeout with 0 samples completed.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# FIX-1 + FIX-2 — argv flags
# ---------------------------------------------------------------------------


def test_audit_argv_pins_max_connections_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """FIX-1 — ``--max-connections 1`` present in argv."""
    from autoresearch import train

    argv = train._build_audit_command()
    # Look for the flag + the immediate next-arg value
    assert "--max-connections" in argv, (
        "OL-AUDIT-BURST-FIX FIX-1 regressed: --max-connections missing — "
        "inspect_ai default 10 will re-introduce 429 storm under Max OAuth."
    )
    idx = argv.index("--max-connections")
    assert argv[idx + 1] == "1"


def test_audit_argv_pins_max_samples_one() -> None:
    """FIX-2 — ``--max-samples 1`` present in argv."""
    from autoresearch import train

    argv = train._build_audit_command()
    assert "--max-samples" in argv, (
        "OL-AUDIT-BURST-FIX FIX-2 regressed: --max-samples missing — "
        "inspect_ai's per-sample parallelism will reburst connections."
    )
    idx = argv.index("--max-samples")
    assert argv[idx + 1] == "1"


def test_audit_argv_order_flags_before_use_oauth() -> None:
    """The burst-fix flags must come BEFORE ``--use-oauth`` so flag-
    parser ordering doesn't drop them when ``--use-oauth`` is the
    sentinel for OAuth path."""
    from autoresearch import train

    argv = train._build_audit_command()
    if "--use-oauth" in argv:
        assert argv.index("--max-connections") < argv.index("--use-oauth")
        assert argv.index("--max-samples") < argv.index("--use-oauth")


def test_audit_argv_source_payg_skips_use_oauth() -> None:
    """When operator pins ``source=api_key`` (PAYG), argv excludes
    ``--use-oauth`` but still has the burst-fix flags."""
    from autoresearch import train

    # Inject a fake config with source=api_key
    class _PaygCfg:
        budget_minutes = 5
        target_model = "claude-opus-4-7"
        judge_model = "claude-opus-4-7"
        source = "api_key"
        seed_limit = 2
        seed_select = "plugins/petri_audit/seeds"
        dim_set = "5axes"
        max_turns = 5

    import contextlib

    with contextlib.suppress(AttributeError):
        from unittest.mock import patch

        with patch("autoresearch.train._get_autoresearch_config", return_value=_PaygCfg()):
            argv = train._build_audit_command()
    assert "--use-oauth" not in argv, "source=api_key must NOT use OAuth"
    assert "--max-connections" in argv
    assert "--max-samples" in argv


# ---------------------------------------------------------------------------
# FIX-3 — audit lane
# ---------------------------------------------------------------------------


def test_audit_lane_singleton_default_capacity() -> None:
    """Lane singleton initialises with ``max_concurrent=1`` and the
    canonical name surface (matches Paperclip's 1-agent-at-a-time
    pattern)."""
    from core.llm.audit_lane import AUDIT_LANE_NAME, AUDIT_LANE_TIMEOUT_S, get_audit_lane

    lane = get_audit_lane()
    assert lane.name == AUDIT_LANE_NAME == "autoresearch-audit"
    assert lane.max_concurrent == 1
    assert lane.timeout_s == AUDIT_LANE_TIMEOUT_S == 900.0


def test_audit_lane_singleton_is_stable() -> None:
    """Repeat calls to ``get_audit_lane`` return the same instance —
    not a new Lane per call (would defeat serialisation)."""
    from core.llm.audit_lane import get_audit_lane

    assert get_audit_lane() is get_audit_lane()


def test_acquire_audit_lane_serialises_sequential_holders() -> None:
    """Two sequential acquires both succeed; the second waits for the
    first to release."""
    from core.llm.audit_lane import acquire_audit_lane, get_audit_lane

    lane = get_audit_lane()
    with acquire_audit_lane("session-1"):
        assert lane.active_count == 1
    assert lane.active_count == 0
    with acquire_audit_lane("session-2"):
        assert lane.active_count == 1


def test_acquire_audit_lane_blocks_concurrent_holder() -> None:
    """While one holder owns the lane, a second concurrent acquire
    blocks until the first releases. We verify by spawning a thread
    that records timestamps."""
    import time

    from core.llm.audit_lane import acquire_audit_lane

    hold_seconds = 0.3
    release_times: list[float] = []

    def _worker(key: str) -> None:
        with acquire_audit_lane(key):
            release_times.append(time.time())
            time.sleep(hold_seconds)

    t1 = threading.Thread(target=_worker, args=("a",))
    t2 = threading.Thread(target=_worker, args=("b",))
    start = time.time()
    t1.start()
    time.sleep(0.05)  # ensure t1 grabs first
    t2.start()
    t1.join(timeout=2.0)
    t2.join(timeout=2.0)
    assert len(release_times) == 2
    # Second holder must have acquired AFTER first released
    # (with a small slack for thread scheduling)
    gap = release_times[1] - release_times[0]
    assert gap >= hold_seconds - 0.05, (
        f"FIX-3 regressed: second holder acquired too quickly ({gap:.3f}s); "
        f"lane should have serialised — expected >= {hold_seconds}s gap."
    )
    elapsed = time.time() - start
    assert elapsed >= hold_seconds * 2 - 0.1


def test_audit_train_source_grep_pins_lane_integration() -> None:
    """Source-level pin: ``autoresearch/train.py`` must call the audit
    lane around the subprocess. A future refactor that drops the
    ``with acquire_audit_lane(...)`` wrapper re-introduces the
    overlapping-audit race.
    """
    from autoresearch import train

    source = Path(train.__file__).read_text(encoding="utf-8")
    assert "from core.llm.audit_lane import acquire_audit_lane" in source, (
        "FIX-3 regressed: autoresearch/train.py no longer imports the audit lane."
    )
    assert "with acquire_audit_lane(" in source, (
        "FIX-3 regressed: subprocess.run no longer wrapped in audit lane."
    )
