"""Codex OAuth runtime cache refresh regressions."""

from __future__ import annotations

import time


class _FakeOpenAI:
    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs


def test_codex_oauth_adapter_invalidates_loop_cache_when_token_changes(monkeypatch) -> None:
    from core.llm.adapters import codex_oauth
    from core.llm.providers.codex import _ResolvedCodexToken

    current_token = {"value": "access-old"}

    class FakeCache:
        def __init__(self) -> None:
            self.client: dict[str, str] | None = None
            self.invalidations = 0

        def get(self, builder):
            if self.client is None:
                self.client = builder()
            return self.client

        def invalidate(self) -> None:
            self.invalidations += 1
            self.client = None

    def fake_resolve(*, force_refresh: bool = False) -> _ResolvedCodexToken:
        assert force_refresh is True
        return _ResolvedCodexToken(
            token=current_token["value"],
            source="codex-cli:~/.codex/auth.json",
            expires_at=time.time() + 3600,
        )

    fake_cache = FakeCache()
    adapter = codex_oauth.CodexOAuthAdapter()
    adapter._clients = fake_cache
    monkeypatch.setattr("core.llm.providers.codex._resolve_codex_token_info", fake_resolve)
    monkeypatch.setattr(
        codex_oauth,
        "build_async_codex_client",
        lambda token: {"api_key": token},
    )

    first = adapter._get_client()
    again = adapter._get_client()
    current_token["value"] = "access-new"
    second = adapter._get_client()

    assert first is again
    assert second is not first
    assert first["api_key"] == "access-old"
    assert second["api_key"] == "access-new"
    assert fake_cache.invalidations == 2
