# GEODE Hook/Auth Wiring Audit Matrix

> 58 HookEvent 전수 감사 + Auth Profile 와이어링 점검 결과

## 1. HookEvent Audit Logger Coverage (58개)

| # | Event | Trigger Mode | Audit Logger | Dedicated Handler | Status |
|---|---|---|---|---|---|
| 1 | `PIPELINE_START` | trigger | run_log | stuck_tracker, metrics | OK |
| 2 | `PIPELINE_END` | trigger | run_log | stuck, journal, notification, snapshot, outcomes | OK |
| 3 | `PIPELINE_ERROR` | trigger | run_log | stuck, journal, notification | OK |
| 4 | `NODE_BOOTSTRAP` | trigger | run_log | - | OK |
| 5 | `NODE_ENTER` | trigger | run_log | task_bridge, stuck_detector | OK |
| 6 | `NODE_EXIT` | trigger | run_log | task_bridge, stuck_detector | OK |
| 7 | `NODE_ERROR` | trigger | run_log | task_bridge, stuck_detector | OK |
| 8 | `ANALYST_COMPLETE` | trigger | run_log | - | OK |
| 9 | `EVALUATOR_COMPLETE` | trigger | run_log | - | OK |
| 10 | `SCORING_COMPLETE` | trigger | run_log | drift_scan, scoring_drift | OK |
| 11 | `VERIFICATION_PASS` | trigger | run_log | - | OK |
| 12 | `VERIFICATION_FAIL` | trigger | run_log, verif_fail | - | OK |
| 13 | `DRIFT_DETECTED` | trigger | run_log, drift_logger | snapshot, pipeline_trigger, notification | OK |
| 14 | `OUTCOME_COLLECTED` | trigger | run_log, outcome_logger | outcome_feedback_cycle | OK |
| 15 | `MODEL_PROMOTED` | trigger | run_log, model_promotion_logger | - | OK |
| 16 | `SNAPSHOT_CAPTURED` | trigger | run_log, snapshot_logger | - | OK |
| 17 | `TRIGGER_FIRED` | trigger | run_log, trigger_logger | - | OK |
| 18 | `POST_ANALYSIS` | trigger | run_log, post_analysis | - | OK |
| 19 | `MEMORY_SAVED` | trigger | run_log, **memory_saved** | - | FIXED |
| 20 | `RULE_CREATED` | trigger | run_log | - | OK |
| 21 | `RULE_UPDATED` | trigger | run_log | - | OK |
| 22 | `RULE_DELETED` | trigger | run_log | - | OK |
| 23 | `PROMPT_ASSEMBLED` | trigger | run_log | - | OK |
| 24 | `SUBAGENT_STARTED` | trigger | run_log, sa_started | - | OK |
| 25 | `SUBAGENT_COMPLETED` | trigger | run_log | journal_subagent | OK |
| 26 | `SUBAGENT_FAILED` | trigger | run_log | notification | OK |
| 27 | `TOOL_RECOVERY_ATTEMPTED` | trigger | run_log, recovery_try | - | OK |
| 28 | `TOOL_RECOVERY_SUCCEEDED` | trigger | run_log, **recovery_ok** | metrics | FIXED |
| 29 | `TOOL_RECOVERY_FAILED` | trigger | run_log, recovery_fail | - | OK |
| 30 | `TURN_COMPLETE` | trigger | run_log | auto_memory, auto_learn, llm_extract | OK |
| 31 | `CONTEXT_CRITICAL` | trigger | run_log, ctx_critical | - | OK |
| 32 | `CONTEXT_OVERFLOW_ACTION` | with_result | run_log | context_action_hook | OK |
| 33 | `SESSION_START` | trigger | run_log | session_start_logger | OK |
| 34 | `SESSION_END` | trigger | run_log | session_end_logger, tool_offload_cleanup | OK |
| 35 | `MODEL_SWITCHED` | trigger | run_log | model_switch_logger | OK |
| 36 | `LLM_CALL_START` | trigger | run_log, llm_start | - | OK |
| 37 | `LLM_CALL_END` | trigger | run_log | llm_slow_logger, metrics | OK |
| 38 | `LLM_CALL_FAILED` | trigger | run_log, **llm_failed** | - | FIXED |
| 39 | `LLM_CALL_RETRY` | trigger | run_log, **llm_retry** | - | FIXED |
| 40 | `TOOL_APPROVAL_REQUESTED` | trigger | run_log, **approval_req** | - | FIXED |
| 41 | `TOOL_APPROVAL_GRANTED` | trigger | run_log | approval_tracker | OK |
| 42 | `TOOL_APPROVAL_DENIED` | trigger | run_log | approval_tracker_denied | OK |
| 43 | `FALLBACK_CROSS_PROVIDER` | trigger | run_log, xprovider_fb | - | OK |
| 44 | `PIPELINE_TIMEOUT` | trigger | run_log, pipe_timeout | - | OK |
| 45 | `SHUTDOWN_STARTED` | trigger | run_log, shutdown | - | OK |
| 46 | `CONFIG_RELOADED` | trigger | run_log, config_reload | - | OK |
| 47 | `TOOL_RESULT_OFFLOADED` | trigger | run_log, **tool_offload** | - | FIXED |
| 48 | `MCP_SERVER_CONNECTED` | trigger | run_log, **mcp_ok** | - | FIXED |
| 49 | `MCP_SERVER_FAILED` | trigger | run_log, mcp_fail | - | OK |
| 50 | `USER_INPUT_RECEIVED` | interceptor | run_log, user_input | - | OK |
| 51 | `TOOL_EXEC_START` | interceptor | run_log, tool_start | - | OK |
| 52 | `TOOL_EXEC_END` | with_result | run_log, tool_end | - | OK |
| 53 | `TOOL_EXEC_FAILED` | trigger | run_log, tool_failed | - | OK |
| 54 | `TOOL_RESULT_TRANSFORM` | with_result | run_log, tool_transform | - | OK |
| 55 | `COST_WARNING` | trigger | run_log, cost_warn | - | OK |
| 56 | `COST_LIMIT_EXCEEDED` | trigger | run_log, cost_exceeded | - | OK |
| 57 | `EXECUTION_CANCELLED` | trigger | run_log, exec_cancel | - | OK |
| 58 | `REASONING_METRICS` | trigger | run_log, **reasoning_metrics** | - | FIXED |

**FIXED** = 이번 PR에서 추가된 audit logger (8건)

## 2. Auth Profile Wiring

| 항목 | 이전 | 이후 | 참조 |
|------|------|------|------|
| `mark_used()` | `credentials.py:31` | 동일 | - |
| `mark_success()` | **미호출** | `fallback.py` 성공 시 호출 | OpenClaw `markAuthProfileGood` |
| `mark_failure()` | **미호출** | `fallback.py` 실패 시 호출 | OpenClaw `markAuthProfileFailure` |
| `mark_failure(is_auth_error=True)` | **미호출** | auth 에러 분류 후 호출 | Hermes `_is_auth_error` |
| Profile 추적 | 없음 | `_last_profile[provider]` | OpenClaw `lastGood[provider]` |
| 401 auto-refresh | 정의만 | `_try_managed_refresh()` via `mark_failure` | Hermes `handle_401` |
| Proactive refresh | 정의만 | `resolve()` 내 만료 120s 전 re-read | Hermes `REFRESH_SKEW` |

## 3. Credential Scrubbing

| 패턴 | 예시 | 적용 위치 |
|------|------|-----------|
| `sk-*` | `sk-proj-abc123...` | `tool_error()`, LLM router |
| `ghp_*` | `ghp_1234567890abcdef` | 동일 |
| `Bearer` | `Bearer eyJhbG...` | 동일 |
| `xoxb-*` | `xoxb-1234-5678-abc...` | 동일 |
| `token=`, `key=`, `password=` | URL query params | 동일 |

## 4. Cross-Codebase Grounding

| GEODE 구현 | Hermes Agent 참조 | OpenClaw 참조 |
|---|---|---|
| `_notify_success()` | `_reset_server_error()` | `markAuthProfileGood()` |
| `_notify_failure()` | `_bump_server_error()` | `markAuthProfileFailure()` |
| `_is_auth_error()` | `_is_auth_error()` | `classifyFailoverReason()` |
| `_resolve_rotator_provider()` | N/A | `resolveAuthProfileOrder()` |
| `scrub_credentials()` | `_CREDENTIAL_PATTERN` | N/A |
| `register_refresher()` | `handle_401()` | `refreshProviderOAuthCredentialWithPlugin()` |
