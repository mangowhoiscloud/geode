"""Tests for the slopsquatting package-existence guard (PR-EXEC-HARDENING).

``parse_install_packages`` is pure; ``check_install_command`` is exercised with a
MOCKED httpx client so no test touches the real network.
"""

from __future__ import annotations

import asyncio

import pytest
from core.tools.package_guard import check_install_command, parse_install_packages


class TestParseInstallPackages:
    def test_pip_install_multiple(self) -> None:
        assert parse_install_packages("pip install foo bar") == [
            ("pypi", "foo"),
            ("pypi", "bar"),
        ]

    def test_uv_pip_install_strips_version(self) -> None:
        assert parse_install_packages("uv pip install x==1.0") == [("pypi", "x")]

    def test_uv_add(self) -> None:
        assert parse_install_packages("uv add requests") == [("pypi", "requests")]

    def test_pip3(self) -> None:
        assert parse_install_packages("pip3 install requests") == [("pypi", "requests")]

    def test_npm_install(self) -> None:
        assert parse_install_packages("npm install left-pad") == [("npm", "left-pad")]

    def test_flags_paths_urls_vcs_scoped_skipped(self) -> None:
        cmd = (
            "pip install --upgrade real-pkg ./local /abs/path ~/home "
            "https://example.com/x.whl git+https://github.com/a/b @scope/pkg"
        )
        # Only the bare name ``real-pkg`` survives; flag/path/url/vcs/scoped args
        # all fail-open (skipped).
        assert parse_install_packages(cmd) == [("pypi", "real-pkg")]

    def test_extras_stripped(self) -> None:
        assert parse_install_packages("pip install fastapi[all]") == [("pypi", "fastapi")]

    def test_non_install_command(self) -> None:
        assert parse_install_packages("ls -la") == []
        assert parse_install_packages("pip list") == []
        assert parse_install_packages("echo pip install foo") == []

    def test_compound_command_does_not_bypass_guard(self) -> None:
        # A compound command must be parsed per-segment: an install hidden after
        # a shell operator is still caught, and the operator / sub-command tokens
        # are never mistaken for package names.
        assert parse_install_packages("echo hi && pip install slopsquat-fake") == [
            ("pypi", "slopsquat-fake")
        ]
        assert parse_install_packages("pip install x && pip install y") == [
            ("pypi", "x"),
            ("pypi", "y"),
        ]
        assert parse_install_packages("cat foo | uv pip install bar==1.2") == [("pypi", "bar")]

    def test_wrapper_prefixes_detected(self) -> None:
        # python -m pip / generic env-var prefix / env wrapper must not evade.
        assert parse_install_packages("python -m pip install fakepkg") == [("pypi", "fakepkg")]
        assert parse_install_packages("python3 -m pip install fakepkg") == [("pypi", "fakepkg")]
        assert parse_install_packages("FOO=bar pip install fakepkg") == [("pypi", "fakepkg")]
        assert parse_install_packages("env pip install fakepkg") == [("pypi", "fakepkg")]

    def test_custom_index_skips_segment_fail_open(self) -> None:
        # A custom index/registry (flag OR env var) means the source is not
        # public PyPI/npm; a public 404 is not definitive, so the segment is
        # skipped (fail-open) to never false-block a private-index install.
        assert parse_install_packages("pip install --index-url https://corp internal-pkg") == []
        assert parse_install_packages("pip install -i https://corp internal-pkg") == []
        assert parse_install_packages("npm install --registry https://corp internal-pkg") == []
        assert parse_install_packages("PIP_INDEX_URL=https://corp pip install internal-pkg") == []
        assert parse_install_packages("UV_INDEX_URL=https://corp uv pip install internal") == []


class _FakeResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


class _FakeClient:
    """Minimal async-context httpx.AsyncClient stand-in.

    ``status_for`` maps a name → status code; ``raise_on_get`` simulates a
    network error. Unknown names default to 404 (missing).
    """

    def __init__(
        self,
        status_for: dict[str, int] | None = None,
        *,
        raise_on_get: bool = False,
        **_kwargs: object,
    ) -> None:
        self._status_for = status_for or {}
        self._raise = raise_on_get

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    async def get(self, url: str) -> _FakeResponse:
        if self._raise:
            raise RuntimeError("network down")
        # pypi: .../<name>/json  ; npm: .../<name>
        trimmed = url.rstrip("/")
        name = trimmed.rsplit("/", 1)[-1]
        if name == "json":
            name = trimmed.rsplit("/", 2)[-2]
        return _FakeResponse(self._status_for.get(name, 404))


def _patch_client(monkeypatch: pytest.MonkeyPatch, **kwargs: object) -> None:
    def _factory(**client_kwargs: object) -> _FakeClient:
        return _FakeClient(**kwargs, **client_kwargs)

    monkeypatch.setattr("core.tools.package_guard.httpx.AsyncClient", _factory)


class TestCheckInstallCommand:
    def test_missing_package_blocks(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_client(monkeypatch, status_for={})  # everything 404s
        reason = asyncio.run(check_install_command("pip install totally-fake-pkg"))
        assert reason is not None
        assert "totally-fake-pkg" in reason
        assert "slopsquatted" in reason

    def test_existing_package_allowed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_client(monkeypatch, status_for={"requests": 200})
        assert asyncio.run(check_install_command("pip install requests")) is None

    def test_network_error_fails_open(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_client(monkeypatch, raise_on_get=True)
        assert asyncio.run(check_install_command("pip install anything")) is None

    def test_guard_disabled_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from core.config import settings

        monkeypatch.setattr(settings, "package_install_guard", False)
        # Even with a client that would 404, the disabled guard short-circuits.
        _patch_client(monkeypatch, status_for={})
        assert asyncio.run(check_install_command("pip install totally-fake-pkg")) is None

    def test_non_install_command_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_client(monkeypatch, status_for={})
        assert asyncio.run(check_install_command("ls -la")) is None
