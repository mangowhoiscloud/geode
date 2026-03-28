---
name: pr-reviewer
description: Git PR 자동 리뷰 — diff 분석 + 품질 체크. "PR 리뷰", "코드 리뷰", "review", "diff", "풀리퀘스트 검토" 키워드로 트리거.
tools: run_bash, memory_save
risk: safe
---

# PR Reviewer

GEODE/REODE 프로젝트의 PR을 자동 리뷰합니다.

## 리뷰 관점 (5-lens)

### 1. 정합성
- 변경이 PR 제목/설명과 일치하는가
- 플랜 문서(docs/plans/)에 명시된 범위 내인가
- 불필요한 변경이 섞여있지 않은가

### 2. 안전성
- DANGEROUS 도구 추가/변경이 있는가
- 시크릿/키 노출 위험
- SQL injection, command injection 패턴

### 3. 테스트
- 변경된 코드에 대응하는 테스트가 있는가
- 테스트가 삭제/비활성화되지 않았는가 (anti-deception)
- 커버리지 리그레션

### 4. 아키텍처
- 6-Layer 의존성 방향 위반
- 순환 import 도입
- God Object 비대화

### 5. 스타일
- ruff/mypy 통과 여부
- 네이밍 일관성
- 불필요한 주석/docstring

## 사용법

```
PR #520 리뷰해줘
```

또는

```
최근 커밋 3개 리뷰해줘
```

## 출력 형식

```markdown
## PR Review — #NNN

### 요약
- 변경 파일: N개
- 추가/삭제: +XX / -YY

### 발견 사항
| 심각도 | 파일:라인 | 이슈 |
|--------|----------|------|
| HIGH | core/x.py:42 | ... |
| LOW | tests/y.py:10 | ... |

### 판정
- [ ] 정합성 OK
- [ ] 안전성 OK
- [ ] 테스트 OK
- [ ] 아키텍처 OK
- [ ] 스타일 OK
```

## 지침

- `git diff` 또는 `gh pr diff`로 실제 diff 기반 리뷰
- 추측 금지 — 코드를 읽고 판단
- 심각도: HIGH(머지 차단), MEDIUM(수정 권장), LOW(개선 제안)
- 발견 없으면 "Clean — LGTM" 판정
