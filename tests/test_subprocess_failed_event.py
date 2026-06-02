"""PR-MINIMAL-4 — subprocess_failed journal event on non-zero exit.

Pre-PR ``core/self_improving/train.py:run_audit`` only emitted
``subprocess_finished`` (with ``exit_code`` in the payload). The
top-level ``audit_failed`` event at ``main()`` caught the resulting
``RuntimeError`` but lost subprocess-specific context (exit_code,
run_log path). PR-MINIMAL-4 inserts a dedicated
``subprocess_failed`` event before the ``raise RuntimeError`` so
downstream consumers grouping by event name can alert on it.
"""

from __future__ import annotations

import inspect


def test_subprocess_failed_event_emitted_before_runtime_error() -> None:
    """Source-grep the shared post-processing helper — the non-zero-exit
    branch must emit ``subprocess_failed`` BEFORE the ``raise RuntimeError``
    so a downstream consumer sees the typed event, not just the generic
    top-level ``audit_failed`` catch.

    PR-ASYNC-FIRST S1 (2026-06-03) — this branch moved out of ``run_audit``
    into the shared ``_finalize_audit_result`` helper that BOTH the sync
    ``run_audit`` and the async ``run_audit_async`` call, so they cannot
    drift. Grep the helper, not ``run_audit``.
    """
    from core.self_improving import train

    src = inspect.getsource(train._finalize_audit_result)
    # The event name appears in the source.
    assert '"subprocess_failed"' in src, (
        "_finalize_audit_result must emit subprocess_failed when returncode != 0 "
        "so downstream consumers grouping by event name can alert on it."
    )
    # The event is emitted at error level.
    # Pin the level so a refactor that drops it (and downgrades the
    # event to default INFO) surfaces here.
    assert 'level="error"' in src
    # The event must come before the raise — same branch.
    sub_idx = src.index('"subprocess_failed"')
    raise_idx = src.index('raise RuntimeError(f"audit subprocess exit=')
    assert sub_idx < raise_idx, (
        "subprocess_failed event must be emitted BEFORE the RuntimeError "
        "so the journal row lands even if the exception unwinds the stack."
    )


def test_subprocess_failed_payload_includes_exit_code_and_run_log() -> None:
    """The payload must carry enough diagnostic context (exit_code,
    run_log path, stderr tail) for the operator to triage without
    having to grep the raw run.log."""
    from core.self_improving import train

    src = inspect.getsource(train._finalize_audit_result)
    # exit_code must be present in the payload
    assert '"exit_code": returncode' in src
    # run_log path must be present in the payload
    assert '"run_log": str(RUN_LOG)' in src
    # stderr tail (best-effort, last 5 lines) for at-a-glance triage
    assert '"stderr_tail"' in src


def test_subprocess_finished_event_still_emitted() -> None:
    """Pin that the existing ``subprocess_finished`` event still fires
    on normal exit — PR-MINIMAL-4 ADDS a sibling event, doesn't
    replace any existing one. Post-S1 it lives in the shared helper."""
    from core.self_improving import train

    src = inspect.getsource(train._finalize_audit_result)
    assert '"subprocess_finished"' in src


def test_subprocess_timeout_event_still_emitted() -> None:
    """The existing ``subprocess_timeout`` event (TimeoutExpired
    branch) must still fire. PR-MINIMAL-4 leaves timeout-branch
    behavior unchanged."""
    from core.self_improving import train

    src = inspect.getsource(train.run_audit)
    assert '"subprocess_timeout"' in src
