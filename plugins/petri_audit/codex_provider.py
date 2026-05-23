"""inspect_ai ModelAPI for OpenAI Codex (ChatGPT Plus OAuth subscription).

# OAuth 제약 + 검증 일정 (2026-05-14)
#
# 본 모듈 의 fix 의 집합 = PR #6 (initial bridge) + smoke 1..9 의
# post-smoke fixes (entry-points fast-path, count_tokens tiktoken
# override, async stream context, instructions placeholder). 모든 제약
# 인벤토리 + same-provider 옵션 + 2026-05-25 이후 의 검증 일정 의 SOT:
# ``docs/audits/2026-05-14-petri-oauth-constraints.md``.
#
# 본 PR 의 deliverable 은 코드 + bias 축 만. live audit 의 valid
# baseline 측정 은 ChatGPT backend 의 cybersecurity content filter
# (PR #5 trial 의 13/13 seed reject) 의 의존 → operator credential
# refresh 또는 Trusted Access program 가입 의 user-side 결정 의 후속.

Bridges ``inspect_ai`` (and therefore inspect-petri's judge / auditor)
into the Codex OAuth path that already lives in
``core/llm/providers/codex.py`` so judge calls consume the user's
ChatGPT Plus subscription quota instead of per-token billing.

Registered as ``@modelapi(name="openai-codex")`` from
``plugins/petri_audit/__init__.py`` (under the same try/except guard
as the GEODE target).

The provider name is exposed via ``inspect_ai`` model ids of the
form ``openai-codex/<model>`` — e.g. ``openai-codex/gpt-5.5``,
``openai-codex/gpt-5.4-mini``. ``plugins/petri_audit/models.py`` is
the auto-router: when a Codex OAuth token is available it rewrites
``gpt-5.*`` ids to that form; otherwise the legacy
``openai/<model>`` (per-token PAYG) path is kept.

Compatibility gaps with inspect_ai's stock ``OpenAIAPI`` (3-codebase
grounded in ``docs/research/codex-oauth-request-spec.md``):

- ``client.responses.create(**)`` (non-streaming) → ``responses.stream``
  required by chatgpt.com/backend-api/codex.
- ``max_output_tokens`` parameter → 400 ``Unsupported parameter`` on
  the Plus backend. Must be stripped.
- System prompt in ``input`` list as ``role:developer`` → Codex backend
  expects ``instructions=<system>`` field. Hermes / Codex Rust both
  shift system out of input.
- ``response.completed`` event from the Plus backend omits the
  ``output`` field, so ``stream.get_final_response().output == []``
  even when output items were emitted. Must accumulate
  ``response.output_item.done`` events (codex.py:331-344 pattern).

This module re-uses inspect_ai's input/tool/choice converters
(``openai_responses_inputs``, ``openai_responses_tools``,
``openai_responses_tool_choice``, ``openai_responses_chat_choices``)
so the wire-format converters are owned by exactly one place.
"""

from __future__ import annotations

from logging import getLogger
from typing import Any

logger = getLogger(__name__)

__all__ = [
    "get_codex_oauth_metadata",
    "is_codex_oauth_available",
    "register",
]


def get_codex_oauth_metadata() -> dict[str, Any] | None:
    """Return the Codex OAuth token's plan + account info verbatim.

    The Codex access token is a JWT whose ``https://api.openai.com/auth``
    claim carries the user's ``chatgpt_plan_type`` (e.g. ``"plus"``,
    ``"prolite"``, ``"team"`` — whatever ChatGPT issues), the
    ``chatgpt_account_id``, and the token's ``exp`` timestamp. The
    ``/auth`` picker UI surfaces these dynamically so the label
    matches whatever subscription the user is actually logged into —
    no plan enumeration is hardcoded.

    Returns ``None`` when:

    - no Codex OAuth token is reachable (``_resolve_codex_token``
      empty)
    - the token is not a valid JWT (parts != 3)
    - the JWT payload cannot be decoded
    """
    import base64
    import json

    try:
        from core.llm.providers.codex import _resolve_codex_token
    except ImportError:
        return None
    try:
        token = _resolve_codex_token()
    except Exception:
        return None
    if not token:
        return None
    parts = token.split(".")
    if len(parts) < 2:
        return None
    try:
        padded = parts[1] + "=" * (4 - len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
    except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
        return None
    auth_claim = payload.get("https://api.openai.com/auth", {})
    if not isinstance(auth_claim, dict):
        auth_claim = {}
    return {
        "plan_type": auth_claim.get("chatgpt_plan_type"),
        "account_id": auth_claim.get("chatgpt_account_id"),
        "user_id": auth_claim.get("chatgpt_user_id"),
        "expires_at": payload.get("exp"),
    }


def is_codex_oauth_available() -> bool:
    """True when a Codex OAuth token can be resolved.

    Read-only check — does not mutate any cached client. Used by
    ``plugins.petri_audit.models.to_inspect_model`` to auto-route
    gpt-5.x ids to the ``openai-codex/`` provider when a token is
    available, and to keep the per-token ``openai/`` path when not.
    """
    try:
        from core.llm.providers.codex import _resolve_codex_token
    except ImportError:
        return False
    try:
        return bool(_resolve_codex_token())
    except Exception:
        return False


def register() -> None:
    """Register ``OpenAICodexAPI`` with ``inspect_ai`` as ``openai-codex``.

    Imports ``inspect_ai`` lazily; raises ``ImportError`` if the
    ``[audit]`` optional extra is not installed. ``plugins/petri_audit/
    __init__.py`` wraps the call in try/except so the plugin remains
    importable on the default ``uv sync``.

    Calling ``register()`` more than once is safe — ``inspect_ai``'s
    registry replaces an existing entry of the same name.
    """
    from typing import Any as _Any

    from inspect_ai.model import modelapi
    from inspect_ai.model._providers.openai import OpenAIAPI as _StockOpenAIAPI

    @modelapi(name="openai-codex")
    class OpenAICodexAPI(_StockOpenAIAPI):  # type: ignore[misc, unused-ignore]
        """OAuth-routed variant of inspect_ai's stock ``OpenAIAPI``.

        Subclass invariants:

        - ``base_url`` is forced to ``CODEX_BASE_URL`` so every call
          lands on chatgpt.com/backend-api/codex regardless of the env
          ``OPENAI_BASE_URL``.
        - ``api_key`` is the OAuth access token (Bearer); parent's
          ``OPENAI_API_KEY`` env probe is short-circuited because we
          pre-populate ``kwargs["api_key"]``.
        - ``responses_api`` is forced ``True`` — Chat Completions is
          unsupported on the Plus backend.
        - ``responses_store`` is forced ``False`` — server-side state
          is rejected by the Plus backend.
        - ``generate()`` is overridden to use streaming, strip
          ``max_output_tokens``, move system into ``instructions=``,
          and apply the codex-rs output-item accumulator workaround.
        """

        def __init__(self, *args: _Any, **kwargs: _Any) -> None:
            from core.config import CODEX_BASE_URL
            from core.llm.providers.codex import (
                _resolve_codex_token,
                build_codex_oauth_headers,
            )
            from inspect_ai.model._providers.util import (
                environment_prerequisite_error,
            )

            token = kwargs.get("api_key") or _resolve_codex_token()
            if not token:
                raise environment_prerequisite_error(
                    "OpenAI Codex (ChatGPT Plus)",
                    [
                        "~/.codex/auth.json (Codex CLI login)",
                        "openai-codex profile in GEODE ProfileStore",
                    ],
                )

            # Stash token + account headers; ``_create_client`` reads
            # these because parent ``__init__`` calls ``initialize()``
            # which in turn calls ``self._create_client()`` BEFORE our
            # subclass attributes are normally set. We set them first
            # so the override is safe.
            self._codex_token = token
            self._codex_headers = build_codex_oauth_headers(token)

            kwargs["api_key"] = token
            kwargs["base_url"] = kwargs.get("base_url") or CODEX_BASE_URL
            kwargs["responses_api"] = True
            kwargs["responses_store"] = False

            super().__init__(*args, **kwargs)

        def _create_client(self) -> _Any:
            from inspect_ai.model._openai import OpenAIAsyncHttpxClient
            from inspect_ai.model._providers.util import model_base_url
            from openai import AsyncOpenAI
            from openai._types import NOT_GIVEN

            existing: _Any = getattr(self, "http_client", None)
            if existing is None or existing.is_closed:
                self.http_client = OpenAIAsyncHttpxClient()

            return AsyncOpenAI(
                api_key=self._codex_token,
                base_url=model_base_url(self.base_url, "OPENAI_BASE_URL"),
                http_client=self.http_client,
                default_headers=self._codex_headers,
                timeout=self.client_timeout if self.client_timeout is not None else NOT_GIVEN,
                **self.model_args,
            )

        async def count_tokens(
            self,
            input: _Any,
            config: _Any = None,
        ) -> int:
            """Force tiktoken-based local counting.

            Stock ``OpenAIAPI.count_tokens`` hits
            ``client.responses.input_tokens.count`` when ``responses_api=True``,
            but the ChatGPT Plus backend returns
            ``PermissionDeniedError`` on that endpoint. tiktoken handles
            local counting for gpt-5.x and avoids the round-trip, which
            also keeps subscription quota free for actual generations.

            Mirrors the non-responses-API branch in
            ``inspect_ai/model/_providers/openai.py:count_tokens`` so the
            return shape matches what callers like ``count_tool_tokens``
            and the compaction loop expect.
            """
            if isinstance(input, str):
                single: int = await self.count_text_tokens(input)
                return single
            from inspect_ai.model._tokens import count_tokens as _count_tokens

            multi: int = await _count_tokens(input, self.count_text_tokens, self.count_media_tokens)
            return multi

        async def generate(
            self,
            input: _Any,
            tools: _Any,
            tool_choice: _Any,
            config: _Any,
        ) -> _Any:
            from inspect_ai.log._samples import set_active_model_event_call
            from inspect_ai.model._generate_config import has_image_output
            from inspect_ai.model._model_call import as_error_response
            from inspect_ai.model._model_output import ModelOutput
            from inspect_ai.model._openai import (
                openai_handle_bad_request,
                openai_media_filter,
            )
            from inspect_ai.model._openai_responses import (
                openai_responses_chat_choices,
                openai_responses_inputs,
                openai_responses_tool_choice,
                openai_responses_tools,
            )
            from inspect_ai.model._providers.openai_responses import (
                completion_params_responses,
                model_usage_from_response,
            )
            from inspect_ai.tool._tools._computer._computer import (
                is_computer_tool_info,
            )
            from openai import BadRequestError
            from openai._types import NOT_GIVEN

            request_id = self._http_hooks.start_request()

            # Step I.b (2026-05-23) — Codex encrypted-reasoning replay is
            # owned by inspect_ai, NOT this subclass. ``openai_responses_inputs``
            # walks the ``ChatMessage`` list and translates every
            # ``inspect_ai.tool.ContentReasoning`` block on prior
            # ``ChatMessageAssistant`` turns into a Codex Responses-API
            # ``{"type": "reasoning", "encrypted_content": ...}`` typed
            # item (see ``inspect_ai/model/_openai_responses.py:1130-1131``
            # → ``responses_reasoning_from_reasoning`` at line 860). Petri's
            # ``OpenAICodexAPI`` therefore inherits A2's per-turn reasoning
            # replay for free across multi-turn audits — do NOT reimplement
            # the replay logic from
            # ``core.llm.adapters._openai_common.build_codex_input`` here;
            # that helper exists for the GEODE AgenticLoop's ``Message``
            # path, and the two should not drift. The integration is
            # smoke-tested by
            # ``tests/plugins/petri_audit/test_codex_reasoning_replay_inspect_pipeline.py``.
            raw_input_items = await openai_responses_inputs(
                input, self, synthesize_phase=self.responses_phase
            )
            instructions_parts: list[str] = []
            cleaned_input: list[_Any] = []
            for item in raw_input_items:
                role = item.get("role") if isinstance(item, dict) else getattr(item, "role", None)
                item_type = (
                    item.get("type") if isinstance(item, dict) else getattr(item, "type", None)
                )
                if item_type == "message" and role == "developer":
                    content = (
                        item.get("content")
                        if isinstance(item, dict)
                        else getattr(item, "content", None)
                    )
                    instructions_parts.append(_content_to_text(content))
                    continue
                cleaned_input.append(item)
            instructions = "\n\n".join(p for p in instructions_parts if p).strip()

            tool_params = (
                openai_responses_tools(tools, self.model_name, config)
                if (len(tools) > 0 or has_image_output(config.modalities))
                else NOT_GIVEN
            )

            params = completion_params_responses(
                self.service_model_name(),
                model_info=self,
                config=config,
                service_tier=self.service_tier,
                prompt_cache_key=self.prompt_cache_key,
                prompt_cache_retention=self.prompt_cache_retention,
                safety_identifier=self.safety_identifier,
                responses_store=False,
                tools=len(tools) > 0,
                tool_params=[] if not isinstance(tool_params, list) else tool_params,
                has_computer_tool=any(is_computer_tool_info(t) for t in tools),
            )
            # Codex backend rejects ``max_output_tokens`` (400).
            params.pop("max_output_tokens", None)

            request: dict[str, _Any] = dict(
                input=cleaned_input,
                tools=tool_params,
                tool_choice=openai_responses_tool_choice(tool_choice, tool_params)
                if isinstance(tool_params, list) and tool_choice != "auto" and len(tools) > 0
                else NOT_GIVEN,
                extra_headers={"X-Inspect-Request-Id": request_id} | (config.extra_headers or {}),
                **params,
            )
            # ChatGPT Plus backend's /responses endpoint rejects requests
            # missing the ``instructions`` field with
            # ``BadRequestError: 'Instructions are required'``. Stock OpenAI
            # API treats it as optional, but the Codex backend is strict.
            # When no system message was present in the input (e.g. petri's
            # judge call uses tool_choice instead of a system prompt), fall
            # back to a minimal placeholder so the field is non-empty.
            request["instructions"] = instructions or "You are a helpful assistant."
            if len(tools) > 0 and "parallel_tool_calls" not in request:
                request["parallel_tool_calls"] = (
                    True if config.parallel_tool_calls is None else config.parallel_tool_calls
                )

            model_call = set_active_model_event_call(request=request, filter=openai_media_filter)

            try:
                final_response = await _stream_and_accumulate(self.client, request)
                model_call.set_response(
                    final_response.model_dump(warnings=False),
                    self._http_hooks.end_request(request_id),
                )
                choices = openai_responses_chat_choices(
                    self.service_model_name(), final_response, tools
                )
                return (
                    ModelOutput(
                        model=final_response.model,
                        choices=choices,
                        usage=model_usage_from_response(final_response),
                    ),
                    model_call,
                )
            except BadRequestError as e:
                model_call.set_error(
                    as_error_response(e.body),
                    self._http_hooks.end_request(request_id),
                )
                return (
                    openai_handle_bad_request(self.service_model_name(), e),
                    model_call,
                )

    # Module-level alias so callers can isinstance-check / introspect
    # the registered type without re-running the decorator.
    globals()["OpenAICodexAPI"] = OpenAICodexAPI


async def _stream_and_accumulate(client: Any, request: dict[str, Any]) -> Any:
    """Streaming wrapper around ``client.responses.stream(...)``.

    Implements the codex.py:331-344 pattern: accumulate ``response.
    output_item.done`` events and use ``stream.get_final_response()``
    as a shell, overwriting ``final.output`` with the accumulated
    items because the chatgpt.com backend's ``response.completed``
    SSE payload omits the ``output`` field (proven against codex-rs
    ``ResponseCompleted`` struct).

    The ``AsyncOpenAI`` client returns ``AsyncResponseStreamManager``
    from ``client.responses.stream(...)``, which only supports the
    ``async with`` protocol and yields async iteration. The earlier
    ``asyncio.to_thread + sync with`` shape was for the sync
    ``OpenAI`` client; switching to the native async context manager
    matches the actual client type ``_create_client`` constructs.
    """
    async with client.responses.stream(**request) as stream:
        accumulated_items: list[Any] = []
        async for event in stream:
            if getattr(event, "type", "") == "response.output_item.done":
                item = getattr(event, "item", None)
                if item is not None:
                    accumulated_items.append(item)
        final = await stream.get_final_response()
        if accumulated_items:
            final.output = accumulated_items
        return final


def _content_to_text(content: Any) -> str:
    """Flatten an inspect_ai ``content`` field to plain text.

    Accepts the three shapes ``openai_responses_inputs`` may emit for
    a system/developer message: str, list[ContentTextParam], dict.
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for piece in content:
            if isinstance(piece, str):
                parts.append(piece)
            elif isinstance(piece, dict):
                txt = piece.get("text")
                if isinstance(txt, str):
                    parts.append(txt)
        return "\n".join(parts)
    if isinstance(content, dict):
        txt = content.get("text")
        return txt if isinstance(txt, str) else ""
    return ""
