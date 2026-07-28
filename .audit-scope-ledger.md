# Prompt-grammar alignment — Phase 0 scope ledger (24e8b3c08, 2026-07-28T21:50:09Z)

## S1. ClaudeAgenticAdapter (dead cache apparatus) — instantiation census
```
$ grep -rn 'ClaudeAgenticAdapter(' core/ plugins/ --include='*.py'
$ grep -rn 'ClaudeAgenticAdapter' core/llm/adapters/registry.py | wc -l
       0
$ grep -rln 'ClaudeAgenticAdapter' tests/
tests/core/llm/test_provider_parity_v0532.py
tests/core/llm/test_tool_search_defer_wire.py
tests/core/llm/test_anthropic_agentic_stream.py
tests/core/llm/test_anthropic_sampling_params.py
tests/core/llm/adapters/test_computer_use_live_path.py
tests/core/self_improving/test_m4_4_in_context_wiring.py
```

## S2. Cache apparatus location vs production path
```
$ grep -n 'cache_control\|PROMPT_CACHE_BOUNDARY\|apply_messages_cache_control\|_static_system_cache_control' core/llm/providers/anthropic.py | head -20
417:    """Convert a system prompt string to content block format with cache_control.
429:            cache_control={"type": "ephemeral"},
434:def _static_system_cache_control() -> dict[str, str]:
435:    """``cache_control`` for the stable static system prefix (agentic adapter).
440:    ephemeral ``cache_control`` (no beta header). The 2x write premium amortizes
461:# Anthropic allows up to 4 cache_control breakpoints per request.  The agentic
486:    """Whether :func:`apply_messages_cache_control` would actually attach a
505:    """Indices of non-system messages to mark with ``cache_control``.
557:def apply_messages_cache_control(
562:    """Return a copy of *messages* with ephemeral cache_control on up to
572:    Mirrors Hermes ``apply_anthropic_cache_control`` (system_and_3) and
601:            # cache_control cannot be set for empty text blocks``.
602:            # Skip cache_control whenever the message body is empty;
613:                    "cache_control": {"type": "ephemeral"},
620:            # rejects ``{"type":"text","text":"","cache_control":...}``
624:            last_block["cache_control"] = {"type": "ephemeral"}
726:    {"name", "description", "input_schema", "cache_control", "type", "strict", "defer_loading"}
1065:            # cache_control for reuse across turns; dynamic content after
1067:            from core.agent.system_prompt import PROMPT_CACHE_BOUNDARY
1069:            if PROMPT_CACHE_BOUNDARY in system:
$ grep -n 'cache_control\|PROMPT_CACHE_BOUNDARY' core/llm/adapters/_anthropic_common.py core/llm/adapters/anthropic_oauth.py
```

## S3. apply_in_context_slots (S5 slots) callers
```
$ grep -rn 'apply_in_context_slots' core/ plugins/ --include='*.py'
core/llm/providers/anthropic.py:957:        # path inside ``apply_in_context_slots`` when no SoT is
core/llm/providers/anthropic.py:962:        from core.self_improving.loop.inject.in_context_wiring import apply_in_context_slots
core/llm/providers/anthropic.py:964:        messages, system = apply_in_context_slots(messages, system=system)
core/self_improving/loop/inject/in_context_wiring.py:58:__all__ = ["apply_in_context_slots"]
core/self_improving/loop/inject/in_context_wiring.py:61:def apply_in_context_slots(
```

## S4. codex resp_input WARNING false positive
```
$ sed -n '554,560p' core/llm/adapters/codex_oauth.py
    if not isinstance(resp_input, list) or not resp_input:
        return
    has_null = any(isinstance(m, dict) and m.get("content") is None for m in resp_input[:cap])
    if not (has_null or log.isEnabledFor(logging.DEBUG)):
        return
    shape_parts: list[str] = []
    for idx, item in enumerate(resp_input[:cap]):
$ grep -n 'content.*None' tests/core/llm/test_codex_oauth_input_shape_diagnostic.py
10:the prefix carries any ``content=None`` entry (and at DEBUG unconditionally)
21:def test_log_emits_warning_when_any_content_is_null(caplog) -> None:  # type: ignore[no-untyped-def]
22:    """``content=None`` anywhere in the first 30 entries triggers WARN."""
25:        {"role": "assistant", "content": None},  # the offending entry
31:    assert matching, "no WARN emitted despite content=None in prefix"
34:    assert "[1]assistant content=None" in msg
38:def test_log_silent_when_all_content_present_and_not_debug(caplog) -> None:  # type: ignore[no-untyped-def]
67:        {"role": "user", "content": None},  # forces WARN
76:    assert "[2]user content=None" in msg
```

## S5. reflection tool_uses input type asymmetry
```
$ grep -n 'isinstance(payload, dict)\|def _extract_reflection_input' core/agent/loop/_reflection.py
166:def _extract_reflection_input(result: Any) -> dict[str, Any] | None:
188:                if isinstance(payload, dict):
196:            if isinstance(payload, dict):
$ grep -n 'input=' core/llm/adapters/_anthropic_common.py | head -3
$ grep -n 'arguments' core/llm/adapters/_openai_common.py | grep -n 'input\|ToolUse' | head -5
768:                        "arguments": json.dumps(block.get("input", {}), ensure_ascii=False),
894:                        "arguments": json.dumps(block.get("input", {}), ensure_ascii=False),
1038:                    "input": getattr(fn, "arguments", "{}"),
1155:                    "input": _attr_or_key(item, "arguments") or "{}",
$ grep -n 'json.loads' core/llm/adapters/translation.py | head -3
143:                input_field = json.loads(input_field) if input_field else {}
```

## S6. Post-envelope XML injections (unification targets)
```
$ grep -n '_system_suffix\|dynamic_context' core/agent/loop/_context.py core/agent/system_prompt.py | head -12
core/agent/system_prompt.py:57:PROMPT_CACHE_BOUNDARY = "<dynamic_context>"
core/agent/system_prompt.py:250:      <dynamic_context>    ──── changes per turn → no cache
core/agent/system_prompt.py:259:      </dynamic_context>
core/agent/system_prompt.py:304:        return static + "\n\n" + AGENTIC_SUFFIX + "\n\n" + dynamic + "\n\n</dynamic_context>"
core/agent/system_prompt.py:367:    # markdown, cache-stable] // <dynamic_context> [injected per-turn XML
core/agent/system_prompt.py:368:    # envelopes] </dynamic_context>. Moving the suffix out of the loop-level
core/agent/system_prompt.py:380:        + "\n\n</dynamic_context>"
core/agent/loop/_context.py:115:        # its authored-static zone (before <dynamic_context>), so memory
core/agent/loop/_context.py:120:    if loop._system_suffix:
core/agent/loop/_context.py:121:        prompt += "\n\n" + loop._system_suffix
$ grep -n 'decomposition_hint\|preflight_hint\|reflection_hint\|plan_hint' core/agent/loop/agent_loop.py | head -12
954:        decomposition_hint: str | None,
955:        reflection_hint: str | None = None,
969:            if decomposition_hint:
970:                system_prompt += "\n\n" + decomposition_hint
971:            if reflection_hint:
972:                system_prompt += "\n\n" + reflection_hint
974:            _plan_consume = getattr(self, "_consume_plan_hint", None)
975:            plan_hint = _plan_consume() if callable(_plan_consume) else ""
976:            if isinstance(plan_hint, str) and plan_hint:
977:                system_prompt += "\n\n" + plan_hint
1459:    def _consume_plan_hint(self) -> str:
1477:    def _consume_reflection_hint(self) -> str:
$ sed -n '1893,1910p' core/agent/loop/agent_loop.py
        if decomposition_hint:
            system_prompt += "\n\n" + decomposition_hint
        if preflight_hint:
            system_prompt += "\n\n" + preflight_hint

        # Failure reflection injection — prepend the prior turn's verify-FAIL
        # analysis (consume semantics; cleared after read).
        reflection_hint = self._consume_reflection_hint()
        if reflection_hint:
            system_prompt += "\n\n" + reflection_hint

        # Plan injection — render the current-step ``<plan>`` block
        # (read-only consume; plan persists until advance / replan).
        plan_hint = self._consume_plan_hint()
        if plan_hint:
            system_prompt += "\n\n" + plan_hint

        # Prune old messages to stay within context budget (Karpathy P6)
$ sed -n '965,980p' core/agent/loop/agent_loop.py
        drift_detected = await self._sync_model_from_settings_async()
        prompt_dirty = self._prompt_dirty
        if drift_detected or prompt_dirty:
            system_prompt = self._build_system_prompt()
            if decomposition_hint:
                system_prompt += "\n\n" + decomposition_hint
            if reflection_hint:
                system_prompt += "\n\n" + reflection_hint
            # re-apply the active plan on rebuild (getattr tolerates stub loops)
            _plan_consume = getattr(self, "_consume_plan_hint", None)
            plan_hint = _plan_consume() if callable(_plan_consume) else ""
            if isinstance(plan_hint, str) and plan_hint:
                system_prompt += "\n\n" + plan_hint
            self._prompt_dirty = False
            # Fire PROMPT_ASSEMBLED on each per-round rebuild (no-op if no hooks)
            hooks = getattr(self, "_hooks", None)
```

## S7. Hangul in model-facing strings (full sweep)
```
$ grep -rn '[가-힣]' core/llm/prompts/ core/llm/prompt_assembler.py 2>/dev/null | head
core/llm/prompt_assembler.py:15:- Inline math: wrap with `$...$` (예: 수익률은 $r_t = (P_t - P_{t-1}) / P_{t-1}$ 입니다).
$ grep -rln '[가-힣]' core/tools/*.py | while read f; do echo "== $f"; grep -n '[가-힣]' "$f" | grep -iE 'description|example|prompt|instruction' | head -3; done
== core/tools/calendar_tools.py
30:            "Examples: '내일 일정 뭐 있어?', 'show my schedule for next week'"
101:            "Examples: '금요일 3시에 분석 미팅 잡아줘', 'schedule a meeting tomorrow at 2pm'"
== core/tools/memory_tools.py
$ grep -rn '[가-힣]' core/agent/system_prompt.py core/agent/loop/_reflection.py core/agent/loop/_context.py | head -5
core/agent/loop/_context.py:87:        # SoT 가 부재면 apply_*_policy 는 registry.get_context_block() 에
core/agent/loop/_context.py:88:        # 위임 (no behavior change). 정책이 있으면 per-skill description /
core/agent/loop/_context.py:89:        # user_invocable override 적용.
core/agent/loop/_reflection.py:339:        # ADR-012 S0b — 5축의 ``reflection`` SoT 가 인퍼런스 경로에서
core/agent/loop/_reflection.py:340:        # 실제로 적용되는 단일 지점. 정책이 부재하면 ``apply_reflection_policy``
```

## S8. Codex replay id-retention asymmetry + store= usage
```
$ grep -n 'store' core/llm/adapters/_openai_common.py core/llm/adapters/codex_oauth.py | grep -v history | head -8
core/llm/adapters/codex_oauth.py:157:        - ``store = False`` is required.
core/llm/adapters/codex_oauth.py:171:        (``store=False`` makes server-side resolution by id impossible).
core/llm/adapters/codex_oauth.py:259:        ``instructions`` for system text, ``store=False``, no
core/llm/adapters/codex_oauth.py:291:        Codex backend requires ``store=False`` (same constraint as
core/llm/adapters/codex_oauth.py:340:            "store": False,
core/llm/adapters/codex_oauth.py:393:                    ("geode_profile_store", "no openai-codex profile"),
core/llm/adapters/_openai_common.py:874:                # half-wired failure Phase A fixed for Anthropic). The stored
core/llm/adapters/_openai_common.py:1149:            # unstable under ``store=False``). Mirrors the legacy normaliser
$ sed -n '603,614p' core/llm/adapters/_openai_common.py
            if m.codex_output_items and not disable_output_replay:
                out.extend(_responses_input_safe_output_item(item) for item in m.codex_output_items)
                continue
            # Replay this turn's encrypted reasoning items (id-stripped)
            # right before the assistant's converted entries.
            for ri in m.codex_reasoning_items:
                if not isinstance(ri, dict) or not ri.get("encrypted_content"):
                    continue
                replayed = {k: v for k, v in ri.items() if k != "id"}
                # PR-CODEX-MULTITURN-SUMMARY-PRESERVE (2026-05-26,
                # Codex MCP catch) — defensive injection at the
                # replay layer. The capture-path fix at
$ sed -n '1315,1328p' core/llm/adapters/_openai_common.py
def _responses_input_safe_output_item(item: dict[str, Any]) -> dict[str, Any]:
    """Return a prior Responses output item in the shape Codex accepts as input.

    OpenAI documents manual context management as passing prior ``response.output``
    items into the next ``input`` array. The Codex subscription validator rejects
    top-level ``status`` on replayed reasoning items, even though that field is
    populated on API-returned output items. Preserve the semantic payload and
    item ids, but drop return-only lifecycle metadata before sending it back.
    """
    safe = _json_safe(dict(item))
    if isinstance(safe, dict):
        return {k: v for k, v in safe.items() if k != "status" and v is not None}
    return dict(item)

```

## S9. GEODE.md stale tool count
```
$ grep -n '66' GEODE.md | head -2; python3 -c "import json; print('definitions.json tools:', len(json.load(open('core/tools/definitions.json'))))"
9:Agent: GEODE, a general-purpose autonomous execution agent built on a `while(tool_use)` loop. Natural-language requests are read, the right tool is selected from the 66 available, results are observed, and the next action is chosen — repeating until the task is actually done.
66:RUNTIME:  ToolRegistry(66), MCP Registry, Skills, Memory(5-Tier), Reports
definitions.json tools: 78
```

## S10. build_codex_input system-role guard parity
```
$ grep -n 'role.*system\|skip' core/llm/adapters/agentic_response.py | head -5
$ sed -n '630,636p' core/llm/adapters/_openai_common.py
        if m.role == "user":
            out.extend(_convert_user_msg_to_responses(m.content))
            continue
        out.append({"role": m.role, "content": _stringify(m.content)})
    return out


```

## S11. Legacy candidates census (adapters/prompt paths never referenced)
```
$ for c in $(grep -rhoE 'class [A-Za-z]+Adapter' core/llm/ | awk '{print $2}' | sort -u); do n=$(grep -rn "$c(" core/ plugins/ --include='*.py' | grep -v "class $c" | wc -l | tr -d ' '); echo "$c instantiations=$n"; done
AnthropicOAuthAdapter instantiations=0
AnthropicPaygAdapter instantiations=0
ClaudeAgenticAdapter instantiations=0
ClaudeCliAdapter instantiations=0
CodexCliAdapter instantiations=0
CodexOAuthAdapter instantiations=0
GlmCodingPlanAdapter instantiations=0
GlmPaygAdapter instantiations=0
LLMAdapter instantiations=0
OpenAIAdapter instantiations=0
OpenAIPaygAdapter instantiations=0
$ grep -n 'legacy' core/agent/system_injection.py core/agent/system_prompt.py | head -5
core/agent/system_injection.py:113:    A legacy reminder persisted at position 0 by the pre-2026-06-10 prepend
core/agent/system_injection.py:149:    """Check if a message is a system reminder (for legacy-prefix strip)."""
core/agent/system_prompt.py:226:    legacy date guard for Anthropic, GLM, and unknown providers, where it still
```

## S12. system-reminder breakpoint burn site
```
$ sed -n '528,548p' core/llm/providers/anthropic.py
    markable = [i for i in non_system if _is_markable(messages[i].get("content"))]
    if not markable:
        return []

    total_blocks = sum(_content_block_count(messages[i].get("content")) for i in non_system)
    if total_blocks <= _CACHE_LOOKBACK_BLOCKS:
        return markable[-n_breakpoints:]

    # ``end_offset[idx]`` = content blocks AFTER ``idx``'s final block (0 for the
    # very last message). Walk from the end accumulating each message's own block
    # count *after* recording, so the distance between two breakpoints is the
    # difference of their end_offsets.
    end_offset: dict[int, int] = {}
    acc = 0
    for idx in reversed(non_system):
        end_offset[idx] = acc
        acc += _content_block_count(messages[idx].get("content"))

    selected = [markable[-1]]
    last_offset = end_offset[markable[-1]]
    for idx in reversed(markable[:-1]):
```

## S11-보정. 어댑터 census 정정 — registry 등록 방식 확인 (S11의 '전부 0'은 grep 패턴 한계)
```
$ grep -n 'Adapter' core/llm/adapters/registry.py | grep -vE '^\s*#' | head -20
1:"""LLMAdapter registry — mutable global lookup.
5:- ``registerServerAdapter(adapter)`` → :func:`register_adapter`
6:- ``unregisterServerAdapter(type)`` → :func:`unregister_adapter`
7:- ``requireServerAdapter(type)`` → :func:`get_adapter`
30:    LLMAdapter,
36:_REGISTRY: dict[str, LLMAdapter] = {}
39:class AdapterAlreadyRegisteredError(RuntimeError):
43:class AdapterNotFoundError(KeyError):
47:def register_adapter(adapter: LLMAdapter, *, replace: bool = False) -> None:
50:    Re-registration with ``replace=False`` raises :class:`AdapterAlreadyRegisteredError`
64:        raise AdapterAlreadyRegisteredError(
81:def get_adapter(name: str) -> LLMAdapter:
84:    Raises :class:`AdapterNotFoundError` when missing.
89:        raise AdapterNotFoundError(
94:def list_adapters() -> list[LLMAdapter]:
103:    :meth:`LLMAdapter.test_environment` probe so picker UIs / readiness
142:def resolve_for(provider: str, source: str) -> LLMAdapter:
152:    AdapterUnavailableError) showed convention-enforced translation does
162:    Raises :class:`AdapterNotFoundError` when no adapter matches.
178:        raise AdapterNotFoundError(
```
판정: ClaudeAgenticAdapter만 registry 부재(진짜 dead). 나머지는 registry 경유 생성 — census의 0은 오탐.

## S13. 힌트/서픽스의 현재 포맷 (XML 통일 대상 상태)
```
$ grep -n 'decomposition\|<' core/agent/loop/_decompose*.py 2>/dev/null | head -4
core/agent/loop/agent_loop.py:1877:            decomposition_hint = await self._try_decompose(user_input)
core/agent/loop/agent_loop.py:1825:            preflight_hint = render_preflight_hint(self._task_preflight)
core/agent/loop/agent_loop.py:1872:        preflight_hint = self._prepare_task_preflight(user_input)
$ reflection/plan tag 확인
261:    ``<reflection>`` block that the next ``AgenticLoop.arun`` can prepend.
267:    lines = ["<reflection>", "Self-evaluation flagged the previous turn:"]
275:    lines.append("</reflection>")
core/agent/loop/agent_loop.py:1460:        """Render the active :class:`Plan` as a ``<plan>...</plan>`` block.
core/agent/loop/agent_loop.py:1904:        # Plan injection — render the current-step ``<plan>`` block
core/agent/plan.py:259:    """Render the current plan state as a `<plan>...</plan>` block.
$ _system_suffix 주입원
core/agent/prompt_dump.py:23:``_system_suffix`` (e.g. the Petri seed scenario). The dump covers the
core/agent/verify.py:24:  prepend this to the next round's ``loop._system_suffix`` so the model
core/agent/loop/agent_loop.py:381:        self._system_suffix = system_suffix
```

## S14. legacy index-0 reminder strip (Compat 1-release grace 초과 후보)
```
$ sed -n '108,135p' core/agent/system_injection.py

    The input list is NOT modified — the reminder exists only in the
    per-request copy, never in the stored conversation history (see module
    docstring for the prompt-cache contract this protects).

    A legacy reminder persisted at position 0 by the pre-2026-06-10 prepend
    design is stripped, so long-lived sessions converge to a stable prefix
    after one call.

    Args:
        messages: Conversation history (left untouched).
        model: Current model name (for context).
        round_idx: Current round index in the agentic loop.
        extra_context: Additional key-value pairs to include.

    Returns:
        A new list ``[*history, reminder]`` — or the input list unchanged
        when there is nothing to inject.
    """
    base = messages
    if base and _is_system_reminder(base[0]):
        base = base[1:]

    reminder = build_system_reminder(
        model=model,
        round_idx=round_idx,
        extra_context=extra_context,
    )
```

## S15. providers/ 전수 census — adapters 단일 진입점화 대상 분류
```
$ ls core/llm/providers/ && wc -l core/llm/providers/*.py | tail -1
__init__.py
anthropic.py
codex.py
glm.py
openai.py
    1902 total

$ 클래스별 외부(자기 모듈 제외, tests 제외) 참조 수
anthropic.ClaudeAgenticAdapter prod_refs=2 test_files=6
codex._ResolvedCodexToken prod_refs=0 test_files=1
openai.OpenAIAdapter prod_refs=2 test_files=3

$ 모듈 단위 import 참조 (프로덕션)
providers/anthropic.py imported_by_prod=19
providers/codex.py imported_by_prod=9
providers/glm.py imported_by_prod=7
providers/openai.py imported_by_prod=4
```

## S16. providers/ 심볼별 프로덕션 임포트 상세 (keep/move/delete 판정 근거)
```
$ grep -rn 'from core.llm.providers' core/ plugins/ --include='*.py' | grep -v 'core/llm/providers/'
core/llm/fallback.py:150:            from core.llm.providers.openai import reset_openai_client
core/llm/provider_dispatch.py:60:    from core.llm.providers.anthropic import RETRYABLE_ERRORS
core/llm/provider_dispatch.py:74:    from core.llm.providers.anthropic import get_anthropic_client
core/tools/computer_grounding.py:142:    from core.llm.providers.glm import _get_async_glm_client
core/llm/adapters/glm_payg.py:40:from core.llm.providers.glm import build_glm_reasoning_extra_body
core/llm/adapters/_anthropic_common.py:60:    from core.llm.providers.anthropic import (
core/llm/adapters/_anthropic_common.py:178:    from core.llm.providers.anthropic import is_computer_use_enabled
core/llm/adapters/_anthropic_common.py:240:    from core.llm.providers.anthropic import apply_tool_search_defer
core/llm/adapters/glm_coding_plan.py:46:from core.llm.providers.glm import build_glm_reasoning_extra_body
core/llm/router/calls/_failover.py:63:    from core.llm.providers.anthropic import (
core/llm/router/calls/_failover.py:66:    from core.llm.providers.anthropic import (
core/llm/adapters/_openai_common.py:405:    from core.llm.providers.codex import build_codex_oauth_headers
core/llm/adapters/_openai_common.py:717:    from core.llm.providers.anthropic import is_computer_use_enabled
core/llm/adapters/codex_oauth.py:125:        from core.llm.providers.codex import _resolve_codex_token_info
core/llm/adapters/codex_oauth.py:386:        from core.llm.providers.codex import _resolve_codex_token
core/llm/adapters/codex_oauth.py:433:        from core.llm.providers.codex import _resolve_codex_token
core/llm/router/calls/text.py:13:from core.llm.providers.anthropic import get_anthropic_client
core/llm/router/calls/text.py:14:from core.llm.providers.anthropic import (
core/llm/router/calls/text.py:17:from core.llm.providers.anthropic import (
core/agent/loop/_response.py:51:        from core.llm.providers.anthropic import is_computer_use_enabled
core/agent/loop/_tool_factory.py:55:        from core.llm.providers.anthropic import is_computer_use_enabled
core/cli/quota_banner.py:415:        from core.llm.providers.anthropic import register_quota_setter
core/agent/loop/agent_loop.py:529:            from core.llm.providers.anthropic import is_computer_use_enabled
core/cli/tool_handlers/single_tool.py:230:        from core.llm.providers.anthropic import is_computer_use_enabled
core/cli/tool_handlers/single_tool.py:254:        from core.llm.providers.anthropic import is_computer_use_enabled
core/cli/commands/login.py:161:            from core.llm.providers.codex import reset_codex_client
core/cli/commands/login.py:584:            from core.llm.providers.glm import reset_glm_client
core/cli/commands/login.py:701:                    from core.llm.providers.codex import reset_codex_client
core/cli/commands/login.py:979:        from core.llm.providers.glm import reset_glm_client
core/cli/prompt_session.py:172:        from core.llm.providers.anthropic import register_quota_setter
core/cli/commands/key.py:74:            from core.llm.providers.openai import reset_openai_client
core/cli/commands/key.py:93:            from core.llm.providers.glm import reset_glm_client
core/cli/commands/key.py:114:            from core.llm.providers.openai import reset_openai_client
core/cli/commands/key.py:125:            from core.llm.providers.glm import reset_glm_client
plugins/petri_audit/codex_provider.py:88:        from core.llm.providers.codex import _resolve_codex_token
plugins/petri_audit/codex_provider.py:120:        from core.llm.providers.codex import _resolve_codex_token
plugins/petri_audit/codex_provider.py:168:            from core.llm.providers.codex import (

$ ClaudeAgenticAdapter/OpenAIAdapter의 prod_refs 정체
core/llm/adapters/_anthropic_common.py:171:    ``ClaudeAgenticAdapter.agentic_call`` (PR-MAINPATH-67, 2026-05-24 removed
core/llm/adapters/_anthropic_common.py:231:    shaping was first wired into the legacy ``ClaudeAgenticAdapter``
core/llm/fallback.py:235:    (``OpenAIAdapter._retry_with_backoff``) to eliminate DRY violation.
core/llm/adapters/__init__.py:20:hierarchy (sync ``ClaudeAdapter`` / ``OpenAIAdapter.generate*`` surface
```

## S17. router 층 생존 확인
```
$ grep -rn 'from core.llm.router import' core/ plugins/ | grep -v 'core/llm/router/' | head
core/ui/status.py:23 · core/ui/agentic_ui/render.py:90 · core/llm/commentary.py:17
core/llm/providers/openai.py:154 · core/llm/providers/anthropic.py:940 · core/self_improving/loop/mutate/runner.py:787
```
판정: router는 live(commentary·mutate runner·failover) — 삭제 대상 아님. 단 Anthropic 캐시가 router text 경로에는 살아있고 AgenticLoop adapter 경로에만 죽어있다는 nuance 확정.

## 최종 분류표 (판정 근거 = 위 S1-S17)

| ID | 항목 | 분류 | 근거 |
|----|------|------|------|
| A1 | Anthropic 캐시를 adapters 프로덕션 경로(build_create/stream_kwargs)에 배선 (+oauth identity 블록 합성) | FIX(배선) | S1·S2 — 장치가 dead 클래스에만 존재 |
| A2 | codex resp_input WARNING 오발(`m.get("content") is None`이 키부재 포착) + 마스킹 테스트 교정 | FIX(버그) | S4 |
| A3 | `_extract_reflection_input` str payload 미수용(OpenAI계 전 프로바이더 reflection 파손) | FIX(버그) | S5 — :1038/:1155는 str, :188/:196은 dict만 |
| A4 | mid-run 재빌드에서 preflight_hint 유실 | FIX(버그) | S6 :969-977 |
| A5 | system-reminder가 message 브레이크포인트 1/3 소모(매 라운드 byte-diff) | FIX(A1과 동반) | S12 |
| A6 | XML 주입 통일: decomposition_hint(비XML)·_GATEWAY_SUFFIX(markdown)·petri suffix를 XML 태깅하고 힌트 전부를 `<dynamic_context>` 봉투 안으로 | UNIFY | S6·S13 — preflight/reflection/plan은 이미 XML, 봉투 밖 부착이 문제 |
| A7 | 모델-대면 한글 4곳 영역화 | FIX(CANNOT) | S7 — prompt_assembler:15(전 시스템 프롬프트 정적 존), calendar_tools:30·101, memory_tools:586 |
| A8 | codex 재생 2경로 id 정책 상반 — safe_output_item에서 reasoning형 id 제거로 정렬 | FIX(정렬) | S8 — store=False 고정, 형제 경로는 id-strip |
| A9 | GEODE.md 도구 수 66 하드코딩(실 78+) — 수사 제거 | FIX(드리프트) | S9 |
| A10 | build_codex_input의 system-role 가드 부재(형제 빌더와 비대칭) | FIX(정렬) | S10 |
| D1 | providers/anthropic.py `ClaudeAgenticAdapter`+agentic 전용 블록 삭제 (캐시/슬롯 헬퍼는 유지—adapters가 임포트) | DELETE | S1 — registry 부재·인스턴스화 0, tests 6파일 repoint |
| D2 | providers/openai.py `OpenAIAdapter` 삭제 (client mgmt·retry 유틸 유지) | DELETE | S15·S16 — prod 참조는 주석뿐 |
| D3 | system_injection 레거시 index-0 reminder strip 삭제 | DELETE | S14 — pre-2026-06-10, 1-release grace 초과 |
| M2 | `apply_in_context_slots`(ADR-012 M4.4 표면)를 adapters 경로에 재배선 — dead 클래스에 갇혀 표면 단절 상태 | REWIRE | S3 |
| KEEP | providers/ 저수준 유틸(get_*_client·reset_*_client·_resolve_codex_token·is_computer_use_enabled·register_quota_setter·retry/backoff·캐시 헬퍼)와 router 층 | KEEP | S16·S17 — adapters가 하위 primitive로 사용 |

## S18. Codex 라운드1 반영 (2026-07-29)
| 지적 | 처분 |
|------|------|
| H1 platform 백엔드 id-strip 오염 | build_codex_input에 backend 스레딩 — codex만 strip, platform은 verbatim 재생(OpenAI 수동 컨텍스트 관리 지침) |
| H2 extended thinking budget<max_tokens 위반 | max_tokens 확장(+budget)+temperature=1 이식 복원, 테스트 계약 pin |
| M3 S5 슬롯이 1h static 블록 오염 | dynamic 내부(closing 앞)로 주입 재배선 |
| M4 리포인트 테스트 약화 | TTL=1h·adaptive 실행 검증·oauth identity 합성·platform/codex id 분기 테스트 보강 |
| L5 rfind 중간 태그 오인 | closing 뒤 공백-only 검증 추가 |
| M6 native web_search/fetch 주입 유실 | context-mgmt와 함께 명시 보류(모듈 주석+본 원장+칸반) — live 검증 필요한 요청-의미 변경 |
