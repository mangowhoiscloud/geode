"""Test isolation for CLI self-improving viewers.

The runtime ``baseline.json`` lives OUTSIDE the repo at
``~/.geode/self-improving/baseline.json`` (``core.paths.BASELINE_JSON_PATH``,
derived from ``RUNTIME_ROOT`` at import time). The global
``_isolate_state_root`` fixture (``tests/conftest.py``) redirects the
``STATE_ROOT`` / ``AUTORESEARCH_STATE_DIR`` family but NOT this
import-time-frozen constant, so a developer box with a real promoted
baseline leaks it into ``outer_bundle.load_bundle_events`` (a synthetic
``baseline`` event) and ``_cmd_status`` (a "promoted" block instead of
"no baseline yet"). CI passes only because a clean HOME has no baseline.

Redirect it to a fresh empty tmp dir for every CLI test so the readers
observe the fixture-supplied state, never the machine's. Tests that stage
their own baseline still ``monkeypatch.setattr("core.paths.BASELINE_JSON_PATH", ...)``
after this fixture, which simply overrides the redirect.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_runtime_baseline(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    import core.paths as cp

    sandbox = tmp_path_factory.mktemp("baseline-isolation")
    monkeypatch.setattr(cp, "BASELINE_JSON_PATH", sandbox / "baseline.json")
