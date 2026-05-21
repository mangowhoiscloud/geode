---
name: viz-frame-audit
description: 영상 (Manim mp4 / 1080p60) 의 노이즈·slop 검수 워크플로우. ffmpeg 으로 비트별 프레임 추출 → Read 로 시각 확인 → 4 카테고리 결함 식별 (naive 화살표 / 패딩 침범 / 글자 깨짐 / 프레임 순서 오류) → fix → 재렌더 → 동일 timestamp 재검수. 12+ 사례 카탈로그 포함. Triggered by "노이즈", "slop", "프레임 검수", "영상 audit", "글자 깨짐", "패딩 침범", "frame extract", "naive arrow".
user-invocable: false
---

# Viz Frame Audit

영상은 한 번 렌더한 뒤 *프레임 단위로 시각 검수* 하지 않으면 결함이 잘 보이지 않는다.
이 skill 은 4 카테고리 결함 (사용자가 명시한 기준) 을 따라 ffmpeg + Read tool 로
체계적으로 audit 하는 워크플로우 + 검증된 결함 카탈로그를 제공한다.

Scene 작성 자체는 동반 skill [[manim-scene-craft]] 참고.

## 0. 4 카테고리 — 검수 축

| # | 카테고리 | 정의 | 검출 단서 |
|---|---|---|---|
| 1 | **Naive 화살표** | head 크기 부족, 색 불일치, 점선 vs head 색 분리, 라벨이 점선 위에 침범 | head_size ≤ 0.24, head_color ≠ body color, vertical 화살표 + `UP * 0.25` label |
| 2 | **패딩 침범** | 텍스트 / 박스가 다른 박스 경계와 0.1 단위 이내, 캔버스 가장자리 cropping | box height < content height, 행 라벨 `LEFT * 6.0` 이상, outline lines 7개+ 작은 박스 |
| 3 | **글자 깨짐 / 자간 drift** | Helvetica Neue + Pango 의 특정 글리프 페어 오측정 ("GE ODE", "g eneration", "fit ness", "cr itic") | 한 단어 안에 비정상 space, 작은 font_size 에서 더 심함 |
| 4 | **프레임 순서 오류** | transition 중 빈 frame, 컨텐츠 누적 안 됨, line endpoint 가 dots 도달 못함, fade-out 후 새 컨텐츠 늦게 등장 | `_clear_section` 과 `_set_section_title` 분리 호출, LaggedStart 후 별도 `Create(connectors)` |

## 1. 워크플로우 — 검수 절차

```bash
# 1) timestamp 분포 결정 — 영상 길이의 핵심 비트 7~10 timestamp
# 51.75s 영상이면 약 5초 간격, 32s 영상이면 2-3초 간격
mkdir -p /tmp/<name>_audit && rm -f /tmp/<name>_audit/*.png

# 2) 프레임 추출 — ffmpeg -ss <t> + -update 1 -frames:v 1
for t in 2.5 6.5 10.5 14.5 18.5 24.0 28.0; do
    ffmpeg -hide_banner -loglevel error -ss $t \
        -i media/videos/<scene>/1080p60/<Name>-EN.mp4 \
        -frames:v 1 -update 1 -q:v 2 /tmp/<name>_audit/EN_${t}s.png -y
done
```

3) **Read tool 로 각 프레임 확인** — 시각 정보가 들어오므로 LLM 이 직접 결함 식별 가능. `Bash` 의 `tail` / `cat` 으로는 보이지 않음.

4) 결함 정리 → fix 적용 → 재렌더 → 동일 timestamp 재추출 → 동일 Read 비교.

## 2. 결함 카탈로그 (실제 사례)

### 2-1. Naive 화살표

| 사례 | 발견 위치 | 증상 | Fix |
|---|---|---|---|
| Geode hero 결함 #4 | `_dashed_arrow_with_head` default head_size=0.24 | 1080p 에서 화살표 head 가 너무 작아 점선 끝 점으로만 보임 | `head_size: float = 0.32` default 상향 |
| Geode hero 결함 #2 | s2→s3 arrow + arrow_label_s2_to_s3 | slope≈2 의 vertical 화살표 + `UP * 0.25` label → 점선이 `auto-i[mprove]` 글자 중간을 가로지름 | label 을 화살표 perpendicular 방향으로 `LEFT * 0.72 + UP * 0.05` |
| Geode hero 결함 #3 | s1→s2 arrow + arrow_label_s1_to_s2 | `UP * 0.25` 라벨이 evolver 박스 우측 경계와 거의 닿음 | label 을 Petri 쪽으로 bias — `RIGHT * 0.55 + UP * 0.22` |

### 2-2. 패딩 침범

| 사례 | 위치 | 증상 | Fix |
|---|---|---|---|
| Filewalk 결함 #1 | Bit 1 `_file_card` 박스 (height=2.0) + outline 7 items | 헤더 (filename + LoC pill) 가 outline 첫 줄과 수직 충돌 — 글자 겹쳐 인식 불가 | 박스 2.5 + `VGroup(header_block, lines).arrange(DOWN, buff=0.18).next_to(body.get_top(), DOWN, buff=0.16)` 단일 arrange |
| Filewalk 결함 #2 | Bit 1 행 라벨 `LEFT * 6.0` + font 15 | 라벨 width ~3.0 → left edge x=-7.5, 캔버스 left limit -7.11 침범 | `LEFT * 5.6` + `font_size=13` |
| Filewalk 결함 #4 | Bit 5 LoC chart legend (y=1.6) + "1308" label (y top 1.56) | legend bottom 과 label top 0.06 단위로 겹침 | legend y 2.05 로 상향 + chart_h 3.0 → 2.9 |
| Filewalk 결함 #5 | Bit 6 heatmap row label x=-2.2 (right edge -1.6) + col 1 cell left=-1.67 | 행 라벨 → 셀 gap 0.07 — 시각적으로 닿음 | label right edge − 0.35 으로 추가 보정 |
| Hero 결함 #7 | Rubric Detail tier card dim font 9 | "cooperation_with_harmful_sysprompt" 같은 긴 dim 이름이 박스 가장자리에 닿음 + 가독성 매우 낮음 | font 9 → 11, header 14 → 16, chunk step `len(dims) // 3` → `// 4` |

### 2-3. 글자 깨짐 / 자간 drift

| 사례 | 단어 | 증상 | Fix |
|---|---|---|---|
| Hero 결함 #1 | `"GEODE " + _t("stage_1")` outer_label | Helvetica Neue + Pango 가 GE 와 ODE 사이 spurious 0.06 단위 space 삽입 | prefix 제거 — `_t("stage_1")` 단독. 다른 곳의 GEODE 워드마크 (title, footer) 는 폰트 크기 ≥ 18 이라 영향 작음 |
| Hero 결함 #6 | x-axis `_t("generations_label")` = "generation", font 16 | "g eneration" → "g eneratio ns" 자간 drift | "generations" 로 변경 + font 16 → 20. 큰 font 에서는 per-pair kerning 결함 미시감 |
| 검증된 회귀 단어 목록 (Inter 폰트 사용 시 발생, Helvetica Neue 로 mitigate) | "GEODE" / "critic" / "Petri audit" / "generation" / "fitness" | 컨소넌트 페어 사이 spurious space | Inter 사용 금지 — `EN_FONT = "Helvetica Neue"` 고정. font_size ≥ 16 권장 |

### 2-4. 프레임 순서 오류

| 사례 | 위치 | 증상 | Fix |
|---|---|---|---|
| Filewalk 결함 #6 | `_clear_section()` + `_set_section_title()` 분리 호출 | Bit 5→6 transition 동안 ~0.8s 빈 / 반투명 frame | `_set_section_title` 안에서 `(fade-out 이전 title + fade-out 이전 content + fade-in 새 title)` 한 play call 로 묶기 |
| Hero 결함 #5 | outro ratchet — `LaggedStart(*dots, 2.5s)` 후 `Create(connectors, 0.6s)` 분리 | 모든 dots 가 먼저 등장 → connector line 이 늦게 그려짐 → 마지막 dot 이 line 에서 떠 있는 frame 발생 | `AnimationGroup(FadeIn(dot), FadeIn(commit), Create(connectors[i-1]))` 을 LaggedStart 안에서 interleave |

## 3. timestamp 선정 — bit 별 안전 마진

bit 의 transition 직전 + 직후 timestamp 는 *반드시* 피한다 (transition 중인 frame 은
빈 / 반투명 화면이라 결함 식별에 부적합). 각 bit 의 wait phase 한가운데를 노린다:

```
bit_N: _set_section_title (0.4s) → _file_detail (0.6s play + 2.4s wait) ≈ 3.4s
```

→ bit 시작 후 1.0~3.0s 안의 frame 이 가장 검수 가능 (wait phase 중간).

## 4. Fix → 재렌더 → 비교

```bash
# fix 적용 후 EN 만 먼저 재렌더 (KO 는 동일 fix 라 EN 검수 후 진행)
rm -rf media/videos/<scene>
uv run manim -qh -o <Name>-EN scripts/visualizations/<file>.py <SceneClass>

# 동일 timestamp 추출 — 직전 audit 의 EN_*.png 와 1:1 비교
for t in 2.5 6.5 10.5 14.5 18.5 24.0 28.0; do
    ffmpeg -hide_banner -loglevel error -ss $t \
        -i media/videos/<scene>/1080p60/<Name>-EN.mp4 \
        -frames:v 1 -update 1 -q:v 2 /tmp/<name>_audit/EN2_${t}s.png -y
done
```

Read EN2_${t}s.png 으로 직전 결함 사라졌는지 확인. **새 결함이 생기지 않았는지도 동시에 검사** —
fix 가 인접 영역에 collateral 회귀를 만든 경우 (예: 박스 height 늘려서 다음 bit 영역 침범).

KO 도 동일 timestamp 로 추출 — 한국어 텍스트가 영문보다 width 다를 수 있어
패딩 / 줄바꿈이 EN 과 다르게 깨질 수 있다. KO 별도 검수 필수.

## 5. CI 가드 — 매 PR 마다 자동 회귀 방지

`scripts/visualizations/verify_hero_layout.py` 가 `SITES` 튜플의 모든 (lang × site)
페어에 대해 텍스트 measure → 박스 width/height ratio 가 baseline + 0.03 (tolerance) 를
넘으면 fail.

새 박스 / 새 텍스트 추가 시 `SITES` 에 한 줄 append + 로컬 `--update-baseline` →
`layout_baseline.json` commit. CI step 은 `--static-check` 만 실행 (Manim import 없이
JSON 검사) 으로 ~1s 안에 완료.

## 6. 사용자 보고 — 결함 정리 표 양식

audit 결과를 사용자에게 보고할 때는 항상 4-카테고리 분류 + 위치 명시 표로:

```markdown
**Bit X (영역명, ~tt s)**
- 카테고리 N: 증상 한 줄
- 카테고리 M: 증상 한 줄

→ 수정 진행 여부 묻기. 자동으로 fix 하지 않음 (사용자가 의도된 디자인인지 판단해야 함).
```

fix 적용 후엔 동일 양식의 *Before/After 표* 로 검증 결과 보고:

```markdown
| # | 결함 | 수정 | 검증 timestamp |
|---|---|---|---|
| 1 | "GE ODE" 자간 깨짐 | prefix 제거 | EN_9s OK |
| 2 | "→ auto-improve" 점선에 잘림 | 라벨 LEFT*0.72 | EN_25s OK |
| ... |
```

## 7. 사용자가 선호하는 표현 — 회피해야 할 말투

- "완벽" / "Perfect" 같은 자평 단어 금지 — 사용자가 "naive" 한 자평으로 인식.
- "수정했습니다" 가 아니라 "수정 적용. 검증 timestamp X OK." 형식.
- 4 카테고리 명시 — 사용자가 본 skill 의 결함 분류 축을 명시적으로 요구했음 (2026-05-21 GeodeHero audit 세션).
