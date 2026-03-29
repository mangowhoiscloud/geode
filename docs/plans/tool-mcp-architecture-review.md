# GEODE Tool/Skill/Bash/MCP 아키텍처 리뷰 + MCP 카탈로그 단일화

> 작성: 2026-03-26 (세션 34)
> 실행 모델: Sonnet이 자율 구현 가능하도록 파일·라인·코드 수준으로 기술

---

## 0. 현재 구성 실측 (AS-IS)

### 4가지 도구 시스템

| 시스템 | 개수 | 위치 | 역할 |
|--------|------|------|------|
| **Native Tools** | 47개 | `definitions.json` + `tool_handlers.py` (45 핸들러) | GEODE 내장 기능 (분석, 메모리, 스케줄 등) |
| **Skills** | 22개 (.geode/skills/) + core/skills/ 런타임 | `.geode/skills/` Markdown + `core/skills/skills.py` | 프롬프트 주입 전문 지식 (파이프라인, 검증, gitflow 등) |
| **Bash** | 1개 (run_bash) | `tool_handlers.py` 내 handle_run_bash | 셸 명령 실행, DANGEROUS 권한 |
| **MCP** | 35+ 카탈로그, 8 DEFAULT, 22 AUTO_DISCOVER | `catalog.py` + `registry.py` + `mcp_servers.json` | 외부 서비스 연결 (브라우저, 검색, DB 등) |

### 기능 중복 실측

| 기능 | Native Tool | MCP 서버 | 상태 |
|------|------------|---------|------|
| 웹 검색 | `general_web_search` (Anthropic native) | `brave-search`, `tavily-search`, `exa` | **3중 겹침** |
| 웹 페이지 읽기 | `web_fetch` (Anthropic native) | `fetch` (MCP, 현재 E404) | 겹치지만 MCP 쪽 깨짐 |
| YouTube | `youtube_search` (도구) | `youtube-transcript` (MCP) | 용도 다름 (검색 vs 자막) |
| Reddit | `reddit_sentiment` (도구) | `reddit` (MCP) | **겹침** |
| Steam | `steam_info` (도구) | `steam` (MCP) | **겹침** |
| Google Trends | `google_trends` (도구) | `google-trends` (MCP, E404) | MCP 깨짐 |
| 메모리 | `memory_search`/`memory_save` (도구) | `memory` (MCP, 미연결) | 독립 |
| 파일 읽기 | `read_document` (도구) | `filesystem` (MCP, 미연결) | 독립 |
| Git | 없음 | `git` (MCP, 미연결) | MCP만 |
| 브라우저 | 없음 | `playwright`, `playwriter` | MCP만 |

### 아키텍처 문제점

1. **MCP 3중 설정**: catalog.py(382줄) + registry.py(257줄) + mcp_servers.json — 서버 추가마다 3곳 수정
2. **Native/MCP 기능 겹침**: steam, reddit, web_search 등 같은 기능이 두 시스템에 존재
3. **깨진 MCP 엔트리**: fetch(E404), google-trends(E404)가 카탈로그에 잔류
4. **스케줄러 callback=None**: 스케줄러가 fire는 하지만 실행할 콜백이 없음
5. **Skills은 잘 분리됨**: 프롬프트 주입 전용으로 도구와 겹치지 않음 (문제 없음)

---

## 1. MCP 카탈로그 단일화 (P0)

### 소크라틱 게이트 통과 완료

- Q1: 코드에 단일화 없음 (실측 확인)
- Q2: 서버 추가마다 3곳 수정 + 불일치 버그 가능
- Q3: 수정 파일 수 3→1로 측정
- Q4: registry → manager 흡수가 가장 단순
- Q5: Claude Code/Codex/Cline/OpenAI Agents SDK 4종 모두 설정 1곳

### Phase 1: Registry → Manager 흡수

**목표**: `registry.py` 삭제, 로직을 `manager.py`로 이동

**수정 파일 및 구체적 변경:**

#### 1-1. `core/mcp/manager.py` — load_config() 수정

현재 (L262-307):
```python
def load_config(self) -> int:
    from core.mcp.registry import MCPRegistry
    registry = MCPRegistry(dotenv_path=".env")
    self._servers = registry.discover()

    if _CONFIG_PATH.exists():
        file_servers = json.loads(_CONFIG_PATH.read_text())
        self._servers.update(file_servers)
```

변경 후:
```python
def load_config(self) -> int:
    """Load MCP servers from config file only (no registry)."""
    self._servers = {}

    # Primary: .geode/config.toml [mcp.servers] 섹션
    config_toml = Path(".geode/config.toml")
    if config_toml.exists():
        import tomllib
        with open(config_toml, "rb") as f:
            toml_data = tomllib.load(f)
        mcp_section = toml_data.get("mcp", {}).get("servers", {})
        for name, cfg in mcp_section.items():
            self._servers[name] = {
                "command": cfg["command"],
                "args": cfg.get("args", []),
                "env": self._resolve_env(cfg.get("env", {})),
            }

    # Fallback: .claude/mcp_servers.json (레거시 호환)
    if _CONFIG_PATH.exists():
        file_servers = json.loads(_CONFIG_PATH.read_text())
        for name, cfg in file_servers.items():
            if name not in self._servers:  # toml이 우선
                self._servers[name] = cfg

    return len(self._servers)
```

#### 1-2. `core/mcp/registry.py` — 삭제

- 파일 전체 삭제 (257줄)

#### 1-3. 소비자 3곳 import 수정

| 파일 | 라인 | 현재 | 변경 |
|------|------|------|------|
| `core/cli/tool_handlers.py` | L668 | `from core.mcp.registry import MCPRegistry` | 삭제, manager에서 직접 status 조회 |
| `core/cli/__init__.py` | L480 | `from core.mcp.registry import MCPRegistry as _MCPReg` | 삭제 |
| `core/cli/tool_handlers.py` | L686-690 | `registry = MCPRegistry(); mcp_status = registry.get_mcp_status(...)` | `mcp_status = mcp_manager.get_status()` |

**구체적으로**: `tool_handlers.py`의 `handle_check_status()` (L666-699)에서 MCPRegistry 사용 부분을 MCPServerManager의 메서드로 대체.

MCPServerManager에 `get_status()` 메서드 추가 필요 (registry.py의 `get_mcp_status()` 로직 이식, ~30줄).

#### 1-4. 테스트 수정

```bash
# registry 관련 테스트 찾기
grep -rl "MCPRegistry\|from core.mcp.registry" tests/

# 해당 테스트에서 MCPRegistry → MCPServerManager로 변경
# 또는 registry 전용 테스트는 삭제
```

### Phase 2: Catalog 검색 전용으로 축소

**목표**: catalog.py에서 서버 실행 설정(command, args, env_keys)을 제거하고 검색 메타데이터만 유지

#### 2-1. `core/mcp/catalog.py` — MCPCatalogEntry 축소

현재:
```python
@dataclass(frozen=True)
class MCPCatalogEntry:
    name: str
    package: str        # ← 실행 설정
    description: str
    tags: tuple[str, ...]
    env_keys: tuple[str, ...] = ()  # ← 실행 설정
    command: str = "npx"            # ← 실행 설정
    extra_args: tuple[str, ...] = ()  # ← 실행 설정
```

변경 후:
```python
@dataclass(frozen=True)
class MCPCatalogEntry:
    name: str
    description: str
    tags: tuple[str, ...]
    install_hint: str  # "npx @playwright/mcp" — 사용자 안내용
```

#### 2-2. 카탈로그 엔트리 정리

- 35+ 엔트리 → 검색 메타데이터만 유지
- E404 엔트리 제거: `fetch`, `google-trends`
- 382줄 → ~150줄 예상

#### 2-3. `install_mcp_server` 핸들러 수정

`core/cli/tool_handlers.py` L1008-1037:
- catalog에서 `install_hint`를 가져와 config.toml에 서버 설정 추가하는 플로우로 변경
- 현재는 catalog의 command/args로 직접 MCPServerManager에 등록

### Phase 3: config.toml 통합

**목표**: `.geode/config.toml`에 `[mcp]` 섹션 추가

#### 3-1. `.geode/config.toml` 확장

현재:
```toml
[gateway]
...
```

추가:
```toml
[mcp.servers.playwright]
command = "npx"
args = ["-y", "@playwright/mcp"]

[mcp.servers.playwriter]
command = "npx"
args = ["-y", "playwriter@latest"]

[mcp.servers.steam]
command = "npx"
args = ["-y", "steam-mcp-server"]

[mcp.servers.brave-search]
command = "npx"
args = ["-y", "@brave/brave-search-mcp-server"]
env = { BRAVE_API_KEY = "${BRAVE_API_KEY}" }

# ... 현재 DEFAULT + AUTO_DISCOVER 서버 모두 이관
```

#### 3-2. `.claude/mcp_servers.json` 처리

- **삭제하지 않음** — Claude Code가 직접 읽는 파일이므로 유지
- GEODE 런타임은 config.toml을 우선 읽되, json을 fallback으로 유지 (Phase 1-1 코드 참조)

---

## 2. 스케줄러 callback 와이어링 (P1)

### 문제

`core/automation/scheduler.py` L539-541:
```python
if job.callback is not None:
    job.callback({"job_id": job.job_id, ...})
# callback이 None이면 아무것도 안 함
```

NL로 생성된 7개 작업 모두 `callback=None`.

### 해결 방향

NLScheduleParser가 작업 생성 시 `action` 필드(실행할 프롬프트 텍스트)를 저장하고, SchedulerService가 fire 시 AgenticLoop에 해당 프롬프트를 전달.

**수정 파일:**

#### 2-1. `core/automation/scheduler.py` — ScheduledJob에 action 필드 추가

```python
@dataclass
class ScheduledJob:
    job_id: str
    name: str
    schedule: Schedule
    callback: Callable | None = None
    action: str = ""  # ← 추가: 실행할 프롬프트 텍스트
    ...
```

`_execute_job()` 수정:
```python
def _execute_job(self, job, now_ms=None):
    ...
    try:
        if job.callback is not None:
            job.callback({"job_id": job.job_id, ...})
        elif job.action:
            # AgenticLoop에 프롬프트 전달 (큐 기반)
            self._enqueue_action(job.action, job.job_id)
        # 둘 다 없으면 no-op (현재 동작 유지)
    ...
```

#### 2-2. 큐 연결

`SchedulerService.__init__()`에 `action_queue: queue.Queue | None = None` 파라미터 추가.
`_enqueue_action()`은 이 큐에 `(job_id, action_text)`를 넣음.

`core/runtime.py`에서 SchedulerService 생성 시 큐를 주입하고, AgenticLoop이 idle 시 큐를 polling.

#### 2-3. NLScheduleParser 수정

`core/automation/nl_scheduler.py`에서 파싱 시 action 텍스트를 보존:

```
"매일 9시에 뉴스 요약해줘" → Schedule(cron="0 9 * * *"), action="뉴스 요약해줘"
"5분마다 서버 상태 확인"   → Schedule(every=300000), action="서버 상태 확인"
```

---

## 3. Native/MCP 기능 겹침 정리 (P2, 별도 이터레이션)

이건 MCP 네이티브 전환 여부 결정 후에 진행. 현재는 기록만.

| 겹침 | 권장 |
|------|------|
| steam_info (Native) vs steam (MCP) | MCP로 통합 (외부 API는 MCP가 자연스러움) |
| reddit_sentiment vs reddit MCP | MCP로 통합 |
| general_web_search vs brave-search MCP | Native 유지 (Anthropic native tool, 더 빠름) |
| google_trends vs google-trends MCP | MCP E404이므로 Native 유지 |

---

## 4. 실행 순서

| 단계 | 작업 | 선행 조건 | 검증 |
|------|------|----------|------|
| **P0-1** | Registry → Manager 흡수 | kent-beck p4 완료 | `uv run pytest tests/ -m "not live" -q` 전체 통과 |
| **P0-2** | Catalog 검색 전용 축소 | P0-1 머지 | 위와 동일 |
| **P0-3** | config.toml 통합 | P0-2 머지 | `uv run geode` 실행 → MCP 서버 연결 확인 |
| **P1** | 스케줄러 callback 와이어링 | P0 완료 | `/schedule create every 1m 테스트` → 실제 실행 확인 |
| **P2** | Native/MCP 겹침 정리 | MCP 네이티브 전환 결정 | E2E dry-run 결과 불변 |

---

## 5. Sonnet 실행 가이드

각 Phase를 독립 PR로 진행. 순서:

1. `git fetch origin && git worktree add .claude/worktrees/mcp-simplify -b feature/mcp-simplify develop`
2. Phase 1 구현 → lint/type/test → 커밋
3. Phase 2 구현 → lint/type/test → 커밋
4. Phase 3 구현 → lint/type/test → 커밋
5. E2E: `uv run geode analyze "Cowboy Bebop" --dry-run` → A (68.4) 확인
6. PR 생성 (HEREDOC)

**테스트 명령어:**
```bash
uv run ruff check core/ tests/
uv run mypy core/
uv run pytest tests/ -m "not live" -q
```
