"""Required Codex model policy rejects requests before any credential/client I/O."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import Mock

import pytest
from core.config import settings
from core.llm.adapters.base import AdapterCallRequest, Message
from core.llm.adapters.codex_oauth import CodexOAuthAdapter


class _ClientBoundaryError(Exception):
    """Offline sentinel proving policy admission reached client creation."""


async def _request(adapter: CodexOAuthAdapter, method: str, model: str) -> None:
    request = AdapterCallRequest(model=model, messages=[Message(role="user", content="probe")])
    if method == "astream":
        async for _event in adapter.astream(request):
            pass
    elif method == "aweb_search":
        await adapter.aweb_search("probe", model=model)
    elif method == "acomplete_text":
        await adapter.acomplete_text("probe", model=model)
    else:
        await adapter.acomplete(request)


@pytest.mark.parametrize("method", ["acomplete", "astream", "aweb_search", "acomplete_text"])
def test_required_policy_blocks_mismatch_before_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, method: str
) -> None:
    path = tmp_path / "policy.toml"
    path.write_text('[policy]\nallowlist = ["gpt-5.6-sol"]\n')
    monkeypatch.setattr(settings, "model_policy_path", str(path))
    adapter = CodexOAuthAdapter()
    client = Mock(side_effect=_ClientBoundaryError)
    monkeypatch.setattr(adapter, "_get_client", client)

    with pytest.raises(ValueError, match="disallowed by the required model policy"):
        asyncio.run(_request(adapter, method, "gpt-5.5"))
    client.assert_not_called()
    with pytest.raises(_ClientBoundaryError):
        asyncio.run(_request(adapter, method, "gpt-5.6-sol"))
    client.assert_called_once_with()


@pytest.mark.parametrize("content", [None, "{{invalid toml}}", '[policy]\nallowlist = "bad"'])
def test_required_policy_invalid_at_construction_does_not_create_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, content: str | None
) -> None:
    path = tmp_path / "policy.toml"
    if content is not None:
        path.write_text(content)
    monkeypatch.setattr(settings, "model_policy_path", str(path))
    client = Mock(side_effect=_ClientBoundaryError)
    monkeypatch.setattr(CodexOAuthAdapter, "_get_client", client)

    with pytest.raises(ValueError, match="required model policy"):
        CodexOAuthAdapter()
    client.assert_not_called()


@pytest.mark.parametrize("method", ["acomplete", "astream", "aweb_search", "acomplete_text"])
def test_default_configuration_preserves_existing_admission(
    monkeypatch: pytest.MonkeyPatch, method: str
) -> None:
    monkeypatch.setattr(settings, "model_policy_path", "")
    adapter = CodexOAuthAdapter()
    client = Mock(side_effect=_ClientBoundaryError)
    monkeypatch.setattr(adapter, "_get_client", client)

    with pytest.raises(_ClientBoundaryError):
        asyncio.run(_request(adapter, method, "gpt-5.5"))
    client.assert_called_once_with()


@pytest.mark.parametrize("mutation", ["replace", "remove", "malform"])
def test_adapter_snapshots_required_policy_for_lifetime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    path = tmp_path / "policy.toml"
    path.write_text('[policy]\nallowlist = ["gpt-5.6-sol"]\n')
    monkeypatch.setattr(settings, "model_policy_path", str(path))
    adapter = CodexOAuthAdapter()
    client = Mock(side_effect=_ClientBoundaryError)
    monkeypatch.setattr(adapter, "_get_client", client)
    if mutation == "remove":
        path.unlink()
    elif mutation == "malform":
        path.write_text("{{invalid toml}}")
    else:
        path.write_text('[policy]\nallowlist = ["gpt-5.5"]\n')
    # Neither file changes nor a settings reload widens this live adapter.
    monkeypatch.setattr(settings, "model_policy_path", "")

    with pytest.raises(ValueError, match="disallowed by the required model policy"):
        asyncio.run(_request(adapter, "acomplete", "gpt-5.5"))
    client.assert_not_called()
    with pytest.raises(_ClientBoundaryError):
        asyncio.run(_request(adapter, "acomplete", "gpt-5.6-sol"))
    client.assert_called_once_with()


@pytest.mark.parametrize("method", ["aweb_search", "acomplete_text"])
def test_required_policy_checks_resolved_default_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, method: str
) -> None:
    import core.config as cfg

    path = tmp_path / "policy.toml"
    path.write_text('[policy]\nallowlist = ["gpt-5.6-sol"]\n')
    monkeypatch.setattr(settings, "model_policy_path", str(path))
    monkeypatch.setattr(cfg, "CODEX_PRIMARY", "gpt-5.5")
    adapter = CodexOAuthAdapter()
    client = Mock(side_effect=_ClientBoundaryError)
    monkeypatch.setattr(adapter, "_get_client", client)

    with pytest.raises(ValueError, match="disallowed by the required model policy"):
        asyncio.run(_request(adapter, method, ""))
    client.assert_not_called()
