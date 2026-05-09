"""GEODE × Petri alignment audit plugin (skeleton, P1).

Scope (P1):
- Directory layout and module surface; no ``inspect-ai`` import in default path.
- ``GeodeTarget.execute`` is a stub that raises NotImplementedError; the real
  implementation lands in P2 with the ``[audit]`` optional extra.
- Intentionally NOT registered with ``core.domains.loader``: petri_audit is an
  external evaluator harness, not a runtime domain like ``game_ip``. Skipping
  registration keeps cold-start unaffected and keeps audit machinery out of
  the default ``geode analyze`` flow.

See ``docs/plans/eval-petri-integration.md`` for the phased rollout (P0..P4).
"""

from __future__ import annotations

__all__: list[str] = []
