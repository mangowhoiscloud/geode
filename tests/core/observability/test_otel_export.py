"""OTel exporter wiring tests — no real OTLP backend required."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from core.observability import (
    OtelExportError,
    disable,
    enable,
    status,
)
from core.observability.otel_export import resolve_endpoint


def _fresh_import_snapshot(tmp_path: Path) -> dict[str, object]:
    completed = subprocess.run(  # noqa: S603 - fixed import-only probe
        [
            sys.executable,
            "-I",
            "-c",
            """
import json
import sys
sys.path.insert(0, sys.argv[1])
import core.observability as obs
print(json.dumps({
    "enabled": obs.status().enabled,
    "traceloop_modules": [name for name in sys.modules
                         if name == "traceloop" or name.startswith("traceloop.")],
}))
""",
            str(Path(__file__).resolve().parents[3]),
        ],
        cwd=tmp_path,
        env={
            "HOME": str(tmp_path),
            "GEODE_HOME": str(tmp_path / "geode"),
            "CODEX_HOME": str(tmp_path / "codex"),
            "GEODE_AUTH_TOML": str(tmp_path / "auth.toml"),
            "OTEL_SDK_DISABLED": "true",
        },
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    return json.loads(completed.stdout)


def test_status_default_disabled(tmp_path: Path) -> None:
    assert _fresh_import_snapshot(tmp_path)["enabled"] is False


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


def test_module_level_imports_do_not_pull_traceloop(tmp_path: Path) -> None:
    """Importing core.observability must not import traceloop on cold path."""
    assert _fresh_import_snapshot(tmp_path)["traceloop_modules"] == []


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
