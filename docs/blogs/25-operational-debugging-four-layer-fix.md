# 자율 에이전트 운영 디버깅 — 4개 레이어를 관통하는 버그 사냥기

> Date: 2026-03-14 | Author: geode-team | Tags: debugging, contextvars, MCP, CLI, sub-agent, dry-run, operations

## 목차

1. 도입 — "동작은 하는데 제대로 동작하지 않는" 에이전트
2. Layer 1: MCP 서버 연결 실패 — Graceful Degradation
3. Layer 2: CLI 입력 렌더링 — 한글 Wide-char와 Escape Code
4. Layer 3: 메모리 컨텍스트 미연결 — ContextVar 생명주기 불일치
5. Layer 4: 서브에이전트 dry-run 강제 — 3-Gap 근본 원인 분석
6. 마무리 — 교훈과 체크리스트

---

## 1. 도입 — "동작은 하는데 제대로 동작하지 않는" 에이전트

자율 에이전트 시스템은 "동작함"과 "제대로 동작함" 사이에 넓은 회색지대가 있습니다. 테스트는 통과하고, CLI는 크래시 없이 실행되지만, 실제 사용 시 미묘한 문제가 계속 발견됩니다.

이 글에서는 GEODE 에이전트 프레임워크 운영 중 발견한 **4개 레이어의 버그**를 하나의 세션에서 진단하고 수정한 과정을 정리합니다. 인프라(MCP) → UI(CLI) → 메모리(ContextVar) → 파이프라인(Sub-agent) 순서로 아래에서 위로 올라가며 문제를 해결했습니다.

```
┌─────────────────────────────────────────────┐
│  Layer 4: Sub-agent dry-run bypass          │  ← 파이프라인 동작
├─────────────────────────────────────────────┤
│  Layer 3: Memory ContextVar wiring          │  ← DI 생명주기
├─────────────────────────────────────────────┤
│  Layer 2: CLI input rendering               │  ← 사용자 인터페이스
├─────────────────────────────────────────────┤
│  Layer 1: MCP server connections            │  ← 외부 인프라
└─────────────────────────────────────────────┘
```

각 문제는 독립적이지만, 하나의 공통 패턴을 공유합니다: **"기본값(default)이 안전한 방향으로 설정되어 있어서 오류가 아닌 열화(degradation)로 나타난다."** 이런 종류의 버그는 테스트로 잡기 어렵고, 실제 사용 시에만 발견됩니다.

---

## 2. Layer 1: MCP 서버 연결 실패 — Graceful Degradation

### 증상

GEODE는 MCP(Model Context Protocol) 서버를 통해 Discord, Slack, Notion 등 외부 도구와 통합합니다. API 키가 설정되지 않은 서버에 연결을 시도하면 `Failed to connect to MCP server` 에러가 로그에 쏟아졌습니다.

### 근본 원인

`MCPServerManager._get_client()`가 환경변수 해소(resolve) 후 빈 값인지 검증하지 않았습니다. `${DISCORD_TOKEN}`이 `.env`에 없으면 빈 문자열로 해소된 채 서버 연결을 시도하고, 당연히 인증 실패합니다.

### 수정

```python
# core/infrastructure/adapters/mcp/manager.py
def _get_client(self, server_name: str) -> StdioMCPClient | None:
    config = self._servers.get(server_name)
    if config is None:
        return None

    command = config.get("command", "")
    args = config.get("args", [])
    env = self._resolve_env(config.get("env", {}))

    # Skip server if any required env var resolved to empty string
    missing = [k for k, v in env.items() if not v]
    if missing:
        log.debug(
            "MCP server '%s' skipped — missing env: %s",
            server_name,
            ", ".join(missing),
        )
        return None

    client = StdioMCPClient(command=command, args=args, env=env)
    if client.connect():
        self._clients[server_name] = client
        return client
    return None
```

> 핵심 설계 결정: 환경변수 미설정을 **에러가 아닌 skip**으로 처리합니다. 에이전트 시스템에서 외부 도구는 선택적(optional)이며, 하나의 도구 연결 실패가 전체 시스템을 중단시키면 안 됩니다.

추가로 `_resolve_env()`에 `.env` 파일 fallback을 도입했습니다. pydantic-settings가 `.env`를 Settings 필드로 로드하지만 `os.environ`에는 주입하지 않기 때문에, MCP 환경변수가 보이지 않는 문제가 있었습니다.

```python
def _resolve_env(self, env: dict[str, str]) -> dict[str, str]:
    if not hasattr(self, "_dotenv_cache"):
        self._dotenv_cache: dict[str, str | None] = {}
        if _DOTENV_PATH.exists():
            self._dotenv_cache = dotenv_values(str(_DOTENV_PATH))

    resolved: dict[str, str] = {}
    for key, value in env.items():
        if value.startswith("${") and value.endswith("}"):
            var_name = value[2:-1]
            resolved[key] = os.environ.get(
                var_name, self._dotenv_cache.get(var_name) or ""
            )
        else:
            resolved[key] = value
    return resolved
```

> `os.environ` → `.env` fallback 순서를 통해 런타임 환경변수가 항상 우선합니다. `.env`는 개발 환경 편의를 위한 보조 수단입니다.

---

## 3. Layer 2: CLI 입력 렌더링 — 한글 Wide-char와 Escape Code

### 증상 1: 한글 백스페이스 잔상

REPL에서 한글을 입력하고 백스페이스로 삭제하면 `ㅛ` 같은 자모(jamo)가 터미널에 잔상으로 남았습니다. 실제 입력 버퍼에서는 제거되었지만 화면에는 보입니다.

### 근본 원인

한글 문자는 터미널에서 2 cell 폭(wide-char)을 차지합니다. 백스페이스가 1 cell만 지우면 반쪽 글자가 남습니다. `prompt_toolkit`은 이를 올바르게 처리하지만, 프롬프트 라인 자체의 repaint가 누락되면 잔상이 남습니다.

### 수정

```python
# 프롬프트 반환 직후 라인을 강제 repaint
if first_line:
    sys.stdout.write(f"\x1b[F\x1b[2K> {first_line}\n")
    sys.stdout.flush()
```

> `\x1b[F`(커서를 이전 줄로)와 `\x1b[2K`(현재 줄 전체 삭제)를 조합하여 깨끗한 프롬프트 라인을 다시 그립니다. 이 방식은 터미널 에뮬레이터에 의존적이지만, xterm 호환 터미널에서 안정적으로 동작합니다.

### 증상 2: 방향키 Escape Code 유출

REPL에서 방향키(↑↓←→)를 누르면 `[A`, `[B` 같은 ANSI escape sequence가 입력 텍스트에 섞여 들어갔습니다.

### 근본 원인

paste drain 로직이 `select.select()`로 50ms 타임아웃 내 stdin 버퍼를 비우는데, 방향키의 escape sequence(`\x1b[A`)가 이 버퍼에 잔류하여 다음 입력에 합류했습니다.

### 수정

```python
# paste drain에서 escape sequence 포함 라인 필터링
if stripped and "\x1b" not in stripped:
    lines.append(stripped)
```

> 단순하지만 효과적입니다. `\x1b`(ESC)가 포함된 라인은 사용자 의도가 아닌 터미널 제어 시퀀스이므로 버림 처리합니다. 실제 사용자 입력에 ESC 문자가 포함되는 경우는 없습니다.

---

## 4. Layer 3: 메모리 컨텍스트 미연결 — ContextVar 생명주기 불일치

### 증상

REPL에서 `note_read` 도구를 호출하면 `"Project memory not available"` 에러가 반환되었습니다. 분석 파이프라인 내에서는 정상 동작합니다.

### 근본 원인

GEODE는 Python `contextvars`로 의존성을 주입합니다.

```
GeodeRuntime._build_memory()  →  set_project_memory()  →  ContextVar 설정
                                  set_org_memory()
```

문제는 이 설정이 **분석 파이프라인 실행 시에만** 호출된다는 것입니다. REPL의 `_interactive_loop()`에서는 `_build_memory()`가 실행되지 않으므로, 파이프라인 밖에서 메모리 도구를 직접 호출하면 ContextVar가 비어 있습니다.

```
_interactive_loop() 시작
  ├─ NL Router → note_read 호출
  │   └─ _project_memory_ctx.get(None) → None  ← 여기서 실패
  │
  └─ NL Router → analyze_ip 호출
      └─ GeodeRuntime.run()
          └─ _build_memory() → set_project_memory()  ← 여기서만 설정됨
```

### 수정

REPL 시작 시 메모리 ContextVar를 초기화합니다.

```python
# core/cli/__init__.py — _interactive_loop() 초반부
from core.memory.organization import MonoLakeOrganizationMemory
from core.memory.project import ProjectMemory
from core.tools.memory_tools import set_org_memory, set_project_memory

try:
    set_project_memory(ProjectMemory())
    set_org_memory(MonoLakeOrganizationMemory())
except Exception:
    log.debug("Memory context initialization skipped", exc_info=True)
```

> ContextVar 기반 DI의 함정입니다. ContextVar는 "설정한 스코프 내에서만 유효"하므로, 여러 진입점(REPL, CLI 명령, 파이프라인)이 있는 시스템에서는 **각 진입점에서 초기화**해야 합니다. 이 패턴이 번거롭다면 애플리케이션 최상위에서 한 번만 설정하는 bootstrap 레이어를 도입하는 것이 대안입니다.

### 메모리 누수 점검

추가로 이 변경이 메모리 누수를 유발하는지 점검했습니다.

| 클래스 | 상태 보유 | 누수 위험 |
|--------|---------|----------|
| `ProjectMemory` | Path 참조만 보유, 캐싱 없음 | 없음 |
| `MonoLakeOrganizationMemory` | `_analysis_results` dict (세션 내 증가) | 세션 종료 시 해제 |
| `InMemorySessionStore` | TTL 기반 eviction 구현 | 없음 |

> `_analysis_results`가 세션 수명 동안 증가하지만, REPL 세션은 유한하므로 실질적 누수 위험은 없습니다. 장시간 서버 모드를 도입한다면 LRU 캐시 또는 weak reference로 전환해야 합니다.

---

## 5. Layer 4: 서브에이전트 dry-run 강제 — 3-Gap 근본 원인 분석

### 증상

`delegate_task`를 통해 서브에이전트에 IP 분석을 위임하면, API 키가 설정되어 있어도 항상 dry-run(fixture only) 모드로 실행되었습니다. 직접 `/analyze` 명령은 정상적으로 live LLM을 호출합니다.

### 3-Gap 분석

이 문제는 단일 원인이 아니라 **3개의 gap이 겹쳐서** 발생했습니다.

```
┌──────────────────────────────────────────────────────┐
│ Gap 1: 핸들러 하드코딩                                  │
│ dry_run = args.get("dry_run", True)  ← 항상 True     │
├──────────────────────────────────────────────────────┤
│ Gap 2: 도구 스키마 미비                                  │
│ delegate_task.args에 dry_run 미정의 → LLM 전달 불가    │
├──────────────────────────────────────────────────────┤
│ Gap 3: 컨텍스트 격리                                    │
│ make_pipeline_handler() → 별도 스레드                   │
│ → _get_readiness() ContextVar 접근 불가                │
└──────────────────────────────────────────────────────┘
```

**Gap 1**만 있었다면 LLM이 `dry_run=False`를 명시적으로 전달하면 해결됩니다. 하지만 **Gap 2** 때문에 LLM은 이 파라미터를 알지 못합니다. 그리고 **Gap 3** 때문에 핸들러가 스스로 ReadinessReport를 조회할 수도 없습니다. 세 gap이 모두 맞물려야 문제가 발생하므로, 개별 테스트로는 발견하기 어렵습니다.

### 설계 결정: 클로저 캡처

대안을 검토한 결과, **클로저 파라미터**가 가장 단순한 해법이었습니다.

| 대안 | 불채택 이유 |
|------|-----------|
| `contextvars.copy_context()` 스레드 전파 | 복잡도 증가, 모든 핸들러에 적용 필요 |
| Global 변수로 readiness 전달 | 테스트 격리 깨짐, anti-pattern |
| `definitions.json`에 `dry_run` 추가 | LLM이 dry-run 여부를 결정하면 안 됨 (시스템 정책) |

> 세 번째 대안이 흥미롭습니다. "LLM에게 선택지를 줄까?"라는 질문인데, dry-run 여부는 **시스템 정책**이지 LLM의 판단 영역이 아닙니다. API 키가 없으면 dry-run, 있으면 live — 이 결정은 코드가 해야 합니다. P10 Simplicity 원칙에 따라 스키마를 건드리지 않았습니다.

### 수정 코드

```python
# core/cli/sub_agent.py
def make_pipeline_handler(
    *,
    run_analysis_fn: Callable[..., dict[str, Any] | None],
    search_fn: Callable[..., dict[str, Any]] | None = None,
    compare_fn: Callable[..., dict[str, Any]] | None = None,
    report_fn: Callable[..., tuple[str, str] | None] | None = None,
    force_dry_run: bool = True,  # 클로저 캡처 포인트
) -> Callable[..., dict[str, Any]]:
    def handler(task_type: str, args: dict[str, Any], **kw) -> dict[str, Any]:
        if task_type == "analyze":
            ip_name = args.get("ip_name", "")
            dry_run = args.get("dry_run", force_dry_run)  # True 대신 force_dry_run
            result = run_analysis_fn(ip_name, dry_run=dry_run)
            ...
    return handler
```

```python
# core/cli/__init__.py — _build_sub_agent_manager()
readiness = _get_readiness()

handler = make_pipeline_handler(
    run_analysis_fn=lambda ip_name, dry_run=..., **_kw: _run_analysis(...),
    ...,
    force_dry_run=readiness.force_dry_run if readiness else True,
)
```

> `force_dry_run`이 클로저에 캡처되는 시점은 **핸들러 생성 시점**입니다. 이후 핸들러가 어떤 스레드에서 실행되든, 생성 시점의 readiness 상태를 그대로 사용합니다. ContextVar의 스레드 격리 문제를 우아하게 우회하는 패턴입니다.

### 영향 매트릭스

| 경로 | API 키 있음 | API 키 없음 |
|------|------------|------------|
| `/analyze Berserk` (직접) | Live LLM (기존 정상) | Fixture (기존 정상) |
| `delegate_task` → analyze | **Live LLM (수정)** | Fixture (기존 정상) |

---

## 6. 마무리

### 공통 패턴: 안전한 기본값의 그림자

네 가지 문제 모두 **"안전한 기본값"이 문제를 은폐**하는 패턴을 공유합니다.

| Layer | 안전한 기본값 | 은폐된 문제 |
|-------|-------------|------------|
| MCP | 연결 실패 → 에러 로그 | 미설정 서버를 매번 시도 |
| CLI | 입력 버퍼에서는 정상 | 화면에 잔상 남음 |
| Memory | `None` → "not available" 메시지 | REPL에서 도구 사용 불가 |
| Sub-agent | `dry_run=True` → fixture 반환 | API 키가 있어도 live 불가 |

이 패턴의 교훈은 명확합니다: **안전한 기본값은 시스템 안정성에는 좋지만, 기능 정확성(correctness)을 보장하지 않습니다.** "crash하지 않는다"와 "올바르게 동작한다"는 다른 문제입니다.

### 디버깅 체크리스트

자율 에이전트 시스템 운영 시 주기적으로 점검할 항목입니다.

- [ ] 외부 연동(MCP, API)이 graceful skip 시 로그 레벨이 적절한가 (error vs debug)
- [ ] 다국어/wide-char 입력의 터미널 렌더링이 정상인가
- [ ] ContextVar 기반 DI가 모든 진입점에서 초기화되는가
- [ ] 서브에이전트 경로와 직접 호출 경로의 동작이 동일한가
- [ ] "기본값으로 동작함"과 "올바르게 동작함"을 구분하여 검증하는가

### 수치

| 항목 | 값 |
|------|-----|
| 수정 파일 | 4개 (`manager.py`, `__init__.py`, `sub_agent.py`, `memory_tools.py`) |
| ADR 작성 | 1건 (ADR-008) |
| PR 수 | 4건 (#76, #77, #79, #81) → develop → main (#82) |
| 테스트 | 2168 passed, 0 failures |
| CI | lint + type + security + test (Python 3.12/3.13) 전체 통과 |
