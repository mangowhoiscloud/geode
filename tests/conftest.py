"""pytest configuration — load .env before any module imports.

This ensures LANGCHAIN_* environment variables are in os.environ
BEFORE @_maybe_traceable decorators are evaluated at import time.

LangSmith tracing is disabled by default during tests to avoid
burning monthly trace quota. Live tests (``-m live``) that need
tracing should set LANGCHAIN_TRACING_V2=true explicitly.
"""

import os

from dotenv import load_dotenv

load_dotenv()  # Must run before test module imports trigger decorator evaluation

# Disable LangSmith tracing during tests unless explicitly overridden
# (e.g. LANGCHAIN_TRACING_V2=true uv run pytest -m live)
if os.environ.get("GEODE_TEST_TRACING") != "1":
    os.environ["LANGCHAIN_TRACING_V2"] = "false"
