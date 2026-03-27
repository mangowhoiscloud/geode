"""L4 Gateway Hooks -- external webhook -> agent trigger (OpenClaw pattern).

Minimal HTTP endpoint that accepts POST requests and dispatches them
to the AgenticLoop processor.  Runs on a daemon thread so it shuts down
with the main process.

Usage (via ``geode serve`` when ``webhook_enabled=True``)::

    curl -X POST http://localhost:8765/webhook \
         -H "Content-Type: application/json" \
         -d '{"action": "summarize today agenda"}'
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

log = logging.getLogger(__name__)


class WebhookHandler(BaseHTTPRequestHandler):
    """Minimal HTTP handler for incoming webhooks."""

    # Set by ``start_webhook_server`` before the server accepts connections.
    _processor: Callable[[str, dict[str, Any]], str] | None = None

    def do_POST(self) -> None:
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8")

        try:
            payload: dict[str, Any] = json.loads(body) if body else {}
        except json.JSONDecodeError:
            payload = {"raw": body}

        # Extract action text -- try common keys
        action = payload.get("action") or payload.get("text") or payload.get("message")
        if action is None:
            action = str(payload) if payload else ""

        processor = WebhookHandler._processor
        if processor and action:
            try:
                response = processor(f"[webhook] {action}", {})
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(
                    json.dumps(
                        {
                            "status": "ok",
                            "response": response[:500] if response else "",
                        }
                    ).encode()
                )
            except Exception as exc:
                log.warning("Webhook processor error: %s", exc, exc_info=True)
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(exc)}).encode())
        else:
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error": "no action or processor"}')

    # Silence per-request access logs (already logged at DEBUG level).
    def log_message(self, fmt: str, *args: Any) -> None:
        log.debug("Webhook: %s", fmt % args)


def start_webhook_server(
    processor: Callable[[str, dict[str, Any]], str],
    *,
    port: int = 8765,
) -> HTTPServer:
    """Start the webhook HTTP server on a daemon thread.

    Args:
        processor: ``(content, metadata) -> response_text`` callable,
                   same signature as ``_gateway_processor`` in ``geode serve``.
        port: TCP port to bind (default 8765).

    Returns:
        The running ``HTTPServer`` instance (call ``.shutdown()`` to stop).
    """
    WebhookHandler._processor = processor
    server = HTTPServer(("127.0.0.1", port), WebhookHandler)
    thread = threading.Thread(
        target=server.serve_forever,
        name="geode-webhook",
        daemon=True,
    )
    thread.start()
    log.info("Webhook server started on port %d", port)
    return server
