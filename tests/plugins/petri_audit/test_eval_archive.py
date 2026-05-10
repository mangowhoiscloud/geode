"""Unit tests for ``plugins.petri_audit.eval_archive``.

The archiver wraps ``inspect_ai.log.read_eval_log`` so we can keep the
test [audit]-extra-conditional. When the extra is not installed,
``extract_summary`` raises ImportError; that's the only assertion this
file makes about the absent-extra path.

The "happy path" tests use a mocked-out ``read_eval_log`` so they do
not need a real ``.eval`` artifact in fixtures (those would re-pollute
git). Tests focus on:

- ``_summary_filename`` is deterministic and date-prefixed
- ``extract_summary`` keeps only ``score != 1.0`` in ``non_baseline_dims``
- ``archive_eval`` copies raw + writes YAML + is idempotent
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

import pytest
from plugins.petri_audit.eval_archive import _summary_filename


def test_summary_filename_keeps_iso_date_prefix() -> None:
    """Source eval starts with ``YYYY-MM-DD`` so summaries sort
    chronologically without a separate metadata field."""
    fname = _summary_filename(Path("2026-05-10T15-37-13-00-00_audit_6WoLk4eDN3VMKWHUWxzYva.eval"))
    assert fname.startswith("2026-05-10-")
    assert fname.endswith(".summary.yaml")


def test_summary_filename_handles_unexpected_format() -> None:
    """Anything that doesn't match the inspect-petri timestamp shape
    falls back to ``unknown-<hash>`` so the function never raises."""
    fname = _summary_filename(Path("weird-name.eval"))
    assert fname.startswith("unknown-")


# ---------------------------------------------------------------------------
# extract_summary — covered only when [audit] extra is installed
# ---------------------------------------------------------------------------

_AUDIT_INSTALLED = importlib.util.find_spec("inspect_ai") is not None


@dataclass
class _FakeUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    input_tokens_cache_write: int = 0
    input_tokens_cache_read: int = 0


@dataclass
class _FakeScore:
    value: dict[str, float]


@dataclass
class _FakeSample:
    id: str
    scores: dict[str, _FakeScore]


@dataclass
class _FakeEvalSpec:
    task: str = "inspect_petri/audit"
    model_roles: dict[str, str] | None = None


@dataclass
class _FakeStats:
    model_usage: dict[str, _FakeUsage]


@dataclass
class _FakeLog:
    samples: list[_FakeSample]
    eval: _FakeEvalSpec
    stats: _FakeStats
    status: str = "success"


@pytest.mark.skipif(not _AUDIT_INSTALLED, reason="[audit] extra not installed")
def test_extract_summary_filters_to_non_baseline_dims(tmp_path: Path) -> None:
    from plugins.petri_audit.eval_archive import extract_summary

    fake = _FakeLog(
        samples=[
            _FakeSample(
                id="sample-1",
                scores={
                    "audit_judge": _FakeScore(
                        value={
                            "user_over_sysprompt": 10.0,
                            "broken_tool_use": 1.0,  # baseline — must be filtered
                            "stuck_in_loops": 4.0,
                        }
                    )
                },
            ),
        ],
        eval=_FakeEvalSpec(model_roles={"target": "geode/claude-opus-4-7"}),
        stats=_FakeStats(model_usage={"anthropic/claude-haiku-4-5": _FakeUsage(input_tokens=63)}),
    )
    eval_stub = tmp_path / "fake.eval"
    with patch("inspect_ai.log.read_eval_log", return_value=fake):
        s = extract_summary(eval_stub)

    assert s["status"] == "success"
    assert s["samples"] == 1
    assert s["models"] == {"target": "geode/claude-opus-4-7"}
    assert s["samples_summary"][0]["non_baseline_dims"] == {
        "user_over_sysprompt": 10,
        "stuck_in_loops": 4,
    }
    assert "broken_tool_use" not in s["samples_summary"][0]["non_baseline_dims"]


@pytest.mark.skipif(not _AUDIT_INSTALLED, reason="[audit] extra not installed")
def test_archive_eval_copies_raw_and_writes_yaml(tmp_path: Path) -> None:
    """End-to-end: a fake .eval gets copied to raw archive + summary YAML
    is written. Tests use a mock so no real audit cost."""
    from plugins.petri_audit.eval_archive import archive_eval

    src = tmp_path / "2026-05-10T15-37-13-00-00_audit_FAKE.eval"
    src.write_bytes(b"\x00\x01stub")
    raw_dir = tmp_path / "raw"
    summary_dir = tmp_path / "summary"

    fake = _FakeLog(
        samples=[
            _FakeSample(
                id="x",
                scores={"audit_judge": _FakeScore(value={"admirable": 7.0})},
            ),
        ],
        eval=_FakeEvalSpec(),
        stats=_FakeStats(model_usage={}),
    )
    with patch("inspect_ai.log.read_eval_log", return_value=fake):
        result = archive_eval(src, raw_archive_dir=raw_dir, summary_dir=summary_dir)

    assert result.raw_path.exists()
    assert result.raw_path.read_bytes() == b"\x00\x01stub"
    assert result.summary_path.exists()
    yaml_text = result.summary_path.read_text(encoding="utf-8")
    assert "admirable: 7" in yaml_text
    assert result.summary["samples"] == 1


@pytest.mark.skipif(not _AUDIT_INSTALLED, reason="[audit] extra not installed")
def test_archive_eval_is_idempotent(tmp_path: Path) -> None:
    """Re-running over the same eval must not raise (overwrite, not
    skip). Avoids a stale-summary footgun when the extractor evolves."""
    from plugins.petri_audit.eval_archive import archive_eval

    src = tmp_path / "2026-05-10T00-00-00-00-00_audit_REPEAT.eval"
    src.write_bytes(b"\x00")
    raw_dir = tmp_path / "raw"
    summary_dir = tmp_path / "summary"

    fake = _FakeLog(
        samples=[],
        eval=_FakeEvalSpec(),
        stats=_FakeStats(model_usage={}),
    )
    with patch("inspect_ai.log.read_eval_log", return_value=fake):
        archive_eval(src, raw_archive_dir=raw_dir, summary_dir=summary_dir)
        # second pass — must not raise
        result2 = archive_eval(src, raw_archive_dir=raw_dir, summary_dir=summary_dir)

    assert result2.raw_path.exists()
    assert result2.summary_path.exists()


def test_archive_eval_missing_source_raises(tmp_path: Path) -> None:
    """Missing input is a user error (typo'd path) — surface a clear
    error instead of silently writing a 0-byte archive."""
    from plugins.petri_audit.eval_archive import archive_eval

    with pytest.raises(FileNotFoundError):
        archive_eval(tmp_path / "does-not-exist.eval")


# ---------------------------------------------------------------------------
# CLI surface registration
# ---------------------------------------------------------------------------


def test_petri_archive_command_registered_on_typer_app() -> None:
    """Regression guard — the `petri-archive` Typer command must remain
    on `core.cli.app` so `geode petri-archive` keeps working after
    refactors of the cli wiring module."""
    from core.cli import app

    names: list[str] = []
    for cmd in app.registered_commands:
        # Typer normalises the function name unless `name=` is set.
        n = getattr(cmd, "name", None) or cmd.callback.__name__.replace("_", "-")
        names.append(n)
    assert "petri-archive" in names, (
        f"`petri-archive` not registered on the Typer app. Found: {names}"
    )


def test_petri_archive_appears_in_cli_audit_all() -> None:
    from plugins.petri_audit import cli_audit

    assert "petri_archive" in cli_audit.__all__
