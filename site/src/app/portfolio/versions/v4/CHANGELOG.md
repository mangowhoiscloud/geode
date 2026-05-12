# GEODE Portfolio v4 — 2026-03-28

## v3 → v4: 10-criteria Audit Fix

### 숫자 정합성 수정 (CLAUDE.md 실측 기준)
- Version: v0.30 → v0.32
- Hooks: 45 → 46 (전 섹션 통일)
- Tests: 2.9K+ → 3.3K+
- Berserk: 82.2 → 81.2 (CLAUDE.md 기준)
- Cowboy Bebop: 69.4 → 68.4
- Ghost in the Shell: 54.0 → 51.7
- REODE rounds: 1,133 → 1,153 (통일)

### 시인성 개선
- SVG fontSize=7 → 8 (최소 가독 기준)
- white fillOpacity 0.15/0.18 → 0.25/0.28 (informational text)
- Em dash(—) prose 사용 → 마침표/쉼표 대체 (architecture.tsx 4건)

### Architecture 정합성
- L4 "47 Tools + 20 Skills" → "54 Tools + 21 Skills" (v2에서 수정 완료)
- text-white/200 CSS 버그 수정 (v2에서 완료)

### 감사에서 발견된 남은 과제 (v5 대상)
- Tools count: 54 vs CLAUDE.md 47 확인 필요 (실측 재검증)
- GameIP DAG: Verification 노드 + Confidence loopback 누락
- Coverage Matrix 합계: 44 → 46 보정 (Session/Automation 이벤트 추가)
- 누락 시스템: ContextCondenser, PromptAssembler, FeedbackLoop, NL Router
- PlanMode 2곳 중복 (agents-tasks + reasoning)
- 40+ em dash 추가 정리
- 테스트 전략/관찰가능성/실패 모드 섹션 신설
