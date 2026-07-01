from __future__ import annotations

from core.cli.ipc_client import IPCClient


def test_send_prompt_refreshes_client_capability_before_prompt(monkeypatch) -> None:
    client = IPCClient()
    client._sock = object()  # truthy sentinel; no real socket needed
    sent: list[dict] = []
    monkeypatch.setattr(client, "_send", lambda payload: sent.append(payload))
    monkeypatch.setattr(client, "_recv", lambda: {"type": "result", "text": ""})

    result = client.send_prompt("hello")

    assert result["type"] == "result"
    assert [payload["type"] for payload in sent[:2]] == ["client_capability", "prompt"]
    assert sent[1]["text"] == "hello"
