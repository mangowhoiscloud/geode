"""pytest configuration — load .env before any module imports.

Hook-based observability (SQLite events + LLM_CALL_START/END) needs no
special test-time setup; the hook system is wired only when an
HookSystem instance is present.
"""

import contextlib
import os
import tempfile

from dotenv import load_dotenv

load_dotenv()  # Must run before test module imports

# Redirect SessionCheckpoint + SessionTranscript to temp dirs during tests
# to prevent production data contamination (.geode/session/, .geode/journal/)
_test_session_dir = os.path.join(tempfile.gettempdir(), "geode_test_sessions")
_test_transcript_dir = os.path.join(tempfile.gettempdir(), "geode_test_transcripts")

from pathlib import Path  # noqa: E402

import core.memory.session_checkpoint as _cp_mod  # noqa: E402
import core.observability.transcript as _tx_mod  # noqa: E402

_cp_mod.DEFAULT_SESSION_DIR = Path(_test_session_dir)
_tx_mod.DEFAULT_TRANSCRIPT_DIR = Path(_test_transcript_dir)


# v0.50.0 — auth-plans singletons (ProfileStore, ProfileRotator, PlanRegistry)
# leak between tests. Reset them around every test so state from one suite
# (e.g. seeding a Coding Plan profile) doesn't influence another. Also
# redirect ~/.geode/auth.toml writes to a temp file so tests can never
# clobber a developer's real credentials.
import pytest  # noqa: E402

_test_auth_toml = os.path.join(tempfile.gettempdir(), "geode_test_auth.toml")
os.environ.setdefault("GEODE_AUTH_TOML", _test_auth_toml)


# CSP-7 (2026-05-22) — Pipeline.run() writes cross-run state to
# ``<repo_root>/state/`` by default. Tests that don't explicitly
# monkeypatch ``core.paths`` constants would otherwise mutate the
# in-repo state/ directory and leak across the test suite (a previous
# test's ``latest_pointer.json`` survives into a later test's
# ``_resolve_seed_select`` reader, breaking isolation). Autouse fixture
# redirects every test's STATE_ROOT to a fresh tmp directory unless
# the test explicitly re-monkeypatches.
@pytest.fixture(autouse=True)
def _isolate_state_root(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    import core.paths as cp

    sandbox = tmp_path_factory.mktemp("state-isolation")
    monkeypatch.setattr(cp, "STATE_ROOT", sandbox)
    monkeypatch.setattr(cp, "AUTORESEARCH_STATE_DIR", sandbox / "autoresearch")
    monkeypatch.setattr(cp, "AUTORESEARCH_HANDOFF_DIR", sandbox / "autoresearch" / "handoff")
    monkeypatch.setattr(cp, "STATE_SEED_GENERATION_DIR", sandbox / "seed_generation")
    monkeypatch.setattr(
        cp,
        "STATE_LATEST_POINTER_PATH",
        sandbox / "autoresearch" / "handoff" / "latest_pointer.json",
    )


@pytest.fixture(autouse=True)
def _reset_auth_singletons():
    from core.llm.strategies import plan_registry as _pr
    from core.wiring import container as _infra

    _infra._profile_store = None
    _infra._profile_rotator = None
    _pr._plan_registry = None
    # Make sure no leftover auth.toml from a prior test run influences this one
    # xdist-parallel race: two workers may both see the file exist then both try
    # to remove it. Tolerate concurrent FileNotFoundError.
    with contextlib.suppress(FileNotFoundError):
        os.remove(_test_auth_toml)
    yield
    _infra._profile_store = None
    _infra._profile_rotator = None
    _pr._plan_registry = None
    # xdist-parallel race: two workers may both see the file exist then both try
    # to remove it. Tolerate concurrent FileNotFoundError.
    with contextlib.suppress(FileNotFoundError):
        os.remove(_test_auth_toml)


@pytest.fixture(autouse=True)
def _bootstrap_adapter_registry():
    """Populate the Path-B adapter registry before each test.

    PR-MAINPATH-1 (2026-05-24) — AgenticLoop now resolves its
    ``_new_adapter`` through ``core.llm.adapters.registry.resolve_for``
    by default (source defaults to ``"payg"``). Production runtime
    calls :func:`bootstrap_builtins` from ``core/wiring/container.py``
    at startup; tests need the same registration so
    ``AgenticLoop.__init__`` doesn't raise ``AdapterNotFoundError``
    with the registry in its empty initial state.
    The reset on the way out prevents per-test registrations from
    leaking into the next test (matches the existing
    ``test_agent_loop_source_route.py`` fixture pattern).
    """
    from core.llm.adapters.registry import _reset_for_test, bootstrap_builtins

    _reset_for_test()
    bootstrap_builtins()
    yield
    _reset_for_test()
