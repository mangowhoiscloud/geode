"""CLI Poller — Unix domain socket server for thin CLI client IPC.

Accepts multiple concurrent CLI client connections. Each connected client
gets an independent IPC session backed by serve's SharedServices (same MCP,
skills, hooks, memory as Slack/Discord pollers). SessionLane per-key
serialization ensures same-session ordering; different sessions run in parallel.

Protocol: line-delimited JSON over Unix domain socket.

Client → Server:
    {"type": "prompt", "text": "summarize this repository", "session_id": "..."}
    {"type": "command", "cmd": "/model", "args": "sonnet"}
    {"type": "exit"}

Server → Client:
    {"type": "stream", "data": "▸ tool_call(...)\\n"}   (during prompt execution)
    {"type": "result", "text": "...", "rounds": 3, "tool_calls": [...]}
    {"type": "command_result", "cmd": "...", "output": "..."}
    {"type": "error", "message": "..."}
    {"type": "session", "session_id": "cli-abc123"}
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import queue
import socket
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from core.server.supervised.services import SharedServices

from core.paths import CLI_SOCKET_PATH  # noqa: E402 — placed after TYPE_CHECKING block

DEFAULT_SOCKET_PATH = CLI_SOCKET_PATH  # P2 — was `Path.home() / ".geode" / "cli.sock"`

# Thread-local terminal capability advertised by the connected thin CLI.
# v0.84.0 — populated when the daemon receives a ``client_capability``
# message. Read by ``_run_prompt_streaming`` to construct the per-thread
# Rich Console with the client's actual TTY-ness and width, so ANSI /
# spinner output is suppressed when the thin CLI's stdout is not a TTY.
_client_capability_local = threading.local()


def _get_client_capability() -> tuple[bool, int]:
    """Return ``(is_tty, width)`` for the current handler thread.

    Defaults to ``(True, 120)`` for backward compatibility with thin
    clients that don't send a ``client_capability`` message.
    """
    is_tty = bool(getattr(_client_capability_local, "is_tty", True))
    width = int(getattr(_client_capability_local, "width", 120))
    if width <= 0:
        width = 120
    return is_tty, width


class _AsyncClientEndpoint:
    """Thread-safe bridge around an asyncio StreamWriter.

    The IPC reader and async prompt runner run on the CLIPoller event loop,
    while approval callbacks may still run in worker threads. This bridge keeps
    writes ordered and routes approval_response messages back to the blocking
    approval prompt without letting worker threads read from the socket.
    """

    def __init__(self, loop: asyncio.AbstractEventLoop, writer: asyncio.StreamWriter) -> None:
        self._loop = loop
        self._writer = writer
        self._write_lock = asyncio.Lock()
        self._pending_sends: set[asyncio.Task[None]] = set()
        self._approval_responses: queue.Queue[str] = queue.Queue()
        self._is_tty = True
        self._width = 120

    async def send_json_async(self, obj: dict[str, Any]) -> None:
        payload = json.dumps(obj, ensure_ascii=False) + "\n"
        async with self._write_lock:
            self._writer.write(payload.encode("utf-8"))
            await self._writer.drain()

    def send_json_nowait(self, obj: dict[str, Any]) -> None:
        """Schedule a write from the endpoint's own event-loop thread."""
        task = self._loop.create_task(self.send_json_async(obj))
        self._pending_sends.add(task)

        def _discard(done: asyncio.Task[None]) -> None:
            self._pending_sends.discard(done)
            with contextlib.suppress(Exception):
                done.result()

        task.add_done_callback(_discard)

    async def drain_pending_sends(self) -> None:
        """Wait for stream/event writes scheduled by sync file-like writers."""
        while self._pending_sends:
            pending = list(self._pending_sends)
            await asyncio.gather(*pending, return_exceptions=True)

    def send_json_threadsafe(self, obj: dict[str, Any], *, timeout_s: float = 5.0) -> None:
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None
        if running_loop is self._loop:
            self.send_json_nowait(obj)
            return
        future = asyncio.run_coroutine_threadsafe(self.send_json_async(obj), self._loop)
        try:
            future.result(timeout=timeout_s)
        except Exception:
            log.debug("Async IPC send failed", exc_info=True)

    def feed_approval_response(self, decision: str) -> None:
        self._approval_responses.put(decision)

    def set_capability(self, *, is_tty: bool, width: int) -> None:
        self._is_tty = is_tty
        self._width = width if width > 0 else 120

    def get_capability(self) -> tuple[bool, int]:
        return self._is_tty, self._width

    def request_approval(
        self,
        tool_name: str,
        detail: str,
        safety_level: str = "write",
    ) -> str:
        import time as _time

        self.send_json_threadsafe(
            {
                "type": "approval_request",
                "tool_name": tool_name,
                "detail": detail,
                "safety_level": safety_level,
            },
            timeout_s=10.0,
        )
        log.debug("HITL: sent approval_request tool=%s level=%s", tool_name, safety_level)
        _t0 = _time.monotonic()
        try:
            decision = self._approval_responses.get(timeout=120.0)
            log.info(
                "HITL: approval_response tool=%s decision=%s elapsed=%.1fs",
                tool_name,
                decision,
                _time.monotonic() - _t0,
            )
            return decision
        except queue.Empty:
            log.warning(
                "HITL: approval TIMEOUT tool=%s elapsed=%.1fs",
                tool_name,
                _time.monotonic() - _t0,
            )
            return "n"

    def close_threadsafe(self) -> None:
        async def _close() -> None:
            self._writer.close()
            with contextlib.suppress(OSError):
                await self._writer.wait_closed()

        future = asyncio.run_coroutine_threadsafe(_close(), self._loop)
        with contextlib.suppress(Exception):
            future.result(timeout=2.0)


class _StreamingWriter:
    """File-like object that relays console writes to a client socket.

    Each ``write()`` call sends ``{"type": "stream", "data": "..."}`` over
    the socket, so the thin client can render agentic UI (tool calls,
    results, token usage) in real-time as the AgenticLoop executes.

    Inspired by:
    - Codex CLI item-based streaming (discrete events over API)
    - OpenClaw System Events Queue (event → client relay)
    - autoresearch P6 L1 capture (capture all stdout)
    """

    def __init__(self, client: socket.socket | _AsyncClientEndpoint) -> None:
        self._client = client

    def write(self, text: str) -> int:
        if not text:
            return 0
        self._send_json({"type": "stream", "data": text})
        return len(text)

    def send_event(self, event_type: str, **data: Any) -> None:
        """Send a structured event (tool_start, tool_end, etc.)."""
        self._send_json({"type": event_type, **data})

    def _send_json(self, obj: dict[str, Any]) -> None:
        if isinstance(self._client, _AsyncClientEndpoint):
            self._client.send_json_threadsafe(obj)
            return
        try:
            payload = json.dumps(obj, ensure_ascii=False) + "\n"
            self._client.sendall(payload.encode("utf-8"))
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    def request_approval(
        self,
        tool_name: str,
        detail: str,
        safety_level: str = "write",
    ) -> str:
        """Send approval request to thin CLI and wait for response.

        Returns 'y', 'n', or 'a' (always).
        """
        if isinstance(self._client, _AsyncClientEndpoint):
            return self._client.request_approval(tool_name, detail, safety_level)

        self._send_json(
            {
                "type": "approval_request",
                "tool_name": tool_name,
                "detail": detail,
                "safety_level": safety_level,
            }
        )
        log.debug("HITL: sent approval_request tool=%s level=%s", tool_name, safety_level)
        import time as _time

        _t0 = _time.monotonic()
        # Block until thin client sends approval_response
        try:
            self._client.settimeout(120.0)  # 2 min for user decision
            buf = b""
            while True:
                chunk = self._client.recv(4096)
                if not chunk:
                    log.warning(
                        "HITL: connection closed tool=%s elapsed=%.1fs",
                        tool_name,
                        _time.monotonic() - _t0,
                    )
                    return "n"
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    msg = json.loads(line.decode("utf-8"))
                    if msg.get("type") == "approval_response":
                        decision = str(msg.get("decision", "n"))
                        log.info(
                            "HITL: approval_response tool=%s decision=%s elapsed=%.1fs",
                            tool_name,
                            decision,
                            _time.monotonic() - _t0,
                        )
                        return decision
                    else:
                        log.debug(
                            "HITL: ignoring non-approval msg type=%s",
                            msg.get("type"),
                        )
        except TimeoutError:
            log.warning(
                "HITL: approval TIMEOUT tool=%s elapsed=%.1fs",
                tool_name,
                _time.monotonic() - _t0,
            )
            return "n"
        except (OSError, json.JSONDecodeError) as exc:
            log.warning(
                "HITL: approval error tool=%s elapsed=%.1fs exc=%s",
                tool_name,
                _time.monotonic() - _t0,
                exc,
            )
            return "n"
        finally:
            self._client.settimeout(None)

    def flush(self) -> None:
        pass

    def isatty(self) -> bool:
        return True  # trick Rich into applying ANSI styles

    def fileno(self) -> int:
        return -1


class CLIPoller:
    """Unix domain socket server for CLI thin-client IPC.

    Unlike BasePoller subclasses (which poll external APIs), CLIPoller
    *listens* for a local CLI client connection. It does not inherit
    BasePoller because the lifecycle is fundamentally different:
    accept-loop vs poll-loop.
    """

    def __init__(
        self,
        services: SharedServices,
        *,
        socket_path: Path | None = None,
        scheduler_service: Any = None,
    ) -> None:
        self._services = services
        self._socket_path = socket_path or DEFAULT_SOCKET_PATH
        self._server: socket.socket | None = None
        self._async_server: asyncio.AbstractServer | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop_event = threading.Event()
        self._ready_event = threading.Event()
        self._startup_error: BaseException | None = None
        self._thread: threading.Thread | None = None
        self._active_clients: set[socket.socket | _AsyncClientEndpoint] = set()
        self._clients_lock = threading.Lock()
        self._scheduler_service = scheduler_service

    @property
    def channel_name(self) -> str:
        return "cli"

    @property
    def socket_path(self) -> Path:
        return self._socket_path

    def start(self) -> None:
        """Start listening on Unix domain socket."""
        if self._thread is not None and self._thread.is_alive():
            return

        # Clean up stale socket file
        if self._socket_path.exists():
            self._socket_path.unlink()

        self._stop_event.clear()
        self._ready_event.clear()
        self._startup_error = None
        self._thread = threading.Thread(
            target=self._run_async_server,
            name="geode-cli-poller",
            daemon=True,
        )
        self._thread.start()
        if not self._ready_event.wait(timeout=5.0):
            raise RuntimeError(f"CLI channel failed to start on {self._socket_path}")
        if self._startup_error is not None:
            raise RuntimeError("CLI channel startup failed") from self._startup_error
        log.info("CLI channel listening on %s", self._socket_path)

    def stop_accepting(self) -> None:
        """Stop accepting new connections but let active handlers finish.

        Closes the server socket and sets the stop event so the accept loop
        exits. Active client handler threads continue running until their
        current request completes.
        """
        self._stop_event.set()
        self._close_async_server()
        if self._server:
            with contextlib.suppress(OSError):
                self._server.close()
            self._server = None
        if self._thread and not self._active_clients:
            self._stop_async_loop()
            self._thread.join(timeout=5.0)
            self._thread = None
        log.info("CLI channel stopped accepting new connections")

    def stop(self) -> None:
        """Stop the socket server and clean up all clients."""
        self._stop_event.set()
        self._close_async_server()
        with self._clients_lock:
            for client in list(self._active_clients):
                if isinstance(client, _AsyncClientEndpoint):
                    client.close_threadsafe()
                else:
                    with contextlib.suppress(OSError):
                        client.close()
            self._active_clients.clear()
        if self._server:
            with contextlib.suppress(OSError):
                self._server.close()
        self._stop_async_loop()
        if self._thread:
            self._thread.join(timeout=5.0)
            self._thread = None
        if self._socket_path.exists():
            with contextlib.suppress(OSError):
                self._socket_path.unlink()
        log.info("CLI channel stopped")

    def _run_async_server(self) -> None:
        """Run the asyncio Unix socket server on the poller thread."""
        try:
            with asyncio.Runner() as runner:
                self._loop = runner.get_loop()
                runner.run(self._serve_async())
        except BaseException as exc:
            self._startup_error = exc
            self._ready_event.set()
            if not self._stop_event.is_set():
                log.warning("CLI async server failed", exc_info=True)
        finally:
            self._loop = None

    async def _serve_async(self) -> None:
        await self._start_async_server()
        while not self._stop_event.is_set():
            await asyncio.sleep(0.1)
        await self._close_async_server_async()

    async def _start_async_server(self) -> None:
        self._socket_path.parent.mkdir(parents=True, exist_ok=True)
        self._async_server = await asyncio.start_unix_server(
            self._handle_async_client,
            path=str(self._socket_path),
            backlog=5,
        )
        os.chmod(str(self._socket_path), 0o600)
        self._ready_event.set()

    async def _close_async_server_async(self) -> None:
        if self._async_server is None:
            return
        self._async_server.close()
        await self._async_server.wait_closed()
        self._async_server = None

    def _close_async_server(self) -> None:
        loop = self._loop
        if loop is None or not loop.is_running():
            return
        future = asyncio.run_coroutine_threadsafe(self._close_async_server_async(), loop)
        with contextlib.suppress(Exception):
            future.result(timeout=5.0)

    def _stop_async_loop(self) -> None:
        # The Runner-owned loop exits when _stop_event is set; keep this
        # method for lifecycle call sites that only need to wake/observe stop.
        return

    async def _handle_async_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle a connected thin CLI client on the async IPC transport."""
        loop = asyncio.get_running_loop()
        endpoint = _AsyncClientEndpoint(loop, writer)
        with self._clients_lock:
            self._active_clients.add(endpoint)
            active = len(self._active_clients)
        log.info("CLI client connected (%d active)", active)
        try:
            await self._handle_client_async(reader, endpoint)
        finally:
            with self._clients_lock:
                self._active_clients.discard(endpoint)
                active = len(self._active_clients)
            writer.close()
            with contextlib.suppress(OSError):
                await writer.wait_closed()
            if self._stop_event.is_set() and active == 0:
                self._stop_async_loop()
            log.info("CLI client session ended (%d active)", active)

    async def _handle_client_async(
        self,
        reader: asyncio.StreamReader,
        endpoint: _AsyncClientEndpoint,
    ) -> None:
        """Async client read loop.

        The thin client owns transport and rendering. The daemon owns shared
        services, lane admission, approval relay, and async AgenticLoop
        execution for each IPC session.
        """
        from core.agent.conversation import ConversationContext
        from core.server.supervised.services import SessionMode

        self._propagate_contextvars()

        conversation = ConversationContext()
        session_id = f"cli-{os.urandom(4).hex()}"

        def _ipc_approval(tool_name: str, detail: str, safety_level: str) -> str:
            return endpoint.request_approval(tool_name, detail, safety_level)

        _executor, agent_loop = self._services.create_session(
            SessionMode.IPC,
            conversation=conversation,
            propagate_context=True,
            approval_callback=_ipc_approval,
        )

        await endpoint.send_json_async({"type": "session", "session_id": session_id})

        while not self._stop_event.is_set():
            try:
                line = await reader.readline()
                if not line:
                    log.info("CLI client disconnected")
                    break
                msg = json.loads(line.decode("utf-8"))

                if msg.get("type") == "approval_response":
                    endpoint.feed_approval_response(str(msg.get("decision", "n")))
                    continue

                msg["_client"] = endpoint
                response = await self._process_message_async(
                    msg,
                    agent_loop,
                    conversation,
                    session_id,
                )
                if response is None:
                    await endpoint.send_json_async({"type": "exit_ack"})
                    return
                await endpoint.send_json_async(response)
            except (ConnectionResetError, BrokenPipeError):
                log.info("CLI client connection lost")
                break
            except json.JSONDecodeError:
                await endpoint.send_json_async({"type": "error", "message": "Invalid JSON"})
            except Exception:
                log.warning("CLI handler error", exc_info=True)
                await endpoint.send_json_async({"type": "error", "message": "Internal error"})

    async def _process_message_async(
        self,
        msg: dict[str, Any],
        loop: Any,
        conversation: Any,
        session_id: str,
    ) -> dict[str, Any] | None:
        msg_type = msg.get("type", "")

        if msg_type == "prompt":
            text = msg.get("text", "").strip()
            if not text:
                return {"type": "error", "message": "Empty prompt"}
            try:
                return await self._run_prompt_streaming_async(
                    text,
                    loop,
                    session_id,
                    msg.get("_client"),
                )
            except Exception as exc:
                log.warning("CLI prompt execution error", exc_info=True)
                return {"type": "error", "message": str(exc)}

        if msg_type == "command":
            return await asyncio.to_thread(self._handle_command_on_server, msg, loop)

        if msg_type == "resume":
            return await asyncio.to_thread(self._handle_resume, msg, loop, conversation)

        if msg_type == "client_capability":
            endpoint = msg.get("_client")
            is_tty = bool(msg.get("is_tty", True))
            width_raw = msg.get("width", 120)
            try:
                width = int(width_raw)
            except (TypeError, ValueError):
                width = 120
            if isinstance(endpoint, _AsyncClientEndpoint):
                endpoint.set_capability(is_tty=is_tty, width=width)
            # Adopt the thin CLI's project-resolved model. The daemon creates the
            # session with its OWN launch-cwd default (``settings.model``); the
            # thin CLI resolves the model at the *caller's* project cwd. Without
            # this the session's project config is ignored and the executed model
            # diverges from the banner. Sent once at session start, before any
            # prompt, so the swap is safe (no in-flight LLM call).
            cli_model = str(msg.get("model", "")).strip()
            if cli_model and cli_model != getattr(loop, "model", ""):
                try:
                    from core.config import _resolve_provider

                    await loop.update_model_async(
                        cli_model, _resolve_provider(cli_model), reason="cli_session_cwd"
                    )
                    log.info(
                        "client_capability: adopted CLI project model %s (session=%s)",
                        cli_model,
                        session_id,
                    )
                except Exception:
                    log.warning(
                        "client_capability: failed to adopt CLI model %s", cli_model, exc_info=True
                    )
            log.debug("client_capability: is_tty=%s width=%d", is_tty, width if width > 0 else 120)
            return {"type": "ack"}

        if msg_type == "exit":
            return None

        if msg_type == "approval_response":
            log.debug("Dropping stale approval_response: %s", msg.get("decision"))
            return {"type": "ack"}

        return {"type": "error", "message": f"Unknown message type: {msg_type}"}

    def _accept_loop(self) -> None:
        """Accept loop — spawns a handler thread per client."""
        while not self._stop_event.is_set():
            try:
                assert self._server is not None
                client, _ = self._server.accept()
                with self._clients_lock:
                    self._active_clients.add(client)
                log.info("CLI client connected (%d active)", len(self._active_clients))
                t = threading.Thread(
                    target=self._client_thread,
                    args=(client,),
                    name=f"geode-cli-{os.urandom(2).hex()}",
                    daemon=True,
                )
                t.start()
            except TimeoutError:
                continue
            except OSError:
                if not self._stop_event.is_set():
                    log.warning("CLI accept error", exc_info=True)
                break

    def _client_thread(self, client: socket.socket) -> None:
        """Run _handle_client and clean up on exit."""
        try:
            self._handle_client(client)
        finally:
            with self._clients_lock:
                self._active_clients.discard(client)
            import contextlib

            with contextlib.suppress(OSError):
                client.close()
            log.info("CLI client session ended (%d active)", len(self._active_clients))

    def _handle_client(self, client: socket.socket) -> None:
        """Handle a connected CLI client session.

        Creates an IPC-mode session (DANGEROUS blocked, WRITE allowed)
        gated by SessionLane + Global Lane via acquire_all_async().
        """
        from core.agent.conversation import ConversationContext
        from core.server.supervised.services import SessionMode

        # ContextVars do NOT propagate to threads — set them explicitly
        self._propagate_contextvars()

        # Thread-local session meter — each IPC session tracks its own
        # model, elapsed time, and token counts independently.
        from core.ui.agentic_ui import init_session_meter

        init_session_meter()

        client.settimeout(None)  # blocking reads
        buf = b""
        conversation = ConversationContext()
        session_id = f"cli-{os.urandom(4).hex()}"

        # Build IPC approval relay: WRITE/DANGEROUS tools prompt thin CLI
        _writer = _StreamingWriter(client)

        def _ipc_approval(tool_name: str, detail: str, safety_level: str) -> str:
            return _writer.request_approval(tool_name, detail, safety_level)

        # Create an IPC session backed by serve's SharedServices
        _executor, loop = self._services.create_session(
            SessionMode.IPC,
            conversation=conversation,
            propagate_context=True,
            approval_callback=_ipc_approval,
        )

        # Send session ID to client
        self._send(client, {"type": "session", "session_id": session_id})

        while not self._stop_event.is_set():
            try:
                chunk = client.recv(65536)
                if not chunk:
                    log.info("CLI client disconnected")
                    break
                buf += chunk

                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    msg = json.loads(line.decode("utf-8"))
                    msg["_client"] = client  # pass socket for streaming
                    response = self._process_message(msg, loop, conversation, session_id)
                    if response is None:
                        # Exit signal
                        self._send(client, {"type": "exit_ack"})
                        return
                    self._send(client, response)
            except (ConnectionResetError, BrokenPipeError):
                log.info("CLI client connection lost")
                break
            except json.JSONDecodeError:
                self._send(client, {"type": "error", "message": "Invalid JSON"})
            except Exception:
                log.warning("CLI handler error", exc_info=True)
                self._send(
                    client,
                    {"type": "error", "message": "Internal error"},
                )

    def _process_message(
        self,
        msg: dict[str, Any],
        loop: Any,
        conversation: Any,
        session_id: str,
    ) -> dict[str, Any] | None:
        """Process a single client message. Returns response dict or None for exit."""
        msg_type = msg.get("type", "")

        if msg_type == "exit":
            return None

        if msg_type == "prompt":
            text = msg.get("text", "").strip()
            if not text:
                return {"type": "error", "message": "Empty prompt"}

            try:
                return self._run_prompt_streaming(
                    text,
                    loop,
                    session_id,
                    msg.get("_client"),
                )
            except Exception as exc:
                log.warning("CLI prompt execution error", exc_info=True)
                return {"type": "error", "message": str(exc)}

        if msg_type == "command":
            return self._handle_command_on_server(msg, loop)

        if msg_type == "resume":
            return self._handle_resume(msg, loop, conversation)

        # v0.84.0 — thin CLI advertises terminal capability so the daemon
        # can suppress ANSI / spinner output when stdout is not a TTY.
        if msg_type == "client_capability":
            is_tty = bool(msg.get("is_tty", True))
            width_raw = msg.get("width", 120)
            try:
                width = int(width_raw)
            except (TypeError, ValueError):
                width = 120
            if width <= 0:
                width = 120
            _client_capability_local.is_tty = is_tty
            _client_capability_local.width = width
            log.debug("client_capability: is_tty=%s width=%d", is_tty, width)
            return {"type": "ack"}

        # Stale approval_response from a timed-out request — silently drop
        if msg_type == "approval_response":
            log.debug("Dropping stale approval_response: %s", msg.get("decision"))
            return {"type": "ack"}

        return {"type": "error", "message": f"Unknown message type: {msg_type}"}

    async def _run_prompt_streaming_async(
        self,
        text: str,
        loop: Any,
        session_id: str,
        client: _AsyncClientEndpoint | None,
    ) -> dict[str, Any]:
        """Run an IPC prompt on the async daemon path.

        This is the canonical IPC role split: the daemon admits the request
        through async lanes and awaits ``AgenticLoop.arun()``; the thin client
        only renders stream/result events.
        """
        self._propagate_contextvars()
        from core.ui.agentic_ui import _ipc_writer_local, init_session_meter
        from core.ui.console import (
            make_session_console,
            reset_thread_console,
            set_thread_console,
        )

        init_session_meter()
        old_quiet = getattr(loop, "_quiet", True)
        old_op_quiet = getattr(loop, "_op_logger", None)
        loop._quiet = False
        if old_op_quiet is not None:
            loop._op_logger._quiet = False

        writer = _StreamingWriter(client) if client else None
        if writer:
            assert client is not None
            is_tty, width = client.get_capability()
            set_thread_console(make_session_console(writer, force_terminal=is_tty, width=width))
            _ipc_writer_local.writer = writer

        try:
            lane_queue = self._services.lane_queue
            if lane_queue is not None:
                async with lane_queue.acquire_all_async(f"cli:{session_id}", ["session", "global"]):
                    result = await loop.arun(text)
            else:
                result = await loop.arun(text)
            if client is not None:
                await client.drain_pending_sends()
        finally:
            if writer:
                reset_thread_console()
                _ipc_writer_local.writer = None
            loop._quiet = old_quiet
            if old_op_quiet is not None:
                loop._op_logger._quiet = old_quiet

        return self._build_prompt_result(loop, result)

    def _run_prompt_streaming(
        self,
        text: str,
        loop: Any,
        session_id: str,
        client: socket.socket | _AsyncClientEndpoint | None,
    ) -> dict[str, Any]:
        """Legacy sync IPC prompt path removed; async server uses _run_prompt_streaming_async."""
        raise RuntimeError("sync IPC prompt path removed; use _run_prompt_streaming_async")

    def _build_prompt_result(self, loop: Any, result: Any) -> dict[str, Any]:
        """Build final IPC result payload from an AgenticResult-like object."""
        # Build final result (tool_calls already rendered via streaming)
        tool_calls: list[dict[str, Any]] = []
        if result and result.tool_calls:
            for tc in result.tool_calls:
                if isinstance(tc, dict):
                    tool_calls.append(
                        {
                            "name": tc.get("name", "?"),
                            "args": tc.get("input", {}),
                        }
                    )
                elif hasattr(tc, "name"):
                    tool_calls.append(
                        {
                            "name": tc.name,
                            "args": getattr(tc, "arguments", {}),
                        }
                    )
        model = getattr(loop, "model", "unknown")
        summary = getattr(result, "summary", "") if result else ""

        return {
            "type": "result",
            "text": result.text if result else "",
            "rounds": result.rounds if result else 0,
            "tool_calls": tool_calls,
            "termination": (result.termination_reason if result else "unknown"),
            "model": model,
            "summary": summary,
        }

    def _handle_command_on_server(self, msg: dict[str, Any], loop: Any) -> dict[str, Any]:
        """Execute a slash command on the server side.

        Captures all console output (with ANSI styling) so it can be
        relayed to the thin client for display.
        """
        cmd = msg.get("cmd", "")
        args = msg.get("args", "")
        # Capture the primary model + effort BEFORE the command so the live-loop
        # sync below fires only when THIS /model actually changed the primary
        # axis. A role-specific switch (``/model reflection X`` writes
        # ``cognitive_reflection_model``), an unknown/login-blocked/list/
        # already-current ``/model``, or ``/model`` with no primary change must
        # NOT touch the live loop — otherwise it would clobber the model the
        # client_capability path adopted at session start (which moves
        # ``loop.model`` WITHOUT moving ``settings.model``). See Codex review,
        # 2026-06-11.
        model_before = ""
        effort_before = ""
        if cmd == "/model" and loop is not None:
            from core.config import settings as _pre_settings

            model_before = (getattr(_pre_settings, "model", "") or "").strip()
            effort_before = (getattr(_pre_settings, "agentic_effort", "") or "").strip()
        try:
            from core.cli import _handle_command
            from core.ui.console import capture_output

            with capture_output() as buf:
                should_break, _verbose, _resume = _handle_command(
                    cmd,
                    args,
                    False,
                    skill_registry=self._services.skill_registry,
                    mcp_manager=self._services.mcp_manager,
                )
            # /model writes config.toml + the daemon's Settings singleton but
            # cmd_model does NOT touch the live session's AgenticLoop — its
            # docstring even says "applies to *new* sessions". So a /model
            # switch inside an interactive REPL was silently ignored until the
            # session ended: the thin CLI relays /model here, the singleton
            # flips, but the loop the next prompt runs on keeps its boot-time
            # model. Operator-reported "fable 5로 바꿔도 opus-4-8로 동작"
            # (2026-06-11) — the thin-CLI ↔ daemon model gap. Sync the live
            # loop here so the switch lands in the SAME session.
            if cmd == "/model" and loop is not None:
                self._sync_live_loop_to_settings(loop, model_before, effort_before)
            return {
                "type": "command_result",
                "cmd": cmd,
                "status": "ok",
                "output": buf.getvalue(),
                "should_break": should_break,
            }
        except Exception as exc:
            log.warning("CLI command error: %s %s", cmd, exc, exc_info=True)
            return {
                "type": "command_result",
                "cmd": cmd,
                "status": "error",
                "message": str(exc),
            }

    def _sync_live_loop_to_settings(self, loop: Any, model_before: str, effort_before: str) -> None:
        """Re-point the live session loop after a ``/model`` changed the primary.

        Called right after a ``/model`` command lands on the daemon. The
        command updated ``settings.model`` (+ ``settings.agentic_effort``)
        but not the AgenticLoop the active session runs on. This mirrors the
        ``client_capability`` adoption path (which only fires once at session
        start) for the mid-session case, using the same synchronous swap
        helpers ``update_model_async`` uses internally — model + provider +
        identity breadcrumb + context-window adapt — minus the async-only
        ``MODEL_SWITCHED`` hook (telemetry, not behaviour). The effort axis is
        re-pointed directly, matching ``services.create_session``'s
        constructor bridge.

        Gated on ``settings.model != model_before`` (the value captured before
        the command ran), NOT on ``settings.model != loop.model``. Only a
        command that *actually moved the primary axis* should touch the live
        loop: a role-specific ``/model reflection X`` moves
        ``cognitive_reflection_model`` and leaves ``settings.model`` untouched,
        and an unknown/blocked/list ``/model`` moves nothing — in both cases
        ``loop.model`` may legitimately differ from ``settings.model`` because
        the ``client_capability`` path adopted the thin CLI's project model
        without moving the singleton. Gating on the singleton delta keeps those
        cases from clobbering the live loop. (Codex review, 2026-06-11.)

        Why an explicit sync rather than the old per-turn drift sync:
        ``_model_switching.sync_model_from_settings_async`` was cut to a
        no-op (PR-DRIFT-CUT, 2026-05-24) because *inferring* drift from
        ``settings.model`` between rounds caused an auto-revert smoke
        incident. The cut left ``/model`` as the operator's sole explicit
        entry point — so the switch must be pushed at the command boundary,
        not inferred. This is that push: it fires ONLY on an explicit
        ``/model`` command that moved the primary axis, so it carries the
        operator's intent without reintroducing speculative drift.
        """
        from core.agent.loop import _model_switching
        from core.config import _resolve_provider, settings

        target = (settings.model or "").strip()
        # Only sync when this command moved the primary axis AND the live loop
        # hasn't already caught up.
        if target and target != model_before and target != getattr(loop, "model", ""):
            try:
                old_model, changed = _model_switching._apply_model_update(
                    loop, target, _resolve_provider(target)
                )
                if changed:
                    _model_switching._inject_model_switch_breadcrumb(loop, old_model, target)
                    loop._adapt_context_for_model(target)
                    log.info("model command: live session loop synced to %s", target)
            except Exception:
                log.warning("model command: live loop model sync failed", exc_info=True)

        new_effort = (getattr(settings, "agentic_effort", "") or "").strip()
        if (
            new_effort
            and new_effort != effort_before
            and getattr(loop, "_effort", None) != new_effort
        ):
            loop._effort = new_effort
            log.info("model command: live session effort synced to %s", new_effort)

    def _handle_resume(
        self,
        msg: dict[str, Any],
        loop: Any,
        conversation: Any,
    ) -> dict[str, Any]:
        """Load a session checkpoint and restore conversation context."""
        try:
            from core.memory.session_checkpoint import SessionCheckpoint

            cp = SessionCheckpoint()

            state = None
            if msg.get("continue"):
                sessions = cp.list_resumable()
                if sessions:
                    state = sessions[0]
            else:
                sid = msg.get("session_id", "")
                if sid:
                    state = cp.load(sid)
            if state is None:
                return {"type": "resume_error", "message": "No resumable session found"}

            # Restore conversation messages
            conversation.messages.clear()
            conversation.messages.extend(state.messages)

            # Sync loop session_id for checkpoint continuity
            loop._session_id = state.session_id

            # Restore model if different
            if state.model and state.model != loop.model:
                from core.async_runtime import run_process_coroutine

                run_process_coroutine(loop.update_model_async(state.model))

            log.info(
                "Session resumed: %s (round=%d, messages=%d)",
                state.session_id,
                state.round_idx,
                len(state.messages),
            )
            return {
                "type": "resumed",
                "session_id": state.session_id,
                "round_idx": state.round_idx,
                "model": state.model,
                "user_input": state.user_input,
                "message_count": len(state.messages),
            }
        except Exception as exc:
            log.warning("Session resume failed", exc_info=True)
            return {"type": "resume_error", "message": str(exc)}

    def _propagate_contextvars(self) -> None:
        """Set ContextVars needed by slash command handlers in this thread.

        Python ContextVars do NOT inherit across threads. The CLI poller
        thread must explicitly set readiness, scheduler_service, memory, and
        profile so that ``_handle_command()`` works correctly.
        """
        try:
            from core.cli import _set_readiness
            from core.cli.session_state import _scheduler_service_ctx
            from core.wiring.startup import check_readiness

            _set_readiness(check_readiness())

            if self._scheduler_service is not None:
                _scheduler_service_ctx.set(self._scheduler_service)

            # Memory and profile — delegated to SharedServices helper
            if hasattr(self._services, "_propagate_contextvars"):
                self._services._propagate_contextvars()
        except Exception:
            log.debug("ContextVar propagation skipped", exc_info=True)

    @staticmethod
    def _send(client: socket.socket | _AsyncClientEndpoint, data: dict[str, Any]) -> None:
        """Send a JSON message to the client (line-delimited)."""
        if isinstance(client, _AsyncClientEndpoint):
            client.send_json_threadsafe(data)
            return
        try:
            payload = json.dumps(data, ensure_ascii=False) + "\n"
            client.sendall(payload.encode("utf-8"))
        except (BrokenPipeError, ConnectionResetError, OSError):
            log.debug("CLI send failed — client disconnected")
