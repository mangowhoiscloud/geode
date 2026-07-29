# 레거시 삭제 재점검 (8674c418f, 2026-07-29T00:36:09Z)

## R1. 삭제 선언 심볼의 실행 코드 잔존 (주석/문자열 제외)
```
--- ClaudeAgenticAdapter
core/llm/adapters/_anthropic_common.py:171:    ``ClaudeAgenticAdapter.agentic_call`` (PR-MAINPATH-67, 2026-05-24 removed
core/llm/adapters/_anthropic_common.py:228:    Ported from the deleted ClaudeAgenticAdapter (stranded, never live);
core/llm/adapters/_anthropic_common.py:258:    Ported from the deleted ClaudeAgenticAdapter; live-verified on
core/llm/adapters/_anthropic_common.py:301:    Ported 2026-07-29 from the never-registered ``ClaudeAgenticAdapter``
--- OpenAIAdapter
core/llm/fallback.py:235:    (the since-deleted ``OpenAIAdapter._retry_with_backoff``) to eliminate DRY violation.
core/llm/providers/openai.py:50:    still hit this singleton (paperclip ``OpenAIAdapter``,
core/llm/adapters/__init__.py:20:hierarchy (sync ``ClaudeAdapter`` / ``OpenAIAdapter.generate*`` surface
--- _resolve_plan_meta
--- _get_retryable_errors
--- _is_system_reminder
--- decomposition_hint
```

## R2. 테스트/문서 잔존 참조
```
--- ClaudeAgenticAdapter (tests+docs)
tests/core/llm/test_provider_parity_v0532.py:56:    ``ClaudeAgenticAdapter`` was deleted (never registered); the live
tests/core/llm/test_anthropic_reasoning_v056.py:86:        # ClaudeAgenticAdapter to the LIVE builder module.
tests/core/llm/test_anthropic_cache_live_path.py:4:``ClaudeAgenticAdapter`` — these tests pin it to ``build_create_kwargs`` /
tests/core/llm/test_anthropic_sampling_params.py:3:Repointed 2026-07-29: previously drove the deleted ``ClaudeAgenticAdapter``;
--- OpenAIAdapter (tests+docs)
tests/core/llm/test_h11_constant_reload.py:41:    # 2026-07-29: OpenAIAdapter deleted; the H11 invariant (routing constants
tests/core/llm/test_adapter_max_retries.py:50:    paperclip ``OpenAIAdapter`` + llm_extract_learning + models.py — same
docs/progress.md:23:- [x] 프롬프트 문법 정렬 + adapters 단일 진입점화 (#2810 → release #2811 → 프리싱크 #2812 → 승격 #2813, main v1.0.4, 2026-07-29) — Phase-0 bash 원장(docs/plans/2026-07-29-prompt-grammar-alignment-ledger.md, S1-S18) 선분류 후 착수. 핵심: Anthropic 캐시 장치 전체(STATIC/DYNAMIC 1h-TTL split·메시지 브레이크포인트·T5 cache_policy·S5 in-context 슬롯·adaptive thinking display=summarized)가 미등록 ClaudeAgenticAdapter에 좌초해 프로덕션 미작동이었음을 라이브 build_create/stream_kwargs로 이식(slots는 dynamic 존, reminder는 브레이크포인트 제외, 봉투 open 태그 wire 보존). XML 주입 통일=inject_runtime_hints 단일 헬퍼(<dynamic_context> 내 삽입, 재빌드 preflight 유실 수정, decomposition_hint 사배관 삭제). 버그: reflection str payload 폐기(OpenAI계 전체)·codex shape WARNING 상시 오발·extended thinking budget<max_tokens 계약. 삭제: ClaudeAgenticAdapter(~360L)+OpenAIAdapter(~160L)+레거시 reminder strip, 순수 −540줄, providers/=저수준 유틸 층. 복잡도 ceiling 래칫 인하(C901 54→52, PLR0912 56→52). Codex(gpt-5.6-sol high) 2라운드: R1 6건(platform id 오염 HIGH·thinking 계약 HIGH·슬롯 static 오염·테스트 약화·rfind·native-tools 분류) 전건 반영 후 PASS. 보류(명시): context-management·native web_search/fetch 재배선 — 라이브 검증 필요(providers/anthropic.py 주석+원장 S18). 리빌드 v1.0.4+kickstart 완료.
docs/progress.md:111:- [x] PR-PRE10-H11-TAIL — v1.0.0 전 punch-list #1: 모델해석 call path의 routing 상수를 boot-frozen 복사본이 아니라 live로 읽도록(운영자: punch-list 전체, Codex 검증). `reload_routing_constants()`가 core.config.* 를 in-place 재바인드하고 function-local import는 live로 재해석하지만, 여러 module-level by-value importer가 부트 복사본을 들고 있어 세션 중 routing.toml 편집이 재시작 전까지 stale였음. call path 전반 해동: providers/{anthropic,openai,glm} + provider_dispatch lambda(codex entry의 live `__import__` 패턴에 일치), OpenAIAdapter.__init__ OPENAI_PRIMARY lazy, streaming retry chain, agent_loop no-act_model ANTHROPIC_PRIMARY fallback, skills/agents.py(AgentDefinition.model default_factory + 빌트인 3 spec의 frozen "model" 키 제거→factory가 live 채움). 죽은 DEFAULT_*_MODEL/*_FALLBACK_MODELS provider alias(소비자 0) 제거. Codex catch 4: semantics 회귀(explicit `model:""` 보존, `get(k,default)`로 복구) + kanban 명시 외 3곳(provider_dispatch·agent_loop·_state) — call-path 2곳 수정. **범위 주석(Codex 합의)**: 런타임 모델해석 경로 한정. 잔존 frozen 1곳=`_state.py` MODEL_PROFILES(/model 피커 라벨·id 목록, ~12 CLI 소비자)=display+picker-id 후속(코어 해석경로 아님). 가드 test_h11_constant_reload(core.config.* 패치→소비자 live 확인)+test_failover live SoT 재지정. 게이트 green+CI 6/6. (PR #2329→#2331, v0.99.220)
```

## R3. providers/ 잔존 심볼의 프로덕션 소비자 수 (0 = 삭제로 새로 죽은 후보)
```
== anthropic (     941L)
  DEAD? _resolve_anthropic_exception prod=0 testfiles=0
  DEAD? _extract_anthropic_quota prod=0 testfiles=1
  DEAD? _feed_banner_from_anthropic_response prod=0 testfiles=1
  DEAD? _sync_response_hook prod=0 testfiles=0
  DEAD? get_async_anthropic_client prod=0 testfiles=1
  DEAD? _content_block_count prod=0 testfiles=1
  DEAD? _is_volatile_reminder prod=0 testfiles=0
  DEAD? _is_markable prod=0 testfiles=0
  DEAD? _select_breakpoint_targets prod=0 testfiles=2
== openai (      92L)
  DEAD? _resolve_openai_key prod=0 testfiles=1
  DEAD? _get_async_openai_client prod=0 testfiles=1
== codex (     236L)
  DEAD? _ResolvedCodexToken prod=0 testfiles=1
  DEAD? _extract_account_id prod=0 testfiles=1
== glm (     140L)
```

## R4. 진짜 고아 판정 (정의 1회 = 어디서도 호출/참조 안 됨)
```
(출력 없으면 고아 0)
```

## R5. stale 주석 — 삭제된 심볼을 '현존'처럼 서술하는 곳
```
50:    still hit this singleton (paperclip ``OpenAIAdapter``,
    """Lazy import and return cached OpenAI client (thread-safe).

    PR-ADAPTER-TIMEOUT-AND-SERIALIZATION (2026-05-28, Codex MCP MED) —
    ``max_retries=0`` matches the adapter-side invariant
    (``_openai_common.build_async_openai_client``) so legacy callers that
    still hit this singleton (paperclip ``OpenAIAdapter``,
    ``llm_extract_learning``, ``models.py``) don't compound SDK + app
    retry loops on stalled streams.
    """
    global _openai_client
    if _openai_client is None:
--- adapters/__init__.py 도입부

PR-LLMCLIENTPORT-COLLAPSE (2026-05-28) — the parallel ``LLMClientPort``
hierarchy (sync ``ClaudeAdapter`` / ``OpenAIAdapter.generate*`` surface
+ ``LLMJsonCallable`` / ``LLMTextCallable`` / ``LLMParsedCallable``
node-DI Protocols + the ``set_llm_callable`` / ``get_llm_json`` ContextVar
chain + ``cross_llm.py`` re-score) is gone. The :class:`LLMAdapter`
Protocol + central dispatch (``core.llm.adapters.dispatch``) is the
--- test_adapter_max_retries.py:50


def test_legacy_openai_provider_singleton_pins_max_retries_zero() -> None:
    """Legacy ``core/llm/providers/openai.py`` singleton is still consumed by
    paperclip ``OpenAIAdapter`` + llm_extract_learning + models.py — same
    spinning risk if SDK retry compounds with app retry."""
    src = (
        Path(__file__).resolve().parents[3] / "core" / "llm" / "providers" / "openai.py"
    ).read_text(encoding="utf-8")
```

## R6. providers/openai.py 싱글턴의 실제 소비자 (주석 주장 검증)
```
$ grep -rn '_get_openai_client\|_get_async_openai_client\|reset_openai_client' core/ plugins/ scripts/ --include='*.py' | grep -v 'providers/openai.py'
core/llm/fallback.py:150:            from core.llm.providers.openai import reset_openai_client
core/llm/fallback.py:153:                reset_openai_client()
core/llm/provider_dispatch.py:88:            "core.llm.providers.openai", fromlist=["_get_openai_client"]
core/llm/provider_dispatch.py:89:        )._get_openai_client(),
core/llm/providers/glm.py:100:    Uses double-checked locking pattern consistent with _get_openai_client().
core/cli/commands/key.py:74:            from core.llm.providers.openai import reset_openai_client
core/cli/commands/key.py:76:            reset_openai_client()
core/cli/commands/key.py:114:            from core.llm.providers.openai import reset_openai_client
core/cli/commands/key.py:116:            reset_openai_client()
core/orchestration/compaction.py:561:    builders (``_get_openai_client`` / ``_get_glm_client``). Now delegates

$ 주석이 지목한 소비자 3종 생존 확인
-- llm_extract_learning:
core/llm/providers/openai.py:51:    ``llm_extract_learning``, ``models.py``) don't compound SDK + app
core/config/_settings.py:75:            "(``core.hooks.llm_extract_learning``), run outside the main "
core/wiring/bootstrap.py:458:        from core.hooks.llm_extract_learning import make_llm_extract_handler
-- models.py:
  core/llm/models.py 부재
```

## R7. async 클라이언트 빌더 실소비자 (OpenAIAdapter 삭제로 고아화 후보)
```
== _get_async_openai_client
  prod refs:
  test refs:
tests/core/llm/test_loop_pollution_guardrails.py
== get_async_anthropic_client
  prod refs:
  test refs:
tests/core/llm/test_loop_pollution_guardrails.py
== system_with_cache
  prod refs:
core/llm/providers/anthropic.py:445:    ephemeral default). One-shot call shapes (``system_with_cache``) and the
core/llm/router/calls/text.py:18:    system_with_cache as _system_with_cache,
  test refs:
```

## R8. adapters가 자체 클라이언트를 만드나 (providers 빌더 우회 여부)
```
core/llm/adapters/anthropic_oauth.py:5:if both are configured. Owns its own ``AsyncAnthropic`` client (Codex MCP
core/llm/adapters/anthropic_oauth.py:24:    build_async_anthropic_client,
core/llm/adapters/anthropic_oauth.py:82:    """Subscription-routed Anthropic adapter — owns its own AsyncAnthropic client."""
core/llm/adapters/anthropic_oauth.py:120:    def _get_client(self) -> Any:
core/llm/adapters/anthropic_oauth.py:139:        return self._clients.get(lambda: build_async_anthropic_client(auth_token=token))
core/llm/adapters/anthropic_oauth.py:142:        client = self._get_client()
core/llm/adapters/anthropic_oauth.py:173:            self._get_client(),
core/llm/adapters/anthropic_oauth.py:193:            self._get_client(),
```

## R9. 광역 스윕 — 스프린트 후 남은 legacy/deprecated/compat 표면
```
-- (a) '레거시'라 자칭하는 프로덕션 심볼
core/llm/prompt_assembler.py:3:The legacy ``PromptAssembler`` class was removed because production prompt
core/llm/providers/codex.py:207:        # legacy provider path is also safe on openai >= 2.26.
core/llm/adapters/dispatch.py:476:    legacy_result: WebSearchResult = await adapter.aweb_search(query, max_results=max_results)
core/agent/loop/agent_loop.py:353:        thinking_budget: int = 0,  # 0 = disabled; >0 = Extended Thinking tokens (legacy)
core/agent/loop/_tool_factory.py:81:MAX_TOOL_RESULT_TOKENS = 0  # backward-compat alias; canonical: settings.max_tool_result_tokens

-- (b) providers/ 최종 형상
     879 core/llm/providers/anthropic.py
     236 core/llm/providers/codex.py
     140 core/llm/providers/glm.py
      73 core/llm/providers/openai.py
    1329 total

-- (c) 라우터 층 text.py 생존(캐시 헬퍼 소비자)
core/llm/adapters/_openai_common.py:361:    # AgenticLoop's ``_call_llm`` retry path.
core/self_improving/loop/__init__.py:28:dispatches through ``core.llm.router.call_with_failover`` so the
core/self_improving/loop/mutate/runner.py:20:   ``core.llm.router.call_with_failover``.
core/self_improving/loop/mutate/runner.py:787:    from core.llm.router import call_with_failover
```

## R10. 삭제 검증 요약
```
-- 삭제된 async 체인 재확인(참조 0이어야 함)
core/llm/adapters/_anthropic_common.py:61:        _async_response_hook,
core/llm/adapters/_anthropic_common.py:69:        event_hooks={"response": [_async_response_hook]},
(출력 없음 = 전부 제거됨)
```


## R11. Codex 라운드1 반영 (2026-07-29)
Codex 판정 FAIL(LOW) — "레거시 잔존은 주석·이력뿐"이라는 감사 결론이 부정확했다. stale 서술 4곳 정정:

| 위치 | 내용 | 처분 |
|------|------|------|
| `tests/core/agent/test_arun_model_drift_sync.py` | 삭제된 `decomposition_hint`가 모듈 독스트링+실행 테스트 함수명 3개에 현재형으로 잔존(실제 대상은 reflection hint) | 함수명·서술 전부 reflection로 정정 |
| `core/llm/providers/anthropic.py:3` | 모듈 독스트링 "sync/async clients 소유" — async는 adapters 층 소유 | 저수준 유틸 층 실태로 재작성 |
| `core/llm/providers/{anthropic,openai}.py` | 제거된 async 캐시를 설명하는 고아 주석 | 삭제 |
| `core/llm/providers/anthropic.py` | `ClaudeAgenticAdapter` 섹션 헤더 | 실제 내용(adapters가 소비하는 request shaping 헬퍼)로 개명 |
| `tests/core/llm/test_loop_pollution_guardrails.py` | 존재하지 않는 형제 테스트명 참조 | 실제 이름으로 정정 |

Codex PASS 판정 항목: 제거 5심볼 소비자 0(getattr/`__import__`/import_module 패턴 포함 재검색), `_async_response_hook` 복원 정확성(실행 본문 동일), liveness 가드 실효성(hook 삭제 재현 시 ImportError 검출, adapter provider import 15노드/19심볼 커버), 가드레일 축소의 커버리지 보존, 연쇄 고아 0.

가드 한계(문서화): AST 워크는 직접 파일의 absolute `ImportFrom`만 처리 — 상대/동적 import는 미커버, `TYPE_CHECKING` 조건부는 오탐 가능(현재 해당 형태 없음).
