# GEODE Portfolio v6→v7→v8 — 2026-03-28 (3-cycle batch)

## v5 → v6
- Feedback Loop 5-Phase 섹션 신설 (Collection → Analysis → Improvement → Validation → RLAIF)
- Navigation 바 신설 (스크롤 400px 이후 표시, 17개 섹션 점프)
- 섹션 id 속성 추가 (smooth scroll 연동)
- 총 18개 섹션 (Feedback + Nav 추가)

## v6 → v7
- Bootstrap 섹션 제거 (Architecture에 통합, 정보 밀도 개선)
- PlanMode SVG 중복 해소: reasoning.tsx 축소, agents-tasks.tsx에 상세 유지
- Hero REODE 실적 프로모션: "83/83 테스트, 5h30m, 1,153턴" 한 줄 설명에 포함
- "Solo-built · 3개월 · 현재 진행형" 문구 정리

## v7 → v8
- Hero stats flex-wrap 반응형 (모바일에서 2줄 래핑)
- Em dash 잔여 5건 정리 (reasoning, loop, automation)
- Orchestration.tsx Gemini Flash → GLM-5 수정 (할루시네이션 제거)

## 3-cycle 누적 성과
- 섹션: 16 → 17 (Feedback 추가, Bootstrap 통합 제거)
- 내비게이션: 없음 → fixed top nav bar
- PlanMode 중복: 2곳 → 1.5곳 (reasoning에서 축소)
- Hero 정보 밀도: REODE 실적 프로모션
- Em dash: ~40건 → ~5건 미만
- 반응형: Hero stats, 모바일 래핑 추가

## 남은 과제 (v9+)
- FeedbackLoop와 Automation/Drift 관계 시각화 연결
- 테스트 전략 / 관찰가능성 섹션 (RunLog, JournalHook, LangSmith)
- Failure mode 테이블 (네트워크, .owner, CI timeout 등)
- 모바일 SVG 가독성 개선 (특히 Racing Track, Hook Architecture)
- Footer 신설 (GitHub, Blog, 크레딧)
