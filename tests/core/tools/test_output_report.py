"""generate_report writes the requested format and returns a real receipt (S6)."""

from __future__ import annotations

import asyncio
import hashlib
import json
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import pytest
from core.memory.vault import Vault
from core.tools.output_tools import GenerateReportTool

_DATA = {
    "findings": ["critical detail", {"file": "a.py", "line": 3}],
    "summary": "user prose <b>not markup</b>",
    "custom_metric": 7,
}


def _run(tmp_path: Path, **kwargs: Any) -> dict[str, Any]:
    tool = GenerateReportTool(vault=Vault(tmp_path / "vault"))
    result: dict[str, Any] = asyncio.run(tool.aexecute(subject="stub audit", **kwargs))
    return result


def _saved(result: dict[str, Any]) -> str:
    artifact = result["result"]["artifact"]
    content = Path(artifact["path"]).read_text(encoding="utf-8")
    assert artifact["bytes"] == len(content.encode("utf-8"))
    assert artifact["sha256"] == hashlib.sha256(content.encode("utf-8")).hexdigest()
    return content


def test_html_report_is_escaped_html_with_all_findings(tmp_path: Path) -> None:
    result = _run(tmp_path, analysis_data=_DATA, format="html")
    path = Path(result["result"]["artifact"]["path"])
    assert path.suffix == ".html" and path.is_relative_to(tmp_path / "vault" / "research")
    content = _saved(result)
    assert content.startswith("<!DOCTYPE html>")
    HTMLParser().feed(content)
    assert "critical detail" in content and "a.py" in content
    assert "&lt;b&gt;not markup&lt;/b&gt;" in content and "<b>" not in content
    assert "custom_metric" in content


def test_markdown_report_preserves_findings_and_unknown_score(tmp_path: Path) -> None:
    content = _saved(_run(tmp_path, analysis_data=_DATA))
    assert content.startswith("# GEODE Analysis Report: stub audit")
    assert "- critical detail" in content
    assert "0.0" not in content
    assert "## Final score\n\n- not provided" in content


def test_json_report_is_parseable_and_keeps_absent_score_null(tmp_path: Path) -> None:
    result = _run(tmp_path, analysis_data=_DATA, format="json")
    assert Path(result["result"]["artifact"]["path"]).suffix == ".json"
    saved = json.loads(_saved(result))
    sections = saved["sections"]
    assert sections["final_score"] is None and sections["tier"] is None
    assert sections["findings"] == _DATA["findings"]
    assert sections["executive_summary"] == _DATA["summary"]
    assert sections["details"] == {"custom_metric": 7}


def test_supplied_score_is_reported(tmp_path: Path) -> None:
    result = _run(tmp_path, analysis_data={"tier": "A", "final_score": 76.2}, format="json")
    assert "76.2" in result["result"]["sections"]["executive_summary"]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"format": "pdf"},
        {"analysis_data": ["not", "an", "object"]},
        {"analysis_data": {"final_score": "N/A"}},
    ],
)
def test_invalid_input_is_rejected_without_an_artifact(
    tmp_path: Path, kwargs: dict[str, Any]
) -> None:
    result = _run(tmp_path, **kwargs)
    assert result["error_type"] == "validation"
    assert not (tmp_path / "vault").exists()


def test_save_failure_is_an_error_not_a_report(tmp_path: Path) -> None:
    class _BrokenVault:
        def save(self, *_args: Any, **_kwargs: Any) -> Path:
            raise OSError("read-only filesystem")

    result = asyncio.run(GenerateReportTool(vault=_BrokenVault()).aexecute(subject="x"))
    assert "error" in result and "not saved" in result["error"]


@pytest.mark.parametrize("fmt", ["markdown", "html", "json"])
@pytest.mark.parametrize(
    "subscores", [[{"name": "quality", "score": 8}], "strong overall", {"quality": 8}]
)
def test_any_shaped_subscores_render_in_every_format(
    tmp_path: Path, fmt: str, subscores: Any
) -> None:
    """Review 7: schema-valid generic data never crashes one format only."""
    data = {"summary": "S", "subscores": subscores, "findings": ["F"]}
    result = _run(tmp_path, analysis_data=data, format=fmt)
    content = _saved(result)
    assert "F" in content and ("quality" in content or "strong overall" in content)
    assert result["result"]["sections"]["scores"] == subscores
