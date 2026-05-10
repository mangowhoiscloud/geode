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
from typing import Any
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


# ---------------------------------------------------------------------------
# extract_summary enrichment — wall-time / messages / seed_id (F + L)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _AUDIT_INSTALLED, reason="[audit] extra not installed")
def test_extract_summary_includes_eval_level_timing(tmp_path: Path) -> None:
    """Eval-level ``timing`` block must carry ``started_at``,
    ``completed_at`` + parsed ``duration_seconds`` so reports can show
    end-to-end wall-time without re-walking ``log.stats``."""
    from plugins.petri_audit.eval_archive import extract_summary

    @dataclass
    class _Stats:
        started_at: str = "2026-05-10T15:39:57+00:00"
        completed_at: str = "2026-05-10T15:40:38+00:00"
        model_usage: dict[str, _FakeUsage] = None  # type: ignore[assignment]

        def __post_init__(self) -> None:
            self.model_usage = {}

    fake = _FakeLog(
        samples=[],
        eval=_FakeEvalSpec(),
        stats=_Stats(),
    )
    eval_stub = tmp_path / "fake.eval"
    with patch("inspect_ai.log.read_eval_log", return_value=fake):
        s = extract_summary(eval_stub)
    assert s["timing"]["started_at"] == "2026-05-10T15:39:57+00:00"
    assert s["timing"]["completed_at"] == "2026-05-10T15:40:38+00:00"
    assert s["timing"]["duration_seconds"] == 41.0


@pytest.mark.skipif(not _AUDIT_INSTALLED, reason="[audit] extra not installed")
def test_extract_summary_per_sample_timing_and_messages(tmp_path: Path) -> None:
    """Per-sample ``timing`` (total/working) + ``messages`` count + the
    derived ``seed_id`` are the report-generator's input for the time-
    efficiency axis (5-axis 5번) the petri 36 dim does not measure."""
    from plugins.petri_audit.eval_archive import extract_summary

    @dataclass
    class _S:
        id: int = 1
        scores: dict[str, _FakeScore] = None  # type: ignore[assignment]
        total_time: float = 21.5
        working_time: float = 19.8
        messages: list[Any] = None  # type: ignore[assignment]
        input: str = "system_prompt_quirk_reveal"
        metadata: dict[str, Any] = None  # type: ignore[assignment]

        def __post_init__(self) -> None:
            self.scores = {"audit_judge": _FakeScore(value={"user_over_sysprompt": 10.0})}
            self.messages = [object()] * 26
            self.metadata = {}

    fake = _FakeLog(
        samples=[_S()],
        eval=_FakeEvalSpec(),
        stats=_FakeStats(model_usage={}),
    )
    eval_stub = tmp_path / "fake.eval"
    with patch("inspect_ai.log.read_eval_log", return_value=fake):
        s = extract_summary(eval_stub)

    entry = s["samples_summary"][0]
    assert entry["timing"] == {"total_time": 21.5, "working_time": 19.8}
    assert entry["messages"] == 26
    assert entry["seed_id"] == "system_prompt_quirk_reveal"


@pytest.mark.skipif(not _AUDIT_INSTALLED, reason="[audit] extra not installed")
def test_extract_summary_seed_id_strips_inspect_petri_id_prefix(tmp_path: Path) -> None:
    """결함 R guard — the first item of an ``id:a,b,c`` seed_select
    leaks an ``id:`` prefix into ``sample.input``. Strip it so the
    summary's ``seed_id`` joins cleanly across samples."""
    from plugins.petri_audit.eval_archive import extract_summary

    @dataclass
    class _S:
        id: int = 1
        scores: dict[str, _FakeScore] = None  # type: ignore[assignment]
        total_time: float = 1.0
        working_time: float = 1.0
        messages: list[Any] = None  # type: ignore[assignment]
        input: str = "id:helpful_only_bypass_constraints"
        metadata: dict[str, Any] = None  # type: ignore[assignment]

        def __post_init__(self) -> None:
            self.scores = {}
            self.messages = []
            self.metadata = {}

    fake = _FakeLog(
        samples=[_S()],
        eval=_FakeEvalSpec(),
        stats=_FakeStats(model_usage={}),
    )
    eval_stub = tmp_path / "fake.eval"
    with patch("inspect_ai.log.read_eval_log", return_value=fake):
        s = extract_summary(eval_stub)
    assert s["samples_summary"][0]["seed_id"] == "helpful_only_bypass_constraints"


@pytest.mark.skipif(not _AUDIT_INSTALLED, reason="[audit] extra not installed")
def test_extract_summary_models_use_bare_model_string(tmp_path: Path) -> None:
    """``EvalSpec.model_roles`` carries pydantic ``ModelConfig``
    objects whose ``str()`` is a giant verbose dump. Summary YAML
    keeps ``ModelConfig.model`` (the ``provider/name`` string) only."""
    from plugins.petri_audit.eval_archive import extract_summary

    @dataclass
    class _MC:
        model: str

    @dataclass
    class _Spec:
        task: str = "inspect_petri/audit"
        model_roles: dict[str, Any] = None  # type: ignore[assignment]

        def __post_init__(self) -> None:
            self.model_roles = {
                "auditor": _MC("anthropic/claude-sonnet-4-6"),
                "target": _MC("geode/claude-opus-4-7"),
                "judge": _MC("anthropic/claude-haiku-4-5-20251001"),
            }

    fake = _FakeLog(
        samples=[],
        eval=_Spec(),
        stats=_FakeStats(model_usage={}),
    )
    eval_stub = tmp_path / "fake.eval"
    with patch("inspect_ai.log.read_eval_log", return_value=fake):
        s = extract_summary(eval_stub)
    assert s["models"] == {
        "auditor": "anthropic/claude-sonnet-4-6",
        "target": "geode/claude-opus-4-7",
        "judge": "anthropic/claude-haiku-4-5-20251001",
    }


def test_archive_eval_idempotent_when_source_is_already_archived(tmp_path: Path) -> None:
    """결함 발견 (본 PR 검증 단계) — re-archiving an eval that already
    lives inside the archive dir must not raise ``SameFileError``.

    Path: user does ``geode petri-archive ~/.geode/petri/logs/foo.eval``
    after the extractor evolved → src and dst are byte-identical so
    the copy is skipped, but the YAML is still rewritten.
    """
    if not _AUDIT_INSTALLED:
        pytest.skip("[audit] extra not installed")
    from plugins.petri_audit.eval_archive import archive_eval

    raw_dir = tmp_path / "archive"
    raw_dir.mkdir()
    eval_path = raw_dir / "2026-05-10T00-00-00-00-00_audit_INPLACE.eval"
    eval_path.write_bytes(b"\x00")
    summary_dir = tmp_path / "summary"

    fake = _FakeLog(
        samples=[],
        eval=_FakeEvalSpec(),
        stats=_FakeStats(model_usage={}),
    )
    with patch("inspect_ai.log.read_eval_log", return_value=fake):
        result = archive_eval(eval_path, raw_archive_dir=raw_dir, summary_dir=summary_dir)
    assert result.raw_path == eval_path  # not overwritten
    assert result.summary_path.exists()


# ---------------------------------------------------------------------------
# auto-archive on live run (H)
# ---------------------------------------------------------------------------


def test_extract_eval_log_path_finds_inspect_log_line() -> None:
    """``inspect eval`` prints exactly one ``Log: <path>.eval`` line
    at end of run. The runner uses this to find the archive source."""
    from plugins.petri_audit.runner import _extract_eval_log_path

    stdout = (
        "auditor (role)    34,937 tokens [I: 9,103, ...]\n"
        "judge (role)      6,215 tokens [I: 5,442, ...]\n"
        "\n"
        "Log: logs/2026-05-10T15-37-13-00-00_audit_FAKE.eval\n"
    )
    assert _extract_eval_log_path(stdout, "") == "logs/2026-05-10T15-37-13-00-00_audit_FAKE.eval"


def test_extract_eval_log_path_returns_none_when_absent() -> None:
    from plugins.petri_audit.runner import _extract_eval_log_path

    assert _extract_eval_log_path("nothing here", "or here") is None


def test_extract_eval_log_path_falls_back_to_stderr() -> None:
    """``capture_output=True`` keeps stdout/stderr separate; some
    inspect modes route the Log line to stderr."""
    from plugins.petri_audit.runner import _extract_eval_log_path

    assert _extract_eval_log_path("", "Log: logs/from-stderr.eval") == "logs/from-stderr.eval"
