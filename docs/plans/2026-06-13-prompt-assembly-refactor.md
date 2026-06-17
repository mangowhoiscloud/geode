# 시스템 프롬프트 어셈블 + 리팩토링 계획 (2026-06-13)

기준 산출물: CL4R1T4S `CLAUDE-FABLE-5.md` (운영자 지정 1급 예시).
입력 데이터: 프롬프트 표면 전수 인벤토리(Explore, 2026-06-13) + P0 덤프 실측.

## 루브릭 (Fable 5에서 증류)

1. 단계적 강조 피라미드 — 일반문 -> bold -> CAPS는 하드 리밋 전용. CRITICAL 남발 = 신호 붕괴
2. 조건부 규칙 패턴 — "X일 때 Y. 그 외엔 Z" (전면 금지 대신 경계 명시)
3. 예시 + Rationale 라벨 — 추상 규칙마다 결정 트리 예시와 정답 근거
4. 도구 설명 = 호출 트리거 명시 — "무엇을 한다"가 아니라 "언제 불러라"
5. 제약의 정당화 — downstream harm / user benefit 프레이밍
6. 자율성·정지 규칙 명문화 — 언제 묻고, 진행하고, 끝내는지
7. 조회성 내용은 밀집 표 — 산문 대신 표/체크리스트
8. 부재의 규율 — 프롬프트 자기언급 없음, 규칙 충돌 시 우선순위 모호성 없음

## 현황 (P0 실측, v0.99.193 기준)

- 어셈블 = 7겹 합성: [wrapper override | generic prefix] + math + style guide
  + heuristics + (persona) // <dynamic_context> // model card + model guidance
  + platform hint + date + G2/G3/G4 memory + user context // AGENTIC_SUFFIX
- 18셀(모델 3 x 표면 6) 전수: 12.4~12.7KB, 실측 4,942~5,087 토큰(Anthropic 기준자)
- 중복 섹션 태그 0 (어셈블 위생 양호) — 도구 스키마 60종은 별도 tools 배열

## 단계

| 단계 | 내용 | 상태 |
|------|------|------|
| P0 | `geode prompt dump` (모델x표면 매트릭스, --measure 실측, 중복 태그 경고) + 구조 가드 5종 | 본 PR |
| P1 | 루브릭 8항으로 덤프 산출물+개별 표면 채점 -> slop 카탈로그(file:line, 심각도) | 다음 |
| P2 | 일괄 개선: (a) 어셈블 코히어런스 (b) router.md+AGENTIC_SUFFIX 재작성 (c) 도구 설명 60종 트리거 패스(tool_search 검색 인덱스 직결) (d) 하드코딩 리터럴 5곳 (e) 시드 에이전트 페르소나 8종 | (c)=P2-c done(v0.99.214). **(b)=P2-b: 루브릭 감사 결과 router.md/AGENTIC_SUFFIX 이미 규율적 → 무리한 재작성 안 함(런타임 프롬프트 고blast+최소주의). 의미보존 미세정돈 1건만 적용(near-empty `### Forbidden tool calls` 스텁→matrix intro fold), v0.99.228** |
| P3 | 해시 re-pin + 어셈블 구조 가드 확장 + 전후 토큰 실측 비교 + wrapper sections는 self-improving baseline 재측정으로 행동 검증 | **DONE(v0.99.228): AGENTIC_SUFFIX 해시 re-pin + 미배선 드리프트 가드 배선(주석의 "CI verifies"를 사실로)+토큰 char-budget ratchet(`test_prompt_integrity.py`). baseline 전체 재측정(near-saturation 비용)은 라이브 1-call 동작 스모크로 대체(conversational→text, 0 spurious tool).** |

## 측정 기준 (Q3)

- 토큰: P0 덤프 전후 비교(동일 매트릭스, --measure)
- 행동: wrapper sections 변경분은 petri dim baseline 재측정
- 구조: 해시 핀 + 중복 태그 0 유지 + 태그 순서 가드
