"""pytest configuration — load .env before any module imports.

This ensures LANGCHAIN_* environment variables are in os.environ
BEFORE @_maybe_traceable decorators are evaluated at import time.

LangSmith tracing is disabled by default during tests to avoid
burning monthly trace quota. Live tests (``-m live``) that need
tracing should set LANGCHAIN_TRACING_V2=true explicitly.
"""

import os
import tempfile

from dotenv import load_dotenv

load_dotenv()  # Must run before test module imports trigger decorator evaluation

# Disable LangSmith tracing during tests unless explicitly overridden
# (e.g. LANGCHAIN_TRACING_V2=true uv run pytest -m live)
if os.environ.get("GEODE_TEST_TRACING") != "1":
    os.environ["LANGCHAIN_TRACING_V2"] = "false"

# Redirect SessionCheckpoint + SessionTranscript to temp dirs during tests
# to prevent production data contamination (.geode/session/, .geode/journal/)
_test_session_dir = os.path.join(tempfile.gettempdir(), "geode_test_sessions")
_test_transcript_dir = os.path.join(tempfile.gettempdir(), "geode_test_transcripts")

from pathlib import Path  # noqa: E402

import core.cli.session_checkpoint as _cp_mod  # noqa: E402
import core.cli.transcript as _tx_mod  # noqa: E402

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


@pytest.fixture(autouse=True)
def _reset_auth_singletons():
    from core.auth import plan_registry as _pr
    from core.lifecycle import container as _infra

    _infra._profile_store = None
    _infra._profile_rotator = None
    _pr._plan_registry = None
    # Make sure no leftover auth.toml from a prior test run influences this one
    if os.path.exists(_test_auth_toml):
        os.remove(_test_auth_toml)
    yield
    _infra._profile_store = None
    _infra._profile_rotator = None
    _pr._plan_registry = None
    if os.path.exists(_test_auth_toml):
        os.remove(_test_auth_toml)
