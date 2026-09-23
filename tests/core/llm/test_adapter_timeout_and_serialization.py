"""Regression pin for PR-ADAPTER-TIMEOUT-AND-SERIALIZATION (2026-05-28).

Two fixes that stem from one production incident — the
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

B. **Summary SDK object → dict normalisation** — the same incident's
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

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

# ---------------------------------------------------------------------------
# A — every OpenAI-family client builder pins explicit httpx Timeout
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("route", ["openai", "glm-payg", "glm-coding-plan"])
def test_adapter_inherits_transport_policy(monkeypatch: pytest.MonkeyPatch, route: str) -> None:
    async def check() -> None:
        from core.config import GLM_PAYG_BASE_URL, settings
        from core.llm.adapters.glm_coding_plan import GlmCodingPlanAdapter
        from core.llm.adapters.glm_payg import GlmPaygAdapter
        from core.llm.adapters.openai_payg import OpenAIPaygAdapter

        monkeypatch.setattr(settings, "openai_api_key", "test-key")
        monkeypatch.setattr(settings, "zai_api_key", "test-key")
        monkeypatch.setattr(settings, "llm_read_timeout", 23.0)
        plan_url = "https://api.z.ai/api/coding/paas/v4"
        monkeypatch.setattr(
            "core.llm.adapters.glm_coding_plan._resolve_coding_plan_endpoint",
            lambda _sources: ("test-plan-key", plan_url),
        )
        adapters = {
            "openai": (OpenAIPaygAdapter, "https://api.openai.com/v1"),
            "glm-payg": (GlmPaygAdapter, GLM_PAYG_BASE_URL),
            "glm-coding-plan": (GlmCodingPlanAdapter, plan_url),
        }
        adapter_type, expected_url = adapters[route]
        adapter = adapter_type()
        async with adapter._get_client() as client:
            assert isinstance(client._client, httpx.AsyncClient)
            assert client._client.timeout.read == 23.0
            assert client.max_retries == 0
            assert str(client.base_url).rstrip("/") == expected_url.rstrip("/")

    asyncio.run(check())


def test_sdk2_serializes_documented_extension_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def check() -> None:
        """SDK serialization evidence only; this does not establish API acceptance."""
        from core.llm.adapters import _openai_common

        requests: list[httpx.Request] = []

        def respond(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(
                200,
                json={"id": "resp_mock", "object": "response", "output": [], "model": "gpt-6-sol"},
            )

        monkeypatch.setattr(
            _openai_common,
            "_build_async_httpx_client",
            lambda: httpx.AsyncClient(transport=httpx.MockTransport(respond)),
        )
        async with _openai_common.build_async_openai_client(
            "test-key", base_url="https://sdk.test/v1"
        ) as client:
            response = await client.responses.create(
                model="gpt-6-sol",
                input="test",
                extra_body={"service_tier": "fast", "prompt_cache_options": {"prewarm": True}},
            )
        assert response.id == "resp_mock"
        assert len(requests) == 1
        assert str(requests[0].url) == "https://sdk.test/v1/responses"
        body = json.loads(requests[0].content)
        assert body["model"] == "gpt-6-sol"
        assert body["service_tier"] == "fast"
        assert body["prompt_cache_options"] == {"prewarm": True}

    asyncio.run(check())


# ---------------------------------------------------------------------------
# B — Summary SDK objects normalise to JSON-safe dicts
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
