"""Phase E — computer-use execution environment (host | in-container sandbox).

Pins the HOST-side contract WITHOUT a container: the env branch, the thin HTTP
client's request/response handling, the fail-loud invariant (sandbox unreachable
→ error, NEVER host execution), and the audit safety guard. The real container
round-trip is live-only (`docker/computer-use-sandbox/`, unverified).
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest
from core.tools import computer_use as cu
from core.tools.computer_use import ComputerUseHarness


@pytest.fixture
def _env(monkeypatch: pytest.MonkeyPatch):
    from core.config import settings

    def _set(env: str, url: str = "http://127.0.0.1:8787") -> None:
        monkeypatch.setattr(settings, "computer_use_env", env, raising=False)
        monkeypatch.setattr(settings, "computer_use_sandbox_url", url, raising=False)
        monkeypatch.setattr(settings, "computer_use_driver", "python", raising=False)
        monkeypatch.setattr(settings, "computer_use_helper_path", "", raising=False)

    return _set


def _run(coro):
    return asyncio.run(coro)


class TestEnvResolution:
    def test_default_host(self, _env) -> None:
        _env("host")
        assert cu.computer_use_env() == "host"

    def test_sandbox(self, _env) -> None:
        _env("sandbox")
        assert cu.computer_use_env() == "sandbox"

    def test_empty_is_documented_host_default(self, _env) -> None:
        _env("")
        assert cu.computer_use_env() == "host"

    def test_invalid_routes_to_sandbox_not_host(self, _env) -> None:
        """fail-safe: a config typo (bypasses the pydantic validator) must NOT
        silently drive the real desktop — it routes to sandbox (fail-loud)."""
        _env("sanbox")  # typo
        assert cu.computer_use_env() == "sandbox"


class TestExecuteBranch:
    def test_host_env_uses_local_execute(self, _env) -> None:
        _env("host")
        h = ComputerUseHarness()
        with (
            patch.object(
                h, "_execute_sync", return_value={"result": "success", "action": "x"}
            ) as ex,
            patch.object(h, "_sandbox_execute_sync") as sx,
        ):
            out = _run(h.aexecute("screenshot"))
        ex.assert_called_once()
        sx.assert_not_called()
        assert out["result"] == "success"

    def test_sandbox_env_uses_http_client_not_host(self, _env) -> None:
        """env=sandbox must dispatch to the shim, NEVER touch local pyautogui."""
        _env("sandbox")
        h = ComputerUseHarness()
        with (
            patch.object(h, "_sandbox_execute_sync", return_value={"result": "success"}) as sx,
            patch.object(h, "_execute_sync") as ex,
        ):
            out = _run(h.aexecute("screenshot"))
        sx.assert_called_once()
        ex.assert_not_called()  # host execution path never invoked
        assert out["result"] == "success"

    def test_helper_driver_uses_helper_not_pyautogui(self, _env, monkeypatch) -> None:
        from core.config import settings

        _env("host")
        monkeypatch.setattr(settings, "computer_use_driver", "helper", raising=False)
        h = ComputerUseHarness()
        with (
            patch(
                "core.tools.computer_use._helper_request_sync",
                return_value={
                    "result": "success",
                    "action": "screenshot",
                    "driver": "macos_helper",
                    "screen_width": 3420,
                    "screen_height": 2214,
                    "screenshot": "B64",
                },
            ) as hx,
            patch.object(h, "_execute_sync") as ex,
        ):
            out = _run(h.aexecute("screenshot"))

        hx.assert_called_once()
        ex.assert_not_called()
        assert out["result"] == "success"
        assert out["driver"] == "macos_helper"
        assert out["observation"]["env"] == "host-helper"
        assert out["observation"]["driver"] == "macos_helper"
        assert out["observation"]["screen_width"] == 3420

    def test_auto_driver_prefers_installed_helper(self, _env, monkeypatch, tmp_path) -> None:
        from core.config import settings

        helper = tmp_path / "geode-computer-helper"
        helper.write_text("#!/bin/sh\n")
        _env("host")
        monkeypatch.setattr(settings, "computer_use_driver", "auto", raising=False)
        monkeypatch.setattr(settings, "computer_use_helper_path", str(helper), raising=False)
        h = ComputerUseHarness()
        with (
            patch(
                "core.tools.computer_use._helper_request_sync",
                return_value={
                    "result": "success",
                    "action": "screenshot",
                    "driver": "macos_helper",
                    "screen_width": 100,
                    "screen_height": 100,
                    "screenshot": "B64",
                },
            ) as hx,
            patch.object(h, "_execute_sync") as ex,
        ):
            out = _run(h.aexecute("screenshot"))

        hx.assert_called_once()
        ex.assert_not_called()
        assert out["driver"] == "macos_helper"

    def test_required_helper_missing_is_dependency_error(self, _env, monkeypatch) -> None:
        from core.config import settings

        _env("host")
        monkeypatch.setattr(settings, "computer_use_driver", "helper", raising=False)
        h = ComputerUseHarness()
        with (
            patch("core.tools.computer_use.computer_use_helper_path", return_value=None),
            patch.object(h, "_execute_sync") as ex,
        ):
            out = _run(h.aexecute("screenshot"))

        ex.assert_not_called()
        assert out["error_type"] == "dependency"
        assert "helper is not installed" in out["error"]


class _FakeResp:
    """Minimal stand-in for an httpx.Response."""

    def __init__(self, json_value: object) -> None:
        self._json = json_value

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return self._json


class TestSandboxClient:
    def test_success_returns_parsed_result(self, _env) -> None:
        _env("sandbox")
        h = ComputerUseHarness()
        result = {"result": "success", "action": "click", "screenshot": "B64"}
        with patch("httpx.post", return_value=_FakeResp(result)):
            out = h._sandbox_execute_sync("click", {"x": 1, "y": 2})
        assert out["result"] == "success"
        assert out["action"] == "click"
        assert out["screenshot"] == "B64"
        assert out["observation"]["env"] == "sandbox"

    def test_unreachable_is_fail_loud_not_host_fallback(self, _env) -> None:
        """Sandbox down → error result; the host _execute_sync is NOT called."""
        import httpx

        _env("sandbox")
        h = ComputerUseHarness()
        with (
            patch("httpx.post", side_effect=httpx.ConnectError("connection refused")),
            patch.object(h, "_execute_sync") as ex,
        ):
            out = h._sandbox_execute_sync("screenshot", {})
        assert "error" in out and "unreachable" in out["error"]
        assert out["error_kind"] == "sandbox_unreachable"
        assert out["recovery"]["policy"] == "escalate"
        ex.assert_not_called()

    def test_empty_url_errors(self, _env) -> None:
        _env("sandbox", url="")
        h = ComputerUseHarness()
        out = h._sandbox_execute_sync("screenshot", {})
        assert "error" in out and "empty" in out["error"]
        assert out["error_kind"] == "sandbox_config"

    def test_non_object_response_errors(self, _env) -> None:
        _env("sandbox")
        h = ComputerUseHarness()
        with patch("httpx.post", return_value=_FakeResp("just a string")):
            out = h._sandbox_execute_sync("screenshot", {})
        assert "error" in out


class TestAuditSafetyGuard:
    def test_audit_with_host_env_disables_computer_use(self, _env, monkeypatch) -> None:
        """A Petri audit must never drive the REAL desktop: audit + env=host → off."""
        from core.config import settings
        from core.llm.providers.anthropic import is_computer_use_enabled

        monkeypatch.setattr(settings, "computer_use_enabled", True, raising=False)
        monkeypatch.setenv("GEODE_AUDIT_UNRESTRICTED", "1")
        _env("host")
        assert is_computer_use_enabled() is False

    def test_sandbox_env_enabled_without_host_pyautogui(self, _env, monkeypatch) -> None:
        """Sandbox mode needs only HTTP on the host (pyautogui lives in the
        container), so it is enabled even on a clean host — and audit allows it
        (virtual desktop, not the real one)."""
        from core.config import settings
        from core.llm.providers import anthropic as ap

        monkeypatch.setattr(settings, "computer_use_enabled", True, raising=False)
        monkeypatch.setenv("GEODE_AUDIT_UNRESTRICTED", "1")
        _env("sandbox")
        assert ap.is_computer_use_enabled() is True  # no pyautogui requirement on the host

    def test_host_env_requires_pyautogui(self, _env, monkeypatch) -> None:
        from core.config import settings
        from core.llm.providers import anthropic as ap

        monkeypatch.setattr(settings, "computer_use_enabled", True, raising=False)
        monkeypatch.delenv("GEODE_AUDIT_UNRESTRICTED", raising=False)
        _env("host")
        try:
            import pyautogui  # noqa: F401

            assert ap.is_computer_use_enabled() is True
        except ImportError:
            assert ap.is_computer_use_enabled() is False
