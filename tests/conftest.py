"""pytest configuration — isolate operator state before test imports.

Hook-based observability (SQLite events + LLM_CALL_START/END) needs no
special test-time setup; the hook system is wired only when an
HookSystem instance is present.
"""

import contextlib
import os
import tempfile
from collections.abc import Iterator

# A non-live test run must never inherit billable provider credentials from the
# operator shell or a repository ``.env``. Tests that exercise credential
# discovery set synthetic values with ``monkeypatch``; explicitly live tests
# resolve their own credentials inside the marked test body.
for _credential_var in (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "ZHIPUAI_API_KEY",
    "ZAI_API_KEY",
    "GOOGLE_API_KEY",
    "GEMINI_API_KEY",
):
    os.environ.pop(_credential_var, None)

# Redirect SessionCheckpoint to a temp directory during tests to prevent
# production data contamination.
_test_session_dir = os.path.join(tempfile.gettempdir(), "geode_test_sessions")

from pathlib import Path  # noqa: E402

import core.memory.session_checkpoint as _cp_mod  # noqa: E402

_cp_mod.DEFAULT_SESSION_DIR = Path(_test_session_dir)


# v0.50.0 — auth-plans singletons (ProfileStore, ProfileRotator, PlanRegistry)
# leak between tests. Reset them around every test so state from one suite
# (e.g. seeding a Coding Plan profile) doesn't influence another. Also
# redirect ~/.geode/auth.toml writes to a temp file so tests can never
# clobber a developer's real credentials.
import pytest  # noqa: E402

_test_auth_toml = os.path.join(tempfile.gettempdir(), "geode_test_auth.toml")
os.environ.setdefault("GEODE_AUTH_TOML", _test_auth_toml)


@pytest.fixture
def managed_geode_runtimes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    """Isolate scheduler state and close every runtime created by a test.

    ``GeodeRuntime.create`` owns two scheduler threads. Tests that only inspect
    wiring used to leave those threads alive and could import real project or
    legacy scheduler jobs. The leaked jobs then ran later in the suite after
    pytest had closed its capture stream.
    """
    from core import runtime as runtime_module
    from core.scheduler import service as scheduler_service

    scheduler_root = tmp_path / "scheduler"
    monkeypatch.setattr(
        scheduler_service,
        "DEFAULT_STORE_PATH",
        scheduler_root / "scheduled_tasks.json",
    )
    monkeypatch.setattr(
        scheduler_service,
        "DEFAULT_LOG_DIR",
        scheduler_root / "logs",
    )
    monkeypatch.setattr(
        scheduler_service,
        "_LEGACY_STORE_PATH",
        scheduler_root / "legacy_jobs.json",
    )

    runtimes: list[runtime_module.GeodeRuntime] = []
    original_create = runtime_module.GeodeRuntime.create.__func__

    def _create(
        cls: type[runtime_module.GeodeRuntime],
        *args: object,
        **kwargs: object,
    ) -> runtime_module.GeodeRuntime:
        runtime = original_create(cls, *args, **kwargs)
        runtimes.append(runtime)
        return runtime

    monkeypatch.setattr(runtime_module.GeodeRuntime, "create", classmethod(_create))
    yield
    for runtime in reversed(runtimes):
        runtime.shutdown()


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
    from core.memory import session_checkpoint, session_manager

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
    session_dir = sandbox / "sessions"
    monkeypatch.setattr(session_checkpoint, "DEFAULT_SESSION_DIR", session_dir)
    monkeypatch.setattr(session_manager, "_DEFAULT_DB_PATH", session_dir / "sessions.db")


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
