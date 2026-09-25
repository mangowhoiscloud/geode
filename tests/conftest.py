"""pytest configuration — isolate operator state before test imports.

Hook-based observability (SQLite events + LLM_CALL_START/END) needs no
special test-time setup; the hook system is wired only when an
HookSystem instance is present.
"""

import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

# Remove inherited provider keys before settings imports. Credential tests set
# synthetic values explicitly; dotenv and managed OAuth sources need separate isolation.
for _credential_var in (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
    "TYPESAFE_API_KEY",
    "ZHIPUAI_API_KEY",
    "ZAI_API_KEY",
    "GOOGLE_API_KEY",
    "GEMINI_API_KEY",
):
    os.environ.pop(_credential_var, None)

# Imports and test collection must not read an operator-provided auth path.
# Keep the directory alive for this interpreter; each test gets its own below.
_test_auth_dir = tempfile.TemporaryDirectory(prefix="geode-test-auth-")
os.environ["GEODE_AUTH_TOML"] = str(Path(_test_auth_dir.name) / "auth.toml")
os.environ["CODEX_HOME"] = str(Path(_test_auth_dir.name) / "codex")

# Redirect SessionCheckpoint to a temp directory during tests to prevent
# production data contamination.
_test_session_dir = os.path.join(tempfile.gettempdir(), "geode_test_sessions")

import core.memory.session_checkpoint as _cp_mod  # noqa: E402

_cp_mod.DEFAULT_SESSION_DIR = Path(_test_session_dir)


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _block_unmarked_http(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    """Offline tests may use MockTransport or loopback, never operator APIs."""
    if request.node.get_closest_marker("live"):
        yield
        return
    import httpx

    sync_request = httpx.HTTPTransport.handle_request
    async_request = httpx.AsyncHTTPTransport.handle_async_request
    blocked: list[str] = []

    def guarded_sync(self: httpx.HTTPTransport, call: httpx.Request) -> httpx.Response:
        if call.url.host not in {"localhost", "127.0.0.1", "::1"}:
            blocked.append("sync")
            raise AssertionError("Unmocked external HTTP in an offline test")
        return sync_request(self, call)

    async def guarded_async(self: httpx.AsyncHTTPTransport, call: httpx.Request) -> httpx.Response:
        if call.url.host not in {"localhost", "127.0.0.1", "::1"}:
            blocked.append("async")
            raise AssertionError("Unmocked external HTTP in an offline test")
        return await async_request(self, call)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", guarded_sync)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", guarded_async)
    yield
    assert not blocked, f"Offline test attempted {len(blocked)} unmocked external HTTP requests"


@pytest.fixture(autouse=True)
def _isolate_judgment_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """Offline tests cannot inherit the operator's dotenv credentials."""
    from core.config import settings
    from pydantic import SecretStr

    monkeypatch.setattr(settings, "typesafe_api_key", SecretStr(""))
    for field in ("anthropic_api_key", "openai_api_key", "openrouter_api_key", "zai_api_key"):
        monkeypatch.setattr(settings, field, "")


@pytest.fixture
def managed_geode_runtimes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    """Isolate external services and close every runtime created by a test.

    ``GeodeRuntime.create`` owns two scheduler threads. Tests that only inspect
    wiring used to leave those threads alive and could import real project or
    legacy scheduler jobs. The leaked jobs then ran later in the suite after
    pytest had closed its capture stream.
    """
    from core import runtime as runtime_module
    from core.config import settings
    from core.scheduler import service as scheduler_service

    # Wiring tests do not own the operator's external gateway or its watcher.
    monkeypatch.setattr(settings, "gateway_enabled", False)
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
def _reset_auth_singletons(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("GEODE_AUTH_TOML", str(tmp_path / "auth.toml"))
    from core.llm.strategies import plan_registry as _pr
    from core.wiring import container as _infra

    _infra._profile_store = None
    _infra._profile_rotator = None
    _pr._plan_registry = None
    try:
        yield
    finally:
        _infra._profile_store = None
        _infra._profile_rotator = None
        _pr._plan_registry = None


@pytest.fixture(autouse=True)
def _bootstrap_adapter_registry(_reset_auth_singletons: None) -> Iterator[None]:
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
