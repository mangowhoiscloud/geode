"""OL-A1 — mutator auto-trigger invariants.

Pins:
- Lock acquire / release semantics + contention.
- Min-interval gate behaviour (no prior run / recent run / old run).
- Timestamp round-trip (read after write).
- ``auto_trigger_mutator`` end-to-end:
    * disabled → no disk I/O
    * interval_blocked → no lock acquired, no runner call
    * lock_busy → runner NOT invoked
    * runner_error → caught, timestamp NOT updated
    * parse_error → caught, timestamp NOT updated, state distinct
    * fired → timestamp updated, lock released
- SchedulerConfig defaults (off / 6-hour cron / 60-min interval).
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture
def trigger_paths(tmp_path: Path) -> Iterator[tuple[Path, Path]]:
    lock = tmp_path / "auto_trigger.lock"
    ts = tmp_path / "auto_trigger_last_run.txt"
    yield lock, ts


# ---------------------------------------------------------------------------
# SchedulerConfig defaults
# ---------------------------------------------------------------------------


def test_scheduler_config_defaults_match_spec() -> None:
    from core.config.self_improving_loop import SchedulerConfig

    cfg = SchedulerConfig()
    assert cfg.enabled is False
    assert cfg.cron == "0 */6 * * *"
    assert cfg.min_interval_minutes == 60


def test_scheduler_config_validates_min_interval_range() -> None:
    """``min_interval_minutes`` is Annotated[int, ge=1, le=1440]."""
    from core.config.self_improving_loop import SchedulerConfig
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        SchedulerConfig(min_interval_minutes=0)
    with pytest.raises(ValidationError):
        SchedulerConfig(min_interval_minutes=1441)
    SchedulerConfig(min_interval_minutes=1)
    SchedulerConfig(min_interval_minutes=1440)


def test_scheduler_config_forbid_extras() -> None:
    """extra='forbid' — unknown key raises so typos surface."""
    from core.config.self_improving_loop import SchedulerConfig
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        SchedulerConfig(does_not_exist=True)  # type: ignore[call-arg]


def test_top_level_self_improving_loop_config_carries_scheduler() -> None:
    from core.config.self_improving_loop import (
        SchedulerConfig,
        SelfImprovingLoopConfig,
    )

    cfg = SelfImprovingLoopConfig()
    assert isinstance(cfg.scheduler, SchedulerConfig)
    assert cfg.scheduler.enabled is False


# ---------------------------------------------------------------------------
# Lock acquire / release
# ---------------------------------------------------------------------------


def test_lock_acquire_returns_fd_when_uncontended(
    trigger_paths: tuple[Path, Path],
) -> None:
    from core.self_improving.loop.auto_trigger import (
        acquire_auto_trigger_lock,
        release_auto_trigger_lock,
    )

    lock_path, _ = trigger_paths
    fd = acquire_auto_trigger_lock(lock_path)
    assert fd is not None
    assert isinstance(fd, int)
    release_auto_trigger_lock(fd)


def test_lock_blocks_second_acquire(trigger_paths: tuple[Path, Path]) -> None:
    """Second acquire while first is held → None (no exception)."""
    from core.self_improving.loop.auto_trigger import (
        acquire_auto_trigger_lock,
        release_auto_trigger_lock,
    )

    lock_path, _ = trigger_paths
    fd1 = acquire_auto_trigger_lock(lock_path)
    assert fd1 is not None
    try:
        fd2 = acquire_auto_trigger_lock(lock_path)
        assert fd2 is None  # NB lock should refuse
    finally:
        release_auto_trigger_lock(fd1)
    # After release, third acquire should succeed
    fd3 = acquire_auto_trigger_lock(lock_path)
    assert fd3 is not None
    release_auto_trigger_lock(fd3)


def test_lock_creates_parent_dir(tmp_path: Path) -> None:
    from core.self_improving.loop.auto_trigger import (
        acquire_auto_trigger_lock,
        release_auto_trigger_lock,
    )

    nested = tmp_path / "deep" / "nested" / "lock.lock"
    assert not nested.parent.exists()
    fd = acquire_auto_trigger_lock(nested)
    assert fd is not None
    assert nested.parent.is_dir()
    release_auto_trigger_lock(fd)


# ---------------------------------------------------------------------------
# Timestamp read / write
# ---------------------------------------------------------------------------


def test_read_timestamp_missing_returns_none(trigger_paths: tuple[Path, Path]) -> None:
    from core.self_improving.loop.auto_trigger import read_last_run_timestamp

    _, ts_path = trigger_paths
    assert read_last_run_timestamp(ts_path) is None


def test_write_then_read_timestamp_round_trip(
    trigger_paths: tuple[Path, Path],
) -> None:
    from core.self_improving.loop.auto_trigger import (
        read_last_run_timestamp,
        write_last_run_timestamp,
    )

    _, ts_path = trigger_paths
    write_last_run_timestamp(1234567890.5, ts_path)
    assert read_last_run_timestamp(ts_path) == pytest.approx(1234567890.5)


def test_read_timestamp_unparseable_returns_none(
    trigger_paths: tuple[Path, Path],
) -> None:
    from core.self_improving.loop.auto_trigger import read_last_run_timestamp

    _, ts_path = trigger_paths
    ts_path.parent.mkdir(parents=True, exist_ok=True)
    ts_path.write_text("not-a-number\n", encoding="utf-8")
    assert read_last_run_timestamp(ts_path) is None


# ---------------------------------------------------------------------------
# Min-interval gate
# ---------------------------------------------------------------------------


def test_min_interval_satisfied_when_no_prior_run(
    trigger_paths: tuple[Path, Path],
) -> None:
    from core.self_improving.loop.auto_trigger import is_min_interval_satisfied

    _, ts_path = trigger_paths
    assert is_min_interval_satisfied(min_interval_minutes=60, timestamp_path=ts_path)


def test_min_interval_blocked_when_recent(trigger_paths: tuple[Path, Path]) -> None:
    from core.self_improving.loop.auto_trigger import (
        is_min_interval_satisfied,
        write_last_run_timestamp,
    )

    _, ts_path = trigger_paths
    now = 1000000.0
    write_last_run_timestamp(now - 30 * 60, ts_path)  # 30 minutes ago
    assert not is_min_interval_satisfied(min_interval_minutes=60, now=now, timestamp_path=ts_path)


def test_min_interval_satisfied_when_old_enough(
    trigger_paths: tuple[Path, Path],
) -> None:
    from core.self_improving.loop.auto_trigger import (
        is_min_interval_satisfied,
        write_last_run_timestamp,
    )

    _, ts_path = trigger_paths
    now = 1000000.0
    write_last_run_timestamp(now - 90 * 60, ts_path)  # 90 minutes ago
    assert is_min_interval_satisfied(min_interval_minutes=60, now=now, timestamp_path=ts_path)


# ---------------------------------------------------------------------------
# auto_trigger_mutator — terminal states
# ---------------------------------------------------------------------------


class _FakeRunner:
    """Stand-in for SelfImprovingLoopRunner."""

    def __init__(self, *, raises: Exception | None = None, target_section: str = "sec1") -> None:
        self._raises = raises
        self._target_section = target_section
        self.run_once_count = 0

    def run_once(self) -> Any:
        self.run_once_count += 1
        if self._raises is not None:
            raise self._raises

        class _M:
            target_section = self._target_section

        # Bind target_section before instantiation
        _M.target_section = self._target_section  # type: ignore[misc]
        return _M()


def test_disabled_short_circuits(trigger_paths: tuple[Path, Path]) -> None:
    from core.self_improving.loop.auto_trigger import auto_trigger_mutator

    lock_path, ts_path = trigger_paths
    runner = _FakeRunner()
    status = auto_trigger_mutator(
        enabled=False,
        min_interval_minutes=60,
        runner_factory=lambda: runner,
        lock_path=lock_path,
        timestamp_path=ts_path,
    )
    assert status.state == "disabled"
    assert runner.run_once_count == 0
    assert not ts_path.exists()  # no I/O on disabled path


def test_interval_blocked_skips_runner(trigger_paths: tuple[Path, Path]) -> None:
    from core.self_improving.loop.auto_trigger import (
        auto_trigger_mutator,
        write_last_run_timestamp,
    )

    lock_path, ts_path = trigger_paths
    now = 1000000.0
    write_last_run_timestamp(now - 10 * 60, ts_path)  # 10 minutes ago
    runner = _FakeRunner()
    status = auto_trigger_mutator(
        enabled=True,
        min_interval_minutes=60,
        runner_factory=lambda: runner,
        lock_path=lock_path,
        timestamp_path=ts_path,
        now=now,
    )
    assert status.state == "interval_blocked"
    assert "min_interval_minutes=60" in status.detail
    assert runner.run_once_count == 0


def test_lock_busy_skips_runner(trigger_paths: tuple[Path, Path]) -> None:
    from core.self_improving.loop.auto_trigger import (
        acquire_auto_trigger_lock,
        auto_trigger_mutator,
        release_auto_trigger_lock,
    )

    lock_path, ts_path = trigger_paths
    held_fd = acquire_auto_trigger_lock(lock_path)
    assert held_fd is not None
    try:
        runner = _FakeRunner()
        status = auto_trigger_mutator(
            enabled=True,
            min_interval_minutes=60,
            runner_factory=lambda: runner,
            lock_path=lock_path,
            timestamp_path=ts_path,
        )
        assert status.state == "lock_busy"
        assert runner.run_once_count == 0
    finally:
        release_auto_trigger_lock(held_fd)


def test_fired_updates_timestamp_and_releases_lock(
    trigger_paths: tuple[Path, Path],
) -> None:
    from core.self_improving.loop.auto_trigger import (
        acquire_auto_trigger_lock,
        auto_trigger_mutator,
        read_last_run_timestamp,
        release_auto_trigger_lock,
    )

    lock_path, ts_path = trigger_paths
    runner = _FakeRunner(target_section="wrapper.intro")
    now = 1234567890.0
    status = auto_trigger_mutator(
        enabled=True,
        min_interval_minutes=60,
        runner_factory=lambda: runner,
        lock_path=lock_path,
        timestamp_path=ts_path,
        now=now,
    )
    assert status.state == "fired"
    assert "wrapper.intro" in status.detail
    assert runner.run_once_count == 1
    # Timestamp persisted
    assert read_last_run_timestamp(ts_path) == pytest.approx(now)
    # Lock released — must be re-acquirable
    fd = acquire_auto_trigger_lock(lock_path)
    assert fd is not None
    release_auto_trigger_lock(fd)


def test_runner_error_does_not_update_timestamp(
    trigger_paths: tuple[Path, Path],
) -> None:
    """Generic exception → runner_error state, timestamp unchanged."""
    from core.self_improving.loop.auto_trigger import (
        auto_trigger_mutator,
        read_last_run_timestamp,
    )

    lock_path, ts_path = trigger_paths
    runner = _FakeRunner(raises=RuntimeError("boom"))
    status = auto_trigger_mutator(
        enabled=True,
        min_interval_minutes=60,
        runner_factory=lambda: runner,
        lock_path=lock_path,
        timestamp_path=ts_path,
    )
    assert status.state == "runner_error"
    assert "boom" in status.detail
    assert runner.run_once_count == 1
    # Timestamp NOT written — next cron retries
    assert read_last_run_timestamp(ts_path) is None


def test_parse_error_distinct_from_runner_error(
    trigger_paths: tuple[Path, Path],
) -> None:
    """ValueError → parse_error (LLM produced garbage), not runner_error."""
    from core.self_improving.loop.auto_trigger import auto_trigger_mutator

    lock_path, ts_path = trigger_paths
    runner = _FakeRunner(raises=ValueError("missing target_section"))
    status = auto_trigger_mutator(
        enabled=True,
        min_interval_minutes=60,
        runner_factory=lambda: runner,
        lock_path=lock_path,
        timestamp_path=ts_path,
    )
    assert status.state == "parse_error"
    assert "missing target_section" in status.detail


def test_runner_factory_raising_yields_runner_error(
    trigger_paths: tuple[Path, Path],
) -> None:
    """Codex MCP catch (PR-OL-A1 fix-up). If the *factory itself* raises
    (e.g., lazy import fails, runner __init__ side-effect), the function
    must still return ``runner_error`` — not propagate. Otherwise the
    'never raises' contract is violated and the scheduler loop crashes."""
    from core.self_improving.loop.auto_trigger import auto_trigger_mutator

    lock_path, ts_path = trigger_paths

    def _broken_factory() -> Any:
        raise RuntimeError("factory exploded")

    status = auto_trigger_mutator(
        enabled=True,
        min_interval_minutes=60,
        runner_factory=_broken_factory,
        lock_path=lock_path,
        timestamp_path=ts_path,
    )
    assert status.state == "runner_error"
    assert "factory exploded" in status.detail


def test_post_lock_interval_recheck_blocks_when_timestamp_freshens(
    trigger_paths: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Codex MCP catch (PR-OL-A1 fix-up). TOCTOU defence: the pre-lock
    interval check can be passed using a stale timestamp; a second
    process can then acquire the lock right after the first holder
    writes a fresh timestamp and releases — both fires land
    < ``min_interval`` apart.

    The post-lock re-check closes that gap. We simulate the race by
    patching ``acquire_auto_trigger_lock`` to write a fresh timestamp
    as a side effect (peer landed a fire just before we acquired).
    """
    from core.self_improving.loop.auto_trigger import (
        auto_trigger_mutator,
        write_last_run_timestamp,
    )

    from core.self_improving.loop import auto_trigger as at_module

    lock_path, ts_path = trigger_paths
    now = 3000000.0
    runner = _FakeRunner()
    real_acquire = at_module.acquire_auto_trigger_lock

    def _acquire_with_peer_side_effect(path: Any = None) -> Any:
        # Peer landed a fresh fire 5 minutes ago BEFORE we acquired.
        write_last_run_timestamp(now - 5 * 60, ts_path)
        return real_acquire(path)

    monkeypatch.setattr(at_module, "acquire_auto_trigger_lock", _acquire_with_peer_side_effect)
    status = auto_trigger_mutator(
        enabled=True,
        min_interval_minutes=60,
        runner_factory=lambda: runner,
        lock_path=lock_path,
        timestamp_path=ts_path,
        now=now,
    )
    assert status.state == "interval_blocked"
    assert "post-lock" in status.detail
    assert runner.run_once_count == 0


def test_lock_released_even_after_runner_raises(
    trigger_paths: tuple[Path, Path],
) -> None:
    """Failure path must NOT leak the lockfile — next firing should
    succeed on lock acquisition."""
    from core.self_improving.loop.auto_trigger import (
        acquire_auto_trigger_lock,
        auto_trigger_mutator,
        release_auto_trigger_lock,
    )

    lock_path, ts_path = trigger_paths
    runner = _FakeRunner(raises=RuntimeError("simulated"))
    auto_trigger_mutator(
        enabled=True,
        min_interval_minutes=60,
        runner_factory=lambda: runner,
        lock_path=lock_path,
        timestamp_path=ts_path,
    )
    fd = acquire_auto_trigger_lock(lock_path)
    assert fd is not None
    release_auto_trigger_lock(fd)


def test_register_auto_trigger_skips_when_disabled() -> None:
    """enabled=False → trigger_manager.register NOT called."""
    from unittest.mock import MagicMock

    from core.self_improving.loop.auto_trigger import register_auto_trigger

    mgr = MagicMock()
    result = register_auto_trigger(mgr, enabled=False, cron="0 */6 * * *", min_interval_minutes=60)
    assert result is False
    mgr.register.assert_not_called()


def test_register_auto_trigger_registers_when_enabled() -> None:
    """enabled=True → trigger_manager.register receives a SCHEDULED
    TriggerConfig with the cron + callback."""
    from unittest.mock import MagicMock

    from core.scheduler.triggers import TriggerType
    from core.self_improving.loop.auto_trigger import (
        AUTO_TRIGGER_TRIGGER_ID,
        register_auto_trigger,
    )

    mgr = MagicMock()
    result = register_auto_trigger(mgr, enabled=True, cron="*/15 * * * *", min_interval_minutes=10)
    assert result is True
    mgr.register.assert_called_once()
    config = mgr.register.call_args[0][0]
    assert config.trigger_id == AUTO_TRIGGER_TRIGGER_ID
    assert config.trigger_type == TriggerType.SCHEDULED
    assert config.cron_expr == "*/15 * * * *"
    assert config.callback is not None
    assert config.enabled is True


def test_registered_callback_invokes_auto_trigger_mutator(
    trigger_paths: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The registered callback must forward into auto_trigger_mutator
    when fired (closure forwarding contract). Patches the default lock/
    timestamp paths so the test does not depend on (or mutate) the
    operator's real ``~/.geode/self-improving-loop/`` state."""
    from unittest.mock import MagicMock

    from core.self_improving.loop.auto_trigger import register_auto_trigger

    from core.self_improving.loop import auto_trigger as at_module

    lock_path, ts_path = trigger_paths
    monkeypatch.setattr(at_module, "AUTO_TRIGGER_LOCK_PATH", lock_path)
    monkeypatch.setattr(at_module, "AUTO_TRIGGER_TIMESTAMP_PATH", ts_path)
    mgr = MagicMock()
    runner = _FakeRunner(target_section="wrapper.section")
    register_auto_trigger(
        mgr,
        enabled=True,
        cron="0 * * * *",
        min_interval_minutes=60,
        runner_factory=lambda: runner,
    )
    callback = mgr.register.call_args[0][0].callback
    # Fire — runner should be called via the closure
    callback({"trigger_id": "self_improving_loop_auto_trigger"})
    assert runner.run_once_count == 1


def test_default_runner_factory_imports_runner_lazily() -> None:
    """When factory=None, the module imports SelfImprovingLoopRunner
    lazily — we don't pay the import cost at module load."""
    import importlib
    import sys

    # Drop the runner if cached, so we can detect a lazy import
    mod_name = "core.self_improving.loop.runner"
    original_runner = sys.modules.pop(mod_name, None)
    try:
        # Importing auto_trigger should NOT trigger the runner import
        at_mod = importlib.import_module("core.self_improving.loop.auto_trigger")
        importlib.reload(at_mod)
        assert mod_name not in sys.modules, (
            "auto_trigger must lazy-import SelfImprovingLoopRunner — "
            "found in sys.modules after auto_trigger import"
        )
    finally:
        if original_runner is not None:
            sys.modules[mod_name] = original_runner
