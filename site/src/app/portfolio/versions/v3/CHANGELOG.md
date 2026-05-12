# GEODE Portfolio v3 — 2026-03-28

## v2 → v3 비교

### 신규: Long-running Agent 반영
- Loop 제목: "while(tool_use)" → **"while True — Long-running Agent"**
- 부제: **"for range(50) → while True + 5 Guards"**
- 스탯: "50 max rounds" → **"∞ while True"**, "4 error recovery" → **"5 safety guards"**
- **5 Safety Guards 테이블 신설**: 수렴감지 · 시간예산 · 컨텍스트80% · 컨텍스트95% · StuckDetector
- Wrap-Up Headroom 설명: 만료 30초 전 tool_choice=none

### 신규: SubAgent 예산 균등화
- Max Rounds: 10 → **50** (부모와 동일)
- Max Tokens: 8192 → **32K** (부모와 동일)

### 유지 (v2에서 양호)
- 16개 섹션 구조
- Multi-LLM 2탭 (Pipeline/Agentic) — 할루시네이션 제거 완료
- REODE 3-pipeline 토글 (Spring with startup_verify)
- Coverage Matrix, PSM Scoring radar
- 접근성 #7A8CA8 텍스트
- CANNOT 23 / CAN 6 정합성

### 남은 과제 (v4 대상)
- 네비게이션 메뉴 신설
- REODE "83/83, 5h30m, 1153턴" 헤드라인 프로모션
- BiasBuster 6종 바이어스 상세 섹션
- CUSUM 3-zone 시각화
- 모바일 SVG 가독성
- 비용 상한 가드 (세션당 $X) — 다음 이터레이션
