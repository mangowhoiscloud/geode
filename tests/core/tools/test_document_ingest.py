"""document_ingest tool wiring and bundle tests."""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from core.tools import document_ingest as mod
from core.tools.document_ingest import DocumentIngestTool

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFINITIONS = REPO_ROOT / "core" / "tools" / "definitions.json"


def _fake_pdf(tmp_path: Path) -> Path:
    pdf = tmp_path / "sample.pdf"
    pdf.write_bytes(b"%PDF-1.4\n% fake fixture\n")
    return pdf


def _patch_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mod, "validate_path", lambda path, write=False: Path(path))


def test_local_text_backend_writes_manifest_and_pages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_paths(monkeypatch)
    pdf = _fake_pdf(tmp_path)

    monkeypatch.setattr(mod.shutil, "which", lambda name: f"/usr/bin/{name}")

    def fake_run(argv: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        out_path = Path(argv[-1])
        out_path.write_text("First page\n\fSecond page\n\f", encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)

    result = asyncio.run(
        DocumentIngestTool().aexecute(
            file_path=str(pdf),
            backend="local_text",
            output_dir=str(tmp_path / "bundle"),
            doc_id="sample-doc",
        )
    )

    bundle = result["result"]
    manifest = json.loads(Path(bundle["manifest_path"]).read_text(encoding="utf-8"))
    assert bundle["backend"] == "local_text"
    assert bundle["page_count"] == 2
    assert manifest["doc_id"] == "sample-doc"
    assert "First page" in Path(bundle["full_text_path"]).read_text(encoding="utf-8")
    assert (Path(bundle["pages_dir"]) / "page-0002.md").read_text(encoding="utf-8") == "Second page"


def test_auto_backend_uses_provider_when_local_text_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_paths(monkeypatch)
    pdf = _fake_pdf(tmp_path)
    monkeypatch.setattr(mod.shutil, "which", lambda name: f"/usr/bin/{name}")

    def fake_run(argv: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        Path(argv[-1]).write_text("", encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    monkeypatch.setattr(
        mod,
        "_openai_pdf_backend",
        lambda *args, **kwargs: mod._IngestedDocument(
            backend="openai_pdf",
            markdown="# Provider parse",
            pages=["# Provider parse"],
        ),
    )

    result = asyncio.run(
        DocumentIngestTool().aexecute(
            file_path=str(pdf),
            backend="auto",
            output_dir=str(tmp_path / "bundle"),
            _tool_context=SimpleNamespace(provider="openai", model="gpt-5.5"),
        )
    )

    assert result["result"]["backend"] == "openai_pdf"
    assert "# Provider parse" in Path(result["result"]["full_text_path"]).read_text(
        encoding="utf-8"
    )


def test_zhipu_payload_uses_layout_parsing_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = _fake_pdf(tmp_path)
    monkeypatch.setenv("ZAI_API_KEY", "test-key")

    class _Settings:
        zai_api_key = ""

    monkeypatch.setattr("core.config.settings", _Settings())

    captured: dict[str, Any] = {}

    class _Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {
                "model": "GLM-OCR",
                "md_results": "# OCR",
                "request_id": "req_123456",
                "data_info": {"num_pages": 1},
                "usage": {"total_tokens": 12},
            }

    def fake_post(url: str, **kwargs: Any) -> _Response:
        captured["url"] = url
        captured.update(kwargs)
        return _Response()

    monkeypatch.setattr(mod.httpx if hasattr(mod, "httpx") else "httpx.post", fake_post)

    result = mod._zhipu_ocr_backend(
        pdf,
        model="glm-ocr",
        timeout_s=30,
        start_page=2,
        end_page=3,
    )

    assert not isinstance(result, dict)
    assert captured["url"].endswith("/layout_parsing")
    assert captured["json"]["file"].startswith("data:application/pdf;base64,")
    assert captured["json"]["start_page_id"] == 2
    assert captured["json"]["end_page_id"] == 3
    assert result.markdown == "# OCR"


def test_document_ingest_is_wired() -> None:
    tools = json.loads(DEFINITIONS.read_text(encoding="utf-8"))
    definition = next(t for t in tools if t.get("name") == "document_ingest")
    assert definition["cost_tier"] == "expensive"
    assert "openai_pdf" in definition["input_schema"]["properties"]["backend"]["enum"]
    assert "claude_pdf" in definition["description"]
    assert "zhipu_ocr" in definition["description"]

    from core.agent.safety import WRITE_TOOLS
    from core.cli.tool_handlers.delegated import _DELEGATED_TOOLS

    assert _DELEGATED_TOOLS["document_ingest"] == (
        "core.tools.document_ingest",
        "DocumentIngestTool",
    )
    assert "document_ingest" in WRITE_TOOLS
