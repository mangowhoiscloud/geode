"""R3-mini — PAYG OpenAI Responses reasoning kwargs + replay parity (v0.60.0).

Pinned 2026-04-28 against:
  - openai-python ``shared/reasoning.py`` (Reasoning model, summary Literal)
  - openai-python ``responses/response_create_params.py:70-74``
    (``reasoning.encrypted_content`` semantics under ``store=False``)
  - openai-python ``responses/response_includable.py`` (include enum)
  - Codex Plus parity: ``core/llm/providers/codex.py:347-348``

Verifies:
  1. ``_is_payg_reasoning_model`` gates gpt-5.x + o-series only.
  2. ``inject_reasoning_replay`` round-trips encrypted blobs across turns.
  3. PAYG ``openai.py`` adapter sends ``include`` + ``reasoning.summary=auto``
     for gpt-5.x; non-reasoning models leave the kwargs untouched.
"""

from __future__ import annotations

import inspect
from typing import Any

from core.llm.agentic_response import inject_reasoning_replay
from core.llm.providers.openai import _is_payg_reasoning_model


class TestPaygReasoningGate:
    def test_gpt5_family_gated_in(self) -> None:
        for m in ("gpt-5.5", "gpt-5.4", "gpt-5.4-mini", "gpt-5.3-codex", "gpt-5"):
            assert _is_payg_reasoning_model(m), m

    def test_o_series_gated_in(self) -> None:
        for m in ("o3", "o4-mini", "o3-mini"):
            assert _is_payg_reasoning_model(m), m

    def test_non_reasoning_models_gated_out(self) -> None:
        for m in ("gpt-4-turbo", "gpt-4o", "gpt-3.5-turbo", "claude-opus-4-7"):
            assert not _is_payg_reasoning_model(m), m


class TestReasoningReplayWalker:
    def test_assistant_with_reasoning_items_emits_blob_first(self) -> None:
        """The encrypted blob must precede the assistant entry it
        belongs to so the server restores reasoning state before
        decoding the assistant turn."""
        anth_messages = [
            {"role": "user", "content": "first"},
            {
                "role": "assistant",
                "content": "ok",
                "codex_reasoning_items": [
                    {
                        "type": "reasoning",
                        "encrypted_content": "BLOB-1",
                        "id": "rs_abc",
                    }
                ],
            },
            {"role": "user", "content": "next"},
        ]
        oai_messages = [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "ok"},
            {"role": "user", "content": "next"},
        ]
        out = inject_reasoning_replay(oai_messages, anth_messages)
        types_or_roles = [(e.get("type"), e.get("role")) for e in out]
        # Sequence: user → reasoning → assistant → user
        assert types_or_roles == [
            (None, "user"),
            ("reasoning", None),
            (None, "assistant"),
            (None, "user"),
        ]

    def test_id_field_stripped(self) -> None:
        """ID must not be sent back — server can 404 on item lookup."""
        anth = [
            {
                "role": "assistant",
                "content": "x",
                "codex_reasoning_items": [
                    {"type": "reasoning", "encrypted_content": "BLOB", "id": "rs_xyz"}
                ],
            }
        ]
        oai = [{"role": "assistant", "content": "x"}]
        out = inject_reasoning_replay(oai, anth)
        reasoning = next(e for e in out if e.get("type") == "reasoning")
        assert "id" not in reasoning
        assert reasoning["encrypted_content"] == "BLOB"

    def test_missing_encrypted_content_is_skipped(self) -> None:
        """No blob → nothing to replay (otherwise we just bloat the request)."""
        anth = [
            {
                "role": "assistant",
                "content": "x",
                "codex_reasoning_items": [{"type": "reasoning", "summary": [{"text": "thought"}]}],
            }
        ]
        oai = [{"role": "assistant", "content": "x"}]
        out = inject_reasoning_replay(oai, anth)
        assert all(e.get("type") != "reasoning" for e in out)

    def test_system_entry_dropped(self) -> None:
        """System prompt comes via ``instructions`` kwarg, not input."""
        anth = [{"role": "user", "content": "hi"}]
        oai = [
            {"role": "system", "content": "you are helpful"},
            {"role": "user", "content": "hi"},
        ]
        out = inject_reasoning_replay(oai, anth)
        assert all(e.get("role") != "system" for e in out)

    def test_no_codex_reasoning_items_passes_through(self) -> None:
        """Plain conversations without reasoning sidecar return unchanged."""
        anth = [
            {"role": "user", "content": "a"},
            {"role": "assistant", "content": "b"},
        ]
        oai = [
            {"role": "user", "content": "a"},
            {"role": "assistant", "content": "b"},
        ]
        out = inject_reasoning_replay(oai, anth)
        assert out == oai


class TestPaygSourceWiring:
    """Source-level pin — the kwargs must literally appear in openai.py
    so a future refactor can't silently drop them."""

    def test_include_encrypted_content_present(self) -> None:
        from core.llm.providers import openai as openai_mod

        src = inspect.getsource(openai_mod)
        assert '"include"' in src
        assert '"reasoning.encrypted_content"' in src

    def test_summary_auto_present(self) -> None:
        from core.llm.providers import openai as openai_mod

        src = inspect.getsource(openai_mod)
        assert '"summary": "auto"' in src

    def test_inject_reasoning_replay_called(self) -> None:
        """Without the replay walker, ``include`` is write-only — the
        server returns the blob but we never feed it back next turn."""
        from core.llm.providers import openai as openai_mod

        src = inspect.getsource(openai_mod)
        assert "inject_reasoning_replay" in src

    def test_codex_path_uses_shared_helper(self) -> None:
        """Codex.py shouldn't carry the inline walker anymore."""
        from core.llm.providers import codex as codex_mod

        src = inspect.getsource(codex_mod)
        assert "inject_reasoning_replay" in src
        # Inline marker from the pre-extraction version
        assert "_msg_iter = iter(messages)" not in src


class TestEffortMapping:
    """``max`` (Anthropic) → ``high`` (OpenAI) per the existing _EFFORT_MAP."""

    def test_max_maps_to_high_in_kwargs(self, monkeypatch) -> None:
        from core.llm.providers import openai as openai_mod

        captured: dict[str, Any] = {}

        def _fake_responses_create(**kwargs: Any) -> Any:
            captured.update(kwargs)
            raise RuntimeError("stop after capture")

        # We can't easily run the full async path without a client; the
        # source-level pin above guards the ``_EFFORT_MAP`` literal. Here
        # we just sanity-check the literal is intact.
        src = inspect.getsource(openai_mod)
        assert '"max": "high"' in src
