"""Conftest for seed_generation tests.

CSP-14 (2026-05-23) — auto-disable the bundle_sync side-effect for all
seed_generation tests that exercise ``Pipeline.arun`` end-to-end.
Without this fixture, the orchestrator's ``sync_run_to_bundle`` call
runs after every test pipeline and writes to the real repo's
``docs/petri-bundle/seeds/<test_run_id>/`` — leaking test artefacts
into the git-tracked publish surface.

The bundle_sync behaviour itself is covered by the dedicated
``test_seed_bundle_sync.py`` suite which sets ``GEODE_REPO_ROOT`` per
test to a tmp_path; this conftest only short-circuits the implicit
call from ``Pipeline.arun`` so non-bundle-sync tests don't pollute
the repo.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _disable_seed_bundle_sync_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default-disable the seed bundle_sync env knob for every test.

    Bundle-sync's own test file overrides this by setting
    ``GEODE_REPO_ROOT`` (and not setting the disable knob) inside its
    fixtures, so its end-to-end assertions still exercise the real
    sync logic.
    """
    monkeypatch.setenv("GEODE_SEED_BUNDLE_SYNC_DISABLED", "1")
