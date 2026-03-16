# HITL 보안 강화 — 자율 에이전트의 안전 게이트 진화 과정

> Date: 2026-03-15 | Author: geode-team | Tags: [hitl, security, tool-executor, sub-agent, mcp, write-tools, auto-approve]

## 목차

1. [도입 — 왜 HITL을 다시 점검해야 했는가](#1-도입--왜-hitl을-다시-점검해야-했는가)
2. [보안 감사 — 7개 우회 벡터 발견](#2-보안-감사--7개-우회-벡터-발견)
3. [설계 결정 1: WRITE_TOOLS 분류 신설](#3-설계-결정-1-write_tools-분류-신설)
4. [설계 결정 2: DANGEROUS auto_approve 무시](#4-설계-결정-2-dangerous-auto_approve-무시)
5. [설계 결정 3: MCP 안전 라우팅](#5-설계-결정-3-mcp-안전-라우팅)
6. [트레이드오프 — 안전성 vs 자율성](#6-트레이드오프--안전성-vs-자율성)
7. [HITL 매트릭스 — 최종 안전 분류 체계](#7-hitl-매트릭스--최종-안전-분류-체계)
8. [마무리](#8-마무리)

---

## 1. 도입 — 왜 HITL을 다시 점검해야 했는가

[이전 포스트](21-clarification-hitl-cost-tracking.md)에서 GEODE의 HITL Safety Gate를 소개했습니다. `SAFE` / `STANDARD` / `DANGEROUS` 3단계 분류로 도구를 나누고, `DANGEROUS`(bash)와 `EXPENSIVE`(분석) 도구에 사용자 승인을 요구하는 구조였습니다.

이 설계는 단일 AgenticLoop 환경에서는 충분했습니다. 그러나 v0.11.0에서 **Sub-Agent 시스템**(P2-B Full AgenticLoop Inheritance)이 도입되면서 상황이 달라졌습니다.

서브에이전트는 부모의 전체 도구 세트를 상속받아 독립 스레드에서 실행됩니다. 이때 `ToolExecutor`가 `auto_approve=True`로 생성되어 HITL 프롬프트 없이 도구를 실행합니다. 이 설계는 서브에이전트가 사용자에게 매번 승인을 요청하는 것이 현실적이지 않다는 판단에서 비롯되었습니다.

문제는 이 `auto_approve=True`가 **모든** 안전 게이트를 우회했다는 점입니다.

```
Parent AgenticLoop (auto_approve=False)
  └─ delegate_task → SubAgentManager
      └─ Worker Thread (auto_approve=True)
          ├─ run_bash("rm -rf /tmp/data")     ← 승인 없이 실행?
          ├─ memory_save("malicious rule")     ← 영속적 상태 변경?
          └─ MCP tool("외부 API 호출")          ← 검사 없이 통과?
```

> 자율성을 높이기 위한 `auto_approve`가 안전 경계까지 무력화한 것입니다. 서브에이전트 도입 후 HITL 체계를 재점검해야 한다는 것은 아키텍처 결정의 2차 효과(second-order effect)입니다.

---

## 2. 보안 감사 — 7개 우회 벡터 발견

ToolExecutor의 전체 실행 경로를 추적하여 7개의 HITL 우회 벡터를 식별했습니다.

### 감사 방법

1. `tool_executor.py`의 `execute()` 메서드에서 모든 분기 경로를 추적
2. 각 분기에서 `auto_approve` 플래그가 안전 게이트를 어떻게 영향하는지 분석
3. MCP 도구가 ToolExecutor를 경유하지 않는 직접 호출 경로 확인
4. 서브에이전트의 재귀 위임(depth > 0) 시나리오 검증

### 발견 결과

| # | 벡터 | 심각도 | 경로 |
|---|------|--------|------|
| 1 | 쓰기 도구(`memory_save`, `note_save`, `set_api_key`, `manage_auth`)가 STANDARD 분류 — 게이트 없음 | **HIGH** | `execute()` → handler 직접 호출 |
| 2 | `auto_approve=True`가 DANGEROUS(`run_bash`)까지 우회 | **HIGH** | `_execute_bash()` → `if not self._auto_approve` 스킵 |
| 3 | MCP 도구가 ToolExecutor 안전 검사 없이 `call_tool()` 직접 실행 | **MEDIUM** | `execute()` → `mcp_manager.call_tool()` |
| 4 | Token Guard는 차단이 아닌 절삭 — 실행 자체는 막지 않음 | **LOW** | `_guard_tool_result()` |
| 5 | EXPENSIVE 도구 서브에이전트 우회 | **MEDIUM** | `auto_approve` → `_confirm_cost()` 스킵 |
| 6 | 중첩 위임으로 bash 승인 우회 | **LOW** | delegate → sub-agent → run_bash |
| 7 | STANDARD 카테고리에 쓰기 도구 포함 | **MEDIUM** | 분류 체계 자체의 공백 |

> 감사 결과, 핵심 문제는 **분류 체계의 공백**(#1, #7)과 **auto_approve의 과도한 범위**(#2, #5)로 수렴했습니다.

---

## 3. 설계 결정 1: WRITE_TOOLS 분류 신설

### 문제

기존 3단계 분류(SAFE / STANDARD / DANGEROUS)에서 쓰기 도구는 STANDARD에 속했습니다. STANDARD는 "일반 실행, 특별한 게이트 없음"을 의미하므로, `memory_save`가 사용자 확인 없이 영속적 상태를 변경할 수 있었습니다.

```python
# AS-IS: memory_save는 STANDARD — 바로 실행
handler = self._handlers.get("memory_save")
return handler(**tool_input)  # 승인 없이 실행
```

### 해결: WRITE_TOOLS 4번째 분류

```python
# core/cli/tool_executor.py
WRITE_TOOLS: frozenset[str] = frozenset(
    {
        "memory_save",
        "note_save",
        "set_api_key",
        "manage_auth",
    }
)
```

> 이 4개 도구를 WRITE_TOOLS로 분리한 기준은 **영속적 상태 변경 여부**입니다. `memory_save`는 세션 메모리에, `note_save`는 `.claude/MEMORY.md`에, `set_api_key`는 인증 정보에, `manage_auth`는 프로필에 영구적인 변경을 가합니다. 읽기 전용 도구(`memory_search`, `note_read`)와 명확히 구분되는 위험 프로필입니다.

### auto_approve 무시 결정

WRITE_TOOLS의 가장 중요한 설계 결정은 **`auto_approve`를 무시**하는 것입니다.

```python
# auto_approve 상태와 무관하게 항상 승인 요구
if tool_name in WRITE_TOOLS and not self._confirm_write(tool_name, tool_input):
    return {"error": "User denied write operation", "denied": True}
```

> DANGEROUS와 WRITE는 모두 `auto_approve`를 무시합니다. 서브에이전트가 사용자 모르게 API 키를 변경하거나 메모리에 악의적 규칙을 주입하는 시나리오를 원천 차단합니다.

### 대안 검토

| 대안 | 장점 | 단점 | 결정 |
|------|------|------|------|
| DANGEROUS에 포함 | 단순 | bash와 쓰기의 위험 프로필이 다름 | 기각 |
| STANDARD 유지 + 별도 화이트리스트 | 기존 구조 유지 | 화이트리스트 관리 복잡 | 기각 |
| **별도 WRITE 분류** | 위험 프로필에 맞는 세분화 | 분류 4단계로 증가 | **채택** |
| 전부 DANGEROUS | 가장 안전 | 쓰기마다 bash 수준 경고는 과잉 | 기각 |

---

## 4. 설계 결정 2: DANGEROUS auto_approve 무시

### 문제

서브에이전트의 `ToolExecutor`는 `auto_approve=True`로 생성됩니다. 기존 코드에서 `_execute_bash()`는 `if not self._auto_approve` 조건으로 승인을 스킵했습니다.

```python
# AS-IS: auto_approve=True이면 bash도 승인 없이 실행
if not self._auto_approve:
    approved = self._request_approval(command, reason)
    if not approved:
        return {"error": "User denied execution", "denied": True}
```

이는 `delegate_task` → 서브에이전트 → `run_bash` 경로로 셸 명령을 무승인 실행할 수 있다는 의미였습니다.

### 해결: auto_approve 조건 제거

```python
# TO-BE: auto_approve 상태와 무관하게 항상 승인 요구
approved = self._request_approval(command, reason)
if not approved:
    return {"error": "User denied execution", "denied": True}
```

> `run_bash`는 시스템 수준의 부작용을 가집니다. 파일 삭제, 프로세스 종료, 네트워크 호출 등 어떤 명령이든 실행 가능합니다. 이런 도구에 `auto_approve`를 적용하는 것은 "편의를 위해 자물쇠를 제거하는 것"과 같습니다. **DANGEROUS 도구는 항상 사용자 승인이 필수**라는 불변 규칙을 확립했습니다.

### 서브에이전트에서의 영향

서브에이전트가 `run_bash`를 호출하면 부모 REPL의 터미널에서 승인 프롬프트가 표시됩니다. 서브에이전트는 승인이 올 때까지 블로킹됩니다.

```
  ⚠ Bash command requires approval
  Command: echo "test from sub-agent"
  Reason:  Sub-agent needs file check

  Allow? [Y/n]
```

> 이 동작은 의도적입니다. 서브에이전트가 셸 명령을 실행해야 한다면, 사용자가 명시적으로 허용해야 합니다. 프롬프트가 방해가 될 수 있지만, 무승인 셸 실행의 위험보다 낫습니다.

---

## 5. 설계 결정 3: MCP 안전 라우팅

### 문제

MCP 도구는 ToolExecutor의 안전 게이트를 **완전히 우회**했습니다. 등록된 핸들러가 없을 때 `mcp_manager.call_tool()`을 직접 호출하여 결과를 반환했습니다.

```python
# AS-IS: MCP 도구 → 안전 검사 없이 직접 실행
if self._mcp_manager is not None:
    server = self._mcp_manager.find_server_for_tool(tool_name)
    if server is not None:
        result = self._mcp_manager.call_tool(server, tool_name, tool_input)
        return result  # 어떤 검사도 없음
```

MCP 서버는 외부 프로세스입니다. 파일시스템 접근, 네트워크 호출, 브라우저 자동화 등 어떤 작업이든 수행할 수 있습니다.

### 해결: _execute_mcp() 경유

```python
# core/cli/tool_executor.py
def _execute_mcp(
    self, server: str, tool_name: str, tool_input: dict[str, Any]
) -> dict[str, Any]:
    log.info("MCP tool: %s → %s (args=%s)", tool_name, server,
             list(tool_input.keys()))

    if not self._auto_approve and not self._confirm_mcp(server, tool_name):
        return {"error": "User denied MCP tool execution", "denied": True}

    assert self._mcp_manager is not None
    result: dict[str, Any] = self._mcp_manager.call_tool(
        server, tool_name, tool_input
    )
    return result
```

> MCP 도구에 대해서는 `auto_approve`를 존중합니다. 서브에이전트가 Steam API나 arXiv 검색을 호출하는 것은 정상적인 분석 흐름의 일부이기 때문입니다. 그러나 부모 AgenticLoop에서는 사용자 확인을 거칩니다.

### MCP와 DANGEROUS/WRITE의 차이

| 분류 | auto_approve 존중 | 이유 |
|------|-------------------|------|
| **DANGEROUS** | 무시 (항상 승인) | 시스템 수준 부작용 (bash) |
| **WRITE** | 무시 (항상 승인) | 영속적 상태 변경 (메모리, 인증) |
| **MCP** | 존중 | 외부 데이터 조회가 주 용도, 서브에이전트 분석 흐름에 필수 |
| **EXPENSIVE** | 존중 | 비용 확인은 편의 기능, 안전 필수 아님 |

---

## 6. 트레이드오프 — 안전성 vs 자율성

### 발전 과정

GEODE의 HITL 체계는 3단계를 거쳐 진화했습니다.

**Phase 1 (v0.6.0)**: 초기 설계
```
SAFE(7종) → 즉시 실행
STANDARD(나머지) → 즉시 실행
DANGEROUS(bash) → 사용자 승인
```

**Phase 2 (v0.10.0)**: 서브에이전트 도입
```
auto_approve=True → STANDARD 스킵 (의도)
auto_approve=True → DANGEROUS 스킵 (비의도적 우회)
auto_approve=True → 쓰기 도구 스킵 (인식 못한 공백)
MCP 도구 → ToolExecutor 우회 (설계 누락)
```

**Phase 3 (v0.12.0)**: 보안 강화
```
SAFE(11종) → 즉시 실행
STANDARD(나머지) → auto_approve 존중
WRITE(4종) → 항상 승인 필수 (auto_approve 무시)
DANGEROUS(1종) → 항상 승인 필수 (auto_approve 무시)
EXPENSIVE(3종) → auto_approve 존중
MCP(외부) → auto_approve 존중 + 로깅
```

### 안전-자율 매트릭스

```
                    안전성 높음
                        │
    DANGEROUS ──────────┼───── WRITE
    (bash: 항상 승인)    │    (쓰기: 항상 승인)
                        │
  ──────────────────────┼──────────────────── 자율성 높음
                        │
    MCP ────────────────┼───── EXPENSIVE
    (외부: 부모만 승인)   │    (비용: 부모만 승인)
                        │
    STANDARD ───────────┼───── SAFE
    (일반: 무게이트)     │    (읽기: 무게이트)
                        │
                    안전성 낮음
```

> 좌상단(DANGEROUS, WRITE)은 어떤 상황에서든 사용자 승인이 필수입니다. 우하단(STANDARD, SAFE)은 자율 실행을 허용합니다. 중간 영역(MCP, EXPENSIVE)은 부모 AgenticLoop에서만 승인을 요구하고 서브에이전트에서는 자율 실행합니다.

---

## 7. HITL 매트릭스 — 최종 안전 분류 체계

### 도구별 분류표

| 분류 | auto_approve 시 | UI 마커 | 도구 | 개수 |
|------|----------------|---------|------|------|
| **SAFE** | 즉시 실행 | (없음) | `list_ips`, `search_ips`, `show_help`, `check_status`, `switch_model`, `memory_search`, `manage_rule`, `web_fetch`, `general_web_search`, `note_read`, `read_document` | 11 |
| **STANDARD** | 즉시 실행 | (없음) | `analyze_ip`*, `batch_analyze`*, `compare_ips`*, `generate_report`, `generate_data`, `schedule_job`, `trigger_event`, `create_plan`, `approve_plan`, `reject_plan`, `modify_plan`, `list_plans`, `youtube_search`, `reddit_sentiment`, `steam_info`, `google_trends`, `rate_result`, `accept_result`, `reject_result`, `rerun_node`, `delegate_task` | 21 |
| **EXPENSIVE** | 즉시 실행 | `$ Cost confirmation` | `analyze_ip` (~$1.50), `batch_analyze` (~$5.00), `compare_ips` (~$3.00) | 3* |
| **WRITE** | 항상 승인 | `✏ Write operation` | `memory_save`, `note_save`, `set_api_key`, `manage_auth` | 4 |
| **DANGEROUS** | 항상 승인 | `⚠ Bash command` | `run_bash` | 1 |
| **MCP** | 즉시 실행 | `⚡ MCP tool` | 외부 MCP 서버 도구 (Steam, Brave, arXiv, Playwright, LinkedIn) | 45+ |

*EXPENSIVE는 STANDARD의 부분집합입니다. 부모 AgenticLoop에서만 비용 확인을 표시합니다.

### 실행 흐름 결정 트리

```
도구 호출 수신
  │
  ├─ DANGEROUS? ──→ 항상 _request_approval() ──→ 승인/거부
  │
  ├─ WRITE? ──→ 항상 _confirm_write() ──→ 승인/거부
  │
  ├─ EXPENSIVE? ──→ auto_approve?
  │                  ├─ True → 즉시 실행 (서브에이전트)
  │                  └─ False → _confirm_cost() → 승인/거부
  │
  ├─ delegate_task? ──→ _execute_delegate() → SubAgentManager
  │
  ├─ 핸들러 있음? ──→ handler(**tool_input)
  │
  └─ MCP fallback? ──→ auto_approve?
                        ├─ True → 즉시 실행 (서브에이전트)
                        └─ False → _confirm_mcp() → 승인/거부
```

### 서브에이전트 안전 보장

| 시나리오 | 부모 | 서브에이전트 | 결과 |
|----------|------|------------|------|
| `analyze_ip` 호출 | 비용 확인 | 즉시 실행 | 서브에이전트는 분석이 주 업무 |
| `memory_save` 호출 | 승인 필수 | **승인 필수** | 영속 상태 변경 차단 |
| `run_bash` 호출 | 승인 필수 | **승인 필수** | 셸 실행 차단 |
| Steam MCP 검색 | 승인 필수 | 즉시 실행 | 외부 데이터 조회는 정상 흐름 |
| `delegate_task` 재귀 | 즉시 실행 | 즉시 실행 | depth 제한(max=2)으로 제어 |

---

## 8. 마무리

### 핵심 정리

| 항목 | 값 |
|------|-----|
| 발견된 우회 벡터 | 7건 (HIGH 2, MEDIUM 3, LOW 2) |
| 수정된 벡터 | 5건 (의도적 허용 2건 제외) |
| 신규 안전 분류 | `WRITE_TOOLS` (4개 도구) |
| auto_approve 무시 대상 | `DANGEROUS` + `WRITE` (5개 도구) |
| auto_approve 존중 대상 | `EXPENSIVE` + `MCP` |
| 추가된 HITL 프롬프트 | 3종 (`_confirm_write`, `_confirm_mcp`, `_request_approval` 강제) |
| 테스트 추가 | 6건 (bash 승인 강제, WRITE 승인 강제, auto_approve 무시 검증) |

### 설계 원칙

1. **DANGEROUS와 WRITE는 불변 게이트**: `auto_approve`, `is_subagent`, `depth` 어떤 플래그도 이 게이트를 비활성화할 수 없습니다.
2. **자율성은 읽기와 분석에만**: 서브에이전트가 자율적으로 수행할 수 있는 것은 데이터 조회와 분석뿐입니다. 상태 변경과 시스템 명령은 항상 사용자 동의가 필요합니다.
3. **외부 도구는 로깅 필수**: MCP 도구는 `auto_approve` 여부와 관계없이 `log.info()`로 기록됩니다. 사후 감사(audit trail)를 위한 최소한의 가시성입니다.

### 체크리스트

- [x] DANGEROUS 도구 auto_approve 우회 차단
- [x] WRITE_TOOLS 신규 분류 + 승인 게이트
- [x] MCP 도구 _execute_mcp() 경유 라우팅
- [x] 서브에이전트 WRITE/DANGEROUS 테스트 검증
- [x] README Delegation Flow 코드 경로 정합성
- [x] CLAUDE.md auto_approve 설명 정확성
