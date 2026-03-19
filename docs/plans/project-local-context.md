# project-local-context — 프로젝트-로컬 컨텍스트 어셈블리 개선

> Date: 2026-03-19 | Status: **Plan**
> 선행: geode-context-hub.md, harness-for-real 리서치
> task_id: `project-local-context`

## 0. 목표

외부 프로젝트(예: `migration-java`, `my-web-app`)에서 `geode`를 실행했을 때, 해당 프로젝트 기준으로 컨텍스트가 자동 구성되도록 한다.

**AS-IS**: `geode init` → GEODE 전용 MEMORY.md 생성 (Berserk, Cowboy Bebop 언급), 빌드/테스트 커맨드 없음
**TO-BE**: `geode init` → 프로젝트 타입 자동 감지 → 범용 템플릿 + 빌드/테스트 커맨드 SOT 생성

## 1. 리서치 요약

### harness-for-real 참조 패턴

| 패턴 | harness-for-real 구현 | GEODE 적용 |
|------|---------------------|-----------|
| **프로젝트 타입 감지** | `init.sh`가 7종 감지 (node/python-uv/python-pip/rust/go/java-maven/java-gradle) + 패키지 매니저 구분 | `geode init`에 동일 로직 Python 구현 |
| **커맨드 SOT** | `.harness-config` (BUILD_CMD/TEST_CMD/LINT_CMD/TYPECHECK_CMD) | `.geode/config.toml [commands]` 섹션 |
| **Hook 템플릿** | `hooks/backpressure.sh` (Post-tool) + `hooks/pre-commit-gate.sh` (Pre-commit) | `.claude/hooks/` 디렉토리에 템플릿 생성 |
| **CLAUDE.md 범용화** | 프로젝트별 규칙만 포함, 도메인 하드코딩 없음 | `ensure_structure()`의 기본 MEMORY.md 범용화 |
| **AGENTS.md** | 60줄 이하 운영 가이드 (빌드/테스트 명령, 패턴, 안티패턴) | `.claude/AGENTS.md` 템플릿 생성 |

## 2. 구현 범위

### 2a. 프로젝트 타입 감지 모듈 (core/cli/project_detect.py 신규)

7종 프로젝트 타입 + 패키지 매니저 자동 감지. 감지 결과를 config.toml에 기록.

### 2b. `.geode/config.toml` 확장 (core/config.py)

[project] + [commands] + [directories] 섹션 추가.

### 2c. `ProjectMemory.ensure_structure()` 범용 템플릿

GEODE 전용 내용 제거, 프로젝트 타입 기반 범용 내용으로 교체.

### 2d. Hook 템플릿 생성

`.claude/hooks/backpressure.sh` + `.claude/hooks/pre-commit-gate.sh`

### 2e. `.claude/settings.json` 훅 등록

PostToolUse + PreToolUse 훅 자동 등록.

## 3. 변경 대상 파일

| # | 파일 | 변경 내용 |
|---|------|----------|
| 1 | `core/cli/project_detect.py` (신규) | 프로젝트 타입 감지 모듈 |
| 2 | `core/cli/__init__.py` | `init` 커맨드에 감지 + hook 생성 통합 |
| 3 | `core/config.py` | `DEFAULT_CONFIG_TOML` 확장 |
| 4 | `core/memory/project.py` | `ensure_structure()` 범용 템플릿 |
| 5 | `tests/test_project_detect.py` (신규) | 프로젝트 타입 감지 테스트 |

## 4. 설계 판단

| 판단 | 근거 |
|------|------|
| `.harness-config` 대신 `.geode/config.toml` 사용 | GEODE는 이미 TOML cascade 구조 |
| Hook을 `.claude/hooks/`에 배치 | Claude Code 네이티브 hooks 디렉토리 |
| 감지 로직을 별도 모듈로 분리 | 테스트 용이성 + 단일 책임 |
| `settings.json` 덮어쓰기 대신 병합 | 기존 사용자 설정 보존 |
