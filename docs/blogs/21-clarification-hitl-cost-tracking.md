# Clarification Step + HITL Safety Gate + LLM Cost Tracking — 에이전트의 방어적 실행 설계

> Date: 2026-03-12 | Author: geode-team | Tags: [clarification, hitl, cost-tracking, slot-filling, agentic-loop, safety]

## 목차

1. [도입 — 자율 실행 에이전트의 세 가지 취약점](#1-도입--자율-실행-에이전트의-세-가지-취약점)
2. [Clarification Step — 되묻기의 설계](#2-clarification-step--되묻기의-설계)
3. [HITL Safety Gate — 비용과 위험의 관문](#3-hitl-safety-gate--비용과-위험의-관문)
4. [LLM Cost Tracking — 실시간 비용 가시성](#4-llm-cost-tracking--실시간-비용-가시성)
5. [AgenticLoop 통합 — 방어적 실행의 전체 흐름](#5-agenticloop-통합--방어적-실행의-전체-흐름)
6. [설계 원천 (Design Origin)](#6-설계-원천-design-origin)
7. [마무리](#7-마무리)

---

## 1. 도입 — 자율 실행 에이전트의 세 가지 취약점

이전 포스트 [Plan-and-Execute x NL Router x Agentic Loop](18-plan-execute-nl-router-agentic-loop.md)에서 GEODE의 `while(tool_use)` 자율 실행 구조를 소개했습니다. LLM이 도구를 호출하고, 결과를 받아 다음 도구를 호출하는 반복 구조입니다.

이 구조는 강력하지만, 프로덕션 환경에서 세 가지 취약점이 드러납니다.

| 취약점 | 증상 | 비용 |
|--------|------|------|
| **파라미터 부재** | "비교해줘"만 입력 → LLM이 빈 값으로 도구 호출 → KeyError 크래시 | 사용자 신뢰 하락 |
| **위험 실행 무게이트** | 비용이 높은 분석($5+)이 확인 없이 실행 | 예산 초과 |
| **비용 불투명** | Claude Opus 4.6($75/M output)를 무자각 호출 | 월 비용 예측 불가 |

이 글에서는 GEODE가 이 세 가지를 어떻게 방어하는지 다룹니다. 핵심 개념은 다음과 같습니다.

```
사용자 입력
  │
  ▼
┌─────────────────────────────────────┐
│  AgenticLoop                        │
│  ┌──────────┐  ┌───────────────┐   │
│  │ LLM      │→ │ ToolExecutor  │   │
│  │ tool_use │  │ ┌───────────┐ │   │
│  └──────────┘  │ │Clarify?   │ │   │
│       ↑        │ │ missing → │─┼─→ "어떤 IP를 분석할까요?"
│       │        │ │ ask user  │ │   │
│       │        │ ├───────────┤ │   │
│       │        │ │Expensive? │ │   │
│       │        │ │ cost gate │─┼─→ "$ Cost confirmation"
│       │        │ ├───────────┤ │   │
│       │        │ │Dangerous? │ │   │
│       │        │ │ approval  │─┼─→ "⚠ Bash command requires approval"
│  ┌────┘        │ └───────────┘ │   │
│  │ result      └───────────────┘   │
│  │                                  │
│  │  ✢ claude-opus-4-6 · ↓1.2k      │
│  │    ↑350 · $0.0353 · 2.1s        │ ← Cost Tracking
│  └──────────────────────────────────┘
```

---

## 2. Clarification Step — 되묻기의 설계

### 2.1 문제: 빈 파라미터의 세 가지 시나리오

LLM 에이전트가 도구를 호출할 때, 필수 파라미터가 비어있는 상황은 세 가지로 분류됩니다.

| 시나리오 | 용어 | 예시 |
|----------|------|------|
| 값이 아예 없음 | **Slot Filling** | "분석해줘" → `ip_name` 없음 |
| 해석이 여러 개 | **Disambiguation** | "비밥 비교해줘" → 누구와? |
| 실행 전 확인 필요 | **Confirmation** | 배치 분석 $5 → 승인? |

기존 GEODE v0.8.0에서는 33개 도구 핸들러 중 3개만 clarification을 지원했습니다. 나머지 30개는 빈 파라미터로 실행되거나, 위임 도구(signal/web)에서 `KeyError`로 크래시했습니다.

### 2.2 표준 Clarification 프로토콜

모든 핸들러가 동일한 형식으로 clarification을 반환하도록 표준화했습니다.

```python
# core/cli/__init__.py
def _clarify(
    tool: str,
    missing: list[str],
    hint: str,
    **extra: Any,
) -> dict[str, Any]:
    """Standard clarification response for missing required params."""
    return {
        "error": f"{tool} requires: {', '.join(missing)}",
        "clarification_needed": True,
        "missing": missing,
        "hint": hint,
        **extra,
    }
```

> 핵심은 `clarification_needed: True` 플래그입니다. LLM은 이 플래그를 보고 도구를 재호출하지 않고 사용자에게 질문합니다. `missing` 필드는 정확히 어떤 값이 부족한지, `hint`는 사용자 언어로 된 질문 템플릿입니다.

### 2.3 적용 패턴: 직접 검증 vs 위임 래퍼

두 가지 패턴으로 33개 핸들러 전체를 커버합니다.

**패턴 A — 직접 검증** (필수 파라미터를 핸들러 내부에서 체크):

```python
# core/cli/__init__.py — handle_create_plan
def handle_create_plan(**kwargs: Any) -> dict[str, Any]:
    ip_name = kwargs.get("ip_name", "")
    if not ip_name:
        return _clarify("create_plan", ["ip_name"], "어떤 IP의 분석 계획을 세울까요?")
    # ... 정상 실행
```

**패턴 B — 위임 래퍼** (외부 Tool 클래스에 위임하는 핸들러의 KeyError 방지):

```python
# core/cli/__init__.py — _safe_delegate
def _safe_delegate(tool_class: type, kwargs: dict[str, Any]) -> dict[str, Any]:
    """Wrap delegated tool execution — catch KeyError as clarification."""
    try:
        return tool_class().execute(**kwargs)
    except (KeyError, TypeError) as exc:
        param = str(exc).strip("'\"")
        return _clarify(
            tool_class.__name__,
            [param],
            f"'{param}' 값을 알려주세요.",
        )
```

> `_safe_delegate`는 9개 위임 도구(web_fetch, youtube_search, steam_info 등)를 한 번에 보호합니다. 기존에는 `WebFetchTool().execute(**kwargs)`를 직접 호출하여 `kwargs["url"]`이 없으면 `KeyError`로 크래시했습니다. 이제는 크래시 대신 "url 값을 알려주세요"라는 clarification이 반환됩니다.

### 2.4 LLM 프롬프트와의 연동

Clarification이 동작하려면 LLM이 프로토콜을 이해해야 합니다.

```markdown
# core/llm/prompts/router.md — Clarification rules (CRITICAL)

Before calling a tool, verify ALL required parameters can be filled from context:
- If a required parameter is missing or ambiguous, ask the user BEFORE calling the tool.
- NEVER retry the same tool call that returned "clarification_needed" without new information.

When a tool returns `"clarification_needed": true`:
- Read the `"missing"` field to understand what is needed.
- Ask the user a concise clarifying question in their language.
- Do NOT call the same tool again until the user provides the missing info.
```

> 프롬프트에 CRITICAL로 명시한 이유는, LLM이 `clarification_needed`를 무시하고 같은 도구를 빈 값으로 재호출하는 패턴이 관찰되었기 때문입니다. "NEVER retry"와 "Do NOT call"이라는 강한 지시어가 이 문제를 방지합니다.

### 2.5 커버리지: Before vs After

| 구분 | 이전 | 이후 |
|------|------|------|
| Clarification 지원 핸들러 | 3/33 | 16/33 + 9 safe_delegate |
| 파라미터 없는 핸들러 (검증 불필요) | — | 8 (list_ips, show_help 등) |
| KeyError 크래시 가능 | 9 | 0 |

---

## 3. HITL Safety Gate — 비용과 위험의 관문

### 3.1 도구 안전 분류 체계

GEODE는 모든 도구를 네 등급으로 분류합니다.

```python
# core/cli/tool_executor.py

SAFE_TOOLS: frozenset[str] = frozenset({
    "list_ips", "search_ips", "show_help", "check_status",
    "switch_model", "memory_search", "manage_rule",
    "web_fetch", "general_web_search", "note_read", "read_document",
})

DANGEROUS_TOOLS: frozenset[str] = frozenset({ "run_bash" })

EXPENSIVE_TOOLS: dict[str, float] = {
    "analyze_ip": 1.50,
    "batch_analyze": 5.00,
    "compare_ips": 3.00,
}

# STANDARD: 나머지 — 확인 없이 실행
```

> 분류 기준은 **되돌릴 수 있는가**(reversibility)와 **비용이 발생하는가**(cost)입니다. `list_ips`는 읽기 전용이므로 SAFE, `run_bash`는 시스템 변경이 가능하므로 DANGEROUS, `analyze_ip`는 LLM 호출 비용이 $1.50 이상이므로 EXPENSIVE입니다.

### 3.2 실행 흐름: ToolExecutor의 게이트 체인

```python
# core/cli/tool_executor.py — execute()
def execute(self, tool_name: str, tool_input: dict[str, Any]) -> dict[str, Any]:
    # Gate 1: Dangerous → user approval
    if tool_name in DANGEROUS_TOOLS:
        return self._execute_dangerous(tool_name, tool_input)

    # Gate 2: Expensive → cost confirmation
    if tool_name in EXPENSIVE_TOOLS and not self._auto_approve:
        cost = EXPENSIVE_TOOLS[tool_name]
        if not self._confirm_cost(tool_name, cost):
            return {"error": "User denied expensive operation", "denied": True}

    # Gate 3: Sub-agent delegation
    if tool_name == "delegate_task":
        return self._execute_delegate(tool_input)

    # Gate 4: Registered handler or MCP fallback
    handler = self._handlers.get(tool_name)
    ...
```

> 게이트 순서가 중요합니다. DANGEROUS가 EXPENSIVE보다 먼저 체크됩니다. `run_bash`가 실수로 EXPENSIVE에도 등록되더라도, DANGEROUS 게이트가 먼저 사용자 승인을 요구합니다.

### 3.3 비용 확인 UX

```
  $ Cost confirmation
  Tool: analyze_ip
  Estimated cost: ~$1.50

  Proceed? [Y/n] _
```

사용자가 `n`을 입력하면 `{"error": "User denied expensive operation", "denied": True}`가 반환되고, LLM은 이를 보고 대안을 제시하거나 사용자에게 설명합니다.

### 3.4 HITL 핸들러 전체 목록

Plan-before-Execute 패턴과 결과 피드백을 지원하는 7개 HITL 도구가 추가되었습니다.

| 도구 | 역할 | HITL 유형 |
|------|------|-----------|
| `reject_plan` | 분석 계획 거부 | Plan Gate |
| `modify_plan` | 계획 수정 (단계 제거/템플릿 변경) | Plan Gate |
| `list_plans` | 계획 목록 조회 | Read-only |
| `rate_result` | 분석 결과 평점 (1-5) | Feedback |
| `accept_result` | 결과 수락 | Feedback |
| `reject_result` | 결과 거부 + 재분석 힌트 | Feedback |
| `rerun_node` | 파이프라인 노드 재실행 | Partial Re-execution |

> `rerun_node`는 전체 파이프라인을 다시 돌리지 않고 `scoring`, `verification`, `synthesizer`만 선택적으로 재실행합니다. 비용이 높은 `analyst` 노드(4개 병렬 LLM 호출)는 재실행 대상에서 제외했습니다.

---

## 4. LLM Cost Tracking — 실시간 비용 가시성

### 4.1 문제: Claude Opus 4.6의 비용 구조

GEODE의 기본 모델은 Claude Opus 4.6입니다.

| 항목 | 가격 |
|------|------|
| Input | $15.00 / 1M tokens |
| Output | $75.00 / 1M tokens |
| Cache Creation | Input x 1.25 |
| Cache Read | Input x 0.1 |

NL Router의 `call_llm_with_tools`는 라운드당 입출력이 발생하고, 최대 5라운드까지 반복됩니다. 단일 사용자 명령이 최대 5회의 LLM 호출을 유발할 수 있습니다. 이 비용이 기존에는 `debug` 레벨 로그에만 기록되어, 사용자가 인지할 수 없었습니다.

### 4.2 3계층 비용 추적 아키텍처

```
┌─────────────────────────────────────────────┐
│ L1: Per-Call Recording                       │
│   get_tracker().record(model, in, out)       │
│   → LLMUsage(cost_usd=...)                  │
│   → log.info("LLM call: ... cost=$0.0353")  │
├─────────────────────────────────────────────┤
│ L2: Real-time Display                        │
│   render_tokens(model, in, out, cost_usd=..)│
│   → ✢ claude-opus-4-6 · ↓1.2k ↑350         │
│     · $0.0353 · 2.1s                        │
├─────────────────────────────────────────────┤
│ L3: Session Summary                          │
│   render_session_cost_summary()              │
│   → Session Cost Summary                     │
│     Calls: 12 | Total: $0.5324              │
└─────────────────────────────────────────────┘
```

### 4.3 L1: Per-Call Recording

모든 LLM 호출 함수(`call_llm`, `call_llm_parsed`, `call_llm_with_tools`, `call_llm_streaming`)에서 응답의 `usage` 객체를 읽고 비용을 계산합니다.

```python
# core/llm/client.py — call_llm 내부
if hasattr(response, "usage") and response.usage:
    in_tok = response.usage.input_tokens
    out_tok = response.usage.output_tokens
    usage = get_tracker().record(model, in_tok, out_tok)
    log.info(
        "LLM call: model=%s in=%d out=%d cost=$%.4f",
        model, in_tok, out_tok, usage.cost_usd,
    )
```

> 로그 레벨을 `debug`에서 `info`로 올렸습니다. `--verbose` 없이도 모든 LLM 호출 비용이 기록됩니다. 프로덕션 환경에서 비용 모니터링이 debug 플래그에 의존해서는 안 됩니다.

### 4.4 L2: Real-time Display

AgenticLoop의 매 라운드마다 `render_tokens`가 호출됩니다.

```python
# core/ui/agentic_ui.py
def render_tokens(
    model: str,
    input_tokens: int,
    output_tokens: int,
    elapsed_s: float | None = None,
    cost_usd: float | None = None,
) -> None:
    """Render token usage line (Claude Code style)."""
    in_str = _fmt_tokens(input_tokens)
    out_str = _fmt_tokens(output_tokens)
    time_str = f" · {elapsed_s:.1f}s" if elapsed_s else ""
    cost_str = f" · ${cost_usd:.4f}" if cost_usd and cost_usd > 0 else ""
    line = f"  [token_info]✢ {model} · ↓{in_str} ↑{out_str}"
    line += f"{cost_str}{time_str}[/token_info]"
    console.print(line)
```

출력 예시:

```
  ✢ claude-opus-4-6 · ↓1.2k ↑350 · $0.0353 · 2.1s
```

> `↓`는 input(다운로드), `↑`는 output(업로드)입니다. Claude Code의 표기법을 따랐습니다. `_fmt_tokens`는 1200을 `1.2k`로 변환하여 가독성을 높입니다.

### 4.5 L3: Session Summary

세션 종료 시(`/quit` 또는 Ctrl+C) 누적 비용을 출력합니다. `/cost` 명령으로 중간 확인도 가능합니다.

```python
# core/ui/agentic_ui.py
def render_session_cost_summary() -> None:
    """Render cumulative session cost summary."""
    acc = get_usage_accumulator()
    if not acc.calls:
        return
    console.print("  Session Cost Summary")
    console.print(f"  Calls: {len(acc.calls)}")
    console.print(f"  Tokens: ↓{in_str} ↑{out_str}")
    console.print(f"  Total: ${acc.total_cost_usd:.4f}")
    # Per-model breakdown (multi-model 사용 시)
    ...
```

출력 예시:

```
  Session Cost Summary
  Calls: 12
  Tokens: ↓15.2k ↑4.1k
  Total: $0.5324
    claude-opus-4-6: $0.4920 (10 calls)
    claude-haiku-4-5: $0.0404 (2 calls)
```

### 4.6 GeodeStatus 스피너 — 실시간 경과 표시

LLM 호출 중 표시되는 스피너에도 비용과 경과 시간이 반영됩니다.

```python
# core/ui/status.py — GeodeStatus._format_spinner
def _format_spinner(self, message: str) -> str:
    elapsed = time.monotonic() - self._start_time
    delta = self._get_token_delta()
    parts = [f"  ✢ {message}"]
    if self._model:
        parts.append(f"{self._model}")
    if delta.cost_usd > 0:
        parts.append(f"${delta.cost_usd:.3f}")
    if elapsed > 0.5:
        mins, secs = divmod(int(elapsed), 60)
        parts.append(f"{mins}m {secs}s" if mins else f"{secs}s")
    return " · ".join(parts)
```

> Claude Code의 `✢ Whisking... (2m 35s · ↑ 3.7k tokens)` 스타일을 참고했습니다. 스피너가 돌아가는 동안에도 사용자는 현재까지의 비용과 경과 시간을 확인할 수 있습니다.

---

## 5. AgenticLoop 통합 — 방어적 실행의 전체 흐름

### 5.1 Clarification 라운드 제한

LLM이 clarification을 무시하고 같은 도구를 반복 호출하는 경우를 방지합니다.

```python
# core/cli/agentic_loop.py
class AgenticLoop:
    MAX_CLARIFICATION_ROUNDS = 3

    def run(self, user_input: str) -> AgenticResult:
        self._clarification_count = 0
        ...

    def _process_tool_calls(self, response):
        ...
        if isinstance(result, dict) and result.get("clarification_needed"):
            self._clarification_count += 1
            if self._clarification_count > self.MAX_CLARIFICATION_ROUNDS:
                result = {
                    "error": (
                        "Too many clarification attempts. "
                        "Please provide all required parameters."
                    ),
                    "max_clarifications_exceeded": True,
                }
```

> 3회 제한의 근거: 일반적으로 사용자가 1~2회 추가 정보를 제공하면 파라미터가 채워집니다. 3회를 초과하면 LLM이 프로토콜을 이해하지 못하는 것이므로, 루프를 끊고 사용자에게 직접 파라미터 입력을 요청합니다.

### 5.2 전체 실행 시퀀스

하나의 사용자 입력이 GEODE를 통과하는 전체 경로입니다.

```
User: "베르세르크 분석해줘"
  │
  ▼
AgenticLoop.run()
  │
  ├─ Round 1: LLM → tool_use: analyze_ip(ip_name="Berserk")
  │   │
  │   ├─ ToolExecutor.execute("analyze_ip", {ip_name: "Berserk"})
  │   │   ├─ DANGEROUS? No
  │   │   ├─ EXPENSIVE? Yes ($1.50) → _confirm_cost()
  │   │   │   └─ User: "Y" ✓
  │   │   └─ handler → _run_analysis("Berserk")
  │   │
  │   ├─ _track_usage() → ✢ claude-opus-4-6 · ↓2.1k ↑800 · $0.0915
  │   └─ tool_result → {"tier": "S", "score": 81.3, ...}
  │
  ├─ Round 2: LLM → end_turn (결과를 텍스트로 정리)
  │   └─ _track_usage() → ✢ claude-opus-4-6 · ↓3.5k ↑200 · $0.0675
  │
  └─ AgenticResult(text="베르세르크는 S 티어(81.3점)...", rounds=2)

Session Cost: $0.1590 (2 calls)
```

### 5.3 Clarification 시퀀스

파라미터가 부족한 경우:

```
User: "비교해줘"
  │
  ├─ Round 1: LLM → tool_use: compare_ips(ip_a="", ip_b="")
  │   └─ handler → _clarify("compare_ips", ["ip_a", "ip_b"],
  │                         "비교할 두 IP를 알려주세요.")
  │
  ├─ Round 2: LLM → text: "비교할 두 IP를 알려주세요."
  │   (clarification_needed=True를 인식 → 도구 재호출 안 함)
  │
  └─ AgenticResult(text="비교할 두 IP를 알려주세요.", rounds=2)

User: "베르세르크랑 카우보이 비밥"
  │
  ├─ Round 1: LLM → tool_use: compare_ips(ip_a="Berserk", ip_b="Cowboy Bebop")
  │   └─ 정상 실행
  ...
```

---

## 6. 설계 원천 (Design Origin)

| 패턴 | 원천 | GEODE 적용 |
|------|------|-----------|
| Clarification Protocol | Claude Code의 `AskUserQuestion` 도구 | `clarification_needed` + `missing` + `hint` |
| Tool Safety Classification | Claude Code의 permission mode (SAFE/STANDARD/DANGEROUS) | 4등급 분류 + cost gate |
| Cost Tracking | Claude Code의 `✢` token display | `render_tokens` + session summary |
| Max Clarification Rounds | OpenClaw의 Attempt Loop (max_attempts=3) | `MAX_CLARIFICATION_ROUNDS = 3` |
| Safe Delegate Wrapper | Python EAFP (Easier to Ask Forgiveness) | `_safe_delegate` — try/except KeyError |

---

## 7. 마무리

### 핵심 정리

| 항목 | 값/설명 |
|------|---------|
| Clarification 커버리지 | 33개 핸들러 중 25개 검증 (8개는 파라미터 없음) |
| KeyError 크래시 가능 도구 | 9 → 0 (`_safe_delegate` 래퍼) |
| 안전 분류 등급 | SAFE / STANDARD / EXPENSIVE / DANGEROUS |
| 비용 확인 임계값 | analyze_ip $1.50, compare_ips $3.00, batch_analyze $5.00 |
| 비용 추적 레벨 | Per-call (L1) + Real-time UI (L2) + Session Summary (L3) |
| Clarification 최대 라운드 | 3 (AgenticLoop 내 카운터) |
| 비용 로그 레벨 | debug → info (항상 기록) |
| 슬래시 명령 | `/cost` — 세션 중간 비용 확인 |

### 체크리스트

- [x] 모든 필수 파라미터 핸들러에 `_clarify()` 적용
- [x] 위임 도구 KeyError → clarification 변환 (`_safe_delegate`)
- [x] LLM 프롬프트에 Clarification rules 명시
- [x] AgenticLoop에 clarification 라운드 제한 (MAX=3)
- [x] ToolExecutor 4등급 안전 분류 (SAFE/STANDARD/EXPENSIVE/DANGEROUS)
- [x] 비용 확인 게이트 (`_confirm_cost`)
- [x] 실시간 토큰 + 비용 표시 (`render_tokens` with `cost_usd`)
- [x] 세션 종료 시 누적 비용 요약 (`render_session_cost_summary`)
- [x] `/cost` 슬래시 명령 추가
- [x] 비용 로그 레벨 debug → info 승격
