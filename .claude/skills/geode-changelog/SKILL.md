---
name: geode-changelog
description: GEODE CHANGELOG.md 관리 규칙. 버전 릴리스, 변경 사항 기록, 범위 결정, 형식 표준. "changelog", "release", "version", "릴리스", "변경사항", "버전" 키워드로 트리거.
---

# GEODE Changelog Convention

## File Location

`/CHANGELOG.md` (project root)

## Format

[Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/) + [SemVer 2.0.0](https://semver.org/)

```markdown
## [X.Y.Z] — YYYY-MM-DD

### Added       ← 새로운 기능
### Changed     ← 기존 기능 변경 (breaking 포함)
### Fixed       ← 버그 수정
### Removed     ← 삭제된 기능
### Architecture ← 구조적 결정 (GEODE 확장)
### Infrastructure ← CI, 빌드, 의존성 (GEODE 확장)
```

## Versioning Policy

```
MAJOR.MINOR.PATCH

MAJOR: 호환성 깨지는 변경 (파이프라인 구조, State 스키마 변경)
MINOR: 새 기능 추가 (새 노드, 새 평가기, 새 도구)
PATCH: 버그 수정, 성능 개선
```

현재: `0.x.y` — pre-release 단계. MINOR = 기능 마일스톤.

## Scope Rules — 기록할 것 / 기록하지 않을 것

### 기록할 것 (Feature-level 집계)
| 유형 | 예시 |
|------|------|
| 새 모듈/클래스 | `AgenticLoop`, `BashTool`, `SubAgentManager` |
| 새 파이프라인 노드 | `evaluator: prospect_judge` |
| 새 도구/명령어 | `/batch`, `run_bash` tool |
| 행동 변경 | NLRouter → AgenticLoop 전환 |
| 수식/임계값 변경 | 스코어링 가중치, Tier 기준 |
| 버그 수정 | confidence 계산 edge case |
| 의존성 추가/제거 | LangGraph 2.0 업그레이드 |
| CI 변경 | 새 검증 job 추가 |

### 기록하지 않을 것
| 유형 | 이유 |
|------|------|
| 내부 리팩터 (행동 불변) | 사용자/개발자 영향 없음 |
| 코드 품질 패스 (R1→R8) | 한 줄로 요약 |
| Merge 커밋 | 노이즈 |
| README/블로그 수정 | changelog 범위 밖 |
| 커밋 단위 기록 | feature 단위로 집계 |

## 작성 절차

### 새 기능 개발 완료 시
1. `[Unreleased]` 섹션에 항목 추가
2. 카테고리별 정리 (Added/Changed/Fixed)
3. 한 줄 요약 + 필요시 커밋 해시 참조

### 릴리스 시
1. `[Unreleased]` → `[X.Y.Z] — YYYY-MM-DD` 로 전환
2. 빈 `[Unreleased]` 섹션 재생성
3. Version History 테이블 업데이트
4. Footer 링크 업데이트
5. `pyproject.toml` + `core/__init__.py` 버전 동기화

### 릴리스 체크리스트
```bash
# 1. 버전 범프
# pyproject.toml: version = "X.Y.Z"
# core/__init__.py: __version__ = "X.Y.Z"

# 2. CHANGELOG.md 업데이트
# [Unreleased] → [X.Y.Z] — YYYY-MM-DD

# 3. 검증
uv run ruff check core/ tests/
uv run mypy core/
uv run pytest tests/ -q

# 4. 태그
git tag -a vX.Y.Z -m "Release vX.Y.Z"
```

## 서브섹션 가이드 (Added 내부)

큰 릴리스는 Added 내부를 기능 영역별로 분류:

```markdown
### Added

#### Core Pipeline
- ...

#### CLI
- ...

#### Memory System
- ...
```

영역 목록 (GEODE 기준):
- Core Pipeline (LangGraph)
- Analysis Engine (Analysts + Evaluators)
- Verification Layer
- CLI (REPL + Commands)
- Agentic Loop
- Memory System
- Infrastructure (Ports/Adapters)
- Orchestration (Hooks/Tasks/Runner)
- Tools & Policies
- Automation (L4.5)

## 예시

```markdown
## [Unreleased]

### Added
- `AgenticLoop` — while(tool_use) multi-round execution loop
- `BashTool` — HITL shell command execution with 9 blocked patterns

### Fixed
- Scoring confidence edge case with empty analyst array
```

## Git 히스토리 → Changelog 변환

커밋 로그에서 changelog 항목을 추출할 때:

```bash
# 마지막 릴리스 이후 feat/fix 커밋만 추출
git log v0.6.0..HEAD --oneline --grep="^feat\|^fix"
```

1. `feat` → Added
2. `fix` → Fixed
3. `refactor` (행동 변경 시) → Changed
4. 동일 기능 영역 커밋 → 하나로 집계
5. Merge/docs/ci/chore → 건너뜀 (ci는 Infrastructure에 해당 시 기록)
