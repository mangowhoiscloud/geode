# Tool Registry와 PolicyChain — LLM Agent의 도구 관리 설계

> Date: 2026-03-09 | Author: geode-team | Tags: tool-registry, policy-chain, lazy-loading, LLM-tools, access-control

## 목차

1. 도입: Agent에게 도구가 필요하다
2. Tool Protocol — 구조적 타이핑
3. ToolRegistry — 등록, 조회, 실행
4. PolicyChain — 다층 접근 제어
5. Lazy Loading (Defer 패턴) — 85% 컨텍스트 절감
6. Runtime 통합
7. 마무리

---

## 1. 도입: Agent에게 도구가 필요하다

LLM Agent가 실제 업무를 수행하려면 외부 시스템과 상호작용할 도구가 필요합니다. GEODE는 17개 도구를 관리하며, 파이프라인 모드(dry_run, evaluation, full_pipeline)에 따라 사용 가능한 도구가 달라집니다. ToolRegistry(도구 레지스트리)와 PolicyChain(정책 체인)으로 이 복잡성을 관리합니다.

## 2. Tool Protocol — 구조적 타이핑

```python
# geode/tools/base.py
@runtime_checkable
class Tool(Protocol):
    """GEODE Tool Protocol. 4개 속성/메서드를 구현하면 유효한 Tool입니다."""

    @property
    def name(self) -> str: ...

    @property
    def description(self) -> str: ...

    @property
    def parameters(self) -> dict[str, Any]: ...

    def execute(self, **kwargs: Any) -> dict[str, Any]: ...
```

> ABC 상속 없이 `Protocol`로 계약을 정의합니다. `isinstance(my_tool, Tool)`로 런타임 검증이 가능하며, 테스트에서 Mock 도구를 쉽게 생성할 수 있습니다.

### 구현 예시

```python
# geode/tools/analyst_tool.py
class RunAnalystTool:
    @property
    def name(self) -> str:
        return "run_analyst"

    @property
    def description(self) -> str:
        return (
            "Run a specific analyst (game_mechanics, player_experience, "
            "growth_potential, discovery) on an IP to get scored analysis."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "analyst_type": {
                    "type": "string",
                    "enum": ANALYST_TYPES,
                },
                "ip_name": {"type": "string"},
            },
            "required": ["analyst_type", "ip_name"],
        }

    def execute(self, **kwargs: Any) -> dict[str, Any]:
        result = get_dry_run_result(kwargs["analyst_type"], kwargs["ip_name"])
        return {"result": {"score": result.score, "key_finding": result.key_finding}}
```

## 3. ToolRegistry — 등록, 조회, 실행

```python
# geode/tools/registry.py
class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """도구 등록. 중복 이름은 ValueError."""
        if tool.name in self._tools:
            raise ValueError(f"Tool '{tool.name}' already registered")
        self._tools[tool.name] = tool

    def to_anthropic_tools(self, *, policy: PolicyChain | None = None,
                           mode: str = "full_pipeline") -> list[dict[str, Any]]:
        """Anthropic API 포맷으로 변환 (PolicyChain 필터링 적용)."""
        allowed = self.list_tools(policy=policy, mode=mode)
        return [
            {"name": t.name, "description": t.description, "input_schema": t.parameters}
            for t in self._tools.values() if t.name in allowed
        ]

    def execute(self, name: str, *, policy: PolicyChain | None = None,
                mode: str = "full_pipeline", **kwargs: Any) -> dict[str, Any]:
        """도구 실행 (정책 검사 포함)."""
        tool = self._tools.get(name)
        if tool is None:
            raise KeyError(f"Tool '{name}' not found")
        if policy is not None and not policy.is_allowed(name, mode=mode):
            raise PermissionError(f"Tool '{name}' blocked by policy")
        return tool.execute(**kwargs)
```

> Registry는 등록, 조회, 실행의 세 가지 책임만 갖습니다. PolicyChain을 옵셔널 파라미터로 받아 정책 검사를 위임하므로, Registry 자체는 정책 로직에 대해 알지 못합니다.

## 4. PolicyChain — 다층 접근 제어

OpenClaw의 6-Layer Resolution(Profile → Global → Agent → Group → Sandbox → Subagent)을 GEODE의 파이프라인 모드에 맞게 적용합니다.

### ToolPolicy — 단일 규칙

```python
# geode/tools/policy.py
@dataclass
class ToolPolicy:
    """단일 정책 규칙. Whitelist가 Blacklist보다 우선합니다."""
    name: str
    mode: str  # "dry_run", "evaluation", "full_pipeline", "*"
    priority: int = 100  # 낮을수록 높은 우선순위
    allowed_tools: set[str] = field(default_factory=set)  # Whitelist
    denied_tools: set[str] = field(default_factory=set)   # Blacklist

    def is_allowed(self, tool_name: str) -> bool:
        if self.allowed_tools:
            return tool_name in self.allowed_tools
        if self.denied_tools:
            return tool_name not in self.denied_tools
        return True
```

### PolicyChain — 다층 평가

```python
# geode/tools/policy.py
class PolicyChain:
    """우선순위 기반 정책 체인. 모든 해당 정책을 통과해야 허용됩니다."""

    def filter_tools(self, tool_names: list[str], *, mode: str = "full_pipeline") -> list[str]:
        applicable = [p for p in self._policies if p.mode in (mode, "*")]
        return [name for name in tool_names if all(p.is_allowed(name) for p in applicable)]

    def audit_check(self, tool_name: str, *, mode: str, user: str = "") -> PolicyAuditResult:
        """감사 추적이 포함된 권한 확인."""
        evaluations = []
        for p in applicable:
            evaluations.append({
                "policy": p.name, "priority": p.priority, "allowed": p.is_allowed(tool_name),
            })
        return PolicyAuditResult(tool_name=tool_name, allowed=allowed, evaluations=evaluations)
```

> `all()` 연산자로 AND 체인을 구현합니다. 하나의 정책이라도 거부하면 도구는 차단됩니다. `audit_check`는 어떤 정책이 차단했는지 추적하여 디버깅에 활용됩니다.

### 기본 정책 구성

```python
# geode/runtime.py
def _build_default_policies() -> PolicyChain:
    chain = PolicyChain()

    # dry_run: LLM 집중 도구 차단
    chain.add_policy(ToolPolicy(
        name="dry_run_block_llm",
        mode="dry_run",
        denied_tools={"run_analyst", "run_evaluator", "send_notification"},
    ))

    # full_pipeline: 알림 도구 기본 차단
    chain.add_policy(ToolPolicy(
        name="full_block_notification",
        mode="full_pipeline",
        denied_tools={"send_notification"},
    ))

    return chain
```

| 모드 | 차단 도구 | 이유 |
|---|---|---|
| dry_run | run_analyst, run_evaluator, send_notification | LLM 호출 없이 시뮬레이션 |
| full_pipeline | send_notification | 명시적 요청만 허용 |
| evaluation | (제한 없음) | 전체 도구 접근 가능 |

## 5. Lazy Loading (Defer 패턴) — 85% 컨텍스트 절감

17개 도구 전체를 LLM 프롬프트에 포함하면 컨텍스트 토큰이 과도하게 소모됩니다. Defer 패턴은 `tool_search` 메타 도구를 사용하여 필요한 도구만 로드합니다.

```python
# geode/tools/registry.py
def to_anthropic_tools_with_defer(
    self, *, policy: PolicyChain | None = None,
    mode: str = "full_pipeline", defer_threshold: int = 5,
) -> list[dict[str, Any]]:
    """도구 수가 임계치 초과 시 defer_loading 적용.

    85% 컨텍스트 토큰 절감.
    """
    tools = self.to_anthropic_tools(policy=policy, mode=mode)

    if len(tools) <= defer_threshold:
        return tools  # 소수 도구는 그대로

    # 카테고리 분류
    categories = {"analysis", "data", "signals", "memory", "output"}

    # tool_search 메타 도구 삽입
    tool_search = {
        "name": "tool_search",
        "description": f"Search GEODE tools. Categories: {', '.join(categories)}",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    }

    # 나머지 도구는 defer 표시
    deferred = [dict(t, defer_loading=True) for t in tools]
    return [tool_search, *deferred]
```

**동작 흐름:**

```
1. LLM은 tool_search만 전체 정의를 받음
2. LLM이 tool_search("signal enrichment")를 호출
3. Registry가 매칭 도구를 반환
4. LLM이 실제 도구(youtube_search 등)를 호출
```

> `defer_threshold=5`일 때 5개 이하의 도구는 전체 정의를 즉시 제공하고, 초과 시에만 Defer 패턴이 활성화됩니다. 이로써 소규모 도구셋에서는 추가 라운드트립 없이 동작합니다.

## 6. Runtime 통합

```python
# geode/runtime.py
def _make_tool_executor(
    llm_adapter: LLMClientPort,
    registry: ToolRegistryPort,
    policy_chain: PolicyChainPort,
) -> LLMToolCallable:

    def _default_tool_executor(name: str, **kwargs: Any) -> dict[str, Any]:
        return registry.execute(name, policy=policy_chain, **kwargs)

    def _tool_fn(system: str, user: str, *,
                 tools: list[dict[str, Any]], **kwargs: Any) -> Any:
        executor = kwargs.pop("tool_executor", None) or _default_tool_executor
        return llm_adapter.generate_with_tools(
            system, user, tools=tools, tool_executor=executor, **kwargs,
        )

    return _tool_fn
```

> Tool Executor는 Registry와 PolicyChain을 LLM Adapter에 바인딩하는 클로저입니다. `generate_with_tools`가 도구를 호출할 때마다 PolicyChain 검증이 자동으로 적용됩니다.

## 7. 마무리

### 핵심 정리

| 항목 | 값/설명 |
|---|---|
| Tool Protocol | `@runtime_checkable` Protocol, 4개 메서드 |
| Registry | 등록/조회/실행, PolicyChain 옵셔널 주입 |
| PolicyChain | 우선순위 AND 체인, Whitelist > Blacklist |
| Defer 패턴 | `tool_search` 메타 도구, 85% 컨텍스트 절감 |
| Defer 임계 | 5개 (이하: 전체 제공, 초과: defer) |
| 기본 정책 | dry_run: LLM 도구 차단, full: 알림 차단 |
| Audit | `audit_check()`로 차단 정책 추적 |

### 체크리스트

- [ ] Tool Protocol 4개 메서드 구현
- [ ] ToolRegistry에 중복 등록 방지
- [ ] PolicyChain AND 체인으로 다층 접근 제어
- [ ] Audit 추적으로 디버깅 지원
- [ ] Defer 패턴으로 대규모 도구셋 컨텍스트 최적화
- [ ] tool_search 메타 도구 카테고리 분류
- [ ] Runtime에서 Registry + PolicyChain 클로저 바인딩
