"""PR-CLEANUP-WORKER-REQUEST-RUN-DIR (2026-05-25) — anti-relapse pin.

``WorkerRequest.run_dir`` was a dead dataclass field — declared with
a docstring suggesting it carried the parent orchestrator's active
run_dir across the IPC boundary, but no producer ever populated it
(PR-Q chose env-var transport instead). The field's docstring caused
PR-RESUME-NO-PERSIST-FIX's first cut to mis-wire the per-task cwd
binding against the dead source, so the smoke 11 ``cwd/`` subdirs
were never created. Test pins:

1. The field is GONE from the dataclass schema.
2. ``to_dict``/``from_dict`` round-trip does NOT echo any ``run_dir``
   key (back-compat callers passing it on the wire silently drop it,
   no crash).
"""

from __future__ import annotations

from dataclasses import fields

from core.agent.worker import WorkerRequest


def test_worker_request_does_not_carry_run_dir_field() -> None:
    field_names = {f.name for f in fields(WorkerRequest)}
    assert "run_dir" not in field_names, (
        f"WorkerRequest.run_dir must stay removed (was dead code that "
        f"misled PR-RESUME-NO-PERSIST-FIX). Live SoT is "
        f"core.observability.run_dir.get_active_run_dir(). "
        f"Current fields: {sorted(field_names)}"
    )


def test_from_dict_silently_drops_legacy_run_dir_key() -> None:
    """Wire-level back-compat — if a parent on an older release
    still emits ``run_dir`` in the WorkerRequest payload, the
    worker must accept the dict without crashing. The field is
    dropped (no longer a constructor kwarg) and from_dict does
    not pass it through."""
    payload = {
        "task_id": "gen-gen1-000-legacy",
        "task_type": "analyze",
        "description": "legacy producer still sends run_dir",
        "run_dir": "/Users/mango/workspace/geode/state/seed-generation/some-run",
    }
    request = WorkerRequest.from_dict(payload)

    assert request.task_id == "gen-gen1-000-legacy"
    # ``hasattr`` is False because the dataclass no longer declares
    # ``run_dir`` at all (not just defaults-to-empty).
    assert not hasattr(request, "run_dir")


def test_to_dict_does_not_include_run_dir_key() -> None:
    request = WorkerRequest(task_id="gen-gen1-000-encode")
    encoded = request.to_dict()
    assert "run_dir" not in encoded
