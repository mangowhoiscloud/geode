"""Regression pin for PR-ADAPTER-TIMEOUT-AND-SERIALIZATION (2026-05-28).

Three sister fixes that all stem from one production incident — the
operator's 2026-05-28 10-minute hang on a single ``gpt-5.5`` turn (serve
log 11:06:19 → 11:16:39, 620062 ms latency):

A. **httpx Timeout wiring** — ``build_async_openai_client`` /
   ``build_async_codex_client`` used the openai SDK's default httpx
   instance, whose read-timeout defaults are long enough that a stalled
   Codex backend stream silently waited ~10 minutes before the SDK's
   retry loop kicked in. The fix shares Anthropic's
   ``settings.llm_*_timeout`` policy with every OpenAI-family client
   (PAYG OpenAI, Codex OAuth, GLM PAYG, GLM Coding Plan) — capping the
   stall at ``settings.llm_read_timeout`` (default 300 s).

B. **SDK retry → UI bridge** — ``openai._base_client`` logs
   ``Retrying request to /responses in 0.49 seconds`` at INFO level
   when it retries, but the line landed only in the serve log file.
   The operator watching the CLI spinner had no signal. A
   ``logging.Handler`` on ``openai._base_client`` re-emits the retry
   line through GEODE's existing ``emit_llm_retry`` event so the same
   UI surface that agent-loop-side retries use covers SDK-side
   retries too.

C. **Summary SDK object → dict normalisation** — the same incident's
   serve log also surfaced
   ``TypeError: Object of type Summary is not JSON serializable`` from
   ``session_manager.py:433`` because ``translate_codex_response``
   stored OpenAI SDK ``ResponseReasoningItem.Summary`` Pydantic objects
   verbatim in ``codex_reasoning_items[*]["summary"]``. The fix
   normalises each summary element to a plain
   ``{"type": "summary_text", "text": ...}`` dict so the downstream
   SQLite session mirror + JSON checkpoint + IPC payload only see
   JSON-safe primitives.
"""

from __future__ import annotations

import json
import logging
import re
from types import SimpleNamespace

# ---------------------------------------------------------------------------
# A — every OpenAI-family client builder pins explicit httpx Timeout
# ---------------------------------------------------------------------------


def test_build_async_openai_client_uses_explicit_httpx_client() -> None:
    """PAYG OpenAI client must own a fresh httpx.AsyncClient with explicit
    Timeout — otherwise SDK default read-timeout can silently hang
    ~10 minutes on a stalled stream (operator incident 2026-05-28)."""
    from core.llm.adapters._openai_common import build_async_openai_client

    client = build_async_openai_client("sk-test-not-real")
    # The openai SDK exposes the underlying transport via ``._client`` on
    # the AsyncOpenAI instance. We verify the timeout pin propagated.
    httpx_client = getattr(client, "_client", None)
    assert httpx_client is not None, (
        "build_async_openai_client did not attach a custom http_client; "
        "SDK default httpx timeout kicks in, recreating the 10-minute "
        "stall incident."
    )
    timeout = httpx_client.timeout
    assert timeout.read is not None and timeout.read <= 600, (
        f"httpx read timeout = {timeout.read} (None or > 600s); the SDK "
        f"will hang past the operator-visible threshold."
    )


def test_build_async_codex_client_uses_explicit_httpx_client() -> None:
    """Codex OAuth client (chatgpt.com/backend-api/codex) — same invariant
    as PAYG. This is the exact path the operator's spinning hit."""
    from core.llm.adapters._openai_common import build_async_codex_client

    # Codex client builder requires a non-empty token; pass a dummy.
    client = build_async_codex_client("dummy-jwt-not-real")
    httpx_client = getattr(client, "_client", None)
    assert httpx_client is not None, (
        "build_async_codex_client did not attach a custom http_client — "
        "regresses the 2026-05-28 10-minute spin."
    )
    timeout = httpx_client.timeout
    assert timeout.read is not None and timeout.read <= 600


def test_openai_payg_adapter_inherits_timeout_via_builder() -> None:
    """End-to-end pin: instantiating the adapter populates a client that
    inherits the explicit timeout, even though the adapter never touches
    httpx directly."""
    from core.config import settings
    from core.llm.adapters.openai_payg import OpenAIPaygAdapter

    # Adapter's _get_client raises when no key — temporarily inject one
    # so the builder runs.
    monkeypatched = False
    if not getattr(settings, "openai_api_key", ""):
        object.__setattr__(settings, "openai_api_key", "sk-test-not-real")
        monkeypatched = True
    try:
        adapter = OpenAIPaygAdapter()
        client = adapter._get_client()
        assert client._client.timeout.read is not None
    finally:
        if monkeypatched:
            object.__setattr__(settings, "openai_api_key", "")


# ---------------------------------------------------------------------------
# B — SDK retry log line surfaces through emit_llm_retry
# ---------------------------------------------------------------------------


def test_sdk_retry_visibility_bridge_emits_on_retrying_log_line() -> None:
    """When openai SDK logs ``Retrying request to ... in 0.5 seconds``,
    the bridge re-emits the GEODE ``emit_llm_retry`` event so the agentic
    UI shows the retry — operator no longer sees an opaque spinner."""
    from core.llm.adapters import _sdk_retry_visibility

    _sdk_retry_visibility._for_test_reset()
    _sdk_retry_visibility.install()

    emitted: list[tuple[int, int, int]] = []

    def _fake_emit(*, delay_s: int, attempt: int, max_attempts: int) -> None:
        emitted.append((delay_s, attempt, max_attempts))

    import core.ui.agentic_ui as agentic_ui_pkg

    original = getattr(agentic_ui_pkg, "emit_llm_retry", None)
    agentic_ui_pkg.emit_llm_retry = _fake_emit  # type: ignore[assignment]
    try:
        sdk_logger = logging.getLogger("openai._base_client")
        # Make sure INFO records reach handlers regardless of root config.
        sdk_logger.setLevel(logging.INFO)
        sdk_logger.info("Retrying request to /responses in 0.49 seconds")
    finally:
        if original is not None:
            agentic_ui_pkg.emit_llm_retry = original
        _sdk_retry_visibility._for_test_reset()

    assert emitted, "Bridge did not re-emit the SDK retry as a GEODE UI event"
    delay_s, attempt, max_attempts = emitted[0]
    assert delay_s >= 1
    assert attempt == 1
    assert max_attempts == 2


def test_sdk_retry_visibility_install_is_idempotent() -> None:
    """Repeated ``install()`` must not stack handlers — would cause the
    same retry log line to be emitted N times to the operator."""
    from core.llm.adapters import _sdk_retry_visibility

    _sdk_retry_visibility._for_test_reset()
    _sdk_retry_visibility.install()
    _sdk_retry_visibility.install()
    _sdk_retry_visibility.install()

    sdk_logger = logging.getLogger("openai._base_client")
    handler_count = sum(
        1
        for h in sdk_logger.handlers
        if isinstance(h, _sdk_retry_visibility._OpenAISdkRetryEventBridge)
    )
    _sdk_retry_visibility._for_test_reset()
    assert handler_count == 1, f"Expected exactly one retry-bridge handler, got {handler_count}"


def test_sdk_retry_visibility_ignores_non_retry_log_lines() -> None:
    """Only the ``Retrying request to ... in N seconds`` shape triggers
    the bridge — other openai SDK logs (request starts, response
    finishes) must not spam the UI."""
    from core.llm.adapters import _sdk_retry_visibility

    _sdk_retry_visibility._for_test_reset()
    _sdk_retry_visibility.install()

    emitted: list[object] = []

    def _fake_emit(*, delay_s: int, attempt: int, max_attempts: int) -> None:
        emitted.append((delay_s, attempt, max_attempts))

    import core.ui.agentic_ui as agentic_ui_pkg

    original = getattr(agentic_ui_pkg, "emit_llm_retry", None)
    agentic_ui_pkg.emit_llm_retry = _fake_emit  # type: ignore[assignment]
    try:
        sdk_logger = logging.getLogger("openai._base_client")
        sdk_logger.setLevel(logging.INFO)
        sdk_logger.info("Sending HTTP Request: POST /responses")
        sdk_logger.info("Received response.completed event")
    finally:
        if original is not None:
            agentic_ui_pkg.emit_llm_retry = original
        _sdk_retry_visibility._for_test_reset()

    assert emitted == [], f"Bridge emitted on non-retry log lines: {emitted!r} — risks UI spam"


# ---------------------------------------------------------------------------
# C — Summary SDK objects normalise to JSON-safe dicts
# ---------------------------------------------------------------------------


def test_normalize_summary_handles_dict_passthrough() -> None:
    """Dicts pass through unchanged (no needless wrapping)."""
    from core.llm.adapters._openai_common import _normalize_summary_list

    out = _normalize_summary_list(
        [{"type": "summary_text", "text": "hello"}, {"type": "summary_text", "text": "world"}]
    )
    assert out == [
        {"type": "summary_text", "text": "hello"},
        {"type": "summary_text", "text": "world"},
    ]
    assert all(isinstance(o, dict) for o in out)


def test_normalize_summary_converts_pydantic_like_objects() -> None:
    """Pydantic v2 ``model_dump()`` is the preferred extraction. Any
    object exposing it is normalised via that surface."""
    from core.llm.adapters._openai_common import _normalize_summary_list

    class _Summary:
        type = "summary_text"
        text = "extracted via model_dump"

        def model_dump(self) -> dict:
            return {"type": self.type, "text": self.text}

    out = _normalize_summary_list([_Summary(), _Summary()])
    assert out == [
        {"type": "summary_text", "text": "extracted via model_dump"},
        {"type": "summary_text", "text": "extracted via model_dump"},
    ]
    # Critical invariant: result is JSON-serialisable (the original bug).
    json.dumps(out)


def test_normalize_summary_falls_back_to_attribute_extraction() -> None:
    """Objects without ``model_dump`` (future SDK variant) still
    normalise via ``.text`` / ``.type`` attribute extraction."""
    from core.llm.adapters._openai_common import _normalize_summary_list

    obj = SimpleNamespace(type="custom", text="attr fallback")
    out = _normalize_summary_list([obj])
    assert out == [{"type": "custom", "text": "attr fallback"}]
    json.dumps(out)


def test_normalize_summary_handles_empty_and_none() -> None:
    """Empty list / None / non-list → ``[]`` (matches original
    ``summary if summary else []`` contract so replay path stays happy)."""
    from core.llm.adapters._openai_common import _normalize_summary_list

    assert _normalize_summary_list(None) == []
    assert _normalize_summary_list([]) == []
    assert _normalize_summary_list("not a list") == []
    assert _normalize_summary_list({"oops": "wrong shape"}) == []


def test_translate_codex_response_emits_json_safe_summary() -> None:
    """End-to-end pin on the original incident: a translated
    AdapterCallResult must be JSON-safe so the SQLite session mirror
    (session_manager.py:433) does not raise TypeError."""
    from core.llm.adapters._openai_common import translate_codex_response

    class _Summary:
        type = "summary_text"
        text = "thinking step"

        def model_dump(self) -> dict:
            return {"type": self.type, "text": self.text}

    reasoning_item = SimpleNamespace(
        type="reasoning",
        encrypted_content="opaque-blob",
        summary=[_Summary()],
        id="resp-abc",
    )
    response = SimpleNamespace(
        output_text="hello",
        output=[reasoning_item],
        status="completed",
        usage=SimpleNamespace(input_tokens=10, output_tokens=5),
    )
    result = translate_codex_response(response, accumulated_items=[reasoning_item])
    assert result.reasoning_items, "Expected one normalised reasoning item"
    entry = result.reasoning_items[0]
    # The whole entry must JSON-serialise without TypeError — that was
    # the production failure.
    json.dumps(entry)
    # Summary list entries are plain dicts now, not SDK objects.
    summary_list = entry.get("summary", [])
    assert all(isinstance(s, dict) for s in summary_list), (
        f"summary still carries SDK objects: {summary_list!r}"
    )
    assert summary_list == [{"type": "summary_text", "text": "thinking step"}]


# ---------------------------------------------------------------------------
# Source-level pin — file content guarantees (single point of regression)
# ---------------------------------------------------------------------------


def test_openai_common_documents_timeout_fix() -> None:
    """Pin the helper name + intent in the source. A future refactor
    that drops ``_build_async_httpx_client`` would lose the timeout cap
    and regress the 10-minute spin — this test fails loudly.

    PR-CODEX-NO-KEEPALIVE (2026-05-28) — ``build_async_codex_client``
    constructs its own inline ``httpx.AsyncClient`` (with
    ``max_keepalive_connections=0`` to avoid Codex-backend stale-
    connection failures) instead of delegating to
    ``_build_async_httpx_client``. The httpx timeout settings still
    flow through ``settings.llm_*`` so the original 10-minute spin
    guarantee is preserved — the assertion now checks the timeout-
    related settings reads inside the codex builder body."""
    from pathlib import Path

    src = (
        Path(__file__).resolve().parents[1] / "core" / "llm" / "adapters" / "_openai_common.py"
    ).read_text(encoding="utf-8")
    assert "_build_async_httpx_client" in src, (
        "_openai_common.py no longer defines _build_async_httpx_client — "
        "OpenAI/Codex/GLM clients lose explicit Timeout pin."
    )
    # build_async_openai_client wires via the shared helper.
    assert re.search(r"def build_async_openai_client.*?http_client", src, re.DOTALL), (
        "build_async_openai_client lost its http_client= wiring"
    )
    # build_async_codex_client now has its own inline httpx client
    # (PR-CODEX-NO-KEEPALIVE) but still wires it via ``http_client=`` and
    # still reads the same llm_*_timeout settings the shared helper
    # uses, so the 10-minute-spin guarantee is preserved.
    codex_body_match = re.search(r"def build_async_codex_client.*?(?=\n\ndef |\Z)", src, re.DOTALL)
    assert codex_body_match is not None, "build_async_codex_client missing"
    codex_src = codex_body_match.group(0)
    assert "http_client=codex_http_client" in codex_src, (
        "build_async_codex_client lost its http_client= wiring"
    )
    assert "settings.llm_read_timeout" in codex_src, (
        "build_async_codex_client lost the llm_read_timeout pin — "
        "the 10-minute-spin guarantee is at risk"
    )
    assert "settings.llm_connect_timeout" in codex_src, (
        "build_async_codex_client lost the llm_connect_timeout pin"
    )
