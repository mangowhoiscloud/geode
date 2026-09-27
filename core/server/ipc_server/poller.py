"""CLI Poller — Unix domain socket server for thin CLI client IPC.

Accepts multiple concurrent CLI client connections. Each connected client
gets an independent IPC session backed by serve's SharedServices (same MCP,
skills, hooks, memory as Slack/Discord messaging receivers). SessionLane per-key
serialization ensures same-session ordering; different sessions run in parallel.

Protocol: line-delimited JSON over Unix domain socket.

Client → Server:
    {"type": "prompt", "text": "summarize this repository", "session_id": "..."}
    {"type": "command", "cmd": "/model", "args": "sonnet"}
    {"type": "command_stream", "cmd": "/plan", "args": "ship safely"}
    {"type": "exit"}

Server → Client:
    {"type": "stream", "data": "▸ tool_call(...)\\n"}   (during prompt execution)
    {"type": "result", "text": "...", "rounds": 3, "tool_calls": [...]}
    {"type": "command_result", "cmd": "...", "output": "..."}
    {"type": "error", "message": "..."}
    {"type": "session", "session_id": "cli-abc123", "version": "0.99.0"}
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import inspect
import logging
import os
import queue
import threading
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from core.ipc_protocol import (
    IPC_EVENT_TYPES,
    IPC_FEATURES,
    IPC_PROTOCOL_VERSION,
    MAX_IPC_MESSAGE_BYTES,
    IPCProtocolError,
    decode_message,
    encode_message,
    negotiate_protocol,
    validate_client_message,
)

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from io import StringIO

    from core.server.supervised.services import SharedServices

from core.paths import CLI_SOCKET_PATH  # noqa: E402 — placed after TYPE_CHECKING block

DEFAULT_SOCKET_PATH = CLI_SOCKET_PATH  # P2 — was `Path.home() / ".geode" / "cli.sock"`


def _session_greeting(session_id: str) -> dict[str, Any]:
    """Build the session greeting sent to a newly connected thin CLI.

    Carries the daemon's package version so a client (``geode doctor``'s
    install-drift check) can detect a stale daemon after a rebuild without a
    dedicated round-trip. Old clients ignore unknown fields. Imported lazily:
    ``core.__version__`` pulls ``importlib.metadata``, which must stay off the
    daemon's cold-start path (see ``core/__init__.py``).
    """
    from core import __version__

    return {
        "type": "session",
        "session_id": session_id,
        "version": __version__,
        "protocol_version": IPC_PROTOCOL_VERSION,
        "features": list(IPC_FEATURES),
    }


def _adopt_skip_permissions(msg: dict[str, Any]) -> None:
    """Adopt the thin CLI's ``--dangerously-skip-permissions`` for THIS connection.

    Sets the PER-SESSION ContextVar (not a process-global) in the connection's
    task / thread, before the first prompt — so the gates + plan handler read it
    at call time and a concurrent normal session is unaffected (Codex review).
    Set explicitly on every ``client_capability`` (True/False) so the value is
    always this connection's intent.
    """
    from core.agent.safety import set_skip_permissions

    skip = bool(msg.get("dangerously_skip_permissions", False))
    set_skip_permissions(skip)
    if skip:
        log.warning("client_capability: --dangerously-skip-permissions ACTIVE (all HITL bypassed)")


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
        # (decision, approval_id) pairs — the id lets request_approval discard
        # a stale reply left over from a previous (timed-out) prompt instead of
        # misrouting it into the wrong gate (PR-HITL-APPROVAL-FSM).
        self._approval_responses: queue.Queue[tuple[str, str]] = queue.Queue()
        self._is_tty = True
        self._width = 120
        self._request_id = ""
        self.session_model_config_applied = False

    async def send_json_async(self, obj: dict[str, Any]) -> None:
        if self._request_id and "request_id" not in obj:
            obj = {**obj, "request_id": self._request_id}
        payload = encode_message(obj)
        async with self._write_lock:
            self._writer.write(payload)
            await self._writer.drain()

    def set_request_id(self, request_id: object) -> None:
        """Correlate outbound events with the request currently being handled."""
        self._request_id = request_id if isinstance(request_id, str) else ""

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

    def feed_approval_response(self, decision: str, approval_id: str = "") -> None:
        self._approval_responses.put((decision, approval_id))

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
        approval_id: str = "",
        *,
        timeout_s: float = 120.0,
    ) -> str:
        import time as _time

        self.send_json_threadsafe(
            {
                "type": "approval_request",
                "tool_name": tool_name,
                "detail": detail,
                "safety_level": safety_level,
                "approval_id": approval_id,
            },
            timeout_s=10.0,
        )
        log.debug(
            "HITL: sent approval_request tool=%s level=%s id=%s",
            tool_name,
            safety_level,
            approval_id,
        )
        _t0 = _time.monotonic()
        deadline = _t0 + timeout_s
        while True:
            remaining = deadline - _time.monotonic()
            if remaining <= 0:
                break
            try:
                decision, reply_id = self._approval_responses.get(timeout=remaining)
            except queue.Empty:
                break
            # A reply for a DIFFERENT prompt (stale leftover from a timed-out
            # request) must not be misrouted into this gate — discard and keep
            # waiting for the matching id. Legacy clients that don't echo the
            # id (empty reply_id) are accepted as-is.
            if approval_id and reply_id and reply_id != approval_id:
                log.warning(
                    "HITL: discarding stale approval reply id=%s (want id=%s tool=%s)",
                    reply_id,
                    approval_id,
                    tool_name,
                )
                continue
            log.info(
                "HITL: approval_response tool=%s decision=%s id=%s elapsed=%.1fs",
                tool_name,
                decision,
                reply_id,
                _time.monotonic() - _t0,
            )
            return decision
        log.warning(
            "HITL: approval TIMEOUT tool=%s id=%s elapsed=%.1fs",
            tool_name,
            approval_id,
            _time.monotonic() - _t0,
        )
        return "n"

    def close_threadsafe(self) -> None:
        self.feed_approval_response("n")

        async def _close() -> None:
            self._writer.close()
            with contextlib.suppress(OSError):
                await self._writer.wait_closed()

        future = asyncio.run_coroutine_threadsafe(_close(), self._loop)
        with contextlib.suppress(Exception):
            future.result(timeout=2.0)


class _StreamingWriter:
    """File-like object that relays console writes to an async client endpoint.

    Each ``write()`` call sends ``{"type": "stream", "data": "..."}`` over
    the socket, so the thin client can render agentic UI (tool calls,
    results, token usage) in real-time as the AgenticLoop executes.

    Inspired by:
    - Codex CLI item-based streaming (discrete events over API)
    - OpenClaw System Events Queue (event → client relay)
    - autoresearch P6 L1 capture (capture all stdout)
    """

    def __init__(self, client: _AsyncClientEndpoint) -> None:
        self._client = client

    def write(self, text: str) -> int:
        if not text:
            return 0
        self._send_json({"type": "stream", "data": text})
        return len(text)

    def send_event(self, event_type: str, **data: Any) -> None:
        """Send a structured event (tool_start, tool_end, etc.)."""
        if event_type not in IPC_EVENT_TYPES:
            raise IPCProtocolError(f"Unknown public IPC event type: {event_type!r}")
        self._send_json({"type": event_type, **data})

    def _send_json(self, obj: dict[str, Any]) -> None:
        self._client.send_json_threadsafe(obj)

    def request_approval(
        self,
        tool_name: str,
        detail: str,
        safety_level: str = "write",
        approval_id: str = "",
    ) -> str:
        """Send approval request to thin CLI and wait for response.

        Returns 'y', 'n', or 'a' (always).
        """
        return self._client.request_approval(tool_name, detail, safety_level, approval_id)

    def flush(self) -> None:
        pass

    def isatty(self) -> bool:
        return True  # trick Rich into applying ANSI styles

    def fileno(self) -> int:
        return -1


class CLIPoller:
    """Unix domain socket server for CLI thin-client IPC.

    Unlike BasePoller subclasses (which poll external APIs), CLIPoller
    *listens* for local CLI connections through an asyncio Unix server. It does
    not inherit BasePoller because the lifecycle is event-driven, not polling.
    """

    def __init__(
        self,
        services: SharedServices,
        *,
        socket_path: Path | None = None,
        scheduler_service: Any = None,
        command_handler: Callable[..., tuple[bool, bool, Any] | Awaitable[tuple[bool, bool, Any]]]
        | None = None,
        context_initializer: Callable[[], None] | None = None,
    ) -> None:
        self._services = services
        self._socket_path = socket_path or DEFAULT_SOCKET_PATH
        self._async_server: asyncio.AbstractServer | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop_event = threading.Event()
        self._ready_event = threading.Event()
        self._thread_error: BaseException | None = None
        self._thread: threading.Thread | None = None
        self._active_clients: set[_AsyncClientEndpoint] = set()
        self._clients_lock = threading.Lock()
        self._scheduler_service = scheduler_service
        self._command_handler = command_handler
        self._context_initializer = context_initializer

    @property
    def channel_name(self) -> str:
        return "cli"

    @property
    def socket_path(self) -> Path:
        return self._socket_path

    def start(self) -> None:
        """Start listening on Unix domain socket."""
        if self._thread is not None and self._thread.is_alive():
            if self._stop_event.is_set():
                raise RuntimeError("CLI channel is still stopping; retry after its worker exits")
            return

        # Clean up stale socket file
        if self._socket_path.exists():
            self._socket_path.unlink()

        self._stop_event.clear()
        self._ready_event.clear()
        self._thread_error = None
        self._thread = threading.Thread(
            target=self._run_async_server,
            name="geode-cli-poller",
            daemon=True,
        )
        self._thread.start()
        if not self._ready_event.wait(timeout=5.0):
            raise RuntimeError(f"CLI channel failed to start on {self._socket_path}")
        if self._thread_error is not None:
            raise RuntimeError("CLI channel startup failed") from self._thread_error
        log.info("CLI channel listening on %s", self._socket_path)

    def stop_accepting(self) -> None:
        """Stop accepting new connections but let active handlers finish.

        Closes the server socket and lets active handlers finish their current
        request.
        """
        self._stop_event.set()
        self._close_async_server()
        thread = self._thread
        if thread is not None and not self._active_clients:
            thread.join(timeout=5.0)
            if not thread.is_alive():
                self._thread = None
        log.info("CLI channel stopped accepting new connections")

    def stop(self) -> None:
        """Attempt owned cleanup, retaining a live worker and the first failure."""
        self._stop_event.set()
        first_error = self._thread_error
        thread = self._thread
        cleanups: list[Callable[[], None]] = [self._close_async_server]
        with self._clients_lock:
            cleanups.extend(client.close_threadsafe for client in self._active_clients)
        if thread is not None:
            cleanups.append(lambda: thread.join(timeout=5.0))
        for cleanup in cleanups:
            try:
                cleanup()
            except BaseException as exc:
                if first_error is None:
                    first_error = exc
                else:
                    log.warning("Additional CLI shutdown failure (%s)", type(exc).__name__)

        if thread is not None and thread.is_alive():
            if first_error is None:
                first_error = TimeoutError(
                    "CLI channel is still stopping; retry stop after its worker exits"
                )
        else:
            self._thread = None
            with self._clients_lock:
                self._active_clients.clear()
            try:
                self._socket_path.unlink(missing_ok=True)
            except OSError as exc:
                if first_error is None:
                    first_error = exc
                else:
                    log.warning("Additional CLI socket cleanup failure (%s)", type(exc).__name__)
        # The worker can fail while join waits for SDK/loop teardown. Its terminal
        # error must reach the host even when admission was already stopped.
        if first_error is None:
            first_error = self._thread_error
        if first_error is not None:
            raise first_error
        log.info("CLI channel stopped")

    def _run_async_server(self) -> None:
        """Run the asyncio Unix socket server on the poller thread."""
        try:
            from core.async_runtime import owned_asyncio_runner

            with owned_asyncio_runner() as runner:
                self._loop = runner.get_loop()
                runner.run(self._serve_async())
        except BaseException as exc:
            self._thread_error = exc
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
            limit=MAX_IPC_MESSAGE_BYTES + 1,
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
        except (ConnectionResetError, BrokenPipeError) as exc:
            # PR-LOOP-POLLUTION-FIX (2026-06-12) — the thin CLI's probe
            # connection (capability handshake) disconnects abruptly; the
            # session-handshake write then fails with ConnectionResetError.
            # Expected client behaviour, not a daemon fault — pre-fix it
            # surfaced as ``asyncio ERROR Unhandled exception in
            # client_connected_cb`` noise on every CLI connect.
            log.info("CLI client dropped during handshake/read (%s) — benign", type(exc).__name__)
        finally:
            with self._clients_lock:
                self._active_clients.discard(endpoint)
                active = len(self._active_clients)
            writer.close()
            with contextlib.suppress(OSError):
                await writer.wait_closed()
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
        from core.agent.session_mode import SessionMode

        self._propagate_contextvars()

        conversation = ConversationContext()
        session_id = f"cli-{os.urandom(4).hex()}"

        def _ipc_approval(
            tool_name: str, detail: str, safety_level: str, approval_id: str = ""
        ) -> str:
            return endpoint.request_approval(tool_name, detail, safety_level, approval_id)

        _executor, agent_loop = self._services.create_session(
            SessionMode.IPC,
            conversation=conversation,
            approval_callback=_ipc_approval,
        )

        await endpoint.send_json_async(_session_greeting(session_id))

        # Dedicated reader pump — PR-HITL-APPROVAL-FSM (2026-07-02).
        #
        # ROOT CAUSE of the A-but-denied incident: the old loop awaited
        # ``_process_message_async`` INLINE, so while a prompt ran (the
        # AgenticLoop awaiting an approval), nothing called
        # ``reader.readline()`` — the thin client's approval_response could
        # never reach ``feed_approval_response``. Every in-prompt approval
        # therefore hit the 120s queue timeout and fail-closed to "n"
        # ("User denied write operation") even when the user answered ``A``,
        # and the late reply then poisoned the NEXT prompt's approval queue.
        # The pump keeps reading during prompt processing and short-circuits
        # approval replies to the endpoint the moment they arrive; everything
        # else is handled strictly in order via the message queue.
        # Bounded: a pipelining/buggy local client must not grow daemon memory
        # while a prompt stalls processing. put_nowait + drop keeps the pump
        # reading (an awaited put on a full queue would re-starve approval
        # replies — the exact defect this pump exists to fix).
        msg_queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(maxsize=256)

        def _enqueue(msg: dict[str, Any] | None) -> None:
            try:
                msg_queue.put_nowait(msg)
            except asyncio.QueueFull:
                if msg is None:
                    # Sentinel must land: drop one backlogged message for it.
                    with contextlib.suppress(asyncio.QueueEmpty):
                        msg_queue.get_nowait()
                    with contextlib.suppress(asyncio.QueueFull):
                        msg_queue.put_nowait(msg)
                else:
                    log.error(
                        "IPC message queue full (256) — dropping %r from client",
                        msg.get("type", "?"),
                    )

        async def _pump_reader() -> None:
            try:
                while True:
                    line = await reader.readline()
                    if not line:
                        return
                    try:
                        msg = decode_message(line.rstrip(b"\n"))
                    except IPCProtocolError:
                        _enqueue({"type": "_invalid_json"})
                        continue
                    if msg.get("type") == "approval_response":
                        endpoint.feed_approval_response(
                            str(msg.get("decision", "n")),
                            str(msg.get("approval_id", "")),
                        )
                        continue
                    _enqueue(msg)
            except (ConnectionResetError, BrokenPipeError, OSError):
                return
            except Exception:
                # Any unexpected pump death must still wake the consumer —
                # a silent exit would block msg_queue.get() forever.
                log.warning("IPC reader pump died unexpectedly", exc_info=True)
            finally:
                endpoint.feed_approval_response("n")
                _enqueue(None)

        pump_task = asyncio.get_running_loop().create_task(_pump_reader())
        try:
            while not self._stop_event.is_set():
                msg = await msg_queue.get()
                if msg is None:
                    log.info("CLI client disconnected")
                    break
                try:
                    if msg.get("type") == "_invalid_json":
                        await endpoint.send_json_async({"type": "error", "message": "Invalid JSON"})
                        continue
                    endpoint.set_request_id(msg.get("request_id"))
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
                except Exception:
                    log.warning("CLI handler error", exc_info=True)
                    await endpoint.send_json_async({"type": "error", "message": "Internal error"})
                finally:
                    endpoint.set_request_id("")
        finally:
            pump_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await pump_task

    async def _process_message_async(
        self,
        msg: dict[str, Any],
        loop: Any,
        conversation: Any,
        session_id: str,
    ) -> dict[str, Any] | None:
        msg_type = msg.get("type", "")
        try:
            validate_client_message(msg)
        except IPCProtocolError as exc:
            return {"type": "protocol_error", "message": str(exc)}

        endpoint = msg.get("_client")
        if (
            isinstance(endpoint, _AsyncClientEndpoint)
            and not endpoint.session_model_config_applied
            and msg_type in {"prompt", "command", "command_stream", "resume"}
        ):
            return {"type": "error", "message": "Initial session settings have not been admitted"}

        if msg_type == "prompt":
            text = msg.get("text", "").strip()
            if not text:
                return {"type": "error", "message": "Empty prompt"}
            try:
                return await self._run_prompt_streaming_async(
                    text,
                    loop,
                    msg.get("_client"),
                )
            except Exception as exc:
                log.warning("CLI prompt execution error", exc_info=True)
                return {"type": "error", "message": str(exc)}

        if msg_type == "command":
            if str(msg.get("cmd") or "").casefold() in {"/goal", "/compact", "/model"}:
                lane_queue = self._services.lane_queue
                if lane_queue is not None:
                    async with lane_queue.acquire_all_async(
                        loop._session_id,
                        ["session", "global"],
                    ):
                        return await self._handle_command_on_server(msg, loop)
            return await self._handle_command_on_server(msg, loop)

        if msg_type == "command_stream":
            try:
                return await self._run_command_streaming_async(msg, loop, msg.get("_client"))
            except Exception as exc:
                log.warning("CLI streaming command error", exc_info=True)
                return {"type": "error", "message": str(exc)}

        if msg_type == "resume":
            return await self._handle_resume_async(msg, loop, conversation)

        if msg_type == "client_capability":
            try:
                protocol_version, features = negotiate_protocol(
                    msg.get("protocol_version"), msg.get("features")
                )
            except IPCProtocolError as exc:
                return {"type": "protocol_error", "message": str(exc)}
            endpoint = msg.get("_client")
            is_tty = bool(msg.get("is_tty", True))
            width_raw = msg.get("width", 120)
            try:
                width = int(width_raw)
            except (TypeError, ValueError):
                width = 120
            if isinstance(endpoint, _AsyncClientEndpoint):
                endpoint.set_capability(is_tty=is_tty, width=width)
            if "session_model_config" not in features:
                return {
                    "type": "error",
                    "message": "Upgrade and reconnect: client session settings unsupported",
                }
            try:
                if (
                    isinstance(endpoint, _AsyncClientEndpoint)
                    and not endpoint.session_model_config_applied
                    and "model_config" not in msg
                ):
                    raise IPCProtocolError("Initial client capability requires model_config")
                if (
                    isinstance(endpoint, _AsyncClientEndpoint)
                    and endpoint.session_model_config_applied
                    and "model_config" in msg
                ):
                    raise IPCProtocolError("Use /model for changes after initial admission")
                workspace = self._session_workspace(loop, str(msg.get("cwd", "")))
                applied = (
                    await self._apply_session_selection(msg, loop, initial=True)
                    if "model_config" in msg
                    else {"model_config": loop._model_settings.model_dump()}
                )
            except Exception as exc:
                return {"type": "error", "message": str(exc)}
            if isinstance(endpoint, _AsyncClientEndpoint):
                endpoint.session_model_config_applied = True
            _adopt_skip_permissions(msg)
            log.debug("client_capability: is_tty=%s width=%d", is_tty, width if width > 0 else 120)
            return {
                "type": "ack",
                "status": "applied",
                "model_config": applied["model_config"],
                **workspace,
                "protocol_version": protocol_version,
                "features": list(features),
            }

        if msg_type == "exit":
            # Clean client exit — the REPL surface's ACTIVE -> COMPLETED
            # edge (docs/architecture/session-state-machine.md § owners).
            try:
                await loop.amark_session_completed()
            except Exception:
                log.debug("amark_session_completed on exit failed", exc_info=True)
            return None

        if msg_type == "approval_response":
            log.debug("Dropping stale approval_response: %s", msg.get("decision"))
            return {"type": "ack"}

        return {"type": "error", "message": f"Unknown message type: {msg_type}"}

    async def _run_command_streaming_async(
        self,
        msg: dict[str, Any],
        loop: Any,
        client: _AsyncClientEndpoint | None,
    ) -> dict[str, Any]:
        """Resolve a trusted DAEMON_STREAM command and run its canonical path."""
        from core.slash_routing import RunLocation, lookup

        cmd = str(msg.get("cmd", "")).strip().lower()
        args = str(msg.get("args", "")).strip()
        spec = lookup(cmd, self._services.command_registry)
        if spec is None:
            raise ValueError(f"Unknown slash command: {cmd or '(empty)'}")
        if spec.location is not RunLocation.DAEMON_STREAM:
            raise ValueError(f"Slash command is not streaming: {cmd}")

        if spec.name == "/plan":
            from core.server.ipc_server.plan_command import run_plan_slash

            lane_queue = self._services.lane_queue
            if lane_queue is not None:
                async with lane_queue.acquire_all_async(loop._session_id, ["session", "global"]):
                    text, plan, created = await run_plan_slash(loop, args)
            else:
                text, plan, created = await run_plan_slash(loop, args)
            if client is not None and plan is not None:
                await client.send_json_async(
                    {
                        "type": "progress_plan",
                        "plan": [
                            {
                                "step": step.description,
                                "status": "in_progress" if index == plan.current else "pending",
                            }
                            for index, step in enumerate(plan.steps)
                        ],
                        "explanation": plan.reasoning,
                    }
                )
            return {
                "type": "result",
                "text": text,
                "rounds": 0,
                "tool_calls": [],
                "termination": "slash_plan",
                "model": getattr(loop, "model", "unknown"),
                "summary": "advisory plan created" if created else "advisory plan status",
            }

        if not spec.handler_path:
            raise ValueError(f"Streaming slash command has no handler: {spec.name}")
        module_name, separator, attr_name = spec.handler_path.partition(":")
        if not separator or not module_name or not attr_name:
            raise ValueError(f"Invalid slash handler path: {spec.handler_path!r}")
        prompt_builder = getattr(importlib.import_module(module_name), attr_name)
        return await self._run_prompt_streaming_async(
            lambda: prompt_builder(
                args,
                skill_registry=self._services.skill_registry,
                agentic_ref=loop,
            ),
            loop,
            client,
            suppress_public_verify=spec.name in {"/grill", "/geo"},
            control_name=spec.name.removeprefix("/"),
        )

    @staticmethod
    def _has_active_control_workflow(loop: Any) -> bool:
        controls = getattr(loop, "_control_state_renderers", {})
        if not isinstance(controls, dict):
            return False
        for name in ("grill", "geo"):
            store = controls.get(name)
            if store is None:
                continue
            state = store.get(loop._session_id)
            if state is None:
                continue
            status = getattr(state, "status", None) or getattr(state, "phase", None)
            if str(status) != "complete":
                return True
        return False

    async def _run_prompt_streaming_async(
        self,
        text: str | Callable[[], str],
        loop: Any,
        client: _AsyncClientEndpoint | None,
        *,
        suppress_public_verify: bool = False,
        control_name: str = "",
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
        writer = _StreamingWriter(client) if client else None
        if writer:
            assert client is not None
            is_tty, width = client.get_capability()
            set_thread_console(make_session_console(writer, force_terminal=is_tty, width=width))
            _ipc_writer_local.writer = writer

        async def _run_admitted() -> dict[str, Any]:
            old_quiet = getattr(loop, "_quiet", True)
            old_op_quiet = getattr(loop, "_op_logger", None)
            old_suppress_verify = getattr(loop, "_suppress_public_verify", False)
            effective_suppression = suppress_public_verify or self._has_active_control_workflow(
                loop
            )
            loop._quiet = False
            loop._suppress_public_verify = effective_suppression
            if old_op_quiet is not None:
                loop._op_logger._quiet = False
            if effective_suppression:
                loop._session_metrics.clear_verify_retry_signal()
            try:
                prompt = text() if callable(text) else text
                result = await loop.arun(prompt)
                response = self._build_prompt_result(loop, result)
                if control_name:
                    controls = getattr(loop, "_control_state_renderers", {})
                    store = controls.get(control_name) if isinstance(controls, dict) else None
                    if store is not None:
                        state = store.get(loop._session_id)
                        response["control_state"] = state.to_dict() if state is not None else None
                return response
            finally:
                loop._quiet = old_quiet
                loop._suppress_public_verify = old_suppress_verify
                if old_op_quiet is not None:
                    loop._op_logger._quiet = old_quiet

        try:
            lane_queue = self._services.lane_queue
            if lane_queue is not None:
                async with lane_queue.acquire_all_async(
                    loop._session_id,
                    ["session", "global"],
                ):
                    response = await _run_admitted()
            else:
                response = await _run_admitted()
            if client is not None:
                await client.drain_pending_sends()
        finally:
            if writer:
                reset_thread_console()
                _ipc_writer_local.writer = None
        return response

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

    @staticmethod
    def _session_workspace(loop: Any, requested: str) -> dict[str, str]:
        """Admit only the existing workspace; never change daemon cwd."""
        from core.paths import get_project_root

        bash = getattr(getattr(loop, "executor", None), "_bash", None)
        working_dir = getattr(bash, "_working_dir", None)
        root = (
            Path(working_dir).resolve()
            if isinstance(working_dir, str)
            else get_project_root().resolve()
        )
        caller = Path(requested).resolve() if requested else root
        if not caller.is_relative_to(root):
            raise ValueError(
                "This daemon serves a different workspace; start serve in the requested project"
            )
        for directory in (caller, *caller.parents):
            if directory == root:
                break
            if (directory / ".git").exists() or (directory / ".geode" / "config.toml").exists():
                raise ValueError("A nested project needs its own serve workspace")
        checkpoint = getattr(loop, "_checkpoint", None)
        return {
            "workspace": str(root),
            "checkpoint_directory": str(checkpoint.session_dir) if checkpoint is not None else "",
        }

    async def _apply_session_selection(
        self, msg: dict[str, Any], loop: Any, *, initial: bool = False
    ) -> dict[str, Any]:
        from core.agent.loop._model_switching import apply_session_model_config
        from core.config.session import SessionModelConfig

        raw = msg.get("model_config")
        if not isinstance(raw, dict):
            raise IPCProtocolError("Session model_config must be an object")
        current = loop._model_settings.updated(
            {"model": loop.model, "effort": loop._effort, "source": loop._source}
        )
        from pydantic import ValidationError

        try:
            candidate = SessionModelConfig.model_validate(raw) if initial else current.updated(raw)
        except ValidationError as exc:
            fields = sorted({str(error["loc"][0]) for error in exc.errors() if error["loc"]})
            raise IPCProtocolError(f"Invalid session model settings: {', '.join(fields)}") from None
        changed = await apply_session_model_config(
            loop, candidate, reason="cli_session" if initial else "user_switch"
        )
        return {
            "type": "command_result",
            "cmd": "/model",
            "status": "applied",
            "changed": changed,
            "model_config": candidate.model_dump(),
        }

    async def _handle_command_on_server(self, msg: dict[str, Any], loop: Any) -> dict[str, Any]:
        """Execute a slash command on the server side.

        Captures all console output (with ANSI styling) so it can be
        relayed to the thin client for display.
        """
        cmd = msg.get("cmd", "")
        args = msg.get("args", "")
        from core.slash_routing import RunLocation, lookup

        spec = lookup(str(cmd).lower(), self._services.command_registry)
        if spec is not None and spec.location is RunLocation.DAEMON_STREAM:
            return {
                "type": "command_result",
                "cmd": cmd,
                "status": "error",
                "message": f"Slash command requires streaming transport: {cmd}",
            }
        if cmd == "/model":
            if "model_config" not in msg:
                return {
                    "type": "command_result",
                    "status": "error",
                    "message": "Explicit session settings required; upgrade and reconnect",
                }
            try:
                return await self._apply_session_selection(msg, loop)
            except Exception as exc:
                return {"type": "command_result", "status": "error", "message": str(exc)}
        buf: StringIO | None = None
        try:
            from core.ui.console import capture_output

            if self._command_handler is None:
                return {
                    "type": "command_result",
                    "cmd": cmd,
                    "status": "error",
                    "message": "daemon command handler is not configured",
                }
            with capture_output() as buf:
                from functools import partial

                dispatch = partial(
                    self._command_handler,
                    cmd,
                    args,
                    False,
                    skill_registry=self._services.skill_registry,
                    mcp_manager=self._services.mcp_manager,
                    command_registry=self._services.command_registry,
                    scheduler_service=self._scheduler_service,
                    agentic_ref=loop,
                )
                if inspect.iscoroutinefunction(self._command_handler):
                    result = dispatch()
                else:
                    sync_dispatch = cast(Callable[[], tuple[bool, bool, Any]], dispatch)
                    result = await asyncio.to_thread(sync_dispatch)
                if inspect.isawaitable(result):
                    result = await result
                should_break, _verbose, _resume = result
            return {
                "type": "command_result",
                "cmd": cmd,
                "status": "ok",
                "output": buf.getvalue(),
                "should_break": should_break,
            }
        except Exception as exc:
            if isinstance(exc, ValueError | OSError):
                # Rejected input may echo user text (even a pasted key); log only the class.
                log.info("CLI command rejected: %s (%s)", cmd, type(exc).__name__)
            else:
                log.warning("CLI command error: %s %s", cmd, exc, exc_info=True)
            return {
                "type": "command_result",
                "cmd": cmd,
                "status": "error",
                "message": str(exc),
                "output": buf.getvalue() if buf is not None else "",
            }

    async def _handle_resume(
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
                sessions = await asyncio.to_thread(cp.list_resumable)
                if sessions:
                    state = sessions[0]
            else:
                sid = msg.get("session_id", "")
                if sid:
                    state = await asyncio.to_thread(cp.load, sid)
            if state is None:
                return {"type": "resume_error", "message": "No resumable session found"}

            # ``--continue`` chooses the newest candidate before waiting for
            # its Lane.  Reloading happens under that Lane, so refuse a
            # candidate that became terminal while admission was queued.
            if msg.get("_require_resumable") and state.status not in ("active", "paused"):
                return {"type": "resume_error", "message": "No resumable session found"}

            from core.agent.loop._model_switching import apply_session_model_config

            candidate = state.model_settings or loop._model_settings.updated(
                {"model": loop.model, "source": loop._source, "effort": loop._effort}
            )
            await apply_session_model_config(loop, candidate, reason="resume")

            # Resume-by-id of a terminal (completed/error) instance takes
            # the explicit reopen edge of the session automaton — the
            # per-turn save() would otherwise warn about an implicit reopen.
            await asyncio.to_thread(cp.reopen, state.session_id)

            # Restore conversation messages
            conversation.messages.clear()
            conversation.messages.extend(state.messages)

            # Machine identity — session id + cognitive state + guard
            # counters through the single shared resume surgery.
            from core.agent.cognitive_state_ctx import set_cognitive_state, set_session_id

            loop.restore_from_checkpoint(state)
            set_cognitive_state(loop.cognitive_state)
            set_session_id(state.session_id)

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
                "model": loop.model,
                "model_config": loop._model_settings.model_dump(),
                "model_config_origin": "checkpoint" if state.model_settings else "current",
                "user_input": state.user_input,
                "message_count": len(state.messages),
                "cognitive_state": loop.cognitive_state.to_snapshot(),
            }
        except Exception as exc:
            log.warning("Session resume failed", exc_info=True)
            return {"type": "resume_error", "message": str(exc)}

    async def _handle_resume_async(
        self,
        msg: dict[str, Any],
        loop: Any,
        conversation: Any,
    ) -> dict[str, Any]:
        """Resolve the target, then reload and restore it under its machine Lane."""
        resolved = dict(msg)
        if msg.get("continue"):
            from core.memory.session_checkpoint import SessionCheckpoint

            sessions = await asyncio.to_thread(SessionCheckpoint().list_resumable)
            if not sessions:
                return {"type": "resume_error", "message": "No resumable session found"}
            resolved.pop("continue", None)
            resolved["session_id"] = sessions[0].session_id
            resolved["_require_resumable"] = True

        session_id = str(resolved.get("session_id") or "")
        lane_queue = self._services.lane_queue
        if not session_id or lane_queue is None:
            return await self._handle_resume(resolved, loop, conversation)
        async with lane_queue.acquire_all_async(session_id, ["session", "global"]):
            return await self._handle_resume(resolved, loop, conversation)

    def _propagate_contextvars(self) -> None:
        """Set request-local CLI readiness in this thread."""
        if self._context_initializer is None:
            return
        try:
            self._context_initializer()
        except Exception:
            log.debug("ContextVar propagation skipped", exc_info=True)
