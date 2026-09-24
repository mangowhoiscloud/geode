"""SDK resources close at their owning loop edge, never at a session edge."""

from __future__ import annotations

import asyncio
import gc
import threading
import weakref
from collections.abc import Callable
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import Any

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


@pytest.mark.usefixtures("managed_geode_runtimes")
def test_runtime_recreation_keeps_shared_and_borrowed_clients_until_loop_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.config import settings
    from core.runtime import GeodeRuntime

    monkeypatch.setattr(settings, "openai_api_key", "fixture-key")
    monkeypatch.setattr(
        "core.llm.adapters.openai_payg.build_async_openai_client", lambda _: Client()
    )

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


def test_rotation_and_registry_replacement_keep_inflight_clients_until_drain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.config import settings
    from core.extensions import ExtensionPolicy

    monkeypatch.setattr(settings, "openai_api_key", "fixture-key")
    monkeypatch.setattr(
        "core.llm.adapters.openai_payg.build_async_openai_client", lambda _: Client()
    )
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
