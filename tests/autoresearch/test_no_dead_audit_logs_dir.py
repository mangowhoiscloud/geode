"""PR-L9 (2026-05-26) — invariant: ``audit_logs/`` dead-dir resurrection guard.

`autoresearch/state/audit_logs/` had a writer-less ``mkdir(parents=True,
exist_ok=True)`` at ``train.py:run_audit`` for an unclear historical
reason. grep showed no caller actually wrote anything inside, so the
constant + mkdir were removed (PR-L9). This invariant pins the cleanup
so a future PR re-introducing ``AUDIT_OUT_DIR = STATE_DIR /
"audit_logs"`` fails fast.

If a real ledger writer is needed, document the writer + reader pair in
the same PR (see CLAUDE.md "Writer destination tracked" rule) so the
directory isn't a phantom side-effect again.
"""

from __future__ import annotations

import inspect

from core.self_improving import train as auto_train


def test_audit_out_dir_constant_not_reintroduced() -> None:
    """``AUDIT_OUT_DIR`` constant must stay deleted."""
    assert not hasattr(auto_train, "AUDIT_OUT_DIR"), (
        "AUDIT_OUT_DIR was deleted in PR-L9 (no writer, no reader). "
        "If you re-introduce it, also wire a real writer/reader pair "
        "and document them in the PR per CLAUDE.md 'Writer destination "
        "tracked' rule."
    )


def test_train_py_does_not_reference_audit_logs_subdir() -> None:
    """train.py source must not reference the dead ``audit_logs`` subdir.

    Codex MCP review #1688 widened the original literal-only check to
    catch both quote styles + bare path fragments, so re-introducing
    via ``STATE_DIR / 'audit_logs'`` or a renamed constant still trips.
    """
    source = inspect.getsource(auto_train)
    for needle in ('"audit_logs"', "'audit_logs'", "audit_logs/"):
        assert needle not in source, (
            f"Reference to autoresearch/state/audit_logs/ ({needle!r}) found "
            "in train.py. If this is intentional, add a writer that actually "
            "emits files into the directory + a reader that consumes them, "
            "and update this invariant accordingly."
        )
