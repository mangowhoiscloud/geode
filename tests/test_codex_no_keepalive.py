"""Regression pin for PR-CODEX-NO-KEEPALIVE (2026-05-28).

The Codex backend (``chatgpt.com/backend-api/codex/responses``) closes
idle HTTP/2 connections within a few seconds without sending a GOAWAY
the client can observe in time. The first call after an idle period
silently reuses a stale connection from httpx's keep-alive pool →
``APIConnectionError`` in ~4ms (observed pattern: 4 parallel web_search
right after a slower LLM call — first fails instantly, the next three
open fresh connections and succeed). Traced via PR-DISPATCH-OBS-EXT's
``adapter_dispatch_attempt`` events 2026-05-28 15:44:37 KST,
run_id ``f6c51cc5e18d`` in ``subject_gateway_analysis.jsonl``.

Fix: ``build_async_codex_client`` uses an httpx client with
``max_keepalive_connections=0`` so every Codex call opens a fresh
TCP+TLS connection. Other OpenAI-family endpoints
(``_build_async_httpx_client``) keep the default keep-alive policy.

This test pins the Codex-specific override at the source level so a
future refactor that consolidates client construction (or accidentally
swaps back to ``_build_async_httpx_client()``) fails visibly.
"""

from __future__ import annotations

import inspect
from pathlib import Path


def test_build_async_codex_client_disables_keepalive() -> None:
    """Source-level pin: ``build_async_codex_client`` constructs its own
    httpx client with ``max_keepalive_connections=0``.

    Pinning at the source rather than runtime because constructing an
    actual ``AsyncOpenAI`` client requires a valid Codex OAuth token
    and would invoke httpx — both are out of scope for a unit test.
    The source assertion + the matching CHANGELOG entry are the
    workflow guard.
    """
    src = (
        Path(__file__).resolve().parents[1] / "core" / "llm" / "adapters" / "_openai_common.py"
    ).read_text(encoding="utf-8")

    # The override must be inside build_async_codex_client, not
    # _build_async_httpx_client (which serves other endpoints).
    import core.llm.adapters._openai_common as openai_common

    codex_builder_src = inspect.getsource(openai_common.build_async_codex_client)
    assert "max_keepalive_connections=0" in codex_builder_src, (
        "build_async_codex_client must override httpx Limits with "
        "max_keepalive_connections=0 — the Codex backend's aggressive "
        "idle-connection cleanup causes first-call APIConnectionError "
        "(stale connection reuse). See PR-CODEX-NO-KEEPALIVE docstring."
    )

    # The default helper used by other OpenAI-family clients (PAYG OpenAI,
    # GLM PAYG, GLM Coding Plan) keeps the default keep-alive policy.
    default_builder_src = inspect.getsource(openai_common._build_async_httpx_client)
    assert "settings.llm_max_keepalive_connections" in default_builder_src, (
        "_build_async_httpx_client must read settings.llm_max_keepalive_connections "
        "(default 5) — the no-keepalive override is Codex-specific."
    )

    # Source-level PR tag pin so the CHANGELOG can grep-verify.
    assert "PR-CODEX-NO-KEEPALIVE" in src


def test_build_async_codex_client_uses_dedicated_httpx_client() -> None:
    """Codex client construction must NOT call ``_build_async_httpx_client()``
    — that helper enables keep-alive (5 idle connections by default). The
    Codex builder constructs an httpx.AsyncClient inline so the keep-alive
    override is impossible to bypass."""
    import core.llm.adapters._openai_common as openai_common

    codex_src = inspect.getsource(openai_common.build_async_codex_client)
    # The default helper name must not appear inside the codex builder body
    # AFTER the docstring. The simplest check: count, and assert the only
    # mention (if any) is the docstring's cross-reference.
    body_lines = codex_src.splitlines()
    # Strip lines that are pure docstring (between triple-quotes).
    in_docstring = False
    docstring_open = '"""'
    body_only: list[str] = []
    for ln in body_lines:
        if docstring_open in ln:
            in_docstring = not in_docstring
            continue
        if not in_docstring:
            body_only.append(ln)
    body = "\n".join(body_only)
    assert "_build_async_httpx_client(" not in body, (
        "build_async_codex_client body must not delegate to "
        "_build_async_httpx_client — that helper enables 5 keep-alive "
        "connections by default which is the failure mode this PR fixes."
    )
    # The replacement: inline httpx.AsyncClient with explicit Limits.
    assert "httpx.AsyncClient(" in body
    assert "httpx.Limits(" in body
