---
name: manim-scene-craft
description: Manim Community Scene 작성 표준 — EN/KO 다국어 lang (GEODE_HERO_LANG env), Helvetica Neue + Pretendard 폰트 페어링, Anthropic-style 팔레트, layout ratchet (verify_hero_layout.py) + CI 가드. Hero / filewalk / compare / critical_floor scene 4종이 같은 패턴 공유. Triggered by "manim", "scene", "영상", "비디오", "1080p60", "EN/KO 렌더", "GEODE_HERO_LANG".
user-invocable: false
---

# Manim Scene Craft

영상 1편을 처음부터 만들 때, 이미 검증된 4 scene (`geode_hero.py`, `autoresearch_filewalk.py`,
`autoresearch_compare.py`, `critical_floor.py`) 가 공유하는 패턴을 그대로 따라가면
폰트 깨짐 / 패딩 침범 / 다국어 회귀 같은 흔한 결함이 사전에 차단된다. 이 문서는
그 공통 패턴을 명시한다. 영상 결함을 *검수* 하는 워크플로우는 동반 skill
[[viz-frame-audit]] 을 참고.

## 0. 의존성 + 폰트 사전 확인

| 항목 | 명령 / 위치 | 비고 |
|------|-------------|------|
| Manim Community | `uv add manim --dev` 후 `uv sync` | macOS 는 `brew install pkg-config cmake` 선행 (pycairo 빌드) |
| EN 폰트 | `HelveticaNeue.ttc` (macOS 기본) — Pango 가 픽업 | Inter 는 Pango ligature 결함 — "GE ODE" / "cr itic" / "Petr i aud it" 자간 깨짐 (검증된 회귀) |
| KO 폰트 | Pretendard (OFL) — `brew install --cask font-pretendard` | Apple SD Gothic Neo 는 초반 멈춤 글리프 artifact 있음 |
| 폰트 존재 가드 | `scripts/visualizations/verify_hero_layout.py` 의 `_ensure_fonts_installed` | `fc-list` 으로 EN/KO 모두 있는지 확인 후 abort |

## 1. Scene 골격

모든 scene 은 다음 구조를 공유한다:

```python
"""Scene 설명 (제목 / Bit 구성 / 데이터 출처).

Render
======
::

    uv run manim -qh -o <Name>-EN scripts/visualizations/<file>.py <SceneClass>
    GEODE_HERO_LANG=ko uv run manim -qh -o <Name>-KO scripts/visualizations/<file>.py <SceneClass>
"""

from __future__ import annotations
import os
from manim import (..., NORMAL, Scene, Text, VGroup, config)

config.background_color = "#FFFFFF"
config.frame_rate = 60

LANG = os.environ.get("GEODE_HERO_LANG", "en").lower()

# Anthropic-style palette (모든 scene 공유)
COLOR_BORROW = "#A4C2F4"      # blue — verbatim / Co-Scientist seed
COLOR_SWAP = "#FFE599"        # yellow — Petri / 도메인 스왑
COLOR_ADD = "#93C47D"         # green — autoresearch / GEODE-only addition
COLOR_REMOVE = "#E06666"      # red — critical regression
COLOR_KARPATHY = "#F4CCCC"    # light pink — Karpathy panel fill
COLOR_GEODE = "#D5E8D4"       # very light green — GEODE panel fill
COLOR_ARROW = "#666666"
COLOR_TEXT = "#000000"
COLOR_TEXT_ACCENT = "#444444"

EN_FONT = "Helvetica Neue"
KOR_FONT = "Pretendard"

T = {
    "en": {"key": "English string", ...},
    "ko": {"key": "한국어 문자열", ...},
}

def _t(key: str) -> str:
    return T.get(LANG, T["en"]).get(key, T["en"].get(key, key))

def _make_text(text: str, **kw) -> Text:
    """Pango 의 weight metric drift 를 막기 위해 매번 NORMAL weight 명시."""
    font = kw.pop("font", None)
    if font is None:
        font = KOR_FONT if LANG == "ko" else EN_FONT
    kw.setdefault("color", COLOR_TEXT)
    kw.setdefault("weight", NORMAL)
    return Text(text, font=font, **kw)
```

`_t` 와 `_make_text` 두 헬퍼는 **scene 내 모든 텍스트 생성 진입점**. 직접 `Text(...)` 호출 금지 —
폰트 + weight 잠금이 빠지면 자간 drift 회귀가 다시 발생한다.

## 2. Bit / Section 구조

```python
TITLE_Y = 3.45
SECTION_TITLE_Y = 2.85          # 비트 부제목 라인
CONTENT_TOP = 2.5
CONTENT_BOTTOM = -2.0
FOOTER_Y = -3.3

class MyScene(Scene):
    def construct(self) -> None:
        self._section_title = None
        self._section_content = VGroup()
        self._show_title()
        self._bit_1_xxx()
        # ...

    def _set_section_title(self, key: str) -> None:
        """Swap title in ONE play call (FadeOut prior title + content + FadeIn new title).

        분리해서 호출하면 transition 사이에 0.5~0.8s 짜리 빈 frame 이 생긴다.
        한 번에 묶어서 처리 — viz-frame-audit 의 결함 #7 (frame order / empty transition).
        """
        new_title = _make_text(_t(key), font_size=18, color=COLOR_TEXT_ACCENT).move_to(
            UP * SECTION_TITLE_Y
        )
        fade_outs = []
        if self._section_title is not None:
            fade_outs.append(FadeOut(self._section_title))
        if len(self._section_content) > 0:
            fade_outs.append(FadeOut(self._section_content))
        if fade_outs:
            self.play(*fade_outs, FadeIn(new_title), run_time=0.4)
        else:
            self.play(FadeIn(new_title), run_time=0.3)
        self._section_title = new_title
        self._section_content = VGroup()
```

각 bit 마지막에서 `self._section_content = VGroup(...)` 으로 새 콘텐츠 등록 →
다음 bit 의 `_set_section_title` 이 자동으로 fadeout.

## 3. 패딩 / 박스 / 텍스트 안전구역

| 컴포넌트 | 안전 규칙 | 위반 시 회귀 |
|---|---|---|
| 박스 + 헤더 + outline lines | `VGroup(header_block, lines).arrange(DOWN, buff=0.18).next_to(body.get_top(), DOWN, buff=0.16)` — 단일 VGroup arrange | 분리 배치하면 헤더와 첫 outline 줄이 수직 충돌 ([[viz-frame-audit]] 의 filewalk 결함 #1) |
| 박스 height | outline lines 개수 × line height + buff 합 + header block (~0.4) + padding (0.3) | 박스 height 부족하면 lines 가 box bottom 침범 |
| 행 라벨 (`Karpathy autoresearch` 등) | `font_size=13`, `LEFT * 5.6` 이상 안쪽 | font 15 + `LEFT * 6.0` 은 캔버스 left edge (-7.11) 침범 위험 |
| 화살표 라벨 | 화살표 center 에서 *perpendicular* 방향으로 ≥ 0.5 단위 offset | `UP * 0.25` 만으로는 vertical 화살표의 dashed line 이 글자를 가로지름 (geode_hero 결함 #2) |
| 캔버스 right limit | x ≤ 7.0 (full canvas 는 7.11 이지만 stroke 두께 고려) | fitness formula 우측 정렬 시 `(lower = better)` cropping |

## 4. 화살표 — `_dashed_arrow_with_head`

```python
def _dashed_arrow_with_head(
    start, end, *,
    color: str = COLOR_ARROW,
    head_color: str | None = None,
    head_size: float = 0.32,   # 0.24 는 1080p 에서 head 가 작아 noise (geode_hero 결함 #4)
    curve_angle: float = 0.0,
    stroke_width: float = 2.5,
    dash_length: float = 0.14,
) -> VGroup:
    """Dashed body + filled triangle head — direction unmistakable.

    stage-coupled tinting: Co-Scientist→Petri 는 head_color=COLOR_SWAP (yellow),
    Petri→autoresearch 는 head_color=COLOR_BORROW (blue), cycle 은 COLOR_ADD (green).
    """
```

## 5. EN/KO 다국어 렌더

```bash
# EN
uv run manim -qh -o <Name>-EN scripts/visualizations/<file>.py <SceneClass>

# KO
GEODE_HERO_LANG=ko uv run manim -qh -o <Name>-KO scripts/visualizations/<file>.py <SceneClass>

# 1080p60 — high quality. -ql 은 480p15 (드래프트), -qm 은 720p30, -qk 는 4K.
# 출력: media/videos/<file>/1080p60/<Name>-{EN,KO}.mp4
```

검수 후 `~/Downloads/` 로 복사 (사용자 쉽게 열기 위함):

```bash
cp media/videos/<file>/1080p60/<Name>-{EN,KO}.mp4 ~/Downloads/
```

## 6. Layout ratchet — `verify_hero_layout.py`

CI 가 `--static-check` 으로 매 PR 마다 baseline JSON 의 OVERFLOW 검사.
로컬에선 `--update-baseline` 으로 새 사이트 추가 후 baseline 갱신.

```bash
# CI 형식 — Manim import 없이 JSON 검사만
uv run python scripts/visualizations/verify_hero_layout.py --static-check

# 로컬 — 측정 + baseline 갱신
uv run python scripts/visualizations/verify_hero_layout.py --update-baseline
```

새 박스 추가 시 — `SITES` 튜플에 `Site(...)` append → 로컬 `--update-baseline` →
`layout_baseline.json` commit. CI 가 향후 PR 에서 동일 텍스트 + 박스가
overflow 임계 1.0 을 넘으면 fail.

CI step (`.github/workflows/ci.yml`):
```yaml
- name: Hero viz layout ratchet
  if: needs.changes.outputs.code == 'true'
  run: uv run python scripts/visualizations/verify_hero_layout.py --static-check
```

## 7. 데이터 SoT — `docs/visualizations/`

영상의 모든 수치 / 비교 / 매핑은 markdown SoT 문서에서 가져온다 (영상은 시각화 한 후
"SoT 와 일치" 만 검증):

| Scene | SoT 문서 |
|---|---|
| `geode_hero.py` | `docs/visualizations/geode-hero-storyboard.md` (12-bit 구성), `text-overflow-map.md` (overflow 사이트 카탈로그) |
| `autoresearch_compare.py` + `autoresearch_filewalk.py` | `docs/visualizations/autoresearch-comparison.md` (3-section: 8 verbatim / 7 swap / 11 add, 6-file LoC) |
| `critical_floor.py` | `autoresearch/train.py` (`compute_fitness` line 692, `_dim_score` line 627) |

수치 변경 시 — markdown 먼저, 그 다음 scene `LOC` / `OUTLINE` / `HEATMAP` 등
모듈 상수 — 한 방향만. CHANGELOG / PR-body parity 가드는
`feedback_changelog_implementation_parity` 메모리 참고.

## 8. 흔한 회귀 — 사전 체크

PR 전에 아래 5 항목 빠르게 grep:

1. `grep -n "Text(" scripts/visualizations/<file>.py` → `_make_text` 가 아닌 raw `Text(` 가 있으면 폰트 잠금 누락
2. 비트 사이 `_clear_section()` 호출 + `_set_section_title()` 두 번 따로 — 한 번에 묶지 않으면 빈 frame 발생
3. 화살표 라벨이 `arrow.get_center() + UP * 0.25` 만으로 위치 — vertical 화살표면 점선이 글자를 가로지름
4. `font_size=15` 이상 + `LEFT * 6.0` 이상 위치 — 캔버스 left edge cropping
5. 작은 박스 (height ≤ 2.0) 안에 outline lines 7개 이상 — height 부족 침범

검수 워크플로우 + 결함 카탈로그는 [[viz-frame-audit]] 참조.
