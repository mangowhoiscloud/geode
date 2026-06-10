"""Regression pin for the Codex MCP BLOCKER caught during
PR-ADAPTER-TIMEOUT-AND-SERIALIZATION (2026-05-28).

Without ``max_retries=0`` on the OpenAI-family clients, the SDK's
internal retry loop (default 2) compounds with GEODE's own
``_LLM_RETRY_CAP`` retry path — the operator's 2026-05-28 10-minute
spin would have stayed at ~10 minutes even after the httpx Timeout fix
(300 s read × 2 SDK attempts = 600 s before app retry even sees the
failure). Anthropic adapter has always pinned ``max_retries=0`` —
this PR brings OpenAI / Codex / GLM (PAYG + OAuth + Coding Plan, plus
the legacy singleton paths) to the same invariant so retry is owned
by a single source.
"""

from __future__ import annotations

from pathlib import Path


def test_openai_payg_builder_pins_max_retries_zero() -> None:
    """``build_async_openai_client`` must pass ``max_retries=0`` so SDK
    retry does not compound with GEODE's agent-loop retry."""
    src = (
        Path(__file__).resolve().parents[3] / "core" / "llm" / "adapters" / "_openai_common.py"
    ).read_text(encoding="utf-8")
    assert "max_retries=0" in src, (
        "_openai_common.py no longer pins max_retries=0 on the OpenAI/Codex "
        "client builders. SDK x app retry compounding re-introduces the "
        "10-minute spin the operator hit on 2026-05-28."
    )


def test_codex_oauth_builder_pins_max_retries_zero() -> None:
    """Same invariant for the Codex backend client builder."""
    src = (
        Path(__file__).resolve().parents[3] / "core" / "llm" / "adapters" / "_openai_common.py"
    ).read_text(encoding="utf-8")
    # The Codex builder's max_retries=0 lives in a different block from the
    # PAYG one; ensure both code paths set the kwarg by checking source
    # contains at least two occurrences within the builder region.
    assert src.count("max_retries=0") >= 2, (
        "_openai_common.py contains < 2 max_retries=0 occurrences — one of "
        "build_async_openai_client / build_async_codex_client likely lost "
        "the pin."
    )


def test_legacy_openai_provider_singleton_pins_max_retries_zero() -> None:
    """Legacy ``core/llm/providers/openai.py`` singleton is still consumed by
    paperclip ``OpenAIAdapter`` + llm_extract_learning + models.py — same
    spinning risk if SDK retry compounds with app retry."""
    src = (
        Path(__file__).resolve().parents[3] / "core" / "llm" / "providers" / "openai.py"
    ).read_text(encoding="utf-8")
    assert "max_retries=0" in src, (
        "Legacy openai provider singleton lost max_retries=0 — spinning "
        "regresses for paperclip / llm_extract_learning callers."
    )


def test_legacy_codex_provider_singleton_pins_max_retries_zero() -> None:
    src = (
        Path(__file__).resolve().parents[3] / "core" / "llm" / "providers" / "codex.py"
    ).read_text(encoding="utf-8")
    assert "max_retries=0" in src


def test_legacy_glm_provider_singleton_pins_max_retries_zero() -> None:
    src = (Path(__file__).resolve().parents[3] / "core" / "llm" / "providers" / "glm.py").read_text(
        encoding="utf-8"
    )
    assert "max_retries=0" in src


def test_anthropic_adapter_keeps_max_retries_zero() -> None:
    """Parity pin — Anthropic adapter had this invariant from day 1
    (``_anthropic_common.py:60``). A future refactor that drops it would
    introduce the same spinning risk on the Anthropic side."""
    src = (
        Path(__file__).resolve().parents[3] / "core" / "llm" / "adapters" / "_anthropic_common.py"
    ).read_text(encoding="utf-8")
    assert "max_retries=0" in src, (
        "_anthropic_common.py no longer pins max_retries=0 — provider parity "
        "with the new OpenAI/Codex/GLM pinning broken."
    )
