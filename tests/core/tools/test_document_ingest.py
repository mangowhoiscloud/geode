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


def test_local_text_backend_honors_page_range(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_paths(monkeypatch)
    pdf = _fake_pdf(tmp_path)
    monkeypatch.setattr(mod.shutil, "which", lambda name: f"/usr/bin/{name}")

    def fake_run(argv: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        out_path = Path(argv[-1])
        out_path.write_text("First\n\fSecond\n\fThird\n\f", encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)

    result = asyncio.run(
        DocumentIngestTool().aexecute(
            file_path=str(pdf),
            backend="local_text",
            page_range="2-3",
            output_dir=str(tmp_path / "bundle"),
        )
    )

    bundle = result["result"]
    full_text = Path(bundle["full_text_path"]).read_text(encoding="utf-8")
    manifest = json.loads(Path(bundle["manifest_path"]).read_text(encoding="utf-8"))
    assert bundle["page_count"] == 2
    assert "## Page 1" not in full_text
    assert "## Page 2" in full_text
    assert "Third" in full_text
    assert manifest["metadata"]["requested_page_range"] == "2-3"
    assert manifest["metadata"]["page_numbers"] == [2, 3]


def test_page_range_rejects_zero() -> None:
    result = mod._parse_page_selection(page_range="0-2", start_page=None, end_page=None)

    assert isinstance(result, dict)
    assert result["error_type"] == "validation"
    assert "1-indexed" in result["error"]


def test_page_chunk_size_must_be_positive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_paths(monkeypatch)
    pdf = _fake_pdf(tmp_path)

    result = asyncio.run(
        DocumentIngestTool().aexecute(
            file_path=str(pdf),
            backend="local_text",
            page_chunk_size=-1,
        )
    )

    assert result["error_type"] == "validation"
    assert "page_chunk_size" in result["error"]


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

    monkeypatch.setattr("httpx.post", fake_post)

    result = mod._zhipu_ocr_backend(
        pdf,
        model="glm-ocr",
        timeout_s=30,
        page_selection=mod._PageSelection(((2, 3),)),
        page_chunk_size=100,
    )

    assert not isinstance(result, dict)
    assert captured["url"].endswith("/layout_parsing")
    assert captured["json"]["file"].startswith("data:application/pdf;base64,")
    assert captured["json"]["start_page_id"] == 2
    assert captured["json"]["end_page_id"] == 3
    assert result.markdown == "# OCR"


def test_zhipu_page_range_is_chunked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pdf = _fake_pdf(tmp_path)
    monkeypatch.setenv("ZAI_API_KEY", "test-key")

    class _Settings:
        zai_api_key = ""

    monkeypatch.setattr("core.config.settings", _Settings())

    captured: list[dict[str, Any]] = []

    class _Response:
        def __init__(self, payload: dict[str, Any]) -> None:
            self.payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            start = self.payload.get("start_page_id")
            end = self.payload.get("end_page_id")
            return {
                "model": "GLM-OCR",
                "md_results": f"# OCR {start}-{end}",
                "request_id": f"req_{start}_{end}",
                "data_info": {"num_pages": end - start + 1},
                "usage": {"total_tokens": 10},
            }

    def fake_post(url: str, **kwargs: Any) -> _Response:
        payload = kwargs["json"]
        captured.append(payload)
        return _Response(payload)

    monkeypatch.setattr("httpx.post", fake_post)

    page_selection = mod._parse_page_selection(page_range="1-205", start_page=None, end_page=None)
    assert not isinstance(page_selection, dict)

    result = mod._zhipu_ocr_backend(
        pdf,
        model="glm-ocr",
        timeout_s=30,
        page_selection=page_selection,
        page_chunk_size=100,
    )

    assert not isinstance(result, dict)
    assert [(p["start_page_id"], p["end_page_id"]) for p in captured] == [
        (1, 100),
        (101, 200),
        (201, 205),
    ]
    assert result.metadata["page_chunk_count"] == 3
    assert "# OCR 201-205" in result.markdown
    assert result.raw_response["chunks"][0]["page_range"] == "1-100"


def test_zhipu_all_pages_requires_known_page_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = _fake_pdf(tmp_path)
    monkeypatch.setenv("ZAI_API_KEY", "test-key")
    monkeypatch.setattr(mod.importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr(mod, "_pdf_page_count", lambda path: None)

    class _Settings:
        zai_api_key = ""

    monkeypatch.setattr("core.config.settings", _Settings())

    result = mod._zhipu_ocr_backend(
        pdf,
        model="glm-ocr",
        timeout_s=30,
        page_selection=mod._PageSelection(),
        page_chunk_size=100,
    )

    assert isinstance(result, dict)
    assert result["error_type"] == "validation"
    assert "bounded page_range" in result["hint"]


def test_document_ingest_is_wired() -> None:
    tools = json.loads(DEFINITIONS.read_text(encoding="utf-8"))
    definition = next(t for t in tools if t.get("name") == "document_ingest")
    assert definition["cost_tier"] == "expensive"
    assert "openai_pdf" in definition["input_schema"]["properties"]["backend"]["enum"]
    assert "page_range" in definition["input_schema"]["properties"]
    assert definition["input_schema"]["properties"]["page_chunk_size"]["minimum"] == 1
    assert "claude_pdf" in definition["description"]
    assert "zhipu_ocr" in definition["description"]

    from core.agent.safety import WRITE_TOOLS
    from core.cli.tool_handlers.delegated import _DELEGATED_TOOLS

    assert _DELEGATED_TOOLS["document_ingest"] == (
        "core.tools.document_ingest",
        "DocumentIngestTool",
    )
    assert "document_ingest" in WRITE_TOOLS
