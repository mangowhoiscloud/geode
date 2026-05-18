"""Shared fixtures for ``tests/plugins/petri_audit/``.

PR-β1 (2026-05-19) introduced strict-mode credential resolution: when
``[outer_loop] fallback_to_payg`` is unset, the new default is
``False`` (per the consolidation plan's settled decision #2). The
existing registry / models / petri-cli tests pre-date that policy and
seed ``ANTHROPIC_API_KEY`` expecting the resolver to fall through to
``api_key``.

Rather than force every legacy test to opt-in, the conftest applies a
session-wide autouse override that pins
``outer_loop_fallback_policy()`` to ``True`` (= pre-PR-β1 behaviour)
**except** for the four new policy tests that exercise the helper
directly. Those tests carry the marker ``policy_real`` so they
bypass the stub.

Strict-mode tests
(``test_credential_source.py::test_fallback_disabled_*``) pass
``fallback_to_payg=False`` directly to ``resolve_credential_source``
and so are unaffected by this fixture either way.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _pin_fallback_policy_true(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pin ``outer_loop_fallback_policy()`` to ``True`` for legacy tests.

    Tests carrying the ``policy_real`` marker get the real helper so
    they can verify the loader contract end-to-end.
    """
    if request.node.get_closest_marker("policy_real") is not None:
        return
    from plugins.petri_audit import credential_source as cs

    monkeypatch.setattr(cs, "outer_loop_fallback_policy", lambda: True)
