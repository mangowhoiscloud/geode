"""GEODE × Petri alignment audit plugin (P2-d).

Registers ``GeodeModelAPI`` with ``inspect_ai`` when the ``[audit]``
optional extra is installed; otherwise the registration is silently
skipped so plain ``import plugins.petri_audit`` keeps working on a
default ``uv sync`` (no ``inspect_ai`` import on cold-start).

Intentionally NOT registered with ``core.domains.loader``: petri_audit is
an external evaluator harness, not a runtime domain like ``game_ip``.
Skipping registration keeps the audit machinery out of the default
``geode analyze`` flow.

See ``docs/plans/eval-petri-integration.md`` for the phased rollout
(P0 GAP audit, P1/P2-a/P2-b/P2-d skeleton, P3 first live audit).
"""

from __future__ import annotations

import logging as _logging

# Audit-extra hookup: invoking ``register()`` triggers the
# ``@modelapi(name="geode")`` decorator inside that function, which
# registers ``GeodeModelAPI`` with ``inspect_ai``'s registry. The
# try/except keeps ``import plugins.petri_audit`` working when the
# ``[audit]`` extra is absent (default ``uv sync``); registration only
# matters when the user is actually running an audit.
try:
    from plugins.petri_audit.targets.geode_target import register as _register

    _register()
except ImportError:
    _logging.getLogger(__name__).debug(
        "petri_audit ModelAPI registration deferred — "
        "[audit] extra not installed",
        exc_info=True,
    )

__all__: list[str] = []
