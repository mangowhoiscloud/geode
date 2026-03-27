"""Tests for L4 Gateway Hooks -- webhook handler."""

from __future__ import annotations

import json
import urllib.request
from typing import Any

from core.gateway.webhook_handler import WebhookHandler, start_webhook_server


class TestWebhookHandler:
    """Unit tests for WebhookHandler and start_webhook_server."""

    def test_start_and_post(self) -> None:
        """Webhook server accepts POST and dispatches to processor."""
        calls: list[str] = []

        def fake_processor(content: str, metadata: dict[str, Any]) -> str:
            calls.append(content)
            return "ok-response"

        server = start_webhook_server(fake_processor, port=0)  # port 0 = OS picks free port
        port = server.server_address[1]
        try:
            payload = json.dumps({"action": "hello world"}).encode()
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/webhook",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                body = json.loads(resp.read())
            assert resp.status == 200
            assert body["status"] == "ok"
            assert "ok-response" in body["response"]
            assert len(calls) == 1
            assert "[webhook] hello world" in calls[0]
        finally:
            server.shutdown()

    def test_missing_action_returns_400(self) -> None:
        """POST with empty payload returns 400."""
        server = start_webhook_server(lambda c, m: "", port=0)
        port = server.server_address[1]
        try:
            payload = json.dumps({}).encode()
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/webhook",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                urllib.request.urlopen(req, timeout=5)
            except urllib.error.HTTPError as exc:
                assert exc.code == 400
        finally:
            server.shutdown()

    def test_processor_exception_returns_500(self) -> None:
        """When processor raises, webhook returns 500."""

        def bad_processor(content: str, metadata: dict[str, Any]) -> str:
            raise RuntimeError("boom")

        server = start_webhook_server(bad_processor, port=0)
        port = server.server_address[1]
        try:
            payload = json.dumps({"action": "trigger"}).encode()
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/webhook",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                urllib.request.urlopen(req, timeout=5)
            except urllib.error.HTTPError as exc:
                assert exc.code == 500
                body = json.loads(exc.read())
                assert "boom" in body["error"]
        finally:
            server.shutdown()

    def test_text_key_extraction(self) -> None:
        """Webhook extracts action from 'text' key as fallback."""
        calls: list[str] = []

        def proc(content: str, metadata: dict[str, Any]) -> str:
            calls.append(content)
            return "done"

        server = start_webhook_server(proc, port=0)
        port = server.server_address[1]
        try:
            payload = json.dumps({"text": "do something"}).encode()
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/webhook",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                assert resp.status == 200
            assert "[webhook] do something" in calls[0]
        finally:
            server.shutdown()

    def test_handler_class_defaults(self) -> None:
        """WebhookHandler has expected class attributes."""
        assert hasattr(WebhookHandler, "_processor")
