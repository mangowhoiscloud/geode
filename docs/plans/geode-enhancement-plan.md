# .geode 고도화 -- 구현 계획

> Date: 2026-03-17 | ADR: `docs/adr/ADR-011-geode-enhancement.md`
> Research: `docs/plans/research-geode-enhancement.md`

## Phase 1: Quick Wins (1-2일)

### 1.1. Config Cascade -- TOML 기반 설정 파일

**목표**: `~/.geode/config.toml`(글로벌) + `.geode/config.toml`(프로젝트)을 `Settings`에 통합.

**우선순위**: CLI > env > `.geode/config.toml` > `~/.geode/config.toml` > 기본값

#### 변경 파일

| 파일 | 변경 내용 |
|------|----------|
| `core/config.py` | `_load_toml_config()` 헬퍼 추가. `Settings.__init__` 후 TOML 값으로 미설정 필드 덮어쓰기 |
| `core/config.py` | `GLOBAL_CONFIG_PATH`, `PROJECT_CONFIG_PATH` 상수 추가 |
| `tests/test_config_cascade.py` | 신규: 4-level 오버라이드 순서 검증 |

#### 구현 상세

```python
# core/config.py 추가

import tomllib  # Python 3.11+ 내장
from pathlib import Path

GLOBAL_CONFIG_PATH = Path.home() / ".geode" / "config.toml"
PROJECT_CONFIG_PATH = Path(".geode") / "config.toml"

def _load_toml_config() -> dict[str, Any]:
    """Load and merge TOML configs: project overrides global."""
    merged: dict[str, Any] = {}

    # Global first (lowest priority)
    if GLOBAL_CONFIG_PATH.exists():
        with open(GLOBAL_CONFIG_PATH, "rb") as f:
            merged.update(_flatten_toml(tomllib.load(f)))

    # Project overrides global
    if PROJECT_CONFIG_PATH.exists():
        with open(PROJECT_CONFIG_PATH, "rb") as f:
            merged.update(_flatten_toml(tomllib.load(f)))

    return merged

def _flatten_toml(data: dict, prefix: str = "") -> dict[str, Any]:
    """Flatten nested TOML sections to flat key mapping.

    [llm]
    primary_model = "claude-opus-4-6"

    -> {"model": "claude-opus-4-6"}  (mapped to Settings field names)
    """
    result: dict[str, Any] = {}
    TOML_TO_SETTINGS: dict[str, str] = {
        "llm.primary_model": "model",
        "llm.secondary_model": "default_secondary_model",
        "output.language": "",  # user_profile preference
        "output.verbose": "verbose",
        "pipeline.confidence_threshold": "confidence_threshold",
        "pipeline.max_iterations": "max_iterations",
        "cost.monthly_budget_usd": "",  # new field
        # ... 추가 매핑
    }
    for key, value in data.items():
        full_key = f"{prefix}{key}" if prefix else key
        if isinstance(value, dict):
            result.update(_flatten_toml(value, f"{full_key}."))
        else:
            mapped = TOML_TO_SETTINGS.get(full_key)
            if mapped:
                result[mapped] = value
    return result
```

**Settings 통합 방법**: `_get_settings()` 내에서 TOML 로딩 후, env/CLI로 설정되지 않은 필드만 TOML 값으로 채운다. Pydantic Settings v2의 `model_post_init` 또는 `Settings` 생성 후 직접 필드 업데이트.

#### config.toml 템플릿

```toml
# ~/.geode/config.toml (글로벌 기본값)
# 프로젝트별 오버라이드: .geode/config.toml

[llm]
primary_model = "claude-opus-4-6"
# secondary_model = "gpt-5.4"

[output]
# language = "ko"
# format = "concise"
verbose = false

[pipeline]
confidence_threshold = 0.7
max_iterations = 5

[cost]
# monthly_budget_usd = 50.0
# warning_threshold_pct = 80
```

#### 테스트 전략

```python
# tests/test_config_cascade.py

def test_global_config_loaded(tmp_path):
    """글로벌 config.toml이 Settings 기본값을 오버라이드."""

def test_project_overrides_global(tmp_path):
    """프로젝트 config.toml이 글로벌을 오버라이드."""

def test_env_overrides_toml(tmp_path, monkeypatch):
    """환경변수가 TOML 설정을 오버라이드."""

def test_missing_toml_graceful():
    """TOML 파일 없으면 기존 동작 유지 (regression)."""

def test_malformed_toml_warning(tmp_path):
    """손상된 TOML 파일 → 경고 로그 + 기본값 폴백."""
```

---

### 1.2. Run History Context Injection

**목표**: `ContextAssembler.assemble()`에서 최근 RunLog 3건을 1줄 요약으로 주입.

#### 변경 파일

| 파일 | 변경 내용 |
|------|----------|
| `core/memory/context.py` | `_inject_run_history()` 메서드 추가 |
| `core/memory/context.py` | `ContextAssembler.__init__`에 `run_log_dir` 파라미터 추가 |
| `core/runtime.py` | `_build_context_assembler()`에서 `run_log_dir` 전달 |
| `tests/test_context_assembler.py` | RunLog 주입 검증 테스트 추가 |

#### 구현 상세

```python
# core/memory/context.py 추가

def _inject_run_history(
    self,
    ip_name: str,
    context: dict[str, Any],
    max_entries: int = 3,
) -> None:
    """P6 Context Budget L2: 최근 실행 이력을 1줄 요약으로 주입.

    주입 형식: "Recent: Berserk S/81.3 (2h ago) | Cowboy Bebop A/68.4 (1d ago)"
    """
    if not self._run_log_dir:
        return

    from core.orchestration.run_log import RunLog

    # IP별 RunLog에서 pipeline_end 이벤트만 추출
    session_key = f"ip_{ip_name.lower().replace(' ', '_')}_analysis"
    run_log = RunLog(session_key, log_dir=self._run_log_dir)
    entries = run_log.read(limit=max_entries, event_filter="pipeline_end")

    if not entries:
        return

    # L2 추출: 1줄 요약
    summaries = []
    now = time.time()
    for entry in entries:
        tier = entry.metadata.get("tier", "?")
        score = entry.metadata.get("score", "?")
        age = _format_age(now - entry.timestamp)
        name = entry.metadata.get("ip_name", ip_name)
        summaries.append(f"{name} {tier}/{score} ({age})")

    context["_run_history"] = " | ".join(summaries)
```

#### P6 Context Budget 준수

| 층 | 적용 |
|----|------|
| L1 차단 | RunLog 전체를 컨텍스트에 넣지 않음 |
| L2 추출 | `pipeline_end` 이벤트의 tier/score/timestamp만 |
| L3 요약 | `"Berserk S/81.3 (2h ago)"` 형식 1줄 |

**주입 위치**: `_build_llm_summary()`의 Session 버짓(40%) 내에 포함.

---

### 1.3. `geode init` 명령

**목표**: 신규 프로젝트에서 `.geode/` + `.claude/` 구조를 자동 생성.

#### 변경 파일

| 파일 | 변경 내용 |
|------|----------|
| `geode/cli.py` (또는 `core/cli/commands.py`) | `init` 서브커맨드 추가 |
| `core/memory/project.py` | 기존 `ensure_structure()` 활용 |
| `core/memory/user_profile.py` | 기존 `ensure_structure()` 활용 |
| `tests/test_geode_init.py` | 신규 |

#### 구현 상세

```python
@app.command()
def init(
    force: bool = typer.Option(False, "--force", "-f", help="기존 구조 덮어쓰기"),
):
    """프로젝트 .geode/ 구조 초기화."""
    from core.memory.project import ProjectMemory
    from core.memory.user_profile import FileBasedUserProfile

    project_mem = ProjectMemory(Path("."))
    user_profile = FileBasedUserProfile()

    # .claude/ (ProjectMemory)
    created_claude = project_mem.ensure_structure()

    # .geode/ 구조
    geode_dirs = [
        Path(".geode/snapshots"),
        Path(".geode/reports"),
        Path(".geode/result_cache"),
        Path(".geode/models"),
        Path(".geode/sessions"),
    ]
    for d in geode_dirs:
        d.mkdir(parents=True, exist_ok=True)

    # config.toml 템플릿
    config_path = Path(".geode/config.toml")
    if not config_path.exists() or force:
        config_path.write_text(DEFAULT_CONFIG_TOML, encoding="utf-8")

    # ~/.geode/user_profile
    created_profile = user_profile.ensure_structure()

    # .gitignore에 .geode/ 추가
    _ensure_gitignore()

    console.print("[green]GEODE 프로젝트 구조를 초기화했습니다.[/green]")
```

**`.gitignore` 자동 추가 항목**:

```gitignore
# GEODE
.geode/
```

---

## Phase 2: Core Enhancements (3-5일)

### 2.1. Cost Tracker 영속화

**목표**: 세션별 LLM 비용을 `~/.geode/usage/YYYY-MM.jsonl`에 영속 기록.

#### 변경 파일

| 파일 | 변경 내용 |
|------|----------|
| `core/llm/token_tracker.py` | `CostPersistence` 클래스 추가 |
| `core/llm/token_tracker.py` | `TokenTracker.record()`에서 JSONL append |
| `core/config.py` | `cost_monthly_budget_usd`, `cost_warning_threshold_pct` 필드 추가 |
| `core/cli/commands.py` | `/usage` 슬래시 커맨드 추가 |
| `tests/test_cost_persistence.py` | 신규 |

#### JSONL 스키마

```jsonl
{"ts":1710000000,"model":"claude-opus-4-6","in":1200,"out":350,"cost":0.0148,"session":"abc","ip":"Berserk"}
```

#### 집계 명령

```
$ geode usage
                GEODE Usage Report -- 2026-03

  Model               Calls    Input     Output    Cost
  ─────────────────────────────────────────────────────
  claude-opus-4-6     142      168.5K    42.1K     $3.47
  gpt-5.4             38       22.3K     8.7K      $0.19
  ─────────────────────────────────────────────────────
  Total               180      190.8K    50.8K     $3.66

  Budget: $50.00 | Used: 7.3% | Remaining: $46.34
```

---

### 2.2. Agent Reflection -- 자동 학습 패턴 추출

**목표**: 파이프라인 완료 시 `learned.md`에 패턴 자동 기록.

#### 변경 파일

| 파일 | 변경 내용 |
|------|----------|
| `core/orchestration/hooks.py` | `PIPELINE_COMPLETE` Hook 핸들러 등록 |
| `core/memory/user_profile.py` | `add_learned_pattern()` 활용 (기존) |
| `core/orchestration/hook_discovery.py` | reflection handler 자동 발견 |
| `tests/test_agent_reflection.py` | 신규 |

#### 학습 규칙

```python
REFLECTION_RULES = [
    # Tier 변동 감지
    {
        "condition": lambda prev, curr: prev and prev["tier"] != curr["tier"],
        "pattern": "[{ip}] Tier changed: {prev_tier} -> {curr_tier} (score: {prev_score} -> {curr_score})",
        "category": "tier_change",
    },
    # 반복 실패 패턴
    {
        "condition": lambda entry: entry.get("status") == "error",
        "pattern": "[{ip}] Analysis failed: {error_type}. Consider: {mitigation}",
        "category": "failure",
    },
    # 규칙 적중 횟수
    {
        "condition": lambda entry: entry.get("matched_rules"),
        "pattern": "[{ip}] Rule '{rule_name}' applied — affected {axis_count} axes",
        "category": "rule_hit",
    },
]
```

#### 이전 결과 참조

`ResultCache` 또는 `RunLog`에서 같은 IP의 이전 결과를 조회하여 비교. Karpathy P4 Ratchet 패턴 적용: Tier 하락 시 `learned.md`에 경고 기록.

---

### 2.3. Result Cache Expiry

**목표**: 시간 기반(24h) + prompt hash 기반 캐시 무효화.

#### 변경 파일

| 파일 | 변경 내용 |
|------|----------|
| `core/cli/result_cache.py` | `ResultCache` 클래스에 expiry 로직 추가 |
| `core/cli/result_cache.py` | 캐시 엔트리에 `cached_at`, `prompt_hash` 필드 추가 |
| `tests/test_result_cache.py` | expiry 테스트 추가 |

#### 무효화 조건

```python
def _is_valid(self, entry: dict) -> bool:
    """캐시 엔트리 유효성 검증."""
    # 1. 시간 기반: 24시간 초과 → 무효
    cached_at = entry.get("_cached_at", 0)
    if time.time() - cached_at > 86400:
        return False

    # 2. 프롬프트 해시 기반: 프롬프트 변경 시 → 무효
    cached_hash = entry.get("_prompt_hash", "")
    if cached_hash and cached_hash != self._current_prompt_hash:
        return False

    return True
```

---

### 2.4. Run Log Aggregation -- `geode history` 명령

**목표**: 최근 N회 분석 결과를 요약 테이블로 출력.

#### 변경 파일

| 파일 | 변경 내용 |
|------|----------|
| `core/cli/commands.py` | `/history` 슬래시 커맨드 추가 |
| `core/orchestration/run_log.py` | `RunLogAggregator` 클래스 추가 |
| `tests/test_run_log_aggregator.py` | 신규 |

#### 출력 예시

```
$ geode history --limit 10

  Recent Analyses (last 10)

  IP                  Tier  Score  Cause              When          Cost
  ──────────────────────────────────────────────────────────────────────
  Berserk             S     81.3   conversion_failure 2h ago        $0.15
  Cowboy Bebop        A     68.4   undermarketed      1d ago        $0.12
  Ghost in the Shell  B     51.6   discovery_failure  2d ago        $0.11
  Hades               A     72.1   undermarketed      3d ago        $0.14
  ──────────────────────────────────────────────────────────────────────
  Total: 4 analyses | Avg cost: $0.13 | Avg score: 68.4
```

---

## Phase 3: Advanced Features (1-2주)

### 3.1. Workflow Persistence

**목표**: Plan Mode/Agentic Loop 진행 상태를 `.geode/workflows/`에 저장.

#### 변경 파일

| 파일 | 변경 내용 |
|------|----------|
| `core/orchestration/plan_mode.py` | `save_state()` / `load_state()` 메서드 추가 |
| `core/cli/agentic_loop.py` | 라운드 종료 시 자동 체크포인트 |
| `core/cli/commands.py` | `/resume` 슬래시 커맨드 추가 |
| `tests/test_workflow_persistence.py` | 신규 |

#### 상태 파일 구조

```
.geode/workflows/
├── plan-abc123.json          # Plan Mode 진행 상태
│   {
│     "plan_id": "abc123",
│     "ip_name": "Berserk",
│     "steps": [...],
│     "current_step": 2,
│     "partial_results": {...},
│     "created_at": 1710000000,
│     "updated_at": 1710003600
│   }
└── loop-def456.json          # Agentic Loop 체크포인트
    {
      "session_id": "def456",
      "round": 5,
      "messages": [...],       # 최근 N개 메시지만 (Context Budget)
      "tool_results": [...],
      "created_at": 1710000000
    }
```

#### 재개 흐름

```
$ geode resume

  Pending Workflows:
  1. [plan-abc123] Berserk analysis — step 2/5 (3h ago)
  2. [loop-def456] Research session — round 5 (1d ago)

  Select workflow to resume [1]:
```

---

### 3.2. Usage Dashboard

**목표**: `geode usage` 명령을 Rich 테이블/미니 차트로 확장.

#### 변경 파일

| 파일 | 변경 내용 |
|------|----------|
| `core/cli/commands.py` | `/usage` 커맨드 확장 |
| `core/llm/token_tracker.py` | `UsageAggregator` 클래스 추가 |
| `core/ui/panels.py` | `build_usage_panel()` 추가 |
| `tests/test_usage_dashboard.py` | 신규 |

#### 기능

- 일별/주별/월별 비용 추이
- 모델별 사용 비율
- IP별 분석 비용 평균
- 예산 대비 사용률 경고 (80% 이상 시 Rich Warning)
- `--export json` 옵션으로 JSON 내보내기

---

## Migration Path

### 기존 사용자 영향

| Phase | 마이그레이션 | 하위 호환 |
|-------|------------|:--------:|
| 1.1 Config Cascade | 없음 (TOML 파일 없으면 기존 동작 유지) | O |
| 1.2 Run History Injection | 없음 (RunLog 없으면 주입 안 함) | O |
| 1.3 `geode init` | 없음 (기존 프로젝트에 영향 없음) | O |
| 2.1 Cost Tracker | 없음 (JSONL 새로 생성) | O |
| 2.2 Agent Reflection | 없음 (Hook 추가만) | O |
| 2.3 Cache Expiry | 기존 캐시 무효화 가능 (재분석 필요) | O |
| 3.1 Workflow Persistence | 없음 (새 기능) | O |

**모든 Phase가 하위 호환**. 기존 `.env` + 환경변수 설정은 그대로 동작. TOML은 추가 옵션.

## 테스트 전략

### 신규 테스트 파일

| 파일 | 테스트 수 (예상) | 대상 |
|------|:-------:|------|
| `tests/test_config_cascade.py` | ~10 | TOML 로딩, 4-level 오버라이드, 에러 핸들링 |
| `tests/test_run_history_injection.py` | ~8 | ContextAssembler RunLog 주입, P6 Budget 준수 |
| `tests/test_geode_init.py` | ~6 | 디렉토리 생성, 중복 실행, force 옵션 |
| `tests/test_cost_persistence.py` | ~10 | JSONL 기록, 월별 집계, 예산 경고 |
| `tests/test_agent_reflection.py` | ~8 | 패턴 추출, dedup, Tier 변동 감지 |
| `tests/test_result_cache_expiry.py` | ~6 | 시간 만료, hash 무효화 |
| `tests/test_run_log_aggregator.py` | ~6 | 집계, 필터, 출력 형식 |
| `tests/test_workflow_persistence.py` | ~8 | 저장/복원, 재개, 정리 |

**예상 총 신규 테스트**: ~62개

### Regression 검증

```bash
# 매 Phase 완료 시 실행
uv run ruff check core/ tests/          # lint
uv run mypy core/                        # type check
uv run pytest tests/ -q                  # 전체 regression (2400+ pass)
uv run geode analyze "Berserk" --dry-run # CLI dry-run
```

## 일정 요약

| Phase | 기간 | 산출물 |
|-------|------|--------|
| Phase 1 | 1-2일 | Config Cascade + Run History Injection + `geode init` |
| Phase 2 | 3-5일 | Cost Tracker + Agent Reflection + Cache Expiry + History 명령 |
| Phase 3 | 1-2주 | Workflow Persistence + Usage Dashboard |

**Phase 1만 완료해도** 설정 투명성 + 실행 연속성 + 초기화 UX 3가지 핵심 가치를 얻는다.
