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
# FIX-1 + FIX-2 — `inspect eval` argv flags
# ---------------------------------------------------------------------------
#
# Codex MCP catch (PR-OL-AUDIT-BURST-FIX fix-up): the burst flags must
# land in the actual `inspect eval` argv assembled by
# `plugins/petri_audit/runner.py::build_command`, NOT in the outer
# `geode audit` argv assembled by `autoresearch/train.py::_build_audit_command`.
# The `geode audit` Typer command doesn't accept `--max-connections` —
# the flags would be rejected before reaching `inspect eval`.


pytest.importorskip("inspect_ai")  # build_command checks inspect_ai dim sets


def _build_inspect_cmd() -> list[str]:
    """Helper — call `build_command` with minimal valid args."""
    from plugins.petri_audit.runner import build_command

    return build_command(
        judge="claude-code/claude-opus-4-7",
        auditor="claude-code/claude-sonnet-4-6",
        target="geode/claude-opus-4-7",
        seeds=2,
        max_turns=5,
        tags=None,
        cache=True,
        dim_set="5axes",
        seed_select="plugins/petri_audit/seeds",
    )


def test_inspect_cmd_pins_max_connections_one() -> None:
    """FIX-1 — ``--max-connections 1`` is in the `inspect eval` argv."""
    cmd = _build_inspect_cmd()
    assert "--max-connections" in cmd, (
        "OL-AUDIT-BURST-FIX FIX-1 regressed: --max-connections missing — "
        "inspect_ai default 10 will re-introduce 429 storm under Max OAuth."
    )
    idx = cmd.index("--max-connections")
    assert cmd[idx + 1] == "1"


def test_inspect_cmd_pins_max_samples_one() -> None:
    """FIX-2 — ``--max-samples 1`` is in the `inspect eval` argv."""
    cmd = _build_inspect_cmd()
    assert "--max-samples" in cmd, (
        "OL-AUDIT-BURST-FIX FIX-2 regressed: --max-samples missing — "
        "inspect_ai's per-sample parallelism will reburst connections."
    )
    idx = cmd.index("--max-samples")
    assert cmd[idx + 1] == "1"


def test_inspect_cmd_burst_flags_before_model_role() -> None:
    """The burst flags must come BEFORE the ``--model-role`` flags so
    inspect_ai's CLI parser sees them as eval-level options, not as
    role-scoped flags."""
    cmd = _build_inspect_cmd()
    first_model_role = cmd.index("--model-role")
    assert cmd.index("--max-connections") < first_model_role
    assert cmd.index("--max-samples") < first_model_role


def test_geode_audit_argv_does_not_pass_inspect_flags() -> None:
    """`geode audit` (Typer wrapper) does NOT accept --max-connections;
    the burst flags must stay out of the outer argv. Codex MCP catch.
    """
    from autoresearch import train

    argv = train._build_audit_command()
    assert "--max-connections" not in argv, (
        "OL-AUDIT-BURST-FIX regressed: outer `geode audit` argv MUST NOT "
        "carry --max-connections — Typer wrapper rejects unknown options."
    )
    assert "--max-samples" not in argv


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


def test_audit_lane_lazy_init_is_thread_safe() -> None:
    """Codex MCP catch (PR-OL-AUDIT-BURST-FIX fix-up): two threads
    racing to first-call ``get_audit_lane()`` must observe the SAME
    Lane instance. Pre-fix the lazy init had double-init risk.

    We reset the module-level singleton, spawn N threads that race on
    the first ``get_audit_lane()`` call, and assert they all received
    the identical instance.
    """
    from core.llm import audit_lane

    # Reset the singleton so each thread races the first init.
    audit_lane._AUDIT_LANE = None  # type: ignore[attr-defined]
    seen: list = []
    seen_lock = threading.Lock()
    start_barrier = threading.Barrier(8)

    def _worker() -> None:
        start_barrier.wait()  # all threads race the if-None check
        lane = audit_lane.get_audit_lane()
        with seen_lock:
            seen.append(lane)

    threads = [threading.Thread(target=_worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=2.0)
    assert len(seen) == 8
    # All 8 threads must have received the same instance
    assert len({id(lane) for lane in seen}) == 1, (
        "OL-AUDIT-BURST-FIX fix-up regressed: lazy init race re-introduced — "
        "different Lane instances handed out under concurrency."
    )


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
