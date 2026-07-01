"""PDF document ingest tool.

Builds a GEODE-readable bundle from a local PDF by either extracting an
embedded text layer locally or asking one provider-specific PDF API to parse it.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.paths import get_project_root
from core.tools.base import tool_error
from core.tools.sandbox import validate_path

_BACKENDS = frozenset({"auto", "local_text", "openai_pdf", "claude_pdf", "zhipu_ocr"})
_PROVIDER_BACKENDS = frozenset({"openai_pdf", "claude_pdf", "zhipu_ocr"})
_DEFAULT_PROMPT = (
    "Extract the document into clean Markdown. Preserve headings, lists, tables, "
    "figures, equations, and page-relevant structure where possible."
)
_DOC_ID_SAFE = re.compile(r"[^a-zA-Z0-9._-]+")


@dataclass(slots=True)
class _IngestedDocument:
    backend: str
    markdown: str
    pages: list[str]
    metadata: dict[str, Any] = field(default_factory=dict)
    raw_response: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


class DocumentIngestTool:
    """Ingest a PDF into a manifest + Markdown page bundle."""

    category = "discovery"
    cost_tier = "expensive"

    @property
    def name(self) -> str:
        return "document_ingest"

    @property
    def description(self) -> str:
        return (
            "Ingest a local PDF into a GEODE-readable bundle. Supports local "
            "text-layer extraction plus provider-native OpenAI PDF, Claude PDF, "
            "and Zhipu GLM-OCR backends."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to a local PDF inside the GEODE file sandbox.",
                },
                "backend": {
                    "type": "string",
                    "enum": sorted(_BACKENDS),
                    "description": (
                        "Backend to use. auto tries local text first, then the "
                        "current provider family if local extraction is empty."
                    ),
                },
                "task_prompt": {
                    "type": "string",
                    "description": "Provider prompt for PDF parsing/extraction.",
                },
                "model": {
                    "type": "string",
                    "description": "Provider model override for OpenAI or Claude backends.",
                },
                "doc_id": {
                    "type": "string",
                    "description": "Optional stable output bundle id.",
                },
                "output_dir": {
                    "type": "string",
                    "description": (
                        "Optional output directory. Defaults to "
                        ".geode/documents/<doc_id> under the project root."
                    ),
                },
                "start_page": {
                    "type": "integer",
                    "description": "First PDF page for Zhipu GLM-OCR, 1-indexed.",
                },
                "end_page": {
                    "type": "integer",
                    "description": "Last PDF page for Zhipu GLM-OCR, 1-indexed.",
                },
                "timeout_s": {
                    "type": "integer",
                    "description": "Backend timeout in seconds. Default: 300.",
                },
            },
            "required": ["file_path"],
        }

    async def aexecute(self, **kwargs: Any) -> dict[str, Any]:
        return await asyncio.to_thread(self._execute_sync, **kwargs)

    def _execute_sync(self, **kwargs: Any) -> dict[str, Any]:
        backend = str(kwargs.get("backend") or "auto")
        if backend not in _BACKENDS:
            return tool_error(
                f"Unsupported document_ingest backend: {backend}",
                error_type="validation",
                hint=f"Use one of: {', '.join(sorted(_BACKENDS))}.",
            )

        path_result = validate_path(str(kwargs["file_path"]), write=False)
        if isinstance(path_result, dict):
            return path_result
        pdf_path = path_result
        err = _validate_pdf_path(pdf_path)
        if err:
            return err

        prompt = str(kwargs.get("task_prompt") or _DEFAULT_PROMPT)
        timeout_s = int(kwargs.get("timeout_s") or 300)
        doc_id = _doc_id(kwargs.get("doc_id"), pdf_path)
        output_dir_result = _resolve_output_dir(kwargs.get("output_dir"), doc_id)
        if isinstance(output_dir_result, dict):
            return output_dir_result
        output_dir = output_dir_result

        selected = _select_backend(backend, kwargs.get("_tool_context"))
        extracted = _run_backend(
            selected,
            pdf_path=pdf_path,
            prompt=prompt,
            model=str(kwargs.get("model") or ""),
            timeout_s=timeout_s,
            start_page=kwargs.get("start_page"),
            end_page=kwargs.get("end_page"),
        )
        if isinstance(extracted, dict):
            if backend == "auto" and selected == "local_text":
                fallback = _select_provider_backend(kwargs.get("_tool_context"))
                if fallback:
                    extracted = _run_backend(
                        fallback,
                        pdf_path=pdf_path,
                        prompt=prompt,
                        model=str(kwargs.get("model") or ""),
                        timeout_s=timeout_s,
                        start_page=kwargs.get("start_page"),
                        end_page=kwargs.get("end_page"),
                    )
            if isinstance(extracted, dict):
                return extracted
        if backend == "auto" and selected == "local_text" and not extracted.markdown.strip():
            fallback = _select_provider_backend(kwargs.get("_tool_context"))
            if fallback:
                provider_result = _run_backend(
                    fallback,
                    pdf_path=pdf_path,
                    prompt=prompt,
                    model=str(kwargs.get("model") or ""),
                    timeout_s=timeout_s,
                    start_page=kwargs.get("start_page"),
                    end_page=kwargs.get("end_page"),
                )
                if not isinstance(provider_result, dict):
                    extracted = provider_result

        bundle = _write_bundle(
            output_dir=output_dir,
            doc_id=doc_id,
            pdf_path=pdf_path,
            prompt=prompt,
            document=extracted,
        )
        return {"result": bundle}


def _validate_pdf_path(pdf_path: Path) -> dict[str, Any] | None:
    if not pdf_path.exists():
        return tool_error(
            f"PDF not found: {pdf_path}",
            error_type="not_found",
            context={"file_path": str(pdf_path)},
        )
    if not pdf_path.is_file():
        return tool_error(
            f"Not a file: {pdf_path}",
            error_type="validation",
            context={"file_path": str(pdf_path)},
        )
    if pdf_path.suffix.lower() != ".pdf":
        return tool_error(
            f"document_ingest only accepts PDF files: {pdf_path.name}",
            error_type="validation",
            hint="Provide a .pdf file.",
        )
    return None


def _doc_id(raw: Any, pdf_path: Path) -> str:
    base = str(raw or pdf_path.stem).strip() or "document"
    clean = _DOC_ID_SAFE.sub("-", base).strip(".-")
    return clean[:80] or "document"


def _resolve_output_dir(raw: Any, doc_id: str) -> Path | dict[str, Any]:
    if raw:
        result = validate_path(str(raw), write=True)
        if isinstance(result, dict):
            return result
        return result
    return get_project_root() / ".geode" / "documents" / doc_id


def _select_backend(backend: str, tool_context: Any) -> str:
    if backend != "auto":
        return backend
    if _has_command("pdftotext"):
        return "local_text"
    return _select_provider_backend(tool_context) or "local_text"


def _select_provider_backend(tool_context: Any) -> str:
    provider = str(getattr(tool_context, "provider", "") or "").lower()
    model = str(getattr(tool_context, "model", "") or "").lower()
    if provider in {"openai", "openai-codex"} or model.startswith(("gpt-", "o3", "o4")):
        return "openai_pdf"
    if provider == "anthropic" or model.startswith("claude-"):
        return "claude_pdf"
    if provider in {"glm", "glm-coding"} or model.startswith("glm-"):
        return "zhipu_ocr"
    return ""


def _run_backend(
    backend: str,
    *,
    pdf_path: Path,
    prompt: str,
    model: str,
    timeout_s: int,
    start_page: Any,
    end_page: Any,
) -> _IngestedDocument | dict[str, Any]:
    if backend == "local_text":
        return _local_text_backend(pdf_path, timeout_s=timeout_s)
    if backend == "openai_pdf":
        return _openai_pdf_backend(pdf_path, prompt=prompt, model=model, timeout_s=timeout_s)
    if backend == "claude_pdf":
        return _claude_pdf_backend(pdf_path, prompt=prompt, model=model, timeout_s=timeout_s)
    if backend == "zhipu_ocr":
        return _zhipu_ocr_backend(
            pdf_path,
            model=model or "glm-ocr",
            timeout_s=timeout_s,
            start_page=_optional_int(start_page),
            end_page=_optional_int(end_page),
        )
    return tool_error(f"Unsupported backend: {backend}", error_type="validation")


def _has_command(name: str) -> bool:
    return shutil.which(name) is not None


def _require_command(name: str) -> str | dict[str, Any]:
    command = shutil.which(name)
    if not command:
        return tool_error(
            f"Required command not found: {name}",
            error_type="dependency",
            hint=f"Install {name} or choose a provider PDF backend.",
        )
    return command


def _local_text_backend(pdf_path: Path, *, timeout_s: int) -> _IngestedDocument | dict[str, Any]:
    command = _require_command("pdftotext")
    if isinstance(command, dict):
        return command
    with tempfile.TemporaryDirectory(prefix="geode-pdf-") as tmp:
        out_path = Path(tmp) / "document.txt"
        try:
            proc = subprocess.run(  # noqa: S603
                [command, "-enc", "UTF-8", str(pdf_path), str(out_path)],
                capture_output=True,
                check=False,
                text=True,
                timeout=timeout_s,
            )
        except subprocess.TimeoutExpired:
            return tool_error(
                f"pdftotext timed out after {timeout_s}s",
                error_type="timeout",
                hint="Try a provider PDF backend or split the PDF.",
            )
        if proc.returncode != 0:
            return tool_error(
                f"pdftotext failed: {proc.stderr.strip() or proc.stdout.strip()}",
                error_type="dependency",
                hint="Try a provider PDF backend for scanned or malformed PDFs.",
            )
        text = out_path.read_text(encoding="utf-8", errors="replace")
    pages = _split_pages(text)
    warnings = []
    if not text.strip():
        warnings.append("local_text produced no text; this PDF may be scanned.")
    return _IngestedDocument(
        backend="local_text",
        markdown=_pages_to_markdown(pages),
        pages=pages,
        metadata={"extractor": "pdftotext", "page_count": len(pages)},
        warnings=warnings,
    )


def _openai_pdf_backend(
    pdf_path: Path, *, prompt: str, model: str, timeout_s: int
) -> _IngestedDocument | dict[str, Any]:
    try:
        import openai
    except ImportError:
        return tool_error("openai SDK not installed", error_type="dependency")
    from core.config import OPENAI_PRIMARY, settings

    api_key = settings.openai_api_key or os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        return tool_error(
            "OPENAI_API_KEY is not configured",
            error_type="dependency",
            hint="Set OPENAI_API_KEY or choose another backend.",
        )
    client = openai.OpenAI(api_key=api_key, timeout=timeout_s, max_retries=0)
    file_data = _pdf_data_uri(pdf_path)
    try:
        response = client.responses.create(
            model=model or OPENAI_PRIMARY,
            input=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_file",
                            "filename": pdf_path.name,
                            "file_data": file_data,
                        },
                        {"type": "input_text", "text": prompt},
                    ],
                }
            ],
        )
    except Exception as exc:
        return tool_error(
            f"OpenAI PDF ingest failed: {exc}",
            error_type="connection",
            hint="Try local_text, split the PDF, or verify the model supports PDF input.",
        )
    text = str(getattr(response, "output_text", "") or "")
    raw = _model_dump(response)
    return _IngestedDocument(
        backend="openai_pdf",
        markdown=text,
        pages=[text] if text else [],
        metadata={"model": model or OPENAI_PRIMARY},
        raw_response=raw,
    )


def _claude_pdf_backend(
    pdf_path: Path, *, prompt: str, model: str, timeout_s: int
) -> _IngestedDocument | dict[str, Any]:
    try:
        import anthropic
    except ImportError:
        return tool_error("anthropic SDK not installed", error_type="dependency")
    from core.config import ANTHROPIC_PRIMARY, settings

    api_key = settings.anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return tool_error(
            "ANTHROPIC_API_KEY is not configured",
            error_type="dependency",
            hint="Set ANTHROPIC_API_KEY or choose another backend.",
        )
    client = anthropic.Anthropic(api_key=api_key, timeout=timeout_s, max_retries=0)
    try:
        response = client.messages.create(
            model=model or ANTHROPIC_PRIMARY,
            max_tokens=8192,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "document",
                            "source": {
                                "type": "base64",
                                "media_type": "application/pdf",
                                "data": _pdf_base64(pdf_path),
                            },
                        },
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        )
    except Exception as exc:
        return tool_error(
            f"Claude PDF ingest failed: {exc}",
            error_type="connection",
            hint="Try local_text, split the PDF, or verify the model supports PDF input.",
        )
    text = _anthropic_text(response)
    raw = _model_dump(response)
    return _IngestedDocument(
        backend="claude_pdf",
        markdown=text,
        pages=[text] if text else [],
        metadata={"model": model or ANTHROPIC_PRIMARY},
        raw_response=raw,
    )


def _zhipu_ocr_backend(
    pdf_path: Path,
    *,
    model: str,
    timeout_s: int,
    start_page: int | None,
    end_page: int | None,
) -> _IngestedDocument | dict[str, Any]:
    try:
        import httpx
    except ImportError:
        return tool_error("httpx not installed", error_type="dependency")
    from core.config import settings

    api_key = settings.zai_api_key or os.environ.get("ZAI_API_KEY", "")
    if not api_key:
        return tool_error(
            "ZAI_API_KEY is not configured",
            error_type="dependency",
            hint="Set ZAI_API_KEY or choose another backend.",
        )
    payload: dict[str, Any] = {"model": model or "glm-ocr", "file": _pdf_data_uri(pdf_path)}
    if start_page is not None:
        payload["start_page_id"] = start_page
    if end_page is not None:
        payload["end_page_id"] = end_page
    try:
        response = httpx.post(
            "https://api.z.ai/api/paas/v4/layout_parsing",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=timeout_s,
        )
        response.raise_for_status()
    except Exception as exc:
        return tool_error(
            f"Zhipu GLM-OCR ingest failed: {exc}",
            error_type="connection",
            hint="Try local_text, split the PDF, or check ZAI_API_KEY and GLM-OCR limits.",
        )
    data = response.json()
    markdown = str(data.get("md_results") or "")
    return _IngestedDocument(
        backend="zhipu_ocr",
        markdown=markdown,
        pages=[markdown] if markdown else [],
        metadata={
            "model": data.get("model") or model,
            "request_id": data.get("request_id", ""),
            "data_info": data.get("data_info", {}),
            "usage": data.get("usage", {}),
        },
        raw_response=data if isinstance(data, dict) else {},
    )


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _pdf_base64(pdf_path: Path) -> str:
    return base64.b64encode(pdf_path.read_bytes()).decode("ascii")


def _pdf_data_uri(pdf_path: Path) -> str:
    return f"data:application/pdf;base64,{_pdf_base64(pdf_path)}"


def _split_pages(text: str) -> list[str]:
    pages = text.split("\f")
    if pages and pages[-1].strip() == "":
        pages = pages[:-1]
    return [page.strip() for page in pages]


def _pages_to_markdown(pages: list[str]) -> str:
    if not pages:
        return ""
    return "\n\n".join(f"## Page {index}\n\n{page}" for index, page in enumerate(pages, 1))


def _anthropic_text(response: Any) -> str:
    parts: list[str] = []
    for block in getattr(response, "content", []) or []:
        text = getattr(block, "text", None)
        if isinstance(text, str):
            parts.append(text)
    return "\n".join(parts)


def _model_dump(obj: Any) -> dict[str, Any]:
    if hasattr(obj, "model_dump"):
        dumped = obj.model_dump()
        return dumped if isinstance(dumped, dict) else {}
    if isinstance(obj, dict):
        return obj
    return {}


def _write_bundle(
    *,
    output_dir: Path,
    doc_id: str,
    pdf_path: Path,
    prompt: str,
    document: _IngestedDocument,
) -> dict[str, Any]:
    pages_dir = output_dir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    full_path = output_dir / "full.md"
    manifest_path = output_dir / "manifest.json"
    raw_path = output_dir / "raw_response.json"

    full_path.write_text(document.markdown, encoding="utf-8")
    page_paths = []
    for index, page in enumerate(document.pages, 1):
        page_path = pages_dir / f"page-{index:04d}.md"
        page_path.write_text(page, encoding="utf-8")
        page_paths.append(page_path)
    if document.raw_response:
        raw_path.write_text(
            json.dumps(document.raw_response, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    manifest = {
        "doc_id": doc_id,
        "source_path": str(pdf_path),
        "backend": document.backend,
        "created_at": datetime.now(UTC).isoformat(),
        "task_prompt": prompt,
        "page_count": len(document.pages),
        "chars": len(document.markdown),
        "words": len(document.markdown.split()),
        "full_text_path": str(full_path),
        "pages_dir": str(pages_dir),
        "page_paths": [str(path) for path in page_paths],
        "raw_response_path": str(raw_path) if document.raw_response else "",
        "metadata": document.metadata,
        "warnings": document.warnings,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "doc_id": doc_id,
        "backend": document.backend,
        "page_count": manifest["page_count"],
        "chars": manifest["chars"],
        "words": manifest["words"],
        "output_dir": str(output_dir),
        "manifest_path": str(manifest_path),
        "full_text_path": str(full_path),
        "pages_dir": str(pages_dir),
        "warnings": document.warnings,
    }
