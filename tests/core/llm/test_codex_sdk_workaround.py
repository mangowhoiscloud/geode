"""Regression pin for PR-CODEX-OUTPUT-NULL (2026-05-28).

The ChatGPT subscription backend at ``chatgpt.com/backend-api/codex``
delivers ``response.completed`` events with ``output: null`` because the
actual output items are streamed via separate ``response.output_item.done``
events. Starting in ``openai`` SDK 2.26+, ``ResponseStreamState.
accumulate_event`` calls ``parse_response(event.response)`` on every
``response.completed``; that function iterates ``response.output``
unconditionally, so ``output is None`` raises
``TypeError: 'NoneType' object is not iterable`` during the
``async for event in stream`` loop in
:meth:`core.llm.adapters.codex_oauth.CodexOAuthAdapter.acomplete` —
**before** our own ``accumulated`` list could absorb the items.

``core/llm/adapters/_codex_sdk_workaround.py`` patches
``openai.lib._parsing._responses.parse_response`` (and the symbol
re-imported into the streaming module) to coerce ``response.output``
from ``None`` to ``[]`` before delegating to the original parser. The
test exercises the unpatched crash, applies the patch, and verifies the
same call now returns cleanly. A second test confirms the patch is
idempotent (re-installing is a no-op) and that the install is wired into
both client builders (adapter + legacy provider).

Live HTTP is not required — we synthesise the ``Response`` object the
SDK would have constructed from a Codex backend ``response.completed``
SSE event payload.
"""

from __future__ import annotations

from pathlib import Path

import pytest

try:
    import openai
except ImportError:  # pragma: no cover — openai is a hard runtime dep
    pytest.skip("openai SDK not installed", allow_module_level=True)


def _make_response_with_null_output() -> object:
    """Synthesise an ``openai.types.responses.Response`` carrying
    ``output: None`` — the exact payload the Codex backend sends in its
    ``response.completed`` SSE event.
    """
    from openai.types.responses.response import Response

    # The Pydantic model uses ``output: List[ResponseOutputItem]`` so
    # we have to construct via ``model_construct`` to bypass validation
    # — which mirrors what the SDK's internal SSE deserialiser does
    # when the wire payload says ``"output": null``.
    return Response.model_construct(
        id="resp_test",
        object="response",
        created_at=0.0,
        status="completed",
        output=None,  # the field that crashes parse_response
        model="gpt-5.5",
        instructions=None,
        usage=None,
        metadata={},
        parallel_tool_calls=False,
        tool_choice="auto",
        tools=[],
        temperature=None,
        top_p=None,
        max_output_tokens=None,
        previous_response_id=None,
        reasoning=None,
        text=None,
        truncation=None,
        user=None,
        incomplete_details=None,
        error=None,
        store=False,
    )


def test_unpatched_parse_response_raises_on_null_output() -> None:
    """Source-level pin on the upstream bug we are working around.

    Confirms the failure mode the patch addresses still exists in the
    installed SDK — if a future ``openai`` release fixes this, the test
    will start failing and we can delete the workaround module.
    """
    from core.llm.adapters import _codex_sdk_workaround as wa

    wa._for_test_restore()
    try:
        from openai.lib._parsing._responses import parse_response

        response = _make_response_with_null_output()
        with pytest.raises(TypeError, match=r"NoneType.*not iterable"):
            parse_response(text_format=openai.NotGiven(), input_tools=[], response=response)
    finally:
        wa.install()


def test_patched_parse_response_coerces_null_to_empty() -> None:
    """After ``install()``, ``parse_response`` returns cleanly on null output.

    The Codex adapter's own ``accumulated`` list rebuilds the real output
    items from the streamed ``response.output_item.done`` events, so the
    parsed snapshot being empty is fine — the visible-text-and-tools
    extraction in ``translate_codex_response`` reads from
    ``accumulated_items`` first.
    """
    from core.llm.adapters import _codex_sdk_workaround as wa

    wa.install()  # idempotent
    from openai.lib._parsing._responses import parse_response

    response = _make_response_with_null_output()
    parsed = parse_response(
        text_format=openai.NotGiven(),
        input_tools=[],
        response=response,
    )
    # Empty output list is the safe contract — the SDK consumer
    # (streaming accumulator) doesn't crash and our own accumulator
    # produces the real items separately.
    assert list(parsed.output) == [], (
        f"Patched parse_response returned non-empty output {parsed.output!r}; "
        f"the workaround should coerce only the None case."
    )


def test_install_is_idempotent_and_streaming_module_rebound() -> None:
    """Two installs leave both module references pointing at the patched fn.

    The streaming module imports ``parse_response`` at module load
    (``from ..._parsing._responses import ..., parse_response``) so a
    naive patch on only the source would leave the streaming module's
    local reference pointing at the original (unpatched) callable.
    """
    from core.llm.adapters import _codex_sdk_workaround as wa

    wa.install()
    wa.install()  # second call must be a no-op (no double-wrap)

    import openai.lib._parsing._responses as _parse_mod
    import openai.lib.streaming.responses._responses as _stream_mod

    assert _parse_mod.parse_response is _stream_mod.parse_response, (
        "_codex_sdk_workaround.install rebound the source but not the "
        "streaming module's local reference — the SDK's stream "
        "accumulator will still call the unpatched function."
    )


def test_codex_client_builder_installs_workaround() -> None:
    """Source-level pin: build_async_codex_client triggers install().

    Greps ``_openai_common.py`` for the install call so a future refactor
    that drops it (and silently re-introduces the crash on every
    subscription call) fails this test before the regression re-emerges.
    """
    common_source = (
        Path(__file__).resolve().parents[3] / "core" / "llm" / "adapters" / "_openai_common.py"
    ).read_text(encoding="utf-8")
    assert "_install_codex_workaround" in common_source, (
        "build_async_codex_client no longer installs the parse_response "
        "workaround; every Codex subscription call will TypeError on "
        "openai >= 2.26."
    )


def test_legacy_codex_provider_installs_workaround() -> None:
    """Source-level pin: legacy provider client builder also triggers install()."""
    provider_source = (
        Path(__file__).resolve().parents[3] / "core" / "llm" / "providers" / "codex.py"
    ).read_text(encoding="utf-8")
    assert "_codex_sdk_workaround" in provider_source, (
        "_get_async_codex_client no longer installs the parse_response "
        "workaround; the legacy provider path will crash on subscription."
    )


# Ensure the patch is re-applied for any downstream tests that may run
# after this module — leaving the SDK unpatched would break unrelated
# Codex subscription tests.
def teardown_module(module: object) -> None:
    from core.llm.adapters import _codex_sdk_workaround as wa

    wa.install()
