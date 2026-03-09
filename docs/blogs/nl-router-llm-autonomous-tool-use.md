# NL Router — LLM 자율 Tool Use 기반 자연어 라우팅

> Date: 2026-03-09 | Author: geode-team | Tags: nl-router, tool-use, intent-classification, graceful-degradation, CLI

## 목차

1. 도입: 명령어에서 자연어로
2. NL Router 아키텍처
3. Tool Use 기반 Intent Classification
4. 3-Stage Graceful Degradation
5. 시스템 프롬프트 동적 조립
6. 비용 추적과 Token 효율
7. 마무리

---

## 1. 도입: 명령어에서 자연어로

전통적인 CLI는 정해진 명령어만 처리합니다. GEODE는 사용자가 자연어로 의도를 표현하면 LLM이 적절한 도구를 선택하여 실행하는 NL Router(자연어 라우터)를 구현합니다.

핵심은 정규표현식 기반 패턴 매칭이 아닌, Claude의 Tool Use API를 활용한 자율적 라우팅입니다. LLM이 12개 도구 정의를 받고 스스로 어떤 도구를 호출할지 결정합니다.

## 2. NL Router 아키텍처

```python
# geode/cli/nl_router.py
@dataclass
class NLIntent:
    """자연어 입력에서 분류된 의도."""
    action: str    # analyze, search, list, help, compare, chat
    args: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0  # 1.0 = 정확 매칭, <1.0 = 퍼지

class NLRouter:
    """LLM 자율 NL Router — Claude Opus 4.6 Tool Use.

    LLM이 도구 정의를 받고:
    - 도구를 호출 → action intent
    - 텍스트로 응답 → chat intent

    정규표현식 없이 모든 라우팅을 LLM이 결정합니다.
    """
    def __init__(self, *, llm_enabled: bool = True) -> None:
        self._llm_enabled = llm_enabled

    def classify(self, text: str) -> NLIntent:
        """사용자 입력을 LLM Tool Use로 분류."""
```

> Dual Routing 패턴: Slash 명령(`/analyze Berserk`)은 deterministic dispatch로 직접 처리하고, 자연어("베르세르크를 분석해줘")는 NL Router로 전달됩니다.

## 3. Tool Use 기반 Intent Classification

NL Router는 12개 도구를 Claude에게 제공하고, LLM이 자율적으로 도구를 선택합니다.

```python
# geode/cli/nl_router.py (도구 정의, 12개)
ROUTER_TOOLS = [
    {"name": "list_ips", "description": "Show available IP list", ...},
    {"name": "analyze_ip", "description": "Analyze specific IP", ...},
    {"name": "search_ips", "description": "Keyword/genre search", ...},
    {"name": "compare_ips", "description": "Comparative analysis", ...},
    {"name": "show_help", "description": "Command reference", ...},
    {"name": "generate_report", "description": "Structured report", ...},
    {"name": "batch_analyze", "description": "Multi-IP scoring", ...},
    {"name": "check_status", "description": "System health", ...},
    {"name": "switch_model", "description": "Model/ensemble switching", ...},
]
```

**응답 파싱:**

```python
# geode/cli/nl_router.py
def _parse_tool_use(response: anthropic.types.Message) -> NLIntent:
    """tool_use 응답에서 Intent 추출."""
    for block in response.content:
        if block.type == "tool_use":
            action = _TOOL_ACTION_MAP.get(block.name, "chat")
            return NLIntent(action=action, args=block.input, confidence=1.0)

def _parse_text_response(response: anthropic.types.Message) -> NLIntent:
    """텍스트 응답 → chat intent."""
    text = "".join(b.text for b in response.content if b.type == "text")
    return NLIntent(action="chat", args={"response": text})
```

> LLM이 도구를 호출하면(`stop_reason == "tool_use"`) 해당 도구명을 action으로 매핑합니다. 도구 없이 텍스트만 응답하면 chat intent로 처리합니다. 이 방식으로 별도의 intent classifier 모델 없이 라우팅이 완성됩니다.

### 사용자 입력 → Intent 매핑 예시

| 입력 | Tool Use | Action | Args |
|---|---|---|---|
| "카우보이 비밥 분석해줘" | analyze_ip | analyze | `{"ip_name": "Cowboy Bebop"}` |
| "anime 장르 검색" | search_ips | search | `{"query": "anime"}` |
| "목록 보여줘" | list_ips | list | `{}` |
| "이 시스템이 뭐야?" | (text) | chat | `{"response": "GEODE는..."}` |

## 4. 3-Stage Graceful Degradation

API 키가 없거나 LLM 호출이 실패해도 NL Router는 동작합니다.

```python
# geode/cli/nl_router.py
def classify(self, text: str) -> NLIntent:
    # Stage 1: LLM Tool Use (primary)
    try:
        return self._call_tool_use_router(text)
    except AuthenticationError:
        return NLIntent(action="help", args={"fallback": "auth_error"})
    except BadRequestError as exc:
        if "credit balance" in str(exc).lower():
            return NLIntent(action="help", args={"fallback": "billing"})
        raise
    except Exception:
        pass

    # Stage 2: Offline pattern matching (fallback)
    return self._offline_fallback(text)

def _offline_fallback(text: str) -> NLIntent:
    """LLM 미사용 시 최소 패턴 매칭. 정상 라우팅 경로가 아닙니다."""
    lower = text.lower().strip()
    if any(kw in lower for kw in ("list", "목록", "show")):
        return NLIntent(action="list", confidence=0.5)
    if any(kw in lower for kw in ("help", "도움", "?")):
        return NLIntent(action="help", confidence=0.5)
    # Stage 3: 기본값
    return NLIntent(action="help", args={"fallback": "offline"}, confidence=0.3)
```

| Stage | 조건 | 방식 | Confidence |
|---|---|---|---|
| 1 | API 키 존재, LLM 정상 | Tool Use | 1.0 |
| 2 | API 실패 (rate limit 등) | 키워드 패턴 매칭 | 0.5 |
| 3 | 매칭 실패 | Help 출력 | 0.3 |

> API 장애가 사용자 경험을 완전히 차단하지 않습니다. Confidence가 1.0 미만이면 UI에서 fallback 모드임을 표시하여 사용자에게 정확도 수준을 알립니다.

## 5. 시스템 프롬프트 동적 조립

NL Router의 시스템 프롬프트는 사용 가능한 IP 목록을 동적으로 포함합니다.

```python
# geode/cli/nl_router.py
_ip_name_cache: list[str] | None = None

def _build_system_prompt() -> str:
    """IP fixture 목록을 캐시하여 시스템 프롬프트에 포함."""
    global _ip_name_cache
    if _ip_name_cache is None:
        _ip_name_cache = list(load_all_fixtures().keys())

    notable = ["Berserk", "Ghost in the Shell", "Cowboy Bebop"]
    return (
        "You are GEODE NL Router. Route user requests to tools.\n"
        f"Available IPs ({len(_ip_name_cache)} total): {', '.join(notable[:5])}...\n"
        "IMPORTANT: Use English IP titles even if user speaks Korean."
    )
```

> IP 목록은 첫 호출 시 로드되어 캐시됩니다. 전체 412개 IP를 프롬프트에 넣지 않고 대표 IP만 예시로 제공하여 토큰을 절약합니다. 한국어 입력에도 영어 IP 제목으로 매핑하도록 지시합니다.

## 6. 비용 추적과 Token 효율

```python
# geode/cli/nl_router.py
get_usage_accumulator().record(
    LLMUsage(
        model=LLM_ROUTER_MODEL,
        input_tokens=in_tok,
        output_tokens=out_tok,
        cost_usd=cost,
    )
)
```

NL Router는 경량 모델(Sonnet)을 사용하여 라우팅 비용을 최소화합니다. 분석 파이프라인의 Opus 호출과 별도로 추적되므로 라우팅 오버헤드를 독립적으로 모니터링할 수 있습니다.

| 항목 | NL Router | Pipeline |
|---|---|---|
| 모델 | Sonnet (경량) | Opus (분석) |
| 호출 빈도 | 입력당 1회 | IP당 10-15회 |
| 평균 토큰 | ~200 input, ~50 output | ~2000 input, ~500 output |

## 7. 마무리

### 핵심 정리

| 항목 | 값/설명 |
|---|---|
| 라우팅 방식 | Claude Tool Use API (12개 도구 정의) |
| Intent 분류 | tool_use → action, text → chat |
| Degradation | 3-Stage (LLM → Pattern → Help) |
| IP 목록 | 동적 캐시 (412개 fixture) |
| 비용 모델 | Sonnet (라우팅), Opus (분석) 분리 |
| Dual Routing | Slash (deterministic) + NL (LLM) |

### 체크리스트

- [ ] 12개 Router Tool 정의 (Anthropic Tool Use 포맷)
- [ ] tool_use / text 응답 파싱 분리
- [ ] 3-Stage Graceful Degradation 구현
- [ ] IP fixture 동적 캐시 시스템 프롬프트
- [ ] Confidence 기반 fallback 상태 표시
- [ ] Router 전용 토큰/비용 추적 분리
