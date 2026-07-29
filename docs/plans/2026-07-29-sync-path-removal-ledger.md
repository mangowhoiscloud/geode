# 잔여 레거시 전역 점검 (a67aead19, 2026-07-29T01:18:22Z)
> 직전 점검은 core/llm/ 국한. 이번엔 core/+plugins/ 전역 + lazy-import 인지 census.

## P1. 자칭 레거시/deprecated/shim 표면 (프로덕션 코드)
```
core/paths.py:338:LEGACY_SOT_DIR = GLOBAL_AUTORESEARCH_HANDOFF_DIR
core/paths.py:529:# PR-CLEANUP-1 (2026-05-23) — ``GLOBAL_JOURNAL_DIR`` legacy alias 제거
core/tools/base.py:129:    """Backward-compatible alias for the async-native GEODE tool protocol."""
core/tools/document_ingest.py:151:                        "Deprecated compatibility alias for page_range. First PDF page, 1-indexed."
core/tools/document_ingest.py:157:                        "Deprecated compatibility alias for page_range. Last PDF page, 1-indexed."
core/llm/provider_dispatch.py:17:    """PEP 562 lazy ``settings`` alias for legacy patch sites."""
core/llm/token_tracker.py:484:# Backward-compatible aliases (thin wrappers → TokenTracker)
core/llm/adapters/_anthropic_common.py:126:_COMPUTER_USE_LEGACY = ("computer_20250124", "computer-use-2025-01-24")
core/llm/adapters/_anthropic_common.py:128:_COMPUTER_USE_TYPES = frozenset({_COMPUTER_USE_CURRENT[0], _COMPUTER_USE_LEGACY[0]})
core/llm/router/__init__.py:18:# (LLM*Error lazy re-exports, ``_resolve_provider`` monkeypatch alias,
core/llm/adapters/_openai_common.py:224:_OPENAI_LEGACY_DEFAULT = OpenAIModelSpec(
core/self_improving/loop/mutate/policies.py:109:def _maybe_migrate_legacy_sot(kind: str, new_path: Path) -> None:
core/self_improving/loop/mutate/policies.py:127:    legacy_name = _LEGACY_FILE_NAMES.get(kind)
core/self_improving/loop/mutate/policies.py:130:    legacy_path = LEGACY_SOT_DIR / legacy_name
core/config/self_improving.py:89:"""Backward-compat alias of :class:`CredentialSource` (the canonical enum)."""
core/config/self_improving.py:631:    def _migrate_legacy_role_namespaces(cls, data: Any) -> Any:
core/config/self_improving.py:657:        legacy_petri = data.pop("petri", None)
core/config/self_improving.py:671:        legacy_mutator = data.pop("mutator", None)
core/config/routing_manifest.py:83:    live here. Aliases keep the legacy `ANTHROPIC_SECONDARY` /
core/config/_settings.py:16:    LEGACY_OAUTH_ALIAS,
```

## P2. removal-pledge 스캔 (removed in vX / TODO-remove)
```
core/llm/prompts/__init__.py:13:they served the Game-IP analysis pipeline removed in v0.99.149 and had
core/memory/search_index.py:115:CREATE TRIGGER IF NOT EXISTS indexed_messages_after_delete AFTER DELETE ON indexed_messages BEGIN
core/memory/session_manager.py:380:CREATE TRIGGER IF NOT EXISTS {fts_name}_after_delete AFTER DELETE ON messages BEGIN
core/config/self_improving.py:666:                "section will be removed in v1.1.0 (the first minor after the v1.0.0 stable).",
core/config/self_improving.py:679:                "section will be removed in v1.1.0 (the first minor after the v1.0.0 stable).",
core/scheduler/models.py:77:    delete_after_run: bool = False  # For AT type: auto-delete after success
core/cli/terminal.py:51:    purged (the in-tree analysis graph was removed in v0.99.149). Kept as the
plugins/seed_generation/picker.py:257:                "The legacy file will be removed in v1.0.0.",
```

## P3. 깨진 pledge — seed_generation picker (v1.0.0 제거 약속, 현재 v1.0.6)
```
    if path is not None:
        return _load_overrides_from_file(Path(path))

    # 1. Canonical SoT: ~/.geode/config.toml [seed_generation.role.*]
    canonical_overrides = _load_config_toml_seed_overrides(GLOBAL_CONFIG_TOML)
    if canonical_overrides:
        return canonical_overrides

    # 2. Legacy fallback: ~/.geode/seed_generation.toml
    legacy_overrides = _load_overrides_from_file(GLOBAL_SEED_PIPELINE_TOML)
    if legacy_overrides:
        global _LEGACY_OVERRIDE_WARNED
        if not _LEGACY_OVERRIDE_WARNED:
            log.warning(
                "seed-generation picker: reading legacy %s. Migrate per-role "
                "overrides to ~/.geode/config.toml under [seed_generation.role.<role>] "
                "(see docs/plans/2026-05-23-llm-adapter-abstraction.md). "
                "The legacy file will be removed in v1.0.0.",
                GLOBAL_SEED_PIPELINE_TOML,
            )
            _LEGACY_OVERRIDE_WARNED = True
    return legacy_overrides


def _load_overrides_from_file(target: Path) -> dict[str, dict[str, str]]:
    """Parse a flat ``[<role>]`` override TOML — legacy seed_generation.toml shape."""
    if not target.is_file():
        return {}
    try:
        raw = tomllib.loads(target.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        log.warning(
            "seed-generation picker: %s is not valid TOML (%s) — ignoring overrides",
            target,
            exc,
        )
--- 소비자:
plugins/seed_generation/picker.py:117:# ClaudeCliAdapter (``core/llm/adapters/claude_cli.py:327``): the legacy
plugins/seed_generation/picker.py:207:_LEGACY_OVERRIDE_WARNED = False
plugins/seed_generation/picker.py:213:    """Load per-role overrides — config.toml first, legacy file as fallback.
plugins/seed_generation/picker.py:228:    The legacy ``~/.geode/seed_generation.toml`` schema (per-role top-level
plugins/seed_generation/picker.py:230:    ``config.toml``. The first time the legacy fallback is used, a one-time
plugins/seed_generation/picker.py:233:    The ``source`` value accepts both legacy (``claude-cli`` / ``openai-codex`` /
plugins/seed_generation/picker.py:249:    legacy_overrides = _load_overrides_from_file(GLOBAL_SEED_PIPELINE_TOML)
plugins/seed_generation/picker.py:250:    if legacy_overrides:
```

## P4. 유효 pledge — self_improving v1.1.0 (patch-train이라 아직 유효)
```
                if role_name in legacy_petri and role_name not in autoresearch_section:
                    autoresearch_section[role_name] = legacy_petri[role_name]
            warnings.warn(
                "[self_improving_loop.petri.*] is deprecated; move audit "
                "role bindings to [self_improving_loop.autoresearch.<role>] "
                "(autoresearch is the control-layer SoT). The legacy "
                "section will be removed in v1.1.0 (the first minor after the v1.0.0 stable).",
                DeprecationWarning,
                stacklevel=2,
            )

        legacy_mutator = data.pop("mutator", None)
        if isinstance(legacy_mutator, dict) and legacy_mutator:
            if "mutator" not in autoresearch_section:
                autoresearch_section["mutator"] = legacy_mutator
            warnings.warn(
                "[self_improving_loop.mutator] is deprecated; move the "
                "mutator binding to [self_improving_loop.autoresearch.mutator] "
                "(autoresearch owns its own engineering LLM). The legacy "
                "section will be removed in v1.1.0 (the first minor after the v1.0.0 stable).",
                DeprecationWarning,
                stacklevel=2,
            )
```

## P5. compat 별칭 실소비자 census (lazy-import 인지: 모듈경로 문자열 검색 병행)
```
== LEGACY_SOT_DIR
core/paths.py:338:LEGACY_SOT_DIR = GLOBAL_AUTORESEARCH_HANDOFF_DIR
core/self_improving/loop/mutate/policies.py:58:    LEGACY_SOT_DIR,
core/self_improving/loop/mutate/policies.py:130:    legacy_path = LEGACY_SOT_DIR / legacy_name
core/cli/commands/self_improving.py:700:    from core.paths import LEGACY_SOT_DIR
== LEGACY_OAUTH_ALIAS
core/config/_settings.py:16:    LEGACY_OAUTH_ALIAS,
core/config/_settings.py:408:        allowed = {s.value for s in CredentialSource} | {LEGACY_OAUTH_ALIAS, DISABLE_SENTINEL}
core/config/credential_source.py:60:LEGACY_OAUTH_ALIAS = "oauth"
core/config/credential_source.py:66:__all__ = ["DISABLE_SENTINEL", "LEGACY_OAUTH_ALIAS", "CredentialSource"]
== _OPENAI_LEGACY_DEFAULT
core/llm/adapters/_openai_common.py:224:_OPENAI_LEGACY_DEFAULT = OpenAIModelSpec(
core/llm/adapters/_openai_common.py:243:    Unknown models fall back to :data:`_OPENAI_LEGACY_DEFAULT` with a
core/llm/adapters/_openai_common.py:261:    return _OPENAI_LEGACY_DEFAULT

== core/tools/base.py:129 별칭 정체


@runtime_checkable
class AsyncTool(Tool, Protocol):
    """Backward-compatible alias for the async-native GEODE tool protocol."""


# ---------------------------------------------------------------------------
# Standardized tool error helper

== token_tracker backward-compat wrappers

# ───────────────────────────────────────────────────────────────────────────
# Backward-compatible aliases (thin wrappers → TokenTracker)
# ───────────────────────────────────────────────────────────────────────────


def calculate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_creation_tokens: int = 0,
    cache_read_tokens: int = 0,
) -> float:
    """Backward-compatible: delegates to ``get_tracker().calculate_cost()``."""
    return get_tracker().calculate_cost(

== document_ingest first_page/last_page 별칭 소비자
```

## P6. 운영자 로컬에 legacy seed_generation.toml 실존하나
```
-rw-r--r--@ 1 mango  staff  1164  6  3 16:57 /Users/mango/.geode/seed_generation.toml
core/paths.py:498:GLOBAL_SEED_PIPELINE_TOML = GEODE_HOME / "seed_generation.toml"
plugins/seed_generation/picker.py:52:- **P4 Environment Anchor**: ``GLOBAL_SEED_PIPELINE_TOML`` is the single
plugins/seed_generation/picker.py:67:from core.paths import GLOBAL_CONFIG_TOML, GLOBAL_SEED_PIPELINE_TOML
plugins/seed_generation/picker.py:249:    legacy_overrides = _load_overrides_from_file(GLOBAL_SEED_PIPELINE_TOML)
```

## P7. sync/async 이중 표면 census (운영자 지시: sync 불필요하면 제거, async-only)
```
-- (a) 라이브러리 코드의 asyncio.run() (동기 래퍼 신호)
core/memory/dreaming.py:171:                asyncio.run(
core/self_improving/campaign.py:2347:            band = asyncio.run(
core/self_improving/campaign.py:2393:                floors_by_arm = asyncio.run(
core/self_improving/loop/mutate/runner.py:819:    result, _used_model = asyncio.run(call_with_failover([model], _do_call))
core/agent/verify.py:493:            return asyncio.run(_verify_llm_judge_async(result, loop=loop))
core/agent/loop/_model_switching.py:380:        new_messages, did_compact = asyncio.run(
core/cli/doctor.py:151:        data = asyncio.run(transport.auth_test())
core/cli/doctor.py:214:        asyncio.run(open_socket_mode_url(app_token))
core/cli/doctor.py:340:    return asyncio.run(_probe())
core/cli/typer_serve.py:457:        asyncio.run(_serve_loop())
core/wiring/adapters.py:119:        data = asyncio.run(transport.auth_test())
plugins/benchmark_harness/tau2_turn_supervisor.py:186:        return asyncio.run(state.loop.arun(prompt))
plugins/benchmark_harness/tau2_turn_supervisor.py:195:        return asyncio.run(run())
plugins/petri_audit/mcp_bridge/bridge_server.py:152:        asyncio.run(_serve(tool_specs))

-- (b) sync/async 쌍(def X + async def aX)
```

## P8. sync 표면 정밀 census
```
-- (a) Tool 프로토콜의 sync 실행 경로
  _execute_sync 정의 수:
core/tools/arxiv.py:5
core/tools/file_tools.py:8
core/tools/browser_tools.py:2
core/tools/data_tools.py:3
core/tools/math_tools.py:2
core/tools/profile_tools.py:6
core/tools/arxiv.py:5
core/tools/computer_use.py:7

-- (b) LLMAdapter 프로토콜의 sync 메서드
58:    def __init__(
69:    def mark_recovered(self) -> None:
75:    def include_actionable_attempts(self, prior: Sequence[EmptyModelOutputError]) -> None:
81:    def mark_actionable(self) -> None:
359:    def test_environment(self) -> EnvironmentReport: ...
361:    def list_models(self) -> list[ModelSpec]: ...
363:    def get_quota_windows(self) -> QuotaWindows | None: ...
365:    def detect_credential(self) -> CredentialDetection | None: ...
485:    def computer_tool_param(

-- (c) providers sync 클라이언트 소비자
core/llm/provider_dispatch.py:26:# the cross-module ``RETRYABLE_ERRORS`` / ``get_anthropic_client`` pulls
core/llm/provider_dispatch.py:73:    """v0.88.0 — defer ``get_anthropic_client`` import until first call."""
core/llm/provider_dispatch.py:74:    from core.llm.providers.anthropic import get_anthropic_client
core/llm/provider_dispatch.py:76:    return get_anthropic_client()
core/llm/provider_dispatch.py:88:            "core.llm.providers.openai", fromlist=["_get_openai_client"]
core/llm/provider_dispatch.py:89:        )._get_openai_client(),
core/llm/provider_dispatch.py:95:            "core.llm.providers.glm", fromlist=["_get_glm_client"]
core/llm/provider_dispatch.py:96:        )._get_glm_client(),

-- (d) asyncio.to_thread 브리지 (sync를 async에서 감싸는 지점)
      66
core/async_runtime.py:22:    ``asyncio.to_thread`` worker is the loop-pollution canary: it means an
core/tools/llms_txt.py:312:        return await asyncio.to_thread(self._execute_sync, **kwargs)
core/tools/data_tools.py:25:        return await asyncio.to_thread(self._execute_sync, **kwargs)
core/tools/web_tools.py:122:        return await asyncio.to_thread(self._execute_sync, **kwargs)
core/tools/output_tools.py:118:        return await asyncio.to_thread(self._execute_sync, **kwargs)
core/tools/output_tools.py:189:        return await asyncio.to_thread(self._execute_sync, **kwargs)
core/tools/arxiv.py:104:        aexecute()". We wrap the sync body via ``asyncio.to_thread`` so
core/tools/arxiv.py:108:        return await asyncio.to_thread(self._execute_sync, **kwargs)
```

## P9. sync LLM 체인 생사 판정 (핵심 발견)
```
== _show_commentary
  prod 호출:
  import:
  tests:
tests/core/cli/test_commentary.py
== _handle_memory_action
  prod 호출:
core/cli/tool_handlers/memory.py:56:        _handle_memory_action(memory_args, "", False)
  import:
core/cli/tool_handlers/memory.py:17:    from core.cli import _handle_memory_action
  tests:
== generate_commentary
  prod 호출:
core/cli/__init__.py:109:        text = generate_commentary(user_query=user_text, action=action, context=context)
  import:
core/cli/__init__.py:72:from core.llm.commentary import generate_commentary
  tests:
tests/core/cli/test_commentary.py
== call_llm
  prod 호출:
core/llm/commentary.py:63:        text = call_llm(
core/llm/router/_hooks.py:3:Wires HookSystem into the router so call_llm*/call_with_failover can emit
core/llm/router/__init__.py:44:    call_llm as call_llm,
core/llm/router/calls/__init__.py:5:synchronous text entry point ``call_llm``.
  import:
core/llm/commentary.py:17:from core.llm.router import call_llm
core/llm/router/calls/__init__.py:24:from .text import call_llm as call_llm
  tests:
tests/core/llm/test_failover.py
tests/core/llm/test_routing_policy.py
tests/core/llm/test_llm_client.py
```


## P10. 처분 결과
| 항목 | 판정 | 처분 |
|------|------|------|
| sync LLM 체인 전체(_show_commentary→generate_commentary→call_llm→provider_dispatch→sync SDK clients) | 죽음(입구 호출자 0) | 삭제 — 런타임 async-only |
| _route_provider / router/calls/_route.py | call_llm과 함께 고아 | 삭제, 라우팅 정책 핀은 call_with_failover로 재지정 |
| core/llm/providers/openai.py | sync 삭제 후 전체 고아 | 모듈 삭제 |
| GLM sync client(_get_glm_client) | 고아(async twin은 computer_grounding이 소비) | sync만 삭제 |
| commentary 프롬프트 템플릿+무결성 핀+temperature_commentary | 소비자 삭제로 고아 | 삭제 |
| /key·/login·failover의 reset 경로 | **잠재 버그**: 죽은 sync 싱글턴만 리셋 → 키 회전이 어댑터 캐시에 미반영 | invalidate_provider_clients로 재배선(라이브 경로) |
| seed_generation legacy toml fallback | pledge 위반(v1.0.0 약속, 현 v1.0.6) **이나 운영자 유일 설정원** | 삭제 불가 — 거짓 pledge 문구만 정정, 마이그레이션 필요를 운영자에게 보고 |
| self_improving [petri.*]/[mutator] v1.1.0 pledge | 유효(patch-train, v1.1.0 예약) | 유지 |
| LEGACY_SOT_DIR·LEGACY_OAUTH_ALIAS·_OPENAI_LEGACY_DEFAULT·AsyncTool·token_tracker wrappers | 라이브 소비자 존재 | 유지 |


## P11. Codex 라운드1 반영 (FAIL → 전건 처리)
Codex 판정 FAIL(HIGH) — 재배선이 불완전했고 삭제도 미완이었다.

| # | 지적 | 처분 |
|---|------|------|
| HIGH | `/key <sk-ant-…>`·GLM `set-key`·`/login refresh`·OpenAI OAuth 로그인이 어댑터 캐시를 안 비움 | 누락 4곳 포함 전 7개소를 `invalidate_provider_clients`로 배선 |
| MED | `prompts.__all__`에 삭제 상수 잔존 → `from core.llm.prompts import *`가 AttributeError | `__all__`·독스트링 정리 |
| MED | 연쇄 고아 잔존(router/_usage.py, anthropic sync helper 4종, codex sync client) | 전부 삭제 |
| MED | 대체 라우팅 핀이 소스 문자열 검사라 공허 통과 | 행위 검증으로 교체(정책 불허 모델이 호출되지 않음을 단언) |
| MED | AGENTS.md가 삭제된 providers/openai.py·commentary 템플릿·"4개 hash" 기술 | 실태로 정정(2 템플릿/2 hash, providers=저수준 유틸) |
| MED | "런타임 async-only"는 중앙 completion 스택 한정 | 표현 정정 — document_ingest·prompt_dump의 sync SDK 호출은 별개 층(범위 밖) |

자체 발견 파손 2건(삭제 정규식이 `_async_codex_client` 선언까지 제거, failover 테스트가 삭제된 sync retry 참조)도 같이 수리 — 후자는 5개 invariant를 `retry_with_backoff_async`로 이관.
