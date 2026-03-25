---
name: anti-deception-checklist
description: 가짜 성공 방지를 위한 검증 체크리스트. 테스트 삭제/비활성화, 커버리지 리그레션, 린트 우회, 시크릿 노출 탐지. "deception", "가짜", "fake success", "검증", "체크리스트", "삭제 탐지", "regression" 키워드로 트리거.
user-invocable: false
---

# Anti-Deception Verification Checklist

코드 변경 후 이 체크리스트로 "가짜 성공"을 탐지한다.
빌드가 녹색이 되어도 문제를 숨기는 것이지 해결한 것이 아닐 수 있다.

## Check 1: 테스트 삭제/비활성화 탐지

```bash
# 삭제된 테스트 파일
git diff --name-status HEAD~1 | grep "^D.*test_"

# 새로 추가된 @pytest.mark.skip / skipIf
git diff HEAD~1 -- "*.py" | grep -E "^\+.*@pytest\.mark\.(skip|skipIf|xfail)"

# 테스트 제외 패턴 (pyproject.toml)
git diff HEAD~1 -- pyproject.toml | grep -E "^\+.*(ignore|exclude|deselect)"
```

판정: 정당한 사유 없는 테스트 삭제/비활성화 = **FAIL**

## Check 2: 린트/타입 체크 우회 탐지

```bash
# type: ignore 남발
git diff HEAD~1 -- "*.py" | grep -E "^\+.*# type: ignore"

# noqa 남발
git diff HEAD~1 -- "*.py" | grep -E "^\+.*# noqa"

# ruff/mypy 설정에서 규칙 비활성화
git diff HEAD~1 -- pyproject.toml | grep -E "^\+.*(ignore|exclude|per-file-ignores)"
```

판정: 3개 이상 `type: ignore` 신규 추가 = **WARNING**, 규칙 비활성화 = **FAIL**

## Check 3: 커버리지 리그레션 탐지

```bash
# 커버리지 설정 임계값 하향
git diff HEAD~1 -- pyproject.toml | grep -E "^\+.*(fail_under|min_coverage)"

# 테스트 수 감소 (pytest -q 출력 비교)
uv run pytest tests/ -m "not live" -q 2>&1 | tail -1
```

판정: 커버리지 5% 이상 하락 = **FAIL**

## Check 4: 시크릿 노출 탐지

```bash
# API 키 패턴
grep -rn "sk-ant-\|sk-proj-\|sk-[a-zA-Z0-9]\{20,\}" core/ tests/ --include="*.py"

# 하드코딩된 토큰
grep -rn "Bearer \|token.*=.*['\"][a-zA-Z0-9]\{20,\}" core/ tests/ --include="*.py"

# .env 파일 커밋
git diff --name-status HEAD~1 | grep -E "^A.*\.env$"
```

판정: API 키 패턴 코드 내 노출 = **FAIL**

## Check 5: 의존성 다운그레이드 탐지

```bash
# pyproject.toml 버전 변경
git diff HEAD~1 -- pyproject.toml | grep -E "^\+.*(version|requires-python)"

# uv.lock 변경으로 패키지 버전 다운그레이드
git diff HEAD~1 -- uv.lock | grep -E "^-.*version" | head -10
```

판정: 명시적 사유 없는 의존성 다운그레이드 = **WARNING**

## GEODE 특화 체크

| 항목 | 명령 | FAIL 기준 |
|------|------|----------|
| 테스트 수 래칫 | `pytest -q` 결과 비교 | 기존보다 감소 |
| E2E 티어 불변 | `geode analyze "Cowboy Bebop" --dry-run` | A (68.4) 변동 |
| 도구 수 | `definitions.json` 카운트 | 기존보다 감소 |
| 모듈 수 | `find core/ -name "*.py"` 카운트 | 비합리적 감소 |
