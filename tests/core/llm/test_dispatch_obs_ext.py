"""Regression pin for PR-DISPATCH-OBS-EXT (2026-05-28).

Four observability enhancements layered on top of PR-NO-FALLBACK's
strict-dispatch + ADAPTER_DISPATCH_ATTEMPT hook:

1. ``WebSearchResult`` / ``TextCompletionResult`` carry the selected
   adapter's identity inline (``adapter_name`` / ``adapter_provider`` /
   ``adapter_source``) — single-point enrichment at the dispatch layer.
2. ``begin_session_adapter_tracking`` + ``get_session_adapter_usage``
   provide a per-session ``{adapter_name: {outcome: count}}`` aggregate
   that ``SESSION_ENDED`` emits inline.
3. ``geode adapters stats`` CLI parses ``ADAPTER_DISPATCH_ATTEMPT``
   events from ``~/.geode/runs/*.jsonl`` into a (capability, adapter)
   table with per-outcome counts + p50/p95 latency.
4. ``typer_serve`` restores the ``RotatingFileHandler`` at
   ``SERVE_LOG_PATH`` so the dispatch INFO logs land in
   ``~/.geode/logs/serve.log`` (file recovery; serve startup writes
   "serve.log opened" at INFO).
"""

from __future__ import annotations

import asyncio
import inspect
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# 1. Result dataclasses carry adapter identity fields
# ---------------------------------------------------------------------------


def test_web_search_result_carries_adapter_identity_fields() -> None:
    import dataclasses

    from core.llm.adapters.base import WebSearchResult

    fields = {f.name for f in dataclasses.fields(WebSearchResult)}
    assert {"adapter_name", "adapter_provider", "adapter_source"}.issubset(fields)

    result = WebSearchResult(
        query="q",
        text="hello",
        adapter_name="codex-oauth",
        adapter_provider="openai",
        adapter_source="subscription",
    )
    assert result.adapter_provider == "openai"
    assert result.adapter_source == "subscription"


def test_text_completion_result_carries_adapter_identity_fields() -> None:
    import dataclasses

    from core.llm.adapters.base import TextCompletionResult, UsageSummary

    fields = {f.name for f in dataclasses.fields(TextCompletionResult)}
    assert {"adapter_name", "adapter_provider", "adapter_source"}.issubset(fields)

    result = TextCompletionResult(
        text="hello",
        usage=UsageSummary(input_tokens=1, output_tokens=2),
        adapter_name="anthropic-payg",
        adapter_provider="anthropic",
        adapter_source="payg",
    )
    assert result.adapter_provider == "anthropic"
    assert result.adapter_source == "payg"


def test_dispatch_enriches_web_search_result_with_adapter_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Single-point enrichment: even when the capability impl forgets to
    fill ``adapter_provider`` / ``adapter_source``, ``dispatch`` overwrites
    them with the selected adapter's identity before returning."""
    from core.llm.adapters.base import WebSearchResult
    from core.llm.adapters.dispatch import web_search_via_adapters

    adapter = MagicMock(
        spec_set=["name", "provider", "source", "supports_web_search", "aweb_search"]
    )
    adapter.name = "codex-oauth"
    adapter.provider = "openai"
    adapter.source = "subscription"
    adapter.supports_web_search = True
    adapter.aweb_search = AsyncMock(
        return_value=WebSearchResult(query="q", text="hello", adapter_name="codex-oauth")
    )
    monkeypatch.setattr("core.llm.adapters.dispatch.list_adapters", lambda: [adapter])
    monkeypatch.setattr(
        "core.llm.adapters._source_inference.infer_source", lambda provider: "subscription"
    )

    result = asyncio.run(
        web_search_via_adapters("q", prefer_provider="openai", prefer_source="subscription")
    )
    assert result.adapter_name == "codex-oauth"
    assert result.adapter_provider == "openai"
    assert result.adapter_source == "subscription"


# ---------------------------------------------------------------------------
# 2. Per-session adapter usage counter
# ---------------------------------------------------------------------------


def test_session_adapter_usage_accumulates_across_dispatch_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``begin_session_adapter_tracking`` resets the counter; subsequent
    dispatch attempts increment it; ``get_session_adapter_usage`` returns
    the accumulated breakdown by ``{adapter_name: {outcome: count}}``."""
    from core.llm.adapters.base import WebSearchResult
    from core.llm.adapters.dispatch import (
        begin_session_adapter_tracking,
        get_session_adapter_usage,
        web_search_via_adapters,
    )
    from core.llm.errors import BillingError

    adapter_ok = MagicMock(
        spec_set=["name", "provider", "source", "supports_web_search", "aweb_search"]
    )
    adapter_ok.name = "codex-oauth"
    adapter_ok.provider = "openai"
    adapter_ok.source = "subscription"
    adapter_ok.supports_web_search = True
    adapter_ok.aweb_search = AsyncMock(
        return_value=WebSearchResult(query="q", text="ok", adapter_name="codex-oauth")
    )

    adapter_bill = MagicMock(
        spec_set=["name", "provider", "source", "supports_web_search", "aweb_search"]
    )
    adapter_bill.name = "anthropic-payg"
    adapter_bill.provider = "anthropic"
    adapter_bill.source = "payg"
    adapter_bill.supports_web_search = True
    adapter_bill.aweb_search = AsyncMock(side_effect=BillingError("quota", provider="anthropic"))

    monkeypatch.setattr(
        "core.llm.adapters.dispatch.list_adapters", lambda: [adapter_ok, adapter_bill]
    )
    monkeypatch.setattr("core.llm.adapters._source_inference.infer_source", lambda provider: "payg")

    begin_session_adapter_tracking()
    assert get_session_adapter_usage() == {}

    asyncio.run(
        web_search_via_adapters("q", prefer_provider="openai", prefer_source="subscription")
    )
    asyncio.run(
        web_search_via_adapters("q", prefer_provider="openai", prefer_source="subscription")
    )
    with pytest.raises(BillingError):
        asyncio.run(web_search_via_adapters("q", prefer_provider="anthropic", prefer_source="payg"))

    usage = get_session_adapter_usage()
    assert usage == {
        "codex-oauth": {"success": 2},
        "anthropic-payg": {"billing": 1},
    }


def test_session_adapter_usage_returns_empty_outside_tracked_session() -> None:
    """Dispatches outside a tracked session (CLI helpers, tests that don't
    call ``begin_session_adapter_tracking``) silently skip accumulation."""
    from contextvars import Context

    from core.llm.adapters.dispatch import get_session_adapter_usage

    # Fresh Context() inherits no values — every ContextVar reads its default.
    ctx = Context()
    result = ctx.run(get_session_adapter_usage)
    assert result == {}


def test_session_end_payload_includes_adapter_usage() -> None:
    """Source-level pin: ``_build_lifecycle_payloads`` reads
    ``get_session_adapter_usage`` and emits ``adapter_usage`` into the
    SESSION_ENDED metadata."""
    src = (
        Path(__file__).resolve().parents[3] / "core" / "agent" / "loop" / "_lifecycle.py"
    ).read_text(encoding="utf-8")
    assert "get_session_adapter_usage" in src
    assert '"adapter_usage": adapter_usage' in src


def test_agentic_loop_starts_session_adapter_tracking() -> None:
    """Source-level pin: AgenticLoop calls ``begin_session_adapter_tracking``
    at session start so the SESSION_ENDED payload has a populated counter."""
    src = (
        Path(__file__).resolve().parents[3] / "core" / "agent" / "loop" / "agent_loop.py"
    ).read_text(encoding="utf-8")
    assert "begin_session_adapter_tracking()" in src


def test_lifecycle_resets_tracking_after_session_end() -> None:
    """Codex MCP audit catch — without an explicit ``end_session_adapter_tracking``
    call after the SESSION_ENDED payload is built, any post-finalization
    dispatch leaked into the same context would mutate a stale counter.
    Source-level pin so the reset cannot be silently dropped."""
    src = (
        Path(__file__).resolve().parents[3] / "core" / "agent" / "loop" / "_lifecycle.py"
    ).read_text(encoding="utf-8")
    assert "end_session_adapter_tracking" in src


def test_end_session_adapter_tracking_clears_counter() -> None:
    """After ``end_session_adapter_tracking``, ``get_session_adapter_usage``
    returns empty even if the counter had values."""
    from core.llm.adapters.dispatch import (
        begin_session_adapter_tracking,
        end_session_adapter_tracking,
        get_session_adapter_usage,
    )

    begin_session_adapter_tracking()
    # Simulate an attempt landing in the counter.
    from core.llm.adapters.dispatch import _session_adapter_usage_ctx

    counter = _session_adapter_usage_ctx.get()
    assert counter is not None
    counter.setdefault("test-adapter", {})["success"] = 1
    assert get_session_adapter_usage() == {"test-adapter": {"success": 1}}
    end_session_adapter_tracking()
    assert get_session_adapter_usage() == {}


# ---------------------------------------------------------------------------
# 3. CLI `geode adapters stats` parses jsonl
# ---------------------------------------------------------------------------


def test_adapters_stats_parses_dispatch_attempts_from_jsonl(tmp_path: Path) -> None:
    """End-to-end: write a synthetic ADAPTER_DISPATCH_ATTEMPT jsonl,
    invoke the CLI command, parse the table from stdout."""
    import time

    from core.cli.cmd_adapters import app
    from typer.testing import CliRunner

    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    jsonl = runs_dir / "test.jsonl"

    now = time.time()
    events = [
        {
            "event": "adapter_dispatch_attempt",
            "timestamp": now - 60,  # 1 min ago — inside --since 1h window
            "metadata": {
                "adapter_name": "codex-oauth",
                "provider": "openai",
                "source": "subscription",
                "capability": "supports_web_search",
                "outcome": "success",
                "elapsed_ms": 11184.0,
            },
        },
        {
            "event": "adapter_dispatch_attempt",
            "timestamp": now - 30,
            "metadata": {
                "adapter_name": "glm-payg",
                "provider": "glm",
                "source": "payg",
                "capability": "supports_text_completion",
                "outcome": "billing",
                "elapsed_ms": 250.0,
            },
        },
        # Outside window — should NOT appear in the --since 1h slice
        {
            "event": "adapter_dispatch_attempt",
            "timestamp": now - 7200,  # 2h ago
            "metadata": {
                "adapter_name": "glm-payg",
                "provider": "glm",
                "source": "payg",
                "capability": "supports_text_completion",
                "outcome": "success",
                "elapsed_ms": 100.0,
            },
        },
    ]
    jsonl.write_text("\n".join(json.dumps(e) for e in events), encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(app, ["stats", "--since", "1h", "--runs-dir", str(runs_dir)])
    assert result.exit_code == 0, result.output
    assert "codex-oauth" in result.output
    assert "supports_web_search" in result.output
    assert "glm-payg" in result.output
    assert "supports_text_completion" in result.output
    # Total = 2 (in-window), not 3 (the 2h-old event filtered out)
    assert "2 dispatch attempt" in result.output


def test_adapters_stats_rejects_malformed_since() -> None:
    from core.cli.cmd_adapters import app
    from typer.testing import CliRunner

    runner = CliRunner()
    result = runner.invoke(app, ["stats", "--since", "1x"])
    assert result.exit_code != 0
    assert "unit" in result.output.lower()


def test_adapters_stats_empty_window_message(tmp_path: Path) -> None:
    """When the window has zero events, the CLI prints a no-match message
    + the number of rows it scanned."""
    from core.cli.cmd_adapters import app
    from typer.testing import CliRunner

    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    (runs_dir / "empty.jsonl").write_text("", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(app, ["stats", "--since", "1h", "--runs-dir", str(runs_dir)])
    assert result.exit_code == 0
    assert "No ADAPTER_DISPATCH_ATTEMPT events" in result.output


# ---------------------------------------------------------------------------
# 4. typer_serve wires RotatingFileHandler at SERVE_LOG_PATH
# ---------------------------------------------------------------------------


def test_typer_serve_wires_rotating_file_handler_for_serve_log() -> None:
    """Source-level pin: ``serve`` keeps its file-log contract — dispatch
    INFO logs persist across serve restarts at ``SERVE_LOG_PATH`` with
    10MB / 5-backup rotation. S-6 (2026-06-11) moved the wiring into the
    unified switchboard (``configure_logging("serve")``); the contract is
    now pinned at the switchboard's mode spec instead of inline handler
    construction."""
    src = inspect.getsource(__import__("core.cli.typer_serve", fromlist=["serve"]).serve)
    assert 'configure_logging("serve")' in src

    from core.observability import logging_config
    from core.paths import SERVE_LOG_PATH

    serve_file, _fmt = logging_config._MODE_SPECS["serve"]
    assert serve_file == SERVE_LOG_PATH
    assert logging_config._DEFAULT_MAX_BYTES == 10 * 1024 * 1024
    assert logging_config._DEFAULT_BACKUP_COUNT == 5


# ---------------------------------------------------------------------------
# 5. Tool result inlines adapter_provider / adapter_source
# ---------------------------------------------------------------------------


def test_web_tools_general_web_search_surfaces_adapter_identity() -> None:
    src = (Path(__file__).resolve().parents[3] / "core" / "tools" / "web_tools.py").read_text(
        encoding="utf-8"
    )
    assert '"adapter_provider": result.adapter_provider' in src
    assert '"adapter_source": result.adapter_source' in src


def test_web_search_tool_surfaces_adapter_identity() -> None:
    src = (Path(__file__).resolve().parents[3] / "core" / "tools" / "web_search.py").read_text(
        encoding="utf-8"
    )
    assert '"adapter_provider": result.adapter_provider' in src
    assert '"adapter_source": result.adapter_source' in src
