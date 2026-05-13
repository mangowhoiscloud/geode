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

# Defect B-3 fix (2026-05-11) — namespace-wide ``INFO`` level so that
# ``log.info(...)`` calls inside ``plugins.petri_audit.*`` (notably
# ``_default_geode_runner``'s entry/exit observability and the F-A2
# track_usage diagnostics) propagate up to inspect_ai's root
# ``LogHandler`` and land in the eval's ``LoggerEvent`` stream.
#
# Background — inspect_ai's ``init_logger`` (``_util/logger.py``) sets
# the root level to ``warning`` (default ``DEFAULT_LOG_LEVEL`` from
# ``_util/constants.py``) but configures the transcript writer to
# capture ``info`` and above (``DEFAULT_LOG_LEVEL_TRANSCRIPT='info'``).
# Python ``logging`` rejects records below the effective level of
# their logger chain, so without this setLevel the INFO record never
# reaches the root LogHandler and therefore never makes it into the
# ``.eval`` transcript. The 5/11 archives (PR D/E/F) all carried zero
# ``LoggerEvent`` entries from ``plugins.petri_audit`` for exactly
# this reason — verified post-fix via file-based fa4 evidence in
# ``docs/audits/2026-05-11-petri-observability-audit.md`` §9.6.
_logging.getLogger("plugins.petri_audit").setLevel(_logging.INFO)

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
        "petri_audit ModelAPI registration deferred — [audit] extra not installed",
        exc_info=True,
    )

# PR #6 (2026-05-14) — register the ``openai-codex`` ModelAPI alongside
# ``geode``. ``OpenAICodexAPI`` routes ``openai-codex/<model>`` ids
# through the ChatGPT Plus OAuth path so judge / auditor calls consume
# the user's subscription quota instead of per-token billing. Same
# try/except guard so the default ``uv sync`` (no [audit] extra) is
# unaffected.
try:
    from plugins.petri_audit.codex_provider import register as _register_codex

    _register_codex()
except ImportError:
    _logging.getLogger(__name__).debug(
        "petri_audit openai-codex ModelAPI registration deferred — "
        "[audit] extra not installed",
        exc_info=True,
    )

__all__: list[str] = []
