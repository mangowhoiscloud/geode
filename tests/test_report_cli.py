"""Tests for Report CLI integration."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from core.cli import (
    _generate_report,
    _get_last_result,
    _parse_report_args,
    _set_last_result,
    _state_to_report_dict,
)
from core.cli.commands import COMMAND_MAP, resolve_action
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# TestStateToReportDict
# ---------------------------------------------------------------------------


class _FakeModel(BaseModel):
    value: str
    score: float


class TestStateToReportDict:
    def test_pydantic_model_dumped(self):
        model = _FakeModel(value="test", score=0.5)
        state: dict = {"synthesis": model, "ip_name": "Berserk"}
        result = _state_to_report_dict(state)
        assert result["synthesis"] == {"value": "test", "score": 0.5}
        assert isinstance(result["synthesis"], dict)

    def test_pydantic_list_dumped(self):
        models = [_FakeModel(value="a", score=1.0), _FakeModel(value="b", score=2.0)]
        state: dict = {"analyses": models}
        result = _state_to_report_dict(state)
        assert len(result["analyses"]) == 2
        assert result["analyses"][0] == {"value": "a", "score": 1.0}

    def test_pydantic_dict_dumped(self):
        state: dict = {
            "evaluations": {
                "market": _FakeModel(value="market", score=3.0),
            }
        }
        result = _state_to_report_dict(state)
        assert result["evaluations"]["market"] == {"value": "market", "score": 3.0}

    def test_plain_dict_passthrough(self):
        state: dict = {
            "ip_name": "Berserk",
            "final_score": 85.0,
            "tier": "A",
            "subscores": {"market": 80.0},
        }
        result = _state_to_report_dict(state)
        assert result["ip_name"] == "Berserk"
        assert result["final_score"] == 85.0
        assert result["tier"] == "A"
        assert result["subscores"] == {"market": 80.0}

    def test_missing_fields_defaults(self):
        result = _state_to_report_dict({})
        assert result["ip_name"] == "Unknown IP"
        assert result["final_score"] == 0.0
        assert result["tier"] == "N/A"
        assert result["subscores"] == {}
        assert result["synthesis"] == {}
        assert result["analyses"] == []

    def test_existing_values_not_overridden(self):
        state: dict = {"ip_name": "Cowboy Bebop", "final_score": 92.0}
        result = _state_to_report_dict(state)
        assert result["ip_name"] == "Cowboy Bebop"
        assert result["final_score"] == 92.0


# ---------------------------------------------------------------------------
# TestParseReportArgs
# ---------------------------------------------------------------------------


class TestParseReportArgs:
    def test_ip_name_only(self):
        result = _parse_report_args(["Berserk"])
        assert result["ip_name"] == "Berserk"
        assert result["fmt"] == "md"
        assert result["template"] == "summary"

    def test_with_format(self):
        result = _parse_report_args(["Berserk", "html"])
        assert result["ip_name"] == "Berserk"
        assert result["fmt"] == "html"
        assert result["template"] == "summary"

    def test_with_template(self):
        result = _parse_report_args(["Berserk", "detailed"])
        assert result["ip_name"] == "Berserk"
        assert result["fmt"] == "md"
        assert result["template"] == "detailed"

    def test_format_and_template(self):
        result = _parse_report_args(["Berserk", "html", "detailed"])
        assert result["ip_name"] == "Berserk"
        assert result["fmt"] == "html"
        assert result["template"] == "detailed"

    def test_multiword_ip(self):
        result = _parse_report_args(["Ghost", "in", "the", "Shell"])
        assert result["ip_name"] == "Ghost in the Shell"
        assert result["fmt"] == "md"
        assert result["template"] == "summary"

    def test_multiword_ip_with_format(self):
        result = _parse_report_args(["Cowboy", "Bebop", "json", "executive"])
        assert result["ip_name"] == "Cowboy Bebop"
        assert result["fmt"] == "json"
        assert result["template"] == "executive"

    def test_md_shorthand_to_markdown(self):
        result = _parse_report_args(["Berserk", "md"])
        # "md" is resolved to "markdown" in _parse_report_args
        assert result["fmt"] == "markdown"

    def test_empty_args(self):
        result = _parse_report_args([])
        assert result["ip_name"] == ""
        assert result["fmt"] == "md"
        assert result["template"] == "summary"

    def test_json_format(self):
        result = _parse_report_args(["Berserk", "json"])
        assert result["fmt"] == "json"

    def test_markdown_full_keyword(self):
        result = _parse_report_args(["Berserk", "markdown"])
        assert result["fmt"] == "markdown"


# ---------------------------------------------------------------------------
# TestReportCommand
# ---------------------------------------------------------------------------


class TestReportCommand:
    def test_report_in_command_map(self):
        assert COMMAND_MAP["/report"] == "report"

    def test_rpt_alias(self):
        assert COMMAND_MAP["/rpt"] == "report"

    def test_resolve_report(self):
        assert resolve_action("/report") == "report"
        assert resolve_action("/rpt") == "report"


# ---------------------------------------------------------------------------
# TestGenerateReport
# ---------------------------------------------------------------------------


class TestGenerateReport:
    @patch("core.cli._run_analysis")
    def test_runs_analysis_when_no_cache(self, mock_run):
        mock_run.return_value = {
            "ip_name": "berserk",
            "final_score": 85.0,
            "tier": "A",
            "subscores": {},
            "synthesis": {},
            "analyses": [],
        }
        from core.cli import _result_cache

        _result_cache._cache.clear()
        _generate_report("berserk", verbose=False)
        mock_run.assert_called_once()

    @patch("core.cli._run_analysis")
    def test_uses_cache_when_matching(self, mock_run):
        cached = {
            "ip_name": "berserk",
            "final_score": 85.0,
            "tier": "A",
            "subscores": {},
            "synthesis": {},
            "analyses": [],
        }
        _set_last_result(cached)
        _generate_report("Berserk", verbose=False)
        mock_run.assert_not_called()

    @patch("core.cli._run_analysis")
    def test_runs_analysis_when_cache_differs(self, mock_run):
        from core.cli import _result_cache

        _result_cache._cache.clear()
        _set_last_result({"ip_name": "cowboy bebop", "final_score": 90.0, "tier": "S"})
        mock_run.return_value = {
            "ip_name": "berserk",
            "final_score": 85.0,
            "tier": "A",
        }
        _generate_report("Berserk", verbose=False)
        mock_run.assert_called_once()

    @patch("core.cli._run_analysis")
    def test_file_output(self, mock_run, tmp_path: Path):
        cached = {
            "ip_name": "berserk",
            "final_score": 85.0,
            "tier": "A",
            "subscores": {},
            "synthesis": {},
            "analyses": [],
        }
        _set_last_result(cached)
        out = tmp_path / "report.md"
        _generate_report("Berserk", output=str(out), verbose=False)
        assert out.exists()
        content = out.read_text()
        assert "Berserk" in content or "berserk" in content

    @patch("core.cli._run_analysis")
    def test_unknown_format_fallback(self, mock_run):
        cached = {
            "ip_name": "berserk",
            "final_score": 85.0,
            "tier": "A",
        }
        _set_last_result(cached)
        _generate_report("Berserk", fmt="xml", verbose=False)

    @patch("core.cli._run_analysis")
    def test_returns_none_when_analysis_fails(self, mock_run):
        from core.cli import _result_cache

        _result_cache._cache.clear()
        mock_run.return_value = None
        _generate_report("unknown_ip", verbose=False)
        mock_run.assert_called_once()


# ---------------------------------------------------------------------------
# TestLastResultCache
# ---------------------------------------------------------------------------


class TestLastResultCache:
    def test_set_and_get(self):
        result = {"ip_name": "berserk", "final_score": 85.0}
        _set_last_result(result)
        got = _get_last_result()
        assert got is not None
        assert got["ip_name"] == "berserk"
        assert got["final_score"] == 85.0

    def test_none_is_noop(self):
        _set_last_result(None)  # type: ignore[arg-type]
