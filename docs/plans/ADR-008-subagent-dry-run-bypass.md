# ADR-008: 서브에이전트 파이프라인 dry-run 강제 해제

> Status: Accepted
> Date: 2026-03-14
> Deciders: @mangowhoiscloud

## 컨텍스트

서브에이전트(`delegate_task`)를 통한 IP 가치평가 파이프라인이 API 키가 설정되어 있어도
항상 dry-run(fixture only) 모드로 실행됨. 직접 CLI(`/analyze`, `analyze_ip` 도구)는 정상 동작.

## 근본 원인 (3-gap)

### Gap 1: 핸들러 하드코딩 (sub_agent.py:457)

```python
dry_run = args.get("dry_run", True)  # 항상 True — API 키 상태 무시
```

`make_pipeline_handler()`가 ReadinessReport에 접근하지 못해 `dry_run=True`를 기본값으로 사용.

### Gap 2: 도구 스키마 미비 (definitions.json:343-381)

`delegate_task.args`에 `dry_run` 프로퍼티가 정의되지 않아 LLM이 명시적으로 전달할 수 없음.

### Gap 3: 컨텍스트 격리 (sub_agent.py:438)

`make_pipeline_handler()`가 격리된 스레드에서 실행되어 `_get_readiness()` ContextVar에 접근 불가.

## 결정

### 1. `make_pipeline_handler()`에 `force_dry_run` 클로저 파라미터 전달

`_build_tool_handlers()`에서 `readiness.force_dry_run` 값을 클로저로 캡처하여 전달.
ContextVar 의존 없이 핸들러 생성 시점의 readiness 상태를 고정.

### 2. 핸들러 default를 `force_dry_run` 기준으로 변경

```python
# AS-IS
dry_run = args.get("dry_run", True)

# TO-BE
dry_run = args.get("dry_run", force_dry_run)
```

### 3. 도구 스키마는 변경하지 않음

dry-run 여부는 시스템이 API 키 상태로 결정해야 하며, LLM이 선택하면 안 됨.
`delegate_task` 스키마에 `dry_run` 파라미터를 노출하지 않음 (P10 Simplicity).

## 영향

| 경로 | API 키 있음 | API 키 없음 |
|------|------------|------------|
| `/analyze Berserk` | Live LLM (기존 정상) | Fixture (기존 정상) |
| `delegate_task` → analyze | **Live LLM (수정)** | Fixture (기존 정상) |

## 변경 파일

| 파일 | 변경 |
|------|------|
| `core/cli/sub_agent.py` | `make_pipeline_handler(force_dry_run)` 시그니처 추가, default 변경 |
| `core/cli/__init__.py` | `make_pipeline_handler()` 호출 시 `readiness.force_dry_run` 전달 |

## 대안 검토

| 대안 | 불채택 이유 |
|------|-----------|
| ContextVar를 스레드에 전파 | contextvars.copy_context() 필요, 복잡도 증가 |
| Global 변수로 readiness 전달 | 테스트 격리 깨짐, anti-pattern |
| definitions.json에 dry_run 추가 | LLM이 dry-run 결정하면 안 됨 (시스템 정책) |
