"""GEODE — 범용 자율 실행 에이전트."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # Declare ``__version__`` for mypy / IDEs.  The runtime value is produced
    # lazily by ``__getattr__`` below so module import does not pull
    # ``importlib.metadata`` (~70 ms cumulative including ``email.message`` /
    # ``email.utils``) into the cold-start path.
    __version__: str

_VERSION_CACHE: str | None = None


def _resolve_version() -> str:
    """Resolve the package version from importlib.metadata, with a
    pyproject.toml fallback for non-installed dev environments."""
    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version as _pkg_version

    try:
        return _pkg_version("geode-agent")
    except PackageNotFoundError:
        # Fallback: read from pyproject.toml directly (dev / non-installed env)
        from pathlib import Path as _Path

        _pyproject = _Path(__file__).resolve().parent.parent / "pyproject.toml"
        if _pyproject.exists():
            import re as _re

            _match = _re.search(r'version\s*=\s*"([^"]+)"', _pyproject.read_text())
            return _match.group(1) if _match else "0.0.0-dev"
        return "0.0.0-dev"


def __getattr__(name: str) -> Any:
    """PEP 562 lazy ``__version__`` resolver.

    Cold-start paths that never reference ``core.__version__`` (e.g. the
    serve daemon's ``import core.runtime`` bootstrap) avoid loading
    ``importlib.metadata`` entirely.
    """
    if name == "__version__":
        global _VERSION_CACHE
        if _VERSION_CACHE is None:
            _VERSION_CACHE = _resolve_version()
        return _VERSION_CACHE
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
