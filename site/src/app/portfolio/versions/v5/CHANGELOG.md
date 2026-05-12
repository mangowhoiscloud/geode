# GEODE Portfolio v5 — 2026-03-28

## v4 → v5: 정합성 + DAG + 대시 정리

### GameIP DAG 전면 재작성
- "Cortex" 노드 제거 (코드베이스에 존재하지 않음)
- 9-node 구조: Router → Signals → Analyst×4 → Eval×3 → Scoring → Verify → Synth
- Verification 노드 추가 (6-Layer 라벨)
- Confidence loopback: Verify → Gather → Signals (max 5, animated dashed)
- Router sub-label: "6-Route" → "Memory" (실제 역할)

### 숫자 최종 정합
- Tools: 54 → 52 (definitions.json 실측, 전 섹션 통일)
- Hero: 98 → 96 (52+44)
- Coverage Matrix 합계: 44 → 46 (Automation 5→6, Model Switch 행 추가)

### Em dash 정리 (30+건)
- scaffold.tsx: 제목부 대시 → 마침표
- hero.tsx: "까지 —" → "까지."
- multi-llm.tsx: "DI —" → "DI.", "— Token" → ", Token"
- context-tiers.tsx: 디렉토리 설명 17건 대시 → 마침표

### 유지 (v4에서 양호)
- 46 Hooks, v0.32, 3.3K+ Tests, Score 81.2/68.4/51.7
- Long-running Agent (while True + 5 Guards)
- SubAgent 균등화 (50 rounds, 32K tokens)
- Multi-LLM 2탭 (코드베이스 검증)
- REODE 3-pipeline (Spring startup_verify)

### 다음 (v6 대상)
- NL Router 제거 (코드에서 삭제됨, 대신 LLM 직접 tool routing 설명)
- FeedbackLoop 5-phase 섹션 신설
- 테스트 전략 / 관찰가능성 섹션
- 네비게이션 메뉴
- 모바일 반응형 SVG 개선
