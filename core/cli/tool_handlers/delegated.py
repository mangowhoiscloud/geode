"""Delegated tool handlers — registry-based lazy-import wrappers.

Maps tool name → (module_path, class_name) for lazy-import delegation.
Adding a new delegated tool requires only one line in ``_DELEGATED_TOOLS``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from core.cli.tool_handlers.clarification import _safe_delegate
from core.cli.tool_handlers.registration import UniqueEntries

_DELEGATED_TOOLS = UniqueEntries[str, tuple[str, str]](
    (
        # web / document / note
        ("web_fetch", ("core.tools.web_tools", "WebFetchTool")),
        # PR-LLMS-TXT-TOOL (2026-06-12) — structured /llms.txt index discovery
        ("llms_txt_index", ("core.tools.llms_txt", "LlmsTxtIndexTool")),
        (
            "general_web_search",
            ("core.tools.web_tools", "GeneralWebSearchTool"),
        ),
        # PR-BROWSER-CDP-BRIDGE — drive the operator's real Chrome over CDP
        # (login sessions / fingerprint preserved), unlike headless web_fetch.
        ("browser_scan", ("core.tools.browser_tools", "BrowserScanTool")),
        (
            "browser_execute_js",
            ("core.tools.browser_tools", "BrowserExecuteJsTool"),
        ),
        # PR-AX-UI-PROBE — structured macOS accessibility perception (a cheaper
        # first rung than a computer_use screenshot). macOS-only, soft pyobjc dep.
        ("ui_probe", ("core.tools.ui_probe", "UiProbeTool")),
        ("read_document", ("core.tools.document_tools", "ReadDocumentTool")),
        (
            "document_ingest",
            ("core.tools.document_ingest", "DocumentIngestTool"),
        ),
        ("glob_files", ("core.tools.file_tools", "GlobTool")),
        ("grep_files", ("core.tools.file_tools", "GrepTool")),
        ("edit_file", ("core.tools.file_tools", "EditFileTool")),
        ("write_file", ("core.tools.file_tools", "WriteFileTool")),
        ("note_save", ("core.tools.memory_tools", "NoteSaveTool")),
        ("note_read", ("core.tools.memory_tools", "NoteReadTool")),
        # CSP-2 (2026-05-22) — literature research surface
        ("arxiv_search", ("core.tools.arxiv", "ArxivSearchTool")),
        ("paper_fetch_arxiv", ("core.tools.arxiv", "ArxivFetchTool")),
        (
            "geode_seed_pool_search",
            (
                "plugins.seed_generation.tools.seed_pool_search",
                "SeedPoolSearchTool",
            ),
        ),
        # CSP-13 (2026-05-23) — Loop 2 (debate-turn) of the seed-generation
        # 3-loop port. Records one debate turn to a per-candidate sidecar
        # JSONL and signals continue/synthesize so the sub-agent's
        # AgenticLoop completes the N-turn budget before writing the seed.
        (
            "seed_debate_turn",
            (
                "plugins.seed_generation.tools.seed_debate",
                "SeedDebateTurnTool",
            ),
        ),
        # CSP-14 (2026-05-23) — Loop 3 (paper-analysis) of the seed-generation
        # 3-loop port. Freezes one fetched arXiv paper into a git-tracked
        # snapshot under docs/self-improving/petri-bundle/literature/. Cache-hit on
        # content_hash short-circuits re-writes.
        (
            "freeze_paper_snapshot",
            (
                "plugins.seed_generation.tools.literature_snapshot",
                "FreezePaperSnapshotTool",
            ),
        ),
        # profile
        ("profile_show", ("core.tools.profile_tools", "ProfileShowTool")),
        ("profile_update", ("core.tools.profile_tools", "ProfileUpdateTool")),
        (
            "profile_preference",
            ("core.tools.profile_tools", "ProfilePreferenceTool"),
        ),
        ("profile_learn", ("core.tools.profile_tools", "ProfileLearnTool")),
        # Google Workspace — credentials are registered by /login google.
        ("gmail_search", ("core.tools.google_workspace", "GmailSearchTool")),
        ("gmail_send", ("core.tools.google_workspace", "GmailSendTool")),
        (
            "google_drive_search",
            ("core.tools.google_workspace", "GoogleDriveSearchTool"),
        ),
        (
            "google_drive_create",
            ("core.tools.google_workspace", "GoogleDriveCreateTool"),
        ),
        (
            "google_docs_read",
            ("core.tools.google_workspace", "GoogleDocsReadTool"),
        ),
        (
            "google_docs_write",
            ("core.tools.google_workspace", "GoogleDocsWriteTool"),
        ),
        (
            "google_sheets_read",
            ("core.tools.google_workspace", "GoogleSheetsReadTool"),
        ),
        (
            "google_sheets_write",
            ("core.tools.google_workspace", "GoogleSheetsWriteTool"),
        ),
        (
            "google_tasks_list",
            ("core.tools.google_workspace", "GoogleTasksListTool"),
        ),
        (
            "google_tasks_write",
            ("core.tools.google_workspace", "GoogleTasksWriteTool"),
        ),
        (
            "google_contacts_list",
            ("core.tools.google_workspace", "GoogleContactsListTool"),
        ),
    )
)


def _make_delegate_handler(
    module_path: str,
    class_name: str,
) -> Callable[..., Any]:
    """Return an ASYNC handler that lazily imports *class_name* from
    *module_path* and awaits its ``aexecute``.

    PR-TOOL-EXEC-CONTEXT (2026-05-28) — pulls the framework-injected
    ``_tool_context`` (set by ``ToolCallProcessor``) out of ``kwargs`` and
    forwards it to ``_safe_delegate`` so the underlying tool's
    ``aexecute`` receives it. The reserved-name kwarg must not reach the
    LLM-arg validation path inside the tool, hence the explicit pop.

    PR-LOOP-POLLUTION-FIX (2026-06-12) — the handler is a coroutine
    function so ``ToolExecutor._call_handler_async`` awaits it natively on
    the session loop. The previous sync handler was bridged through
    ``asyncio.to_thread`` + ``run_process_coroutine`` — a brand-new event
    loop per tool call (async → sync → thread → new loop → async double
    inversion, residue of the pre-async-only era) — which poisoned shared
    httpx connection pools. Pinned by
    ``tests/core/llm/test_loop_pollution_guardrails.py``.
    """

    async def _handler(**kwargs: Any) -> dict[str, Any]:
        import importlib

        tool_context = kwargs.pop("_tool_context", None)
        mod = importlib.import_module(module_path)
        tool_cls = getattr(mod, class_name)
        return await _safe_delegate(tool_cls, kwargs, context=tool_context)

    return _handler


def _build_delegated_handlers() -> UniqueEntries[str, Any]:
    """Build all delegated tool handlers from ``_DELEGATED_TOOLS`` registry."""
    return UniqueEntries[str, Any](
        (
            (name, _make_delegate_handler(module, class_name))
            for name, (module, class_name) in _DELEGATED_TOOLS.items()
        )
    )
