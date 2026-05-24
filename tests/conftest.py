"""pytest configuration — load .env before any module imports.

Hook-based observability (RunLog + LLM_CALL_START/END events) needs no
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
    monkeypatch.setattr(cp, "STATE_SELF_IMPROVING_LOOP_DIR", sandbox / "self-improving-loop")
    monkeypatch.setattr(cp, "STATE_SEED_GENERATION_DIR", sandbox / "seed-generation")
    monkeypatch.setattr(
        cp,
        "STATE_LATEST_POINTER_PATH",
        sandbox / "self-improving-loop" / "latest_pointer.json",
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


@pytest.fixture(autouse=True)
def _reset_circuit_breakers():
    """Reset module-level CircuitBreaker singletons before & after each test.

    Failure-injecting tests (e.g. ``test_failover.py::test_no_silent_fallback_to_other_models``)
    raise ``MAX_RETRIES`` RateLimitErrors per invocation, which pushes the
    shared anthropic / openai / glm / codex breakers to the OPEN state.
    When pytest-xdist's ``loadfile`` distribution colocates a failure-
    injecting test with a downstream consumer on the same worker, the
    consumer's first ``can_execute()`` check returns False and the test
    fails with "Circuit breaker is open" — a cascade flake that has
    nothing to do with the consumer's PR.

    Reset both pre- and post-test so accumulated state from prior runs
    can't bleed in either direction.
    """

    def _reset_all() -> None:
        # Import lazily and tolerate ImportError so the reset survives the
        # case where a vendored SDK isn't installed in a stripped-down
        # test environment. AttributeError tolerated for the same reason
        # — a future refactor that renames a singleton shouldn't break
        # the whole conftest.
        with contextlib.suppress(ImportError, AttributeError):
            from core.llm.providers import anthropic as _anth

            _anth._circuit_breaker.reset()
        with contextlib.suppress(ImportError, AttributeError):
            from core.llm.providers import openai as _oai

            _oai._openai_circuit_breaker.reset()
        with contextlib.suppress(ImportError, AttributeError):
            from core.llm.providers import glm as _glm

            _glm._glm_circuit_breaker.reset()
        with contextlib.suppress(ImportError, AttributeError):
            from core.llm.providers import codex as _cdx

            _cdx._codex_circuit_breaker.reset()
        with contextlib.suppress(ImportError, AttributeError):
            from core.llm import provider_dispatch as _disp

            _disp._openai_cb.reset()
            _disp._glm_cb.reset()

    _reset_all()
    yield
    _reset_all()
