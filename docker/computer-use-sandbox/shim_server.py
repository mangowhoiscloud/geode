"""In-container computer-use shim — the server end of the Phase-E sandbox.

Runs INSIDE the Docker image (Xvfb virtual display + pyautogui). The host GEODE
harness, when ``computer_use_env=sandbox``, POSTs ``{"action", "params"}`` to
``/cmd``; this runs the SAME :class:`core.tools.computer_use.ComputerUseHarness`
action against the container's virtual display and returns the identical result
shape (``{"result"/"error", "action", "screenshot"}``). So the host never
touches a display — it only speaks HTTP.

It calls the host-execution primitive ``_execute_sync`` directly (NOT
``aexecute``) so it never re-enters the env branch: inside the container this IS
the host, driving the container's own Xvfb.

unverified — live test required (CANNOT §4d): no Docker host was available to
exercise the round-trip; the action→display→screenshot path is validated only
in a real container.
"""

from __future__ import annotations

import json
import logging
from http.server import BaseHTTPRequestHandler, HTTPServer

from core.tools.computer_use import ComputerUseHarness

log = logging.getLogger(__name__)
_HARNESS = ComputerUseHarness()
_PORT = 8787


class _CmdHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802 — BaseHTTPRequestHandler API
        if self.path != "/cmd":
            self.send_error(404, "only POST /cmd")
            return
        action = ""
        try:
            length = int(self.headers.get("Content-Length", 0) or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
            action = str(body.get("action", ""))
            params = dict(body.get("params") or {})
            result = _HARNESS._execute_sync(action, **params)
        except Exception as exc:  # noqa: BLE001 — surface any shim error as a result
            result = {"error": f"shim error: {exc}", "action": action}
        payload = json.dumps(result).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_args: object) -> None:  # silence default stderr access log
        return


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    log.info("computer-use sandbox shim listening on :%d (POST /cmd)", _PORT)
    HTTPServer(("0.0.0.0", _PORT), _CmdHandler).serve_forever()  # noqa: S104 — container-internal


if __name__ == "__main__":
    main()
