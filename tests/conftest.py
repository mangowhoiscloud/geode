"""pytest configuration — load .env before any module imports.

This ensures LANGCHAIN_* environment variables are in os.environ
BEFORE @_maybe_traceable decorators are evaluated at import time.
"""

from dotenv import load_dotenv

load_dotenv()  # Must run before test module imports trigger decorator evaluation
