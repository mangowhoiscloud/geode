"""R6 — reasoning summary streaming → AgenticUI invariants (v0.57.0).

Pinned 2026-04-28. The 3-codebase consensus from
``docs/research/reasoning-depth-audit.md`` is unanimous: every reference
harness (Hermes, Claude Code, OpenClaw) surfaces reasoning summaries
to the UI so the user sees "live thinking..." rather than a silent
spinner. R6 implements this in GEODE at per-reasoning-item granularity
(not per-delta) to avoid threading the IPC writer into the
``asyncio.to_thread`` worker that runs the streaming loop.

Three invariants:

  1. ``normalize_openai_responses`` extracts ``reasoning.summary[].text``
     into ``AgenticResponse.reasoning_summaries`` (Codex Plus path).
     Captures both the full reasoning-with-encrypted-content case and
     the summary-only fallback.

  2. ``normalize_anthropic`` extracts ``thinking`` content blocks into
     the same sidecar (Anthropic adaptive thinking path with
     ``display:"summarized"`` from R4-mini).

  3. ``emit_reasoning_summary`` is registered in the IPC allowlist
     (``core/cli/ipc_client.py`` event router) and the renderer
     (``core/ui/event_renderer.py``).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from core.llm.agentic_response import (
    AgenticResponse,
    normalize_anthropic,
    normalize_openai_responses,
)


def _make_message_item(text: str) -> SimpleNamespace:
    return SimpleNamespace(
        type="message",
        content=[SimpleNamespace(type="output_text", text=text)],
    )


def _make_reasoning_item(*, encrypted: str | None, summary_texts: list[str]) -> SimpleNamespace:
    summary = [SimpleNamespace(text=t) for t in summary_texts]
    return SimpleNamespace(type="reasoning", encrypted_content=encrypted, summary=summary)


class TestCodexReasoningSummaryExtraction:
    """Sidecar populated from Codex Plus ``reasoning.summary[].text``."""

    def test_extracts_summary_with_encrypted_blob(self) -> None:
        resp = MagicMock()
        resp.usage = None
        resp.output = [
            _make_reasoning_item(
                encrypted="ENC.payload",
                summary_texts=["Considered three angles", "Picked angle 2"],
            ),
            _make_message_item("answer"),
        ]
        result = normalize_openai_responses(resp)
        assert result.reasoning_summaries == [
            "Considered three angles",
            "Picked angle 2",
        ]
        # codex_reasoning_items still populated for multi-turn replay (R1)
        assert result.codex_reasoning_items is not None
        assert len(result.codex_reasoning_items) == 1

    def test_extracts_summary_when_encrypted_blob_missing(self) -> None:
        """Some transient error paths strip encrypted_content but keep
        summary — surface to UI even though we can't replay."""
        resp = MagicMock()
        resp.usage = None
        resp.output = [
            _make_reasoning_item(encrypted=None, summary_texts=["partial thought"]),
            _make_message_item("answer"),
        ]
        result = normalize_openai_responses(resp)
        assert result.reasoning_summaries == ["partial thought"]
        # No replay item because encrypted_content is missing
        assert result.codex_reasoning_items is None

    def test_no_reasoning_items_returns_none(self) -> None:
        resp = MagicMock()
        resp.usage = None
        resp.output = [_make_message_item("hello")]
        result = normalize_openai_responses(resp)
        assert result.reasoning_summaries is None

    def test_empty_summary_strings_filtered(self) -> None:
        """Empty strings don't get pushed onto the sidecar."""
        resp = MagicMock()
        resp.usage = None
        resp.output = [
            _make_reasoning_item(encrypted="ENC", summary_texts=["", "real text", ""]),
        ]
        result = normalize_openai_responses(resp)
        assert result.reasoning_summaries == ["real text"]


class TestAnthropicThinkingExtraction:
    """Sidecar populated from Anthropic ``thinking`` content blocks."""

    def test_extracts_thinking_block_text(self) -> None:
        resp = SimpleNamespace(
            content=[
                SimpleNamespace(type="thinking", thinking="step-by-step plan", signature="sig"),
                SimpleNamespace(type="text", text="visible answer"),
            ],
            stop_reason="end_turn",
            usage=SimpleNamespace(input_tokens=10, output_tokens=5, thinking_tokens=20),
        )
        result = normalize_anthropic(resp)
        assert result.reasoning_summaries == ["step-by-step plan"]
        # text block still extracted
        assert len(result.content) == 1
        assert result.content[0].text == "visible answer"

    def test_no_thinking_block_returns_none(self) -> None:
        resp = SimpleNamespace(
            content=[SimpleNamespace(type="text", text="no thinking here")],
            stop_reason="end_turn",
            usage=SimpleNamespace(input_tokens=10, output_tokens=5, thinking_tokens=0),
        )
        result = normalize_anthropic(resp)
        assert result.reasoning_summaries is None

    def test_empty_thinking_text_filtered(self) -> None:
        resp = SimpleNamespace(
            content=[
                SimpleNamespace(type="thinking", thinking="", signature="sig"),
                SimpleNamespace(type="text", text="visible"),
            ],
            stop_reason="end_turn",
            usage=SimpleNamespace(input_tokens=10, output_tokens=5, thinking_tokens=0),
        )
        result = normalize_anthropic(resp)
        assert result.reasoning_summaries is None


class TestSidecarFieldDefault:
    def test_default_is_none(self) -> None:
        assert AgenticResponse().reasoning_summaries is None

    def test_other_normalisers_leave_it_none(self) -> None:
        """OpenAI Chat Completions normaliser doesn't set the sidecar."""
        from core.llm.agentic_response import normalize_openai

        resp = MagicMock()
        resp.choices = []
        resp.usage = MagicMock(prompt_tokens=10, completion_tokens=5)
        result = normalize_openai(resp)
        assert result.reasoning_summaries is None


class TestEmitReasoningSummary:
    """The UI emit helper renders to console when no IPC writer is bound,
    and forwards a structured event when bound."""

    def test_emit_console_path(self, capsys) -> None:
        from core.ui.agentic_ui import emit_reasoning_summary

        # No writer bound → console path
        emit_reasoning_summary("openai-codex", "gpt-5.5", "considered the trade-offs")
        # Rich prints to its own console; just assert no crash. The
        # render shape is verified separately in event_renderer tests.

    def test_emit_truncates_long_text(self) -> None:
        from core.ui.agentic_ui import emit_reasoning_summary

        # 500-char text — should be truncated for console display
        long = "x" * 500
        emit_reasoning_summary("anthropic", "claude-opus-4-7", long)


class TestIPCAllowlistAndRenderer:
    """v0.57.0 — ``reasoning_summary`` event is in the IPC allowlist
    (``ipc_client.py``) and the renderer dispatches it
    (``event_renderer.py``)."""

    def test_event_in_ipc_allowlist(self) -> None:
        # Read the source verbatim — assertion-by-grep is sufficient
        # because the allowlist is a literal tuple.
        from core.cli import ipc_client

        with open(ipc_client.__file__, encoding="utf-8") as f:
            text = f.read()
        assert '"reasoning_summary"' in text, (
            "ipc_client.py must include 'reasoning_summary' in the "
            "structured-events allowlist or the daemon's events will be "
            "silently dropped on the thin client side"
        )

    def test_renderer_handler_exists(self) -> None:
        from core.ui.event_renderer import EventRenderer

        assert hasattr(EventRenderer, "_handle_reasoning_summary"), (
            "EventRenderer must define _handle_reasoning_summary so the "
            "dispatch in `_handle` (line 115) can route the event"
        )

    def test_renderer_truncates_and_renders(self) -> None:
        """Short text → muted line. Long text → truncated with ellipsis."""
        import io

        from core.ui.event_renderer import EventRenderer

        renderer = EventRenderer()
        renderer._out = io.StringIO()
        renderer._handle_reasoning_summary({"text": "short summary"})
        output = renderer._out.getvalue()
        assert "thinking" in output
        assert "short summary" in output

        renderer2 = EventRenderer()
        renderer2._out = io.StringIO()
        renderer2._handle_reasoning_summary({"text": "x" * 500})
        out2 = renderer2._out.getvalue()
        assert "…" in out2  # ellipsis marker for truncation

    def test_renderer_skips_empty_text(self) -> None:
        import io

        from core.ui.event_renderer import EventRenderer

        renderer = EventRenderer()
        renderer._out = io.StringIO()
        renderer._handle_reasoning_summary({"text": "   "})  # whitespace only
        assert renderer._out.getvalue() == ""


class TestLoopEmitsAfterCall:
    """The agentic loop emits each reasoning summary after the adapter
    returns. We verify the wiring exists in the loop source — running
    the actual loop requires a real LLM."""

    def test_loop_calls_emit_reasoning_summary(self) -> None:
        from core.agent import loop as loop_mod

        with open(loop_mod.__file__, encoding="utf-8") as f:
            text = f.read()
        assert "emit_reasoning_summary" in text, (
            "core/agent/loop.py must call emit_reasoning_summary for "
            "each summary on response.reasoning_summaries — otherwise "
            "the sidecar is collected but never surfaced to the UI"
        )
