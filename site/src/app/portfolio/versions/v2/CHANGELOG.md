# GEODE Portfolio v2 — 2026-03-28

## v1 → v2 비교

### 수정 (Critical)
- Architecture L4: 47→54 Tools, 20→21 Skills (코드베이스 검증 수치)
- Scaffold stage 3: CANNOT 14→23 (CLAUDE.md 실측)
- CSS 버그: `text-white/200` → `text-white/80` (architecture.tsx)

### 개선 (High)
- 접근성: 서브텍스트 `#5A6A8A` → `#7A8CA8` (WCAG AA 준수)
- Hero: 한 줄 설명 추가 ("게임 IP 가치 추론부터 Java 마이그레이션까지")
- Hero: "Solo-built · 3개월 · 현재 진행형" 추가
- 섹션 패딩 통일: `py-28 sm:py-32 px-4 sm:px-6` 전체 적용

### 유지 (v1에서 양호)
- 16개 섹션 구조
- Scaffold 파티클 시스템 (15개)
- Multi-LLM 2탭 분리 (Pipeline/Agentic)
- REODE 3-pipeline 토글
- Coverage Matrix

### 남은 과제 (v3 대상)
- 네비게이션 메뉴/사이드바 신설
- 타임라인 스토리를 Hero 근처로 이동 검토
- L 넘버링 일관성 (Architecture L0~L5 vs Reasoning L1-L4)
- 모든 섹션 server component 전환 검토
- 모바일 SVG 가독성 개선
- REODE "83/83, 5h30m, 1153턴" 헤드라인 프로모션
