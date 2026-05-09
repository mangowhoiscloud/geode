"""Smoke tests for the petri_audit skeleton (P1).

These must pass without ``inspect-ai`` / ``inspect-petri`` installed —
they only verify that the plugin's directory layout and module surface
are importable and that the P1 stubs raise as documented.
"""

from __future__ import annotations

import asyncio

import pytest


def test_petri_audit_package_imports() -> None:
    import plugins.petri_audit  # noqa: F401


def test_geode_target_stub_raises() -> None:
    from plugins.petri_audit.targets.geode_target import GeodeTarget

    target = GeodeTarget()
    assert target.name == "geode"

    with pytest.raises(NotImplementedError, match="P1 stub"):
        asyncio.run(target.execute(state=None, context=None))


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
