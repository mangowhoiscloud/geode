# GEODE Portfolio v9 — 2026-07-10 아카이브

v9는 PR-PORTFOLIO-INTRO(2026-05-30)에서 만든 agent-intro 페이지입니다.
26개 섹션 평면 나열을 8개 내러티브 비트(hero + demo, two-loop 멘탈 모델,
self-evolving 차별점, audit evidence, 탭 능력 지도, lineage)로 압축한
버전이었고, 기술 깊이는 /docs로 옮겼습니다.

## v9 → v10에서 바뀌는 것

- 컨셉 전환: 서브시스템 소개 페이지 → **성장 로그(character sheet)**.
  도트 캐릭터(Geodi)와 GEODE의 성장 과정이 페이지의 축이 됩니다.
- 도트 스프라이트를 이미지가 아니라 `core/ui/geodi_art.py::GEODI_PIXELS`
  그리드에서 직접 렌더(SVG). CLI 웰컴 스크린과 같은 픽셀 데이터.
- 성장 데이터를 산문이 아니라 `src/data/geode/changelog.ts` 실측에서 유도
  (릴리스 수, 주간 캐던스 차트, 5개 성장 막).
- Astryx(@astryxdesign/core, Meta 오픈소스 디자인 시스템)를 컴포넌트
  파운데이션으로 도입, 토큰은 GEODE Axolotl Rose로 리매핑.
