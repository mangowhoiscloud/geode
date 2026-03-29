# Proxy Cleanup — Sonnet 4.6 실행 가이드

> **목표**: 구 경로 backward-compat stub/proxy 파일 삭제 + real 파일 이동. 행동 변경 0.
> **워크트리**: `.claude/worktrees/proxy-cleanup` (branch `feature/proxy-cleanup`)
> **소크라틱**: 5문 통과 (2026-03-27)

---

## 소크라틱 게이트 결과

| # | 질문 | 답변 |
|---|------|------|
| Q1 | 이미 있는가? | stub 파일들 존재, canonical 구현은 별도 위치 — 삭제 대상 |
| Q2 | 안 하면 무엇이 깨지는가? | 구 경로 import가 살아 있으면 혼란 + infrastructure/ 레이어 비대 |
| Q3 | 효과 측정? | mypy + ruff + pytest -m "not live" + dry-run |
| Q4 | 가장 단순한 구현? | 삭제(0-consumer) → 이동+import 갱신(real files) 2단계 |
| Q5 | 프론티어 패턴? | Claude Code, Codex CLI 모두 단일 canonical path 유지 — re-export stub 배제 |

---

## Pre-flight

```bash
cd .claude/worktrees/proxy-cleanup
uv run ruff check core/ tests/ && uv run mypy core/ && uv run pytest tests/ -m "not live" -q --tb=no
```

모두 통과 확인 후 진행.

---

## 스코프 요약

### 삭제 대상 (0 consumer)

| 파일 | 이유 |
|------|------|
| `core/cli/agentic_loop.pyi` | wildcard re-export, 소비자 0 |
| `core/cli/conversation.pyi` | wildcard re-export, 소비자 0 |
| `core/cli/error_recovery.pyi` | wildcard re-export, 소비자 0 |
| `core/cli/sub_agent.pyi` | wildcard re-export, 소비자 0 |
| `core/cli/system_prompt.pyi` | wildcard re-export, 소비자 0 |
| `core/cli/tool_executor.pyi` | wildcard re-export, 소비자 0 |
| `core/infrastructure/ports/calendar_port.pyi` | deprecated stub, 소비자 0 |
| `core/infrastructure/ports/notification_port.pyi` | deprecated stub, 소비자 0 |
| `core/infrastructure/ports/signal_port.pyi` | deprecated stub, 소비자 0 |
| `core/infrastructure/ports/llm_port.py` | re-export to core.llm.router, 소비자 0 |
| `core/infrastructure/ports/agentic_llm_port.py` | re-export stub, 소비자 0 |
| `core/infrastructure/adapters/llm/claude_adapter.py` | re-export to core.llm.router, 소비자 0 |
| `core/infrastructure/adapters/llm/claude_agentic_adapter.py` | re-export stub, 소비자 0 |
| `core/infrastructure/adapters/llm/openai_adapter.py` | re-export stub, 소비자 0 |
| `core/infrastructure/adapters/llm/openai_agentic_adapter.py` | re-export stub, 소비자 0 |
| `core/infrastructure/adapters/llm/glm_adapter.py` | re-export stub, 소비자 0 |
| `core/infrastructure/adapters/llm/glm_agentic_adapter.py` | re-export stub, 소비자 0 |
| `core/infrastructure/adapters/llm/agentic_registry.py` | re-export stub, 소비자 0 |
| `core/infrastructure/adapters/llm/__init__.py` | empty package init |

### 이동 대상 (소비자 있음)

| 원본 | 이동 대상 | 소비자 수 |
|------|----------|-----------|
| `core/infrastructure/atomic_io.py` | `core/utils/atomic_io.py` | 9개 |
| `core/infrastructure/adapters/signal_adapter.py` | `core/mcp/signal_adapter.py` | 1개 (test) |

### 유지 (소비자 40+, 별도 PR)

| 포트 파일 | 소비자 수 | 이유 |
|----------|-----------|------|
| `hook_port.py`, `memory_port.py`, `domain_port.py`, `tool_port.py` | 40+ | 별도 PR 필요 |
| `auth_port.py`, `automation_port.py`, `gateway_port.py`, `orchestration_port.py` | 10+ | 별도 PR 필요 |

---

## Step A: 0-consumer 삭제

### 삭제 명령

```bash
# .pyi 파일 6개
rm core/cli/agentic_loop.pyi core/cli/conversation.pyi core/cli/error_recovery.pyi
rm core/cli/sub_agent.pyi core/cli/system_prompt.pyi core/cli/tool_executor.pyi

# ports .pyi 3개 + unused stubs 2개
rm core/infrastructure/ports/calendar_port.pyi
rm core/infrastructure/ports/notification_port.pyi
rm core/infrastructure/ports/signal_port.pyi
rm core/infrastructure/ports/llm_port.py
rm core/infrastructure/ports/agentic_llm_port.py

# adapters/llm/ 전체 (모두 re-export stub)
rm -rf core/infrastructure/adapters/llm/
```

### 검증

```bash
uv run ruff check core/ tests/
uv run mypy core/
uv run pytest tests/ -m "not live" -q --tb=no -x
```

### 커밋

```bash
git add -A
git commit -m "refactor: 0-consumer backward-compat stub 삭제

proxy-cleanup Step A: .pyi wildcard re-exports 6개,
infrastructure/ports 미사용 stub 5개,
infrastructure/adapters/llm/ re-export 8개 삭제.
소비자 0 확인 후 삭제. 행동 변경 없음."
```

---

## Step B: atomic_io 이동 (9 소비자)

### 현재 소비자

```
core/memory/project_journal.py
core/memory/agent_memory.py
core/memory/vault.py
core/memory/project.py
core/memory/user_profile.py
core/cli/result_cache.py
core/cli/transcript.py
core/cli/session_checkpoint.py
tests/test_atomic_io.py
```

모두: `from core.infrastructure.atomic_io import ...`
→: `from core.utils.atomic_io import ...`

### 작업

1. `core/utils/` 디렉터리 생성 + `__init__.py` 추가
2. `core/infrastructure/atomic_io.py` → `core/utils/atomic_io.py`로 이동 (내용 그대로)
3. 9개 소비자 import 경로 갱신
4. `core/infrastructure/atomic_io.py` 삭제

### 검증

```bash
uv run ruff check core/ tests/
uv run mypy core/
uv run pytest tests/ -m "not live" -q --tb=no -x
```

### 커밋

```bash
git add -A
git commit -m "refactor: atomic_io infrastructure/ → utils/ 이동

proxy-cleanup Step B: atomic_io.py를 core/utils/atomic_io.py로 이동.
9개 소비자 import 경로 갱신. 행동 변경 없음."
```

---

## Step C: signal_adapter 이동 (1 소비자)

### 현재 소비자

```
tests/test_signal_port.py line 8: from core.infrastructure.adapters.signal_adapter import ...
```

### 작업

1. `core/infrastructure/adapters/signal_adapter.py` → `core/mcp/signal_adapter.py`로 이동
2. `tests/test_signal_port.py` import 경로 갱신
3. 원본 파일 삭제

### 검증

```bash
uv run ruff check core/ tests/
uv run mypy core/
uv run pytest tests/test_signal_port.py -v
uv run pytest tests/ -m "not live" -q --tb=no -x
```

### 커밋

```bash
git add -A
git commit -m "refactor: signal_adapter infrastructure/adapters/ → mcp/ 이동

proxy-cleanup Step C: signal_adapter.py를 core/mcp/signal_adapter.py로 이동.
test_signal_port.py import 경로 갱신. 행동 변경 없음."
```

---

## Final: E2E + 품질 게이트

```bash
uv run ruff check core/ tests/        # 0 errors
uv run ruff format --check core/ tests/  # clean
uv run mypy core/                      # 0 errors (211+ files)
uv run pytest tests/ -m "not live" -q  # 3224+ pass
uv run geode analyze "Cowboy Bebop" --dry-run  # A (68.4)
```

> **E2E 비용 주의**: import 경로 변경만 — live LLM 불필요. `--dry-run`만 실행.

---

## 체크리스트

- [ ] Step A: .pyi 6개 삭제
- [ ] Step A: ports 미사용 stub 5개 삭제
- [ ] Step A: adapters/llm/ 전체 삭제
- [ ] Step A: lint/type/test 통과 → 커밋
- [ ] Step B: core/utils/ 생성
- [ ] Step B: atomic_io.py 이동 + 9 소비자 갱신
- [ ] Step B: lint/type/test 통과 → 커밋
- [ ] Step C: signal_adapter.py 이동 + 1 소비자 갱신
- [ ] Step C: lint/type/test 통과 → 커밋
- [ ] E2E dry-run 검증 A (68.4)
- [ ] PR 생성: feature/proxy-cleanup → main

## 위험 요소

| 위험 | 완화 |
|------|------|
| `.pyi` 파일이 IDE type-checking에 영향? | 소비자 0 확인 완료. mypy가 검증 |
| `infrastructure/` 패키지가 다른 `__init__.py`에서 wildcard import? | grep 확인: 없음 |
| `signal_adapter.py`가 `core/mcp/`에서 충돌? | core/mcp/에 signal_adapter.py 없음 확인 |
| canonical ports 변경 시 blast radius? | 이번 PR은 유지 — 40+ 소비자는 별도 PR |
