"""PR-CODEX-OAUTH-EMPTY-TEXT-DUMP (2026-05-25) — regression pins for
the empty-output_text postmortem dump.

Smoke 11/12/13 vote-m000-openai.openai-codex consistently failed
with ``output_text=""``, ``termination_reason="natural"``, 10s
elapsed, $0.04 billed. The codex_oauth adapter now writes a
diagnostic dump so the operator can see what the model actually
emitted (reasoning_items / reasoning_summaries / usage / stop_reason)
without re-running the cycle.

Mirrors ``claude_cli._dump_transient_postmortem`` shape so
``~/.geode/diagnostics/`` houses both, and any operator
``diagnostics tar-up`` workflow catches them with one path filter.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from core.llm.adapters.base import (
    AdapterCallResult,
    UsageSummary,
)
from core.llm.adapters.codex_oauth import _dump_empty_text_postmortem


def _build_result(
    *,
    text: str = "",
    reasoning_items: tuple[dict, ...] = (),
    reasoning_summaries: tuple[str, ...] = (),
    stop_reason: str = "completed",
    input_tokens: int = 100,
    output_tokens: int = 50,
) -> AdapterCallResult:
    return AdapterCallResult(
        text=text,
        usage=UsageSummary(input_tokens=input_tokens, output_tokens=output_tokens),
        stop_reason=stop_reason,
        tool_uses=(),
        raw_response=None,
        reasoning_items=reasoning_items,
        reasoning_summaries=reasoning_summaries,
    )


def test_dump_writes_postmortem_file(tmp_path: Path) -> None:
    """Happy path — empty text + 1 reasoning summary → dump created
    with all 4 diagnostic dimensions."""
    result = _build_result(
        reasoning_items=({"type": "reasoning", "encrypted_content": "abc"},),
        reasoning_summaries=("The user wants me to compare two seeds.",),
    )
    with patch("core.paths.GLOBAL_DIAGNOSTICS_DIR", tmp_path):
        dump_path = _dump_empty_text_postmortem(model="gpt-5.5", result=result)

    assert dump_path is not None
    p = Path(dump_path)
    assert p.is_file()
    assert p.parent.name == "codex-oauth-empty-text"
    assert p.name.endswith("-gpt-5.5.json")
    payload = json.loads(p.read_text(encoding="utf-8"))
    assert payload["model"] == "gpt-5.5"
    assert payload["stop_reason"] == "completed"
    assert payload["usage"]["input_tokens"] == 100
    assert payload["usage"]["output_tokens"] == 50
    assert payload["reasoning_items_count"] == 1
    assert payload["reasoning_summaries_count"] == 1
    assert payload["reasoning_summaries"] == [
        "The user wants me to compare two seeds.",
    ]
    assert payload["reasoning_items"][0]["encrypted_content"] == "abc"


def test_dump_creates_parent_dir(tmp_path: Path) -> None:
    """First-ever dump must create the
    ``~/.geode/diagnostics/codex-oauth-empty-text/`` directory."""
    target = tmp_path / "fresh-diagnostics"
    assert not target.exists()
    result = _build_result()
    with patch("core.paths.GLOBAL_DIAGNOSTICS_DIR", target):
        dump_path = _dump_empty_text_postmortem(model="gpt-5.4-mini", result=result)
    assert dump_path is not None
    assert (target / "codex-oauth-empty-text").is_dir()


def test_dump_handles_empty_reasoning_gracefully(tmp_path: Path) -> None:
    """No reasoning_items / no reasoning_summaries — dump still
    writes (just with empty arrays). Operator sees this as a "the
    model returned nothing at all" signal vs the more common
    "reasoning-only" signal."""
    result = _build_result()
    with patch("core.paths.GLOBAL_DIAGNOSTICS_DIR", tmp_path):
        dump_path = _dump_empty_text_postmortem(model="gpt-5.5", result=result)
    assert dump_path is not None
    payload = json.loads(Path(dump_path).read_text(encoding="utf-8"))
    assert payload["reasoning_items_count"] == 0
    assert payload["reasoning_summaries_count"] == 0
    assert payload["reasoning_items"] == []
    assert payload["reasoning_summaries"] == []


def test_dump_returns_none_on_disk_error(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Disk full / permission denied — return ``None`` so the caller
    logs ``<dump failed>`` and continues. Postmortem is best-effort,
    not correctness-critical."""
    # Point GLOBAL_DIAGNOSTICS_DIR at a non-writable path (a regular
    # file masquerading as a directory).
    blocker = tmp_path / "blocker-file"
    blocker.write_text("not a directory", encoding="utf-8")
    with patch("core.paths.GLOBAL_DIAGNOSTICS_DIR", blocker):
        dump_path = _dump_empty_text_postmortem(model="gpt-5.5", result=_build_result())
    assert dump_path is None


def test_dump_filename_format(tmp_path: Path) -> None:
    """``<ts>-<model>.json`` so ``ls -t`` sorts chronologically and
    model groups alphabetically — same convention as claude_cli."""
    result = _build_result()
    with patch("core.paths.GLOBAL_DIAGNOSTICS_DIR", tmp_path):
        dump_path = _dump_empty_text_postmortem(model="gpt-5.4-mini", result=result)
    assert dump_path is not None
    name = Path(dump_path).name
    ts_part, _, model_part = name.partition("-")
    assert ts_part.isdigit()
    assert model_part == "gpt-5.4-mini.json"
