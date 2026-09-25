"""SDK resources close at their owning loop edge, never at a session edge."""

from __future__ import annotations

import asyncio
import gc
import json
import subprocess
import sys
import textwrap
import threading
import weakref
from collections.abc import Callable
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock, call

import httpx
import pytest
from core.async_runtime import _drain_owned_loop, run_process_coroutine
from core.llm.adapters import registry
from core.llm.loop_affinity import LoopAffineClientCache, drain_current_loop_clients


class Client:
    def __init__(self, *, fail: bool = False) -> None:
        self.loop = asyncio.get_running_loop()
        self.close_count = 0
        self.fail = fail

    async def close(self) -> None:
        assert asyncio.get_running_loop() is self.loop
        assert not self.loop.is_closed()
        self.close_count += 1
        if self.fail:
            raise OSError("fixture cleanup failure")


def test_credential_identity_retires_clients_only_after_successful_construction() -> None:
    cache = LoopAffineClientCache("identity")
    clients: list[Client] = []

    def failed_builder() -> Client:
        raise ValueError("invalid replacement")

    async def work() -> None:
        first = cache.get(Client, identity="first")
        clients.append(first)
        assert cache.get(failed_builder, identity="first") is first
        with pytest.raises(ValueError, match="invalid replacement"):
            cache.get(failed_builder, identity="second")
        assert cache.get(failed_builder, identity="first") is first
        second = cache.get(Client, identity="second")
        clients.append(second)
        assert second is not first
        assert first.close_count == second.close_count == 0

    run_process_coroutine(work())
    assert [client.close_count for client in clients] == [1, 1]


@pytest.mark.usefixtures("managed_geode_runtimes")
def test_runtime_recreation_keeps_shared_and_borrowed_clients_until_loop_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.config import settings
    from core.runtime import GeodeRuntime

    monkeypatch.setattr(settings, "openai_api_key", "fixture-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://sdk-lifecycle.invalid/v1")
    build_client = Mock(side_effect=lambda api_key, *, base_url: Client())
    monkeypatch.setattr("core.llm.adapters.openai_payg.build_async_openai_client", build_client)

    async def work() -> tuple[Client, Client]:
        first_runtime = GeodeRuntime.create("first", log_dir=tmp_path / "first")
        second_runtime = GeodeRuntime.create("second", log_dir=tmp_path / "second")
        adapter = registry.get_adapter("openai-payg")
        first = adapter._get_client()
        borrowed = Client()  # Never passed to a cache: its caller retains ownership.
        first_runtime.shutdown()
        assert adapter._get_client() is first
        assert first.close_count == borrowed.close_count == 0
        second_runtime.shutdown()
        replacement = GeodeRuntime.create("replacement", log_dir=tmp_path / "replacement")
        assert registry.get_adapter("openai-payg")._get_client() is first
        replacement.shutdown()
        return first, borrowed

    owned, borrowed = run_process_coroutine(work())
    assert owned.close_count == 1
    assert borrowed.close_count == 0
    assert owned.loop.is_closed()
    build_client.assert_called_once_with("fixture-key", base_url="https://sdk-lifecycle.invalid/v1")


def test_rotation_and_registry_replacement_keep_inflight_clients_until_drain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.config import settings
    from core.extensions import ExtensionPolicy

    monkeypatch.setattr(settings, "openai_api_key", "fixture-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://sdk-lifecycle.invalid/v1")
    build_client = Mock(side_effect=lambda api_key, *, base_url: Client())
    monkeypatch.setattr("core.llm.adapters.openai_payg.build_async_openai_client", build_client)
    clients: list[Client] = []

    async def work() -> None:
        adapter = registry.get_adapter("openai-payg")
        before = adapter._get_client()
        clients.append(before)
        entered, release = asyncio.Event(), asyncio.Event()

        async def request() -> None:
            entered.set()
            await release.wait()
            assert before.close_count == 0

        pending = asyncio.create_task(request())
        await entered.wait()
        registry.invalidate_provider_clients("openai")
        after = adapter._get_client()
        clients.append(after)
        assert after is not before
        registry.reload_adapters(extension_policy=ExtensionPolicy.empty())
        clients.append(registry.get_adapter("openai-payg")._get_client())
        assert len({id(client) for client in clients}) == 3
        release.set()
        await pending
        assert all(client.close_count == 0 for client in clients)

    run_process_coroutine(work())
    assert [client.close_count for client in clients] == [1, 1, 1]
    assert (
        build_client.call_args_list
        == [call("fixture-key", base_url="https://sdk-lifecycle.invalid/v1")] * 3
    )


def test_pending_work_and_async_generators_finish_before_client_close() -> None:
    cache = LoopAffineClientCache("drain-order")
    settled: list[str] = []
    generators: list[Any] = []
    tasks: list[asyncio.Task[None]] = []

    async def work() -> Client:
        client = cache.get(Client)
        entered = asyncio.Event()

        async def pending() -> None:
            try:
                entered.set()
                await asyncio.Event().wait()
            finally:
                await asyncio.sleep(0)
                assert client.close_count == 0
                settled.append("request")

        async def stream() -> Any:
            try:
                yield "delta"
            finally:
                assert client.close_count == 0
                settled.append("stream")

        tasks.append(asyncio.create_task(pending()))
        await entered.wait()
        generator = stream()
        generators.append(generator)
        assert await anext(generator) == "delta"
        return client

    client = run_process_coroutine(work())
    assert settled == ["request", "stream"]
    assert client.close_count == 1
    assert cache.bound_loop_count() == 0


@pytest.mark.parametrize("primary", [None, ValueError("work failed"), asyncio.CancelledError()])
def test_all_clients_attempted_and_original_failure_preserved(
    primary: BaseException | None, caplog: pytest.LogCaptureFixture
) -> None:
    cache = LoopAffineClientCache("failure")
    clients: list[Client] = []

    async def work() -> None:
        for index in range(7):
            clients.append(cache.get(lambda fail=index != 6: Client(fail=fail)))
            cache.invalidate()
        if primary is not None:
            raise primary

    with pytest.raises(BaseException) as caught:
        run_process_coroutine(work())
    assert [client.close_count for client in clients] == [1] * 7
    assert cache.bound_loop_count() == 0
    if primary is not None:
        assert caught.value is primary
        assert "Loop cleanup also failed after work failed" in caplog.text
    else:
        assert isinstance(caught.value, ExceptionGroup)
        assert "6 client(s)" in str(caught.value)
        assert len(caught.value.exceptions) == 5


def test_failed_client_drain_can_retry_on_the_same_live_loop() -> None:
    cache = LoopAffineClientCache("retry-cleanup")

    async def work() -> None:
        failed = cache.get(lambda: Client(fail=True))
        cache.invalidate()
        sibling = cache.get(Client)
        with pytest.raises(ExceptionGroup, match="1 client"):
            await drain_current_loop_clients()
        assert [failed.close_count, sibling.close_count] == [1, 1]
        assert cache.bound_loop_count() == 0
        replacement = cache.get(Client)
        assert replacement is not failed and replacement is not sibling
        failed.fail = False
        await drain_current_loop_clients()
        assert [failed.close_count, sibling.close_count, replacement.close_count] == [2, 1, 1]
        await drain_current_loop_clients()
        assert [failed.close_count, sibling.close_count, replacement.close_count] == [2, 1, 1]

    asyncio.run(work())


@pytest.mark.parametrize("primary", [None, ValueError("work failed"), asyncio.CancelledError()])
def test_runner_close_failure_preserves_the_original_error(
    primary: BaseException | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    close = asyncio.Runner.close
    close_error = RuntimeError("runner close failed")

    def fail_after_close(runner: asyncio.Runner) -> None:
        close(runner)
        raise close_error

    monkeypatch.setattr(asyncio.Runner, "close", fail_after_close)

    async def work() -> None:
        if primary is not None:
            raise primary

    with pytest.raises(BaseException) as caught:
        run_process_coroutine(work())
    assert caught.value is (primary if primary is not None else close_error)


def test_background_shutdown_failure_is_reported_before_sdk_drain(
    caplog: pytest.LogCaptureFixture,
) -> None:
    cache = LoopAffineClientCache("background-failure")
    tasks: list[asyncio.Task[None]] = []

    async def work() -> Client:
        entered = asyncio.Event()

        async def pending() -> None:
            try:
                entered.set()
                await asyncio.Event().wait()
            finally:
                raise ValueError("private fixture detail")

        tasks.append(asyncio.create_task(pending()))
        await entered.wait()
        return cache.get(Client)

    client = run_process_coroutine(work())
    assert client.close_count == 1
    assert "1 background task(s) failed during loop shutdown (ValueError)" in caplog.text
    assert "private fixture detail" not in caplog.text


@pytest.mark.parametrize(
    ("interruption", "work_fails"),
    [("KeyboardInterrupt", False), ("SystemExit", False), ("SystemExit", True)],
)
def test_background_shutdown_interruption_still_drains_owned_resources(
    tmp_path: Path, interruption: str, work_fails: bool
) -> None:
    # asyncio propagates these exceptions out of task dispatch itself. Keep the
    # real Runner boundary in a subprocess without importing operator settings.
    script = textwrap.dedent("""
        import asyncio, builtins, importlib.util, json, sys, types
        from pathlib import Path

        def deny_network(event, args):
            if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto"}:
                raise AssertionError("No network in shutdown regression")

        sys.addaudithook(deny_network)
        root = Path(sys.argv[1])
        for name in ("core", "core.llm"):
            package = types.ModuleType(name)
            package.__path__ = []
            sys.modules[name] = package
        for name in ("core.llm.loop_affinity", "core.async_runtime"):
            spec = importlib.util.spec_from_file_location(name, root / (name.replace(".", "/") + ".py"))
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
        from core.async_runtime import run_process_coroutine
        from core.llm.loop_affinity import LoopAffineClientCache

        sequence, clients, tasks, generators = [], [], [], []
        cache = LoopAffineClientCache("shutdown-interruption")
        failure = getattr(builtins, sys.argv[2])("fixture interruption")
        primary = ValueError("fixture work failure") if sys.argv[3] == "True" else None

        class Client:
            def __init__(self, index):
                self.index = index
                self.loop = asyncio.get_running_loop()
            async def close(self):
                assert asyncio.get_running_loop() is self.loop and not self.loop.is_closed()
                sequence.append(f"client-{self.index}")

        async def work():
            for index in range(2):
                clients.append(cache.get(lambda index=index: Client(index)))
                cache.invalidate()
            async def stream():
                try:
                    yield "delta"
                finally:
                    sequence.append("asyncgen")
            generator = stream()
            generators.append(generator)
            await anext(generator)
            entered = asyncio.Event()
            async def pending():
                try:
                    entered.set()
                    await asyncio.Event().wait()
                finally:
                    sequence.append("pending")
                    raise failure
            tasks.append(asyncio.create_task(pending()))
            await entered.wait()
            if primary is not None:
                raise primary

        try:
            run_process_coroutine(work())
        except BaseException as caught:
            assert caught is (primary if primary is not None else failure)
        else:
            raise AssertionError("Original interruption was swallowed")
        assert all(client.loop.is_closed() for client in clients)
        sequence.append("loop-closed")
        print(json.dumps(sequence))
        """)
    completed = subprocess.run(  # noqa: S603 - isolated interpreter, tracked sources, synthetic clients
        [
            sys.executable,
            "-I",
            "-B",
            "-c",
            script,
            str(Path(__file__).resolve().parents[2]),
            interruption,
            str(work_fails),
        ],
        cwd=tmp_path,
        env={},
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == [
        "pending",
        "asyncgen",
        "client-0",
        "client-1",
        "loop-closed",
    ]


@pytest.mark.parametrize("drain", [_drain_owned_loop, drain_current_loop_clients])
def test_repeated_cancellation_does_not_abandon_cleanup(drain: Callable[..., Any]) -> None:
    cache = LoopAffineClientCache("cancel")
    clients: list[Client] = []

    async def scenario() -> None:
        owner = asyncio.current_task()
        assert owner is not None

        class CancellingClient(Client):
            async def close(self) -> None:
                owner.cancel("first")
                await asyncio.sleep(0)
                owner.cancel("second")
                await asyncio.sleep(0)
                await super().close()

        clients.append(cache.get(CancellingClient))
        cache.invalidate()
        clients.append(cache.get(Client))
        with pytest.raises(asyncio.CancelledError, match="first"):
            await drain()
        assert [client.close_count for client in clients] == [1, 1]

    asyncio.run(scenario())


def test_one_loop_drain_does_not_close_another_loop_client() -> None:
    cache = LoopAffineClientCache("two-loops")
    ready, release = threading.Event(), threading.Event()
    foreign: list[Client] = []

    async def background() -> None:
        foreign.append(cache.get(Client))
        ready.set()
        await asyncio.to_thread(release.wait)
        assert foreign[0].close_count == 0

    thread = threading.Thread(target=lambda: run_process_coroutine(background()))
    thread.start()
    try:
        assert ready.wait(3)

        async def foreground() -> Client:
            return cache.get(Client)

        own = run_process_coroutine(foreground())
        assert own.close_count == 1
        assert foreign[0].close_count == 0
    finally:
        release.set()
        thread.join(timeout=3)
    assert not thread.is_alive()
    assert foreign[0].close_count == 1


def test_cached_get_releases_closed_external_loop_ownership() -> None:
    cache = LoopAffineClientCache("external-loop-fallback")
    foreign: list[weakref.ReferenceType[Client]] = []

    async def external() -> None:
        foreign.append(weakref.ref(cache.get(Client)))

    async def work() -> None:
        own = cache.get(Client)
        thread = threading.Thread(target=lambda: asyncio.run(external()))
        thread.start()
        thread.join(timeout=3)
        assert not thread.is_alive()
        assert foreign[0]() is not None
        assert cache.get(Client) is own
        gc.collect()
        assert foreign[0]() is None

    run_process_coroutine(work())


def test_cli_poller_normal_stop_drains_before_loop_closes() -> None:
    from core.server.ipc_server.poller import CLIPoller

    cache = LoopAffineClientCache("cli-stop")
    clients: list[Client] = []
    seeded = threading.Event()
    directory = TemporaryDirectory(prefix="geode-sdk-", dir="/tmp")
    poller = CLIPoller(SimpleNamespace(), socket_path=Path(directory.name) / "cli.sock")
    start = poller._start_async_server

    async def start_and_seed() -> None:
        await start()
        clients.append(cache.get(Client))
        seeded.set()

    poller._start_async_server = start_and_seed
    try:
        poller.start()
        assert seeded.wait(3)
    finally:
        poller.stop()
        directory.cleanup()
    assert clients[0].close_count == 1
    assert clients[0].loop.is_closed()
    assert cache.bound_loop_count() == 0


def test_gateway_poller_normal_stop_drains_its_loop() -> None:
    from core.messaging.poller import BasePoller

    cache = LoopAffineClientCache("gateway-stop")
    clients: list[Client] = []

    class Poller(BasePoller):
        channel_name = "fixture"

        def is_configured(self) -> bool:
            return True

        async def _apoll_once(self) -> None:
            clients.append(cache.get(Client))
            self._stop_event.set()

    poller = Poller(SimpleNamespace(), poll_interval_s=0.001)
    poller.start()
    assert poller._thread is not None
    poller._thread.join(timeout=3)
    poller.stop()
    assert clients[0].close_count == 1
    assert clients[0].loop.is_closed()


@pytest.mark.parametrize("provider", ["openai", "anthropic"])
def test_actual_sdk_close_releases_owned_http_transport(provider: str) -> None:
    from anthropic import AsyncAnthropic
    from openai import AsyncOpenAI

    closed: list[bool] = []

    class Transport(httpx.AsyncBaseTransport):
        async def aclose(self) -> None:
            closed.append(True)

    cache = LoopAffineClientCache(provider)
    factory: Callable[..., Any] = AsyncOpenAI if provider == "openai" else AsyncAnthropic

    async def work() -> Any:
        return cache.get(
            lambda: factory(
                api_key="fixture-key", http_client=httpx.AsyncClient(transport=Transport())
            )
        )

    client = run_process_coroutine(work())
    assert client.is_closed()
    assert closed == [True]
