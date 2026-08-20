"""Claude CLI subscription credential behavior."""

from __future__ import annotations

import json
from types import SimpleNamespace

from core.auth.claude_cli_oauth import (
    get_claude_oauth_metadata,
    is_claude_oauth_available,
    resolve_claude_oauth_token,
)


def _security_result(*, returncode: int = 0, stdout: str = "") -> SimpleNamespace:
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr="")


def _keychain_blob(token: str | None = None) -> str:
    token = token or "sk-ant-test"  # nosec B105 - inert fixture credential
    return json.dumps(
        {
            "claudeAiOauth": {
                "accessToken": token,
                "subscriptionType": "max",
                "rateLimitTier": "default_claude_max_20x",
                "scopes": ["user:inference"],
                "expiresAt": 1_778_978_149_370,
            }
        }
    )


def test_keychain_token_and_metadata(monkeypatch) -> None:
    monkeypatch.setattr("core.auth.claude_cli_oauth.platform.system", lambda: "Darwin")
    monkeypatch.setattr(
        "core.auth.claude_cli_oauth.subprocess.run",
        lambda *_args, **_kwargs: _security_result(stdout=_keychain_blob()),
    )

    assert resolve_claude_oauth_token() == "sk-ant-test"
    assert is_claude_oauth_available() is True
    assert get_claude_oauth_metadata() == {
        "subscription_type": "max",
        "rate_limit_tier": "default_claude_max_20x",
        "scopes": ["user:inference"],
        "expires_at": 1_778_978_149_370,
        "source": "keychain",
    }


def test_missing_or_invalid_keychain_is_unavailable(monkeypatch) -> None:
    monkeypatch.setattr("core.auth.claude_cli_oauth.platform.system", lambda: "Darwin")
    monkeypatch.setattr(
        "core.auth.claude_cli_oauth.subprocess.run",
        lambda *_args, **_kwargs: _security_result(returncode=44),
    )
    assert resolve_claude_oauth_token() is None

    monkeypatch.setattr(
        "core.auth.claude_cli_oauth.subprocess.run",
        lambda *_args, **_kwargs: _security_result(stdout=_keychain_blob("wrong-prefix")),
    )
    assert resolve_claude_oauth_token() is None
