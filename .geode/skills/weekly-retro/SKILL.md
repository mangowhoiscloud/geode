---
name: weekly-retro
description: 주간 회고 — git log + 메모리 기반 작업 요약 + 다음 주 계획. "회고", "주간", "retrospective", "이번 주", "weekly", "retro" 키워드로 트리거.
tools: run_bash, memory_save
risk: safe
---

# Weekly Retrospective

지난 주 작업을 자동 요약하고 다음 주 계획을 수립합니다.

## 데이터 소스

1. **git log** — 최근 7일 커밋 (main + develop)
2. **progress.md** — 칸반 보드 Done 항목
3. **CHANGELOG.md** — 릴리스 기록
4. **프로젝트 메모리** — 인사이트, 의사결정 기록

## 회고 형식

```markdown
## 주간 회고 — YYYY-MM-DD ~ YYYY-MM-DD

### 완료한 작업
| PR | 작업 | 분류 |
|----|------|------|
| #NNN | ... | feat/fix/refactor |

### 수치
- 커밋: N개
- PR 머지: N개
- 테스트 증감: +N / -N (현재 XXXX)
- 모듈 수: NNN

### 잘한 점
- ...

### 개선할 점
- ...

### 다음 주 계획
- [ ] 항목 1 (우선순위)
- [ ] 항목 2
- [ ] 항목 3

### 배운 것
- ...
```

## 스케줄 연동

```
/schedule create "every friday at 18:00" action="이번 주 회고 생성해"
```

## 지침

- `git log --oneline --since="7 days ago"` 기반 실측
- 커밋 메시지에서 feat/fix/refactor/docs 자동 분류
- 칸반(progress.md) Done 섹션과 교차 검증
- "다음 주 계획"은 Backlog에서 우선순위 기반 추천
- 완료 후 memory_save로 회고 기록
