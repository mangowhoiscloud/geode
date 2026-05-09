"""Smoke tests for the petri_audit skeleton (P2-a).

These tests must pass without the ``[audit]`` optional extra installed —
they verify that the plugin's directory layout and module surface are
importable and that the factory raises a clear error when the extra is
missing.
"""

from __future__ import annotations

import importlib.util

import pytest

_AUDIT_INSTALLED = importlib.util.find_spec("inspect_ai") is not None


def test_petri_audit_package_imports() -> None:
    import plugins.petri_audit  # noqa: F401


def test_geode_target_module_imports_without_audit_extra() -> None:
    """Importing the target module must NOT trigger inspect_ai import.

    Lazy-import discipline: the module-level surface only references
    ``inspect_ai`` / ``inspect_petri`` under ``TYPE_CHECKING``, so the
    module is loadable on a default ``uv sync`` without the ``[audit]``
    extra installed.
    """
    from plugins.petri_audit.targets import geode_target

    assert hasattr(geode_target, "make_geode_target_agent")
    assert hasattr(geode_target, "_run_geode_loop")


@pytest.mark.skipif(
    _AUDIT_INSTALLED,
    reason="[audit] extra installed — ImportError path covers absent-extra case",
)
def test_factory_raises_import_error_without_audit_extra() -> None:
    """``make_geode_target_agent()`` requires ``[audit]`` extra installed."""
    from plugins.petri_audit.targets.geode_target import make_geode_target_agent

    with pytest.raises(ImportError):
        make_geode_target_agent()


def test_run_geode_loop_is_p2a_stub() -> None:
    """The inner-loop wiring is intentionally not implemented in P2-a."""
    import asyncio

    from plugins.petri_audit.targets.geode_target import _run_geode_loop

    with pytest.raises(NotImplementedError, match="P2-a stub"):
        asyncio.run(_run_geode_loop(messages=[]))


def test_audit_adapter_stub_raises() -> None:
    from plugins.petri_audit.adapter import GeodeAuditAdapter

    adapter = GeodeAuditAdapter()
    with pytest.raises(NotImplementedError, match="P1 stub"):
        adapter.turn(payload=None)


def test_petri_audit_does_not_register_domain() -> None:
    """petri_audit is an external evaluator, not a GEODE domain.

    Importing ``plugins.petri_audit`` must not call ``register_domain``,
    so the audit plugin stays out of the default ``geode analyze`` flow.
    """
    from core.domains.loader import list_domains

    import plugins.petri_audit  # noqa: F401

    assert "petri_audit" not in list_domains()
