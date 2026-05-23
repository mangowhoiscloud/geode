# Hero Viz — Text Overflow & Box Overlap Map (v2 → v3 fix scope)

> 2026-05-20 사용자 피드백 ("글자 깨지는 거 잡아보자. 여전히
> co-scientist에선 박스 겹침. 점선 화살표 표현 고도화. 글자 깨짐
> 발생한 파트 Map → 재정렬. 용어집 마지막 장.") 의 정밀 frame 검토
> 결과.
>
> Source: 1080p60 EN render `media/videos/geode_hero/1080p60/GeodeHero-EN.mp4`,
> 16 frame 캡처 (1s 간격).

## Identified sites

| # | Frame | Bit | Site | Issue (verbatim from frame) | Root cause | Fix |
|---|---|---|---|---|---|---|
| O1 | 7s | Bit 4 | STAGE 1 agent grid — `generator` / `proximity` / `critic` row | agent box 가 좌우로 ~30% overlap. "generator" 의 우측 자가 옆 박스 fill 위에 그려짐. Box 색은 fill_opacity 0.85 라 underlying box 가 비춰보임 | `outer_box.width=3.4` 안에 3 box × `width=1.4` + col spacing `1.0` = 합산 width 가 outer_box 보다 큼 | Agent box width 1.4→1.05; col spacing 1.0→1.15. Outer box width 3.4→3.6 |
| O2 | 7s | Bit 4 | STAGE 1 footer 의 "Survivors" leaderboard label | "Survivors" → "Surviv" cut-off (frame_7s 의 leaderboard 가 첫 fill animation 도중 캡처) — label 자체는 정상이지만 leaderboard 가 fill 되는 transition 중에 일부 slot 이 dim 으로 보임. 실제 정적 frame 은 OK | animation timing — `LaggedStart` 의 fill 0.25s × 3 가 캡처 시점에 절반만 진행 | 실제 글자 깨짐은 아님. PASS (visual artifact of frame timing, not layout bug). 단 보다 안전하게 leaderboard `width=1.4→1.6` 으로 라벨이 박스보다 좁게 |
| O3 | 11s | Bit 6 | Petri box → 4×5 dim grid 사이 점선 화살표 | dashed line 만 있고 head 없음 → "이게 어디로 가는 흐름인가" 직관 약함. 또 line 이 grid 와 visual 으로 평행하지 않음 | `DashedLine` 만 사용 (no arrow tip) | Custom helper `_dashed_arrow_with_head` — `DashedLine` + 작은 `Triangle` tip 결합. 모든 점선 화살표에 head 추가 |
| O4 | 15s | Bit 8 | dim_means / dim_stderr 박스 안 텍스트 `"{broken_tool_use: 2.5, …}"` | "{broken_tool_use" 의 `{` 가 box left edge 와 닿음. 우측은 ellipsis `…` 직전 cut-off 위험 | `means_box.width=3.0` 안에 font_size=11 의 ~30 char text — width-padding 부족 | width 3.0→3.4; font_size 11→10; padding 명시 (`label` 의 `to_edge` 안 쓰고 explicit shift) |
| O5 | 21s | Bit 10 | STAGE 3 의 fitness gauge `0.00` value label | gauge 가 0.00 일 때 fill_rect width=0.01 + value text "0.00" 가 fill_rect 의 우측 edge 와 거의 같은 x 좌표 → 시각적 stacking | `next_to(gauge_track, DOWN)` 이 fill 의 너비와 무관 | value label 을 gauge_track 의 center 아래 (DOWN buff 0.15) 로 고정 |
| O6 | 25s | Bit 12 | Cycle arrow STAGE 3 baseline.json → STAGE 1 | 직선 dashed line 이 STAGE 2 의 dim_boxes / Petri box (dimmed 30%) 위를 가로질러 그려짐 → 다른 element 와 시각적 overlap | 직선 path 선택 (좌하향 long diagonal) | `ArcBetweenPoints` 또는 path 분할: STAGE 3 → DOWN → STAGE 1 의 L-shape |
| O7 | all | global | 모든 점선 화살표 (Bit 5/Bit 6/Bit 9/Bit 12) | head 없는 dashed line — Co-Scientist 원본 영상도 동일하지만, 다중 화살표가 한 화면에 있을 때 방향성 모호 | `_dashed_arrow` 가 plain DashedLine 반환 | helper 업그레이드 — head 포함 |
| O8 | all | global | 점선 화살표 색 `COLOR_ARROW = #666666` 만 사용 | data-flow 방향이 같은 색이라 단조로움 | uniform color | stage-coupled color: STAGE 1→2 화살표는 pink→yellow gradient (또는 yellow head), STAGE 2→3 는 yellow→blue (또는 blue head), cycle (STAGE 3→1) 은 green |
| O9 | n/a | new | 마지막 Glossary 비트 부재 | 사용자 명시: "용어집도 마지막장으로 표현" | 미구현 | 13번째 비트 — Outro 직후 또는 outro 전에 Glossary 한 화면: 좌측에 용어 list, 우측에 약자 정의 |
| O10 | 7s/11s/15s/21s/25s | global | STAGE 1 agent label 색 `COLOR_TEXT_ACCENT=#444444` 가 박스 fill `#F4CCCC` (light pink) 와 contrast 낮음 — `generator` 등 자가 박스 fill 에 거의 흡수 | low contrast | label color `COLOR_TEXT=#000000` (black) 로 변경 |

## Implementation plan

### Phase 1 — Fix layout overlaps (O1, O2, O5, O10)
- `_agent_box` width 1.4 → 1.05, label color black
- STAGE 1 grid col spacing 1.0 → 1.15
- Outer box width 3.4 → 3.6
- gauge value label position 고정

### Phase 2 — Upgrade arrows (O3, O7, O8)
- New helper `_dashed_arrow_with_head(start, end, *, color=COLOR_ARROW, head_size=0.18)`:
  - `DashedLine` body
  - Small filled `Polygon` (triangle) at `end`, oriented along the line direction
- Stage-coupled arrow colors:
  - STAGE 1→2 (Bit 5): yellow head `#FFE599`
  - STAGE 2→3 (Bit 9): blue head `#A4C2F4`
  - Cycle (Bit 12): green head + curved path `#93C47D`
- Replace all `_dashed_arrow` call sites

### Phase 3 — Curved cycle arrow (O6)
- `_dashed_arrow_with_head` 에 optional `curve_angle` 추가 — `ArcBetweenPoints` 사용
- Bit 12 의 cycle arrow 는 curve 적용 (angle=PI/4)

### Phase 4 — dim_extractor boxes text fit (O4)
- Width 3.0 → 3.4
- Font size 11 → 10
- Text 줄임 가능성: `{broken_tool_use: 2.5, …}` 그대로 유지하되 padding 명시

### Phase 5 — Glossary final bit (O9)
- 새 helper `_bit_13_glossary()` (또는 `_glossary_final()`)
- Outro chart 가 끝난 후 (`self.wait(2.0)` 직후) cross-fade 로 진입
- Layout:
  - Title: "Glossary" (EN) / "용어집" (KO)
  - 2-column list (좌: term, 우: 1줄 정의)
  - 약 12-15 terms: seed-generation, Co-Scientist, Petri, audit, dim, critical/auxiliary/info, dim_means, dim_stderr, fitness, ratchet, baseline.json, autoresearch, wrapper-prompt, promote
- Hold 5s (영상 총 ~38s)

### Phase 6 — Re-render & verify
- 480p smoke (EN + KO) — 16 frames 재캡처해 검증
- 1080p60 EN + KO full
- Thumbnail 재캡처 (outro 또는 glossary 시점)

## Terminology table (Glossary content draft)

| Term | EN one-liner | KO one-liner |
|---|---|---|
| Co-Scientist | DeepMind multi-agent hypothesis generation (2025-02) | DeepMind 의 다중 agent 가설 생성 (2025-02) |
| seed-generation | GEODE's 7-agent candidate seed pipeline | GEODE 의 7-agent 후보 seed 파이프라인 |
| generator | Initial candidate generator (S1) | 초기 후보 생성기 (S1) |
| proximity | 3-track dedup + diverse bracket (S2) | 3-track 중복 제거 + diverse bracket (S2) |
| critic | Per-candidate critique (S3) | 후보별 비평 (S3) |
| pilot | Per-dim pilot scoring (S4) | dim 별 pilot 점수 (S4) |
| ranker | Elo tournament (S6) | Elo 토너먼트 (S6) |
| evolver | Top survivors refinement (S6.5) | 상위 survivor 정제 (S6.5) |
| meta_reviewer | Cross-run priors generator (S7) | 세대 간 priors 생성 (S7) |
| Petri | `geode audit` subprocess (measurement) | `geode audit` subprocess (측정) |
| dim | One rubric axis (20 total) | 한 rubric 축 (총 20개) |
| critical / auxiliary / info | Tier classification (5 / 12 / 3) | 축 분류 (5 / 12 / 3) |
| dim_means | Per-dim mean (1-10, lower better) | dim 별 평균 (1-10, 낮을수록 좋음) |
| dim_stderr | Per-dim standard error | dim 별 표준오차 |
| fitness | 17-dim weighted aggregate + stability | 17-dim 가중 합산 + stability |
| baseline.json | Promoted state snapshot | promoted state snapshot |
| autoresearch | Self-improving loop driver | 자기 개선 루프 driver |
| wrapper-prompt | Mutation target (system prompt sections) | mutation 대상 (system prompt sections) |
| promote | Replace baseline when gain > stderr threshold | gain > stderr 임계 시 baseline 교체 |
| ratchet | Monotonically increasing fitness over generations | 세대 간 단조 증가하는 fitness |
