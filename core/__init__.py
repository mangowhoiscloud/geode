"""GEODE — 범용 자율 실행 에이전트."""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

try:
    __version__: str = _pkg_version("geode")
except PackageNotFoundError:
    # Fallback: read from pyproject.toml directly (dev / non-installed env)
    from pathlib import Path as _Path

    _pyproject = _Path(__file__).resolve().parent.parent / "pyproject.toml"
    if _pyproject.exists():
        import re as _re

        _match = _re.search(r'version\s*=\s*"([^"]+)"', _pyproject.read_text())
        __version__ = _match.group(1) if _match else "0.0.0-dev"
    else:
        __version__ = "0.0.0-dev"
