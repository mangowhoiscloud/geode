"""PDF document ingest tool.

Builds a GEODE-readable bundle from a local PDF by either extracting an
embedded text layer locally or asking one provider-specific PDF API to parse it.
"""

from __future__ import annotations

import asyncio
import base64
import importlib.util
import json
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
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
_OPENAI_FILE_LIMIT_BYTES = 50_000_000
_CLAUDE_MESSAGES_REQUEST_LIMIT_BYTES = 32_000_000
_ZHIPU_FILE_LIMIT_BYTES = 50_000_000
_ZHIPU_DEFAULT_PAGE_CHUNK_SIZE = 100
_ZHIPU_FALLBACK_PAGE_CHUNK_SIZE = 30
_PAGE_RANGE_RE = re.compile(r"^\s*(\d+)(?:\s*-\s*(\d+))?\s*$")


@dataclass(slots=True)
class _IngestedDocument:
    backend: str
    markdown: str
    pages: list[str]
    metadata: dict[str, Any] = field(default_factory=dict)
    raw_response: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class _PageSelection:
    ranges: tuple[tuple[int, int | None], ...] = ()

    @property
    def is_all(self) -> bool:
        return not self.ranges

    @property
    def is_bounded(self) -> bool:
        return all(end is not None for _, end in self.ranges)

    def label(self) -> str:
        if self.is_all:
            return "all"
        labels = [
            str(start) if end == start else f"{start}-{end or ''}" for start, end in self.ranges
        ]
        return ",".join(labels)


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
                "page_range": {
                    "type": "string",
                    "description": (
                        "Optional 1-indexed PDF page range, e.g. '1-100' or "
                        "'1-25,40,80-120'. GEODE accepts wide ranges and "
                        "applies provider-specific chunking where needed."
                    ),
                },
                "page_chunk_size": {
                    "type": "integer",
                    "minimum": 1,
                    "description": (
                        "Optional provider chunk size in pages. Zhipu defaults "
                        "to 100 pages per request, with a 30-page retry fallback."
                    ),
                },
                "start_page": {
                    "type": "integer",
                    "description": (
                        "Deprecated compatibility alias for page_range. First PDF page, 1-indexed."
                    ),
                },
                "end_page": {
                    "type": "integer",
                    "description": (
                        "Deprecated compatibility alias for page_range. Last PDF page, 1-indexed."
                    ),
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
        page_selection = _parse_page_selection(
            page_range=kwargs.get("page_range"),
            start_page=kwargs.get("start_page"),
            end_page=kwargs.get("end_page"),
        )
        if isinstance(page_selection, dict):
            return page_selection
        page_chunk_size = _parse_optional_positive_int(
            kwargs.get("page_chunk_size"), "page_chunk_size"
        )
        if isinstance(page_chunk_size, dict):
            return page_chunk_size
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
            page_selection=page_selection,
            page_chunk_size=page_chunk_size,
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
                        page_selection=page_selection,
                        page_chunk_size=page_chunk_size,
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
                    page_selection=page_selection,
                    page_chunk_size=page_chunk_size,
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


def _parse_page_selection(
    *, page_range: Any, start_page: Any, end_page: Any
) -> _PageSelection | dict[str, Any]:
    raw_range = str(page_range or "").strip()
    if raw_range:
        ranges: list[tuple[int, int]] = []
        for segment in raw_range.split(","):
            match = _PAGE_RANGE_RE.match(segment)
            if not match:
                return tool_error(
                    f"Invalid page_range segment: {segment.strip()!r}",
                    error_type="validation",
                    hint="Use 1-indexed ranges like '1-25,40,80-120'.",
                )
            start = int(match.group(1))
            end = int(match.group(2) or start)
            if start < 1 or end < 1:
                return tool_error(
                    "PDF page numbers are 1-indexed and must be positive.",
                    error_type="validation",
                )
            if end < start:
                return tool_error(
                    f"Invalid page_range segment: {segment.strip()!r}",
                    error_type="validation",
                    hint="Range end must be greater than or equal to range start.",
                )
            ranges.append((start, end))
        return _PageSelection(tuple(_merge_page_ranges(ranges)))

    start_value = _parse_optional_positive_int(start_page, "start_page")
    if isinstance(start_value, dict):
        return start_value
    end_value = _parse_optional_positive_int(end_page, "end_page")
    if isinstance(end_value, dict):
        return end_value
    if start_value is None and end_value is None:
        return _PageSelection()
    start = 1 if start_value is None else start_value
    if end_value is not None and end_value < start:
        return tool_error(
            "end_page must be greater than or equal to start_page.",
            error_type="validation",
        )
    return _PageSelection(((start, end_value),))


def _merge_page_ranges(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted(ranges):
        if not merged or start > merged[-1][1] + 1:
            merged.append((start, end))
            continue
        prev_start, prev_end = merged[-1]
        merged[-1] = (prev_start, max(prev_end, end))
    return merged


def _selection_page_count(
    selection: _PageSelection, *, total_pages: int | None = None
) -> int | None:
    if selection.is_all:
        return total_pages
    count = 0
    for start, end in selection.ranges:
        if end is None:
            if total_pages is None:
                return None
            end = total_pages
        count += max(0, end - start + 1)
    return count


def _bounded_ranges(
    selection: _PageSelection, *, total_pages: int | None = None
) -> list[tuple[int, int]]:
    if selection.is_all:
        if total_pages is None:
            return []
        return [(1, total_pages)]
    ranges: list[tuple[int, int]] = []
    for start, end in selection.ranges:
        if end is None:
            if total_pages is None:
                continue
            end = total_pages
        ranges.append((start, end))
    return ranges


def _split_ranges_by_size(ranges: list[tuple[int, int]], chunk_size: int) -> list[tuple[int, int]]:
    chunks: list[tuple[int, int]] = []
    for start, end in ranges:
        current = start
        while current <= end:
            chunk_end = min(end, current + chunk_size - 1)
            chunks.append((current, chunk_end))
            current = chunk_end + 1
    return chunks


def _run_backend(
    backend: str,
    *,
    pdf_path: Path,
    prompt: str,
    model: str,
    timeout_s: int,
    page_selection: _PageSelection,
    page_chunk_size: int | None,
) -> _IngestedDocument | dict[str, Any]:
    if backend == "local_text":
        return _local_text_backend(pdf_path, timeout_s=timeout_s, page_selection=page_selection)
    if backend == "openai_pdf":
        return _openai_pdf_backend(
            pdf_path,
            prompt=prompt,
            model=model,
            timeout_s=timeout_s,
            page_selection=page_selection,
        )
    if backend == "claude_pdf":
        return _claude_pdf_backend(
            pdf_path,
            prompt=prompt,
            model=model,
            timeout_s=timeout_s,
            page_selection=page_selection,
            page_chunk_size=page_chunk_size,
        )
    if backend == "zhipu_ocr":
        return _zhipu_ocr_backend(
            pdf_path,
            model=model or "glm-ocr",
            timeout_s=timeout_s,
            page_selection=page_selection,
            page_chunk_size=page_chunk_size or _ZHIPU_DEFAULT_PAGE_CHUNK_SIZE,
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


def _pdf_page_count(pdf_path: Path, *, timeout_s: int = 30) -> int | None:
    command = shutil.which("pdfinfo")
    if not command:
        return None
    try:
        proc = subprocess.run(  # noqa: S603
            [command, str(pdf_path)],
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout_s,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    for line in proc.stdout.splitlines():
        if line.lower().startswith("pages:"):
            try:
                return int(line.split(":", 1)[1].strip())
            except ValueError:
                return None
    return None


@contextmanager
def _selected_pdf_path(pdf_path: Path, page_selection: _PageSelection) -> Iterator[Path]:
    if page_selection.is_all:
        yield pdf_path
        return
    if not page_selection.is_bounded:
        raise RuntimeError("page_range must be bounded for OpenAI/Claude PDF slicing")
    pdfseparate = _require_command("pdfseparate")
    pdfunite = _require_command("pdfunite")
    if isinstance(pdfseparate, dict) or isinstance(pdfunite, dict):
        raise RuntimeError(
            "page_range for OpenAI/Claude requires poppler's pdfseparate and pdfunite commands"
        )
    with tempfile.TemporaryDirectory(prefix="geode-pdf-slice-") as tmp:
        tmp_dir = Path(tmp)
        page_paths: list[Path] = []
        for start, end in _bounded_ranges(page_selection):
            for page_num in range(start, end + 1):
                page_path = tmp_dir / f"page-{page_num:06d}.pdf"
                proc = subprocess.run(  # noqa: S603
                    [
                        pdfseparate,
                        "-f",
                        str(page_num),
                        "-l",
                        str(page_num),
                        str(pdf_path),
                        str(page_path),
                    ],
                    capture_output=True,
                    check=False,
                    text=True,
                    timeout=60,
                )
                if proc.returncode != 0:
                    raise RuntimeError(proc.stderr.strip() or proc.stdout.strip())
                page_paths.append(page_path)
        sliced_path = tmp_dir / "selection.pdf"
        proc = subprocess.run(  # noqa: S603
            [pdfunite, *[str(path) for path in page_paths], str(sliced_path)],
            capture_output=True,
            check=False,
            text=True,
            timeout=120,
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or proc.stdout.strip())
        yield sliced_path


def _local_text_backend(
    pdf_path: Path, *, timeout_s: int, page_selection: _PageSelection
) -> _IngestedDocument | dict[str, Any]:
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
    page_numbers = list(range(1, len(pages) + 1))
    if not page_selection.is_all:
        pages, page_numbers = _select_extracted_pages(pages, page_selection)
    warnings = []
    if not text.strip():
        warnings.append("local_text produced no text; this PDF may be scanned.")
    return _IngestedDocument(
        backend="local_text",
        markdown=_pages_to_markdown(pages, page_numbers=page_numbers),
        pages=pages,
        metadata={
            "extractor": "pdftotext",
            "page_count": len(pages),
            "requested_page_range": page_selection.label(),
            "page_numbers": page_numbers,
        },
        warnings=warnings,
    )


def _openai_pdf_backend(
    pdf_path: Path, *, prompt: str, model: str, timeout_s: int, page_selection: _PageSelection
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
    try:
        with _selected_pdf_path(pdf_path, page_selection) as selected_pdf:
            if selected_pdf.stat().st_size > _OPENAI_FILE_LIMIT_BYTES:
                return tool_error(
                    "OpenAI PDF input exceeds the 50 MB file-input limit",
                    error_type="validation",
                    hint=(
                        "Use local_text, narrow page_range, or split the PDF "
                        "before using openai_pdf."
                    ),
                    context={
                        "file_size_bytes": selected_pdf.stat().st_size,
                        "limit_bytes": _OPENAI_FILE_LIMIT_BYTES,
                        "page_range": page_selection.label(),
                    },
                )
            client = openai.OpenAI(api_key=api_key, timeout=timeout_s, max_retries=0)
            file_data = _pdf_data_uri(selected_pdf)
            filename = (
                pdf_path.name
                if page_selection.is_all
                else f"{pdf_path.stem}-{page_selection.label()}.pdf"
            )
            response = client.responses.create(
                model=model or OPENAI_PRIMARY,
                input=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_file",
                                "filename": filename,
                                "file_data": file_data,
                            },
                            {"type": "input_text", "text": prompt},
                        ],
                    }
                ],
            )
    except RuntimeError as exc:
        return tool_error(
            f"OpenAI PDF page selection failed: {exc}",
            error_type="dependency",
            hint="Install poppler tools or use local_text/zhipu_ocr for page-range extraction.",
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
        warnings=(
            []
            if page_selection.is_all
            else [f"OpenAI PDF input used page_range={page_selection.label()}"]
        ),
        raw_response=raw,
    )


def _claude_pdf_backend(
    pdf_path: Path,
    *,
    prompt: str,
    model: str,
    timeout_s: int,
    page_selection: _PageSelection,
    page_chunk_size: int | None,
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
    effective_model = model or ANTHROPIC_PRIMARY
    page_limit = _claude_pdf_page_limit(effective_model)
    total_pages = _pdf_page_count(pdf_path)
    requested_pages = _selection_page_count(page_selection, total_pages=total_pages)
    if page_selection.is_all and requested_pages is not None and requested_pages > page_limit:
        return tool_error(
            f"Claude PDF input exceeds the {page_limit}-page request limit for {effective_model}",
            error_type="validation",
            hint="Provide page_range so GEODE can split the PDF into Claude-sized sections.",
            context={
                "page_count": requested_pages,
                "page_limit": page_limit,
                "model": effective_model,
            },
        )

    if page_selection.is_all or (requested_pages is not None and requested_pages <= page_limit):
        selections = [page_selection]
    else:
        ranges = _bounded_ranges(page_selection, total_pages=total_pages)
        if not ranges:
            return tool_error(
                "Claude PDF page_range must be bounded when splitting is required.",
                error_type="validation",
                hint="Use a bounded page_range such as '1-600'.",
            )
        chunk_size = min(page_chunk_size or page_limit, page_limit)
        selections = [
            _PageSelection((chunk,)) for chunk in _split_ranges_by_size(ranges, chunk_size)
        ]

    client = anthropic.Anthropic(api_key=api_key, timeout=timeout_s, max_retries=0)
    documents: list[_IngestedDocument] = []
    for selection in selections:
        single = _claude_pdf_single_request(
            client=client,
            pdf_path=pdf_path,
            prompt=prompt,
            model=effective_model,
            selection=selection,
        )
        if isinstance(single, dict):
            return single
        documents.append(single)

    if len(documents) == 1:
        return documents[0]

    markdown_parts = []
    raw_chunks = []
    for doc, selection in zip(documents, selections, strict=True):
        markdown_parts.append(f"<!-- Claude PDF pages {selection.label()} -->\n\n{doc.markdown}")
        raw_chunks.append(
            {
                "page_range": selection.label(),
                "metadata": doc.metadata,
                "raw_response": doc.raw_response,
            }
        )
    return _IngestedDocument(
        backend="claude_pdf",
        markdown="\n\n".join(markdown_parts),
        pages=[doc.markdown for doc in documents],
        metadata={
            "model": effective_model,
            "requested_page_range": page_selection.label(),
            "page_chunk_count": len(documents),
            "page_limit": page_limit,
            "page_count": requested_pages,
        },
        raw_response={"chunks": raw_chunks},
        warnings=[f"Claude PDF input split into {len(documents)} page chunks."],
    )


def _claude_pdf_single_request(
    *,
    client: Any,
    pdf_path: Path,
    prompt: str,
    model: str,
    selection: _PageSelection,
) -> _IngestedDocument | dict[str, Any]:
    try:
        with _selected_pdf_path(pdf_path, selection) as selected_pdf:
            encoded_size = len(_pdf_base64(selected_pdf))
            if encoded_size > _CLAUDE_MESSAGES_REQUEST_LIMIT_BYTES:
                return tool_error(
                    (
                        "Claude PDF input may exceed the 32 MB Messages "
                        "request limit after base64 encoding"
                    ),
                    error_type="validation",
                    hint=(
                        "Narrow page_range, lower page_chunk_size, or use "
                        "Claude Files API outside document_ingest."
                    ),
                    context={
                        "base64_bytes": encoded_size,
                        "request_limit_bytes": _CLAUDE_MESSAGES_REQUEST_LIMIT_BYTES,
                        "page_range": selection.label(),
                    },
                )
            response = client.messages.create(
                model=model,
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
                                    "data": _pdf_base64(selected_pdf),
                                },
                            },
                            {"type": "text", "text": prompt},
                        ],
                    }
                ],
            )
    except RuntimeError as exc:
        return tool_error(
            f"Claude PDF page selection failed: {exc}",
            error_type="dependency",
            hint="Install poppler tools or use local_text/zhipu_ocr for page-range extraction.",
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
        metadata={"model": model, "requested_page_range": selection.label()},
        raw_response=raw,
    )


def _claude_pdf_page_limit(model: str) -> int:
    lower = model.lower()
    one_m_markers = (
        "claude-fable-5",
        "claude-mythos-5",
        "claude-mythos-preview",
        "claude-sonnet-5",
        "claude-opus-4-8",
        "claude-opus-4-7",
        "claude-opus-4-6",
        "claude-sonnet-4-6",
    )
    return 600 if lower.startswith(one_m_markers) else 100


def _zhipu_ocr_backend(
    pdf_path: Path,
    *,
    model: str,
    timeout_s: int,
    page_selection: _PageSelection,
    page_chunk_size: int,
) -> _IngestedDocument | dict[str, Any]:
    if importlib.util.find_spec("httpx") is None:
        return tool_error("httpx not installed", error_type="dependency")
    from core.config import settings

    api_key = settings.zai_api_key or os.environ.get("ZAI_API_KEY", "")
    if not api_key:
        return tool_error(
            "ZAI_API_KEY is not configured",
            error_type="dependency",
            hint="Set ZAI_API_KEY or choose another backend.",
        )

    if pdf_path.stat().st_size > _ZHIPU_FILE_LIMIT_BYTES:
        return tool_error(
            "Zhipu GLM-OCR input exceeds the 50 MB PDF limit",
            error_type="validation",
            hint="Use local_text, compress the PDF, or split the PDF before using zhipu_ocr.",
            context={
                "file_size_bytes": pdf_path.stat().st_size,
                "limit_bytes": _ZHIPU_FILE_LIMIT_BYTES,
            },
        )

    total_pages = _pdf_page_count(pdf_path)
    ranges = _bounded_ranges(page_selection, total_pages=total_pages)
    if page_selection.is_all and total_pages is not None:
        ranges = [(1, total_pages)]
    elif page_selection.is_all and total_pages is None:
        return tool_error(
            "Zhipu GLM-OCR requires a known page count for all-page ingest.",
            error_type="validation",
            hint=("Install poppler pdfinfo or provide a bounded page_range such as '1-100'."),
        )

    if not ranges:
        data = _zhipu_ocr_request(
            api_key=api_key,
            pdf_path=pdf_path,
            model=model,
            timeout_s=timeout_s,
            start_page=None if page_selection.is_all else page_selection.ranges[0][0],
            end_page=None if page_selection.is_all else page_selection.ranges[0][1],
        )
        if isinstance(data, dict) and "error" in data:
            return data
        return _zhipu_document_from_response(data, model=model, page_range=page_selection.label())

    chunks = _split_ranges_by_size(ranges, max(1, page_chunk_size))
    documents: list[_IngestedDocument] = []
    raw_chunks: list[dict[str, Any]] = []
    for start, end in chunks:
        data = _zhipu_ocr_request(
            api_key=api_key,
            pdf_path=pdf_path,
            model=model,
            timeout_s=timeout_s,
            start_page=start,
            end_page=end,
        )
        if (
            isinstance(data, dict)
            and "error" in data
            and (end - start + 1) > _ZHIPU_FALLBACK_PAGE_CHUNK_SIZE
        ):
            for retry_start, retry_end in _split_ranges_by_size(
                [(start, end)], _ZHIPU_FALLBACK_PAGE_CHUNK_SIZE
            ):
                retry_data = _zhipu_ocr_request(
                    api_key=api_key,
                    pdf_path=pdf_path,
                    model=model,
                    timeout_s=timeout_s,
                    start_page=retry_start,
                    end_page=retry_end,
                )
                if isinstance(retry_data, dict) and "error" in retry_data:
                    return retry_data
                documents.append(
                    _zhipu_document_from_response(
                        retry_data,
                        model=model,
                        page_range=f"{retry_start}-{retry_end}",
                    )
                )
                raw_chunks.append(
                    {
                        "page_range": f"{retry_start}-{retry_end}",
                        "fallback_chunk_size": _ZHIPU_FALLBACK_PAGE_CHUNK_SIZE,
                        "raw_response": retry_data,
                    }
                )
            continue
        if isinstance(data, dict) and "error" in data:
            return data
        documents.append(
            _zhipu_document_from_response(data, model=model, page_range=f"{start}-{end}")
        )
        raw_chunks.append({"page_range": f"{start}-{end}", "raw_response": data})

    if len(documents) == 1:
        document = documents[0]
        document.metadata["requested_page_range"] = page_selection.label()
        document.metadata["page_chunk_size"] = page_chunk_size
        return document

    markdown_parts = []
    total_usage: dict[str, int] = {}
    for doc, chunk in zip(documents, raw_chunks, strict=True):
        markdown_parts.append(
            f"<!-- Zhipu GLM-OCR pages {chunk['page_range']} -->\n\n{doc.markdown}"
        )
        usage = doc.metadata.get("usage", {})
        if isinstance(usage, dict):
            for key, value in usage.items():
                if isinstance(value, int):
                    total_usage[key] = total_usage.get(key, 0) + value
    return _IngestedDocument(
        backend="zhipu_ocr",
        markdown="\n\n".join(markdown_parts),
        pages=[doc.markdown for doc in documents],
        metadata={
            "model": model,
            "requested_page_range": page_selection.label(),
            "page_count": _selection_page_count(page_selection, total_pages=total_pages),
            "page_chunk_size": page_chunk_size,
            "page_chunk_count": len(documents),
            "usage": total_usage,
        },
        raw_response={"chunks": raw_chunks},
        warnings=[f"Zhipu GLM-OCR input split into {len(documents)} page chunks."],
    )


def _zhipu_ocr_request(
    *,
    api_key: str,
    pdf_path: Path,
    model: str,
    timeout_s: int,
    start_page: int | None,
    end_page: int | None,
) -> dict[str, Any]:
    import httpx

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
    return data if isinstance(data, dict) else {}


def _zhipu_document_from_response(
    data: dict[str, Any], *, model: str, page_range: str
) -> _IngestedDocument:
    markdown = str(data.get("md_results") or "")
    return _IngestedDocument(
        backend="zhipu_ocr",
        markdown=markdown,
        pages=[markdown] if markdown else [],
        metadata={
            "model": data.get("model") or model,
            "request_id": data.get("request_id", ""),
            "requested_page_range": page_range,
            "data_info": data.get("data_info", {}),
            "usage": data.get("usage", {}),
        },
        raw_response=data,
    )


def _parse_optional_positive_int(value: Any, field_name: str) -> int | None | dict[str, Any]:
    if value is None or value == "":
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return tool_error(
            f"{field_name} must be an integer.",
            error_type="validation",
            context={field_name: value},
        )
    if parsed < 1:
        return tool_error(
            f"{field_name} must be greater than or equal to 1.",
            error_type="validation",
            context={field_name: value},
        )
    return parsed


def _pdf_base64(pdf_path: Path) -> str:
    return base64.b64encode(pdf_path.read_bytes()).decode("ascii")


def _pdf_data_uri(pdf_path: Path) -> str:
    return f"data:application/pdf;base64,{_pdf_base64(pdf_path)}"


def _split_pages(text: str) -> list[str]:
    pages = text.split("\f")
    if pages and pages[-1].strip() == "":
        pages = pages[:-1]
    return [page.strip() for page in pages]


def _select_extracted_pages(
    pages: list[str], selection: _PageSelection
) -> tuple[list[str], list[int]]:
    selected_pages: list[str] = []
    selected_numbers: list[int] = []
    total = len(pages)
    for start, end in _bounded_ranges(selection, total_pages=total):
        for page_num in range(start, min(end, total) + 1):
            selected_pages.append(pages[page_num - 1])
            selected_numbers.append(page_num)
    return selected_pages, selected_numbers


def _pages_to_markdown(pages: list[str], *, page_numbers: list[int] | None = None) -> str:
    if not pages:
        return ""
    numbers = page_numbers or list(range(1, len(pages) + 1))
    return "\n\n".join(
        f"## Page {number}\n\n{page}" for number, page in zip(numbers, pages, strict=True)
    )


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
