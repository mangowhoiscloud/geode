"""Computer-use on the LIVE OpenAI Responses adapter path (Phase C).

Mirrors the Anthropic Phase-A guard (``test_computer_use_live_path.py``) for the
OpenAI Responses API GA computer-use tool (``{type: "computer"}`` on ``gpt-5.5``).
Both OpenAI live adapters (``OpenAIPaygAdapter`` backend="platform",
``CodexOAuthAdapter`` backend="codex") reach the wire through
``_openai_common.build_responses_kwargs`` — these tests pin the GA tool injection
on that builder, the ComputerUseCapable contract, and the ``computer_call`` /
``computer_call_output`` request+response round-trip.

Backend split (2026-06-17 live E2E, operator-authorized):

- ``backend="platform"`` (PAYG) — ctx7 confirms the Platform API CONTRACT
  (``/websites/developers_openai_api`` guides/tools-computer-use) AND a
  2026-06-17 operator-authorized live E2E confirmed backend ACCEPTANCE: the
  Platform backend accepts ``{type:"computer"}`` on gpt-5.5 and a full
  screenshot round-trip completes (model reads real pixels). The tool IS
  injected.
- ``backend="codex"`` (ChatGPT subscription) — live-REJECTED with
  ``400 Unsupported tool type: computer``. The GA docs are Platform-only, so
  the codex adapter advertises NO computer-use (``supports_computer_use=False``,
  ``computer_tool_param`` → ``None``) and the live builder never injects on it.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from core.llm.adapters import _openai_common as common
from core.llm.adapters.base import (
    AdapterCallRequest,
    ComputerUseCapable,
    Message,
    ToolSpec,
)
from core.tools.computer_use import TARGET_HEIGHT, TARGET_WIDTH

# Provider-agnostic opt-in accessor — shared by the Anthropic + OpenAI paths.
_ENABLED = "core.llm.providers.anthropic.is_computer_use_enabled"
_GA_MODEL = "gpt-5.5"
_NON_GA_MODEL = "gpt-5.4"


def _req(tools: tuple[ToolSpec, ...] = (), model: str = _GA_MODEL) -> AdapterCallRequest:
    return AdapterCallRequest(
        model=model,
        messages=(Message(role="user", content="hi"),),
        tools=tools,
    )


def _build(req: AdapterCallRequest, *, backend: str = "platform") -> dict[str, Any]:
    return common.build_responses_kwargs(req, backend=backend, adapter_name="test")


def _computer_tools(kwargs: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        t for t in kwargs.get("tools", []) if isinstance(t, dict) and t.get("type") == "computer"
    ]


class TestLivePathInjection:
    def test_injects_computer_tool_on_ga_model_when_enabled(self) -> None:
        with patch(_ENABLED, return_value=True):
            kwargs = _build(_req())
        computer = _computer_tools(kwargs)
        assert len(computer) == 1, kwargs.get("tools")
        # GA tool is BARE — dims/environment are preview-only; the GA tool takes
        # no params (geometry inferred from screenshots).
        assert computer[0] == {"type": "computer"}
        # OpenAI Responses has no per-tool beta header (unlike Anthropic).
        assert "extra_headers" not in kwargs

    def test_not_injected_on_non_ga_model(self) -> None:
        """A non-GA OpenAI model (gpt-5.4) must never be offered the GA tool —
        the backend rejects it and the preview shape is out of scope."""
        with patch(_ENABLED, return_value=True):
            kwargs = _build(_req(model=_NON_GA_MODEL))
        assert _computer_tools(kwargs) == []

    def test_not_injected_when_disabled(self) -> None:
        with patch(_ENABLED, return_value=False):
            kwargs = _build(_req())
        assert _computer_tools(kwargs) == []

    def test_injected_even_with_no_registry_tools(self) -> None:
        """Injection is not gated on ``req.tools`` — the GA tool is appended even
        when the request carries no registry tools (the list is created)."""
        with patch(_ENABLED, return_value=True):
            kwargs = _build(_req(tools=()))
        assert [t.get("type") for t in kwargs["tools"]] == ["computer"]

    def test_idempotent_no_double_inject(self) -> None:
        kwargs: dict[str, Any] = {"tools": [common.openai_computer_tool_param()]}
        with patch(_ENABLED, return_value=True):
            common._maybe_inject_openai_computer_use(kwargs, model=_GA_MODEL, backend="platform")
        assert len(_computer_tools(kwargs)) == 1

    def test_codex_backend_never_injected(self) -> None:
        """The ChatGPT-subscription Codex backend proven-rejects the GA tool
        (``400 Unsupported tool type: computer``, 2026-06-17 live E2E), so the
        builder must never inject it even on a GA model with the opt-in on."""
        with patch(_ENABLED, return_value=True):
            kwargs = _build(_req(), backend="codex")
        assert _computer_tools(kwargs) == []

    def test_dated_ga_model_id_resolves_to_ga(self) -> None:
        """A dated id suffix (``gpt-5.5-20260601``) is stripped before the GA
        lookup, so dated GA ids still get the tool."""
        with patch(_ENABLED, return_value=True):
            kwargs = _build(_req(model="gpt-5.5-20260601"))
        assert len(_computer_tools(kwargs)) == 1


class TestComputerUseCapableContract:
    def test_platform_adapter_advertises_computer_use(self) -> None:
        """The PAYG/platform adapter conforms to ComputerUseCapable AND
        advertises support (``supports_computer_use=True``) — the GA tool is
        documented for the Platform API (acceptance still ``unverified``)."""
        from core.llm.adapters.openai_payg import OpenAIPaygAdapter

        adapter = OpenAIPaygAdapter()
        assert isinstance(adapter, ComputerUseCapable)
        assert adapter.supports_computer_use is True

    def test_codex_adapter_advertises_no_computer_use(self) -> None:
        """The codex (subscription) adapter is structurally ComputerUseCapable
        but advertises NO support: ``supports_computer_use=False`` and its
        enumerable ``computer_tool_param`` returns ``None`` — the backend
        proven-rejects the GA tool (2026-06-17 live E2E)."""
        from core.llm.adapters.codex_oauth import CodexOAuthAdapter

        adapter = CodexOAuthAdapter()
        assert adapter.supports_computer_use is False
        assert (
            adapter.computer_tool_param(display_width=TARGET_WIDTH, display_height=TARGET_HEIGHT)
            is None
        )

    def test_adapter_param_matches_injected_param(self) -> None:
        """The platform enumerable contract (``computer_tool_param``) must return
        the exact payload the live builder injects — no drift."""
        from core.llm.adapters.openai_payg import OpenAIPaygAdapter

        adapter = OpenAIPaygAdapter()
        from_method = adapter.computer_tool_param(
            display_width=TARGET_WIDTH, display_height=TARGET_HEIGHT
        )
        with patch(_ENABLED, return_value=True):
            injected = _computer_tools(_build(_req()))[0]
        assert from_method == injected

    def test_codex_param_none_matches_excluded_live_path(self) -> None:
        """Codex enumerable contract (``None``) mirrors the live path, which
        injects nothing on ``backend="codex"`` — the no-drift invariant in the
        rejected direction."""
        from core.llm.adapters.codex_oauth import CodexOAuthAdapter

        adapter = CodexOAuthAdapter()
        from_method = adapter.computer_tool_param(
            display_width=TARGET_WIDTH, display_height=TARGET_HEIGHT
        )
        with patch(_ENABLED, return_value=True):
            injected = _computer_tools(_build(_req(), backend="codex"))
        assert from_method is None
        assert injected == []


class _FakeUsage:
    input_tokens = 1
    output_tokens = 1
    input_tokens_details = None


class _FakeResponse:
    """Minimal stand-in for an OpenAI ``Response`` with typed output items."""

    def __init__(self, output: list[Any]) -> None:
        self.output = output
        self.output_text = ""
        self.status = "completed"
        self.usage = _FakeUsage()


class TestComputerCallParsing:
    def test_computer_call_parsed_to_computer_tool_use(self) -> None:
        """A GA ``computer_call`` output item → a uniform ``computer`` tool_use
        carrying the batched ``actions`` (correlated by ``call_id``)."""
        item = {
            "type": "computer_call",
            "call_id": "cc_123",
            "actions": [
                {"type": "click", "x": 10, "y": 20, "button": "left"},
                {"type": "screenshot"},
            ],
        }
        result = common.translate_codex_response(_FakeResponse([item]))
        assert len(result.tool_uses) == 1
        call = result.tool_uses[0]
        assert call["id"] == "cc_123"
        assert call["name"] == "computer"
        assert call["input"]["actions"] == item["actions"]

    def test_computer_call_single_action_wrapped_into_list(self) -> None:
        """A lone ``action`` (defensive) is wrapped into a single-element
        ``actions`` list so the handler's batch path is the only code path."""
        item = {
            "type": "computer_call",
            "call_id": "cc_1",
            "action": {"type": "click", "x": 1, "y": 2},
        }
        result = common.translate_codex_response(_FakeResponse([item]))
        call = result.tool_uses[0]
        assert call["input"]["actions"] == [{"type": "click", "x": 1, "y": 2}]

    def test_computer_call_preserves_pending_safety_checks(self) -> None:
        item = {
            "type": "computer_call",
            "call_id": "cc_2",
            "actions": [{"type": "screenshot"}],
            "pending_safety_checks": [{"id": "sc_1", "code": "malicious_instructions"}],
        }
        result = common.translate_codex_response(_FakeResponse([item]))
        call = result.tool_uses[0]
        assert call["input"]["pending_safety_checks"] == item["pending_safety_checks"]

    def test_function_call_still_parsed_alongside(self) -> None:
        """The ordinary ``function_call`` path is unchanged by the new branch."""
        items = [
            {"type": "function_call", "call_id": "fc_1", "name": "read_file", "arguments": "{}"},
            {"type": "computer_call", "call_id": "cc_1", "actions": [{"type": "wait"}]},
        ]
        result = common.translate_codex_response(_FakeResponse(items))
        names = {tu["name"] for tu in result.tool_uses}
        assert names == {"read_file", "computer"}


class TestComputerCallOutputFormatting:
    def test_computer_screenshot_result_becomes_computer_call_output(self) -> None:
        """A computer-use ``tool_result`` (image block) → ``computer_call_output``
        carrying a ``computer_screenshot`` data-URL image (JPEG, per harness)."""
        tool_result = {
            "type": "tool_result",
            "tool_use_id": "cc_9",
            "content": [
                {"type": "text", "text": '{"result": "success"}'},
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": "image/jpeg", "data": "B64"},
                },
            ],
        }
        req = AdapterCallRequest(
            model=_GA_MODEL,
            messages=(Message(role="user", content=[tool_result]),),
        )
        resp_input = common.build_codex_input(req)
        outputs = [i for i in resp_input if i.get("type") == "computer_call_output"]
        assert len(outputs) == 1
        out = outputs[0]
        assert out["call_id"] == "cc_9"
        assert out["output"] == {
            "type": "computer_screenshot",
            "image_url": "data:image/jpeg;base64,B64",
        }
        # Ordinary function_call_output must NOT be emitted for this block.
        assert not any(i.get("type") == "function_call_output" for i in resp_input)

    def test_ordinary_tool_result_stays_function_call_output(self) -> None:
        tool_result = {
            "type": "tool_result",
            "tool_use_id": "fc_9",
            "content": '{"ok": true}',
        }
        req = AdapterCallRequest(
            model=_GA_MODEL,
            messages=(Message(role="user", content=[tool_result]),),
        )
        resp_input = common.build_codex_input(req)
        assert any(i.get("type") == "function_call_output" for i in resp_input)
        assert not any(i.get("type") == "computer_call_output" for i in resp_input)

    def test_acknowledged_safety_checks_echoed_from_meta(self) -> None:
        """When the agent echoes ``acknowledged_safety_checks`` in the result
        meta, the ``computer_call_output`` carries them back to clear the
        backend's ``pending_safety_checks``."""
        import json

        meta = {"result": "success", "acknowledged_safety_checks": [{"id": "sc_1"}]}
        tool_result = {
            "type": "tool_result",
            "tool_use_id": "cc_ack",
            "content": [
                {"type": "text", "text": json.dumps(meta)},
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": "image/jpeg", "data": "B64"},
                },
            ],
        }
        req = AdapterCallRequest(
            model=_GA_MODEL,
            messages=(Message(role="user", content=[tool_result]),),
        )
        out = next(
            i for i in common.build_codex_input(req) if i.get("type") == "computer_call_output"
        )
        assert out["acknowledged_safety_checks"] == [{"id": "sc_1"}]


class TestComputerCallReplay:
    """Regression (Codex BLOCKER): the prior assistant ``computer`` tool_use must
    replay as a ``computer_call`` item, NOT a ``function_call`` — else it cannot
    pair with the next-turn ``computer_call_output`` (type mismatch on the same
    ``call_id``), the half-wired failure Phase A fixed for Anthropic."""

    def test_assistant_computer_tool_use_replays_as_computer_call(self) -> None:
        actions = [{"type": "click", "x": 5, "y": 6}]
        tool_use = {
            "type": "tool_use",
            "id": "cc_replay",
            "name": "computer",
            "input": {"actions": actions, "pending_safety_checks": [{"id": "sc_1"}]},
        }
        req = AdapterCallRequest(
            model=_GA_MODEL,
            messages=(Message(role="assistant", content=[tool_use]),),
        )
        items = common.build_codex_input(req)
        calls = [i for i in items if i.get("type") == "computer_call"]
        assert len(calls) == 1, items
        assert calls[0]["call_id"] == "cc_replay"
        assert calls[0]["actions"] == actions
        assert calls[0]["pending_safety_checks"] == [{"id": "sc_1"}]
        # The computer tool_use must NOT also (or instead) become a function_call.
        assert not any(i.get("type") == "function_call" for i in items)

    def test_ordinary_assistant_tool_use_still_replays_as_function_call(self) -> None:
        tool_use = {
            "type": "tool_use",
            "id": "fc_replay",
            "name": "read_file",
            "input": {"path": "x"},
        }
        req = AdapterCallRequest(
            model=_GA_MODEL,
            messages=(Message(role="assistant", content=[tool_use]),),
        )
        items = common.build_codex_input(req)
        assert any(
            i.get("type") == "function_call" and i.get("call_id") == "fc_replay" for i in items
        )
        assert not any(i.get("type") == "computer_call" for i in items)
