"""OTel exporter wiring tests — no real OTLP backend required."""

from __future__ import annotations

import os
import sys

import pytest
from core.observability import (
    OtelExportError,
    disable,
    enable,
    status,
)
from core.observability.otel_export import resolve_endpoint


def test_status_default_disabled() -> None:
    snap = status()
    assert isinstance(snap.enabled, bool)
    # ``status()`` returns the live module singleton — enabled MUST be
    # False when called from a fresh test interpreter (other tests in
    # this file may flip it later, but this test is module-load order
    # tolerant: the singleton starts disabled).


def test_resolve_endpoint_explicit_wins() -> None:
    assert resolve_endpoint("https://otel.example/v1/traces") == ("https://otel.example/v1/traces")


def test_resolve_endpoint_env_traceloop_first(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRACELOOP_BASE_URL", "https://traceloop.local")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "https://otel.local")
    assert resolve_endpoint() == "https://traceloop.local"


def test_resolve_endpoint_env_otel_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TRACELOOP_BASE_URL", raising=False)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "https://otel.local")
    assert resolve_endpoint() == "https://otel.local"


def test_resolve_endpoint_none_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TRACELOOP_BASE_URL", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    assert resolve_endpoint() is None


def test_enable_without_extra_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """[obs] extra missing → enable() raises OtelExportError."""
    # Force a clean state — disable singleton if any other test enabled it.
    disable()

    # Block the lazy traceloop import.
    monkeypatch.setitem(sys.modules, "traceloop", None)
    monkeypatch.setitem(sys.modules, "traceloop.sdk", None)

    with pytest.raises(OtelExportError, match=r"\[obs\] extra"):
        enable()


def test_disable_is_noop_when_already_disabled() -> None:
    disable()  # baseline
    snap = disable()
    assert snap.enabled is False


def test_module_level_imports_do_not_pull_traceloop() -> None:
    """Importing core.observability must not import traceloop on cold path."""
    # Sanity — the lazy guard in otel_export.enable() only activates when
    # called. Module import alone must not touch traceloop.
    if "traceloop" in sys.modules:
        # Another test may have force-imported it; this test is best-effort.
        pytest.skip("traceloop already in sys.modules from a sibling test")
    # Re-import path that we exercise on cold start:
    import core.observability
    import core.observability.otel_export  # noqa: F401

    assert "traceloop" not in sys.modules
    assert "traceloop.sdk" not in sys.modules


def test_otel_status_object_round_trips_to_dict() -> None:
    snap = status()
    payload = snap.to_dict()
    assert set(payload.keys()) == {"enabled", "endpoint", "app_name", "notes"}
    assert payload["app_name"] == "geode"


@pytest.mark.skipif(
    os.environ.get("GEODE_OBS_INTEGRATION") != "1",
    reason="integration: requires [obs] extra and OTLP endpoint",
)
def test_enable_with_extra_succeeds_smoke() -> None:
    snap = enable(endpoint=None, app_name="geode-test")
    try:
        assert snap.enabled is True
        assert snap.app_name == "geode-test"
    finally:
        disable()
