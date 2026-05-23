# GEODE Outer Self-Improving Loop — Hero Visualization Storyboard

> Reference: Google AI Co-Scientist hero video (830×470, 13.7s).
> GEODE adapts the Co-Scientist agent grid + adds two downstream
> stages — **Petri (measurement)** and **autoresearch (selection)** —
> so the visualization covers the full Co-Scientist → Petri →
> autoresearch self-improving cycle.
>
> Source: Manim scene at `scripts/visualizations/geode_hero.py`.
> Renders to two outputs — `geode-hero-en.mp4` and
> `geode-hero-ko.mp4` — via a `lang` parameter.

## Spec

| Property | Value |
|---|---|
| Canvas | 1920×1080 (1080p60), 30 seconds + 5s outro |
| Frame rate | 60 fps |
| Background | `#FFFFFF` (Google Material clean white) |
| Output | `media/videos/geode_hero/1080p60/GeodeSelfImprovingHero.mp4` × 2 (en/ko) |

## Color palette (matches Co-Scientist aesthetic)

| Use | Hex |
|---|---|
| Agent box (default) | `#F4CCCC` (light pink) |
| Tournament winner / promoted | `#A4C2F4` (light blue) |
| Unfilled slot / Supervisor | `#D9D9D9` (light grey) |
| Critical-axis floor (regression) | `#E06666` (red) |
| Auto-promote pass | `#93C47D` (green) |
| Dashed arrows / lines | `#666666` (medium grey) |
| Text default | `#000000` |
| Text accent (formula / dim names) | `#444444` |

## 12-bit sequence + outro

Each bit lists EN / KO text + visual change + animation primitives.

### Stage 1 — Co-Scientist pattern (GEODE seed-generation)

#### Bit 1 — Engineer specifies goal (0–1.5s)

- **EN**: "Engineer specifies a research goal"
- **KO**: "엔지니어가 연구 목표를 명세"
- **Visual**: Engineer person icon (top center) + speech bubble pointing down. Below: faint outline of GEODE agent grid (no fill yet).
- **Animation**: `FadeIn(engineer)` → `Write(speech_bubble_text)`.

#### Bit 2 — Seven specialist agents revealed (1.5–4s)

- **EN**: "GEODE seed-generation: 7 specialist agents"
- **KO**: "GEODE seed-generation — 7 전문 agent"
- **Visual**: Large rounded rectangle (centered, ~600×360 px). Top label "GEODE seed-generation". 7 pink agent boxes inside, arranged 3×3 minus one corner:
  - Row 1: `generator` `proximity` `critic`
  - Row 2: `pilot`     `ranker`    `evolver`
  - Row 3:             `meta_reviewer` (center)
- **Animation**: `Create(outer_box)` then `LaggedStart(*[FadeIn(b) for b in 7_agents], lag_ratio=0.1)`.

#### Bit 3 — Generate → Critique → Evolve chain (4–6s)

- **EN**: "Generate → Critique → Evolve"
- **KO**: "생성 → 비평 → 진화"
- **Visual**: 3 agents (generator → critic → evolver) sequentially brightened (saturation up). Dashed arrows between them.
- **Animation**: `Indicate(generator)` → `Indicate(critic)` → `Indicate(evolver)` chain with 0.4s delay each. Arrows drawn with `GrowArrow`.

#### Bit 4 — Tournament: top survivors emerge (6–8s)

- **EN**: "Tournament — top survivors emerge"
- **KO**: "토너먼트 — 최강 후보 도출"
- **Visual**: Right side: leaderboard panel (5 slots, all grey). Dashed arrow from agent box → leaderboard. Slots fill blue one by one (top to bottom, top 3 fill).
- **Animation**: `Create(leaderboard)` → `Transform(slot_i_grey → slot_i_blue)` × 3, then keep 2 slots grey (eliminated).

### Stage 2 — Petri audit (measurement)

#### Bit 5 — Survivors → Petri audit subprocess (8–10s)

- **EN**: "Survivors → Petri audit subprocess"
- **KO**: "Survivors → Petri audit subprocess"
- **Visual**: Leaderboard shrinks slightly. Dashed arrow extending right to a new box "Petri (geode audit)". The new box is darker (different from pink) — `#FFE599` (soft yellow, indicating measurement layer).
- **Animation**: `Create(petri_box)` + `GrowArrow(survivors_to_petri)`.

#### Bit 6 — 20-dim rubric (10–12.5s)

- **EN**: "20-dim rubric: 5 critical / 12 auxiliary / 3 info"
- **KO**: "20-dim rubric — critical 5 / aux 12 / info 3"
- **Visual**: Petri box expands to show a 4×5 grid (20 cells). Cells colored by tier:
  - 5 cells `#E06666` light tint = critical
  - 12 cells `#FFE599` = auxiliary
  - 3 cells `#D9D9D9` = info
- **Animation**: `Create(grid)` + `LaggedStart(*[FadeIn(cell) for cell in 20_cells], lag_ratio=0.05)`.

#### Bit 7 — LLM judge scores each transcript (12.5–14.5s)

- **EN**: "LLM judge scores each transcript"
- **KO**: "judge LLM 이 transcript 별 점수 부여"
- **Visual**: Each cell flashes a number (0-10). Critical cells average 2-4 (lower better — score is concerning-behavior on 1-10 scale, lower is better). Aux 3-6.
- **Animation**: `LaggedStart(*[Write(number_i) for i in 20], lag_ratio=0.03)` over 1.5s.

#### Bit 8 — dim_extractor: raw mean + stderr (14.5–16.5s)

- **EN**: "dim_extractor → dim_means + dim_stderr"
- **KO**: "dim_extractor → dim_means + dim_stderr"
- **Visual**: Grid collapses → 2 dict-shaped boxes appear to the right: `{dim_means: {broken_tool_use: 3.4, ...}}` and `{dim_stderr: {broken_tool_use: 0.4, ...}}`.
- **Animation**: `Transform(grid → two_dict_boxes)`.

### Stage 3 — autoresearch (selection + promote)

#### Bit 9 — compute_fitness: 17-dim weighted aggregate (16.5–19s)

- **EN**: "compute_fitness: 17-dim weighted aggregate + stability"
- **KO**: "compute_fitness — 17 dim 가중 합산 + stability"
- **Visual**: Dict boxes → equation formula displayed center-right:
  ```
  fitness = Σ (w_i × (10 - dim_means_i)) / 10
          + STABILITY_WEIGHT × (1 - mean(dim_stderr))
  ```
  Below: a single scalar bar (gauge) showing fitness ≈ 0.54.
- **Animation**: `Write(formula)` + `Create(gauge)` + `gauge.value: 0 → 0.54` over 1s.

#### Bit 10 — Critical-axis floor (19–22s)

- **EN**: "Critical-axis floor: regression → fitness = 0.0"
- **KO**: "Critical-axis floor: regression 시 fitness = 0.0"
- **Visual**: 5 critical dims drawn separately as 5 thin red horizontal bars (each candidate's regression vs baseline). A red dashed line at `baseline + stderr + margin`. If any bar crosses → gauge slams to 0.0.
- **Animation**: `Create(5_bars)` → `Create(red_dashed_floor)` → demonstration: bar 3 crosses the floor → `gauge.value: 0.54 → 0.0` with `Flash(gauge, color=RED)`.
- Then reset: `gauge.value: 0.0 → 0.54` (bar 3 below floor) — shows the gate doing its job.

#### Bit 11 — Auto-promote rule (22–25s)

- **EN**: "Auto-promote: raw gain > max(stderr, 0.05)"
- **KO**: "Auto-promote: raw gain > max(stderr, 0.05)"
- **Visual**: gauge value: prior_fitness 0.54 → new_fitness 0.57. Delta arrow `+0.03`. Comparison line at `max(stderr, 0.05) = 0.05`. 0.03 < 0.05 → DISCARD. Then a second example: 0.54 → 0.62 (Δ +0.08 > 0.05) → PROMOTE (gauge turns green, `baseline.json` box updates).
- **Animation**: 2-cycle demonstration. Final state: baseline.json box highlighted green.

#### Bit 12 — Next generation: wrapper-prompt mutation (25–28s)

- **EN**: "Next generation: wrapper-prompt mutation"
- **KO**: "다음 세대: wrapper-prompt mutation"
- **Visual**: baseline.json → arrow → "wrapper-prompt sections" box (5 sections, one section highlighted = mutation target) → arrow back to the GEODE seed-generation box (full loop closure). Generation counter "gen N → gen N+1".
- **Animation**: `GrowArrow` × 3 forming the cycle. `Transform(gen_label: "gen N" → "gen N+1")`.

### Outro — Self-improving over generations (28–35s)

- **EN**: "Self-improving over generations"
- **KO**: "세대를 거듭한 자기 개선"
- **Visual**: All previous elements fade. Center stage: large fitness ratchet chart (x-axis = generation count 1..10, y-axis = fitness). Dotted line of points (each gen's promoted fitness) climbing monotonically. Beside it: vertical git-commit chain (10 colored dots representing promoted commits).
- **Animation**: `Create(chart_axes)` → `LaggedStart(*[Create(dot_i) + Create(commit_i) for i in 10], lag_ratio=0.15)`. End on the full chart held 2s.

## EN / KO text lookup table

| key | EN | KO |
|---|---|---|
| `bit_1` | Engineer specifies a research goal | 엔지니어가 연구 목표를 명세 |
| `bit_2` | GEODE seed-generation: 7 specialist agents | GEODE seed-generation — 7 전문 agent |
| `bit_3` | Generate → Critique → Evolve | 생성 → 비평 → 진화 |
| `bit_4` | Tournament — top survivors emerge | 토너먼트 — 최강 후보 도출 |
| `bit_5` | Survivors → Petri audit subprocess | Survivors → Petri audit subprocess |
| `bit_6` | 20-dim rubric: 5 critical / 12 auxiliary / 3 info | 20-dim rubric — critical 5 / aux 12 / info 3 |
| `bit_7` | LLM judge scores each transcript | judge LLM 이 transcript 별 점수 부여 |
| `bit_8` | dim_extractor → dim_means + dim_stderr | dim_extractor → dim_means + dim_stderr |
| `bit_9` | compute_fitness: 17-dim weighted aggregate + stability | compute_fitness — 17 dim 가중 합산 + stability |
| `bit_10` | Critical-axis floor: regression → fitness = 0.0 | Critical-axis floor: regression 시 fitness = 0.0 |
| `bit_11` | Auto-promote: raw gain > max(stderr, 0.05) | Auto-promote: raw gain > max(stderr, 0.05) |
| `bit_12` | Next generation: wrapper-prompt mutation | 다음 세대: wrapper-prompt mutation |
| `outro` | Self-improving over generations | 세대를 거듭한 자기 개선 |
| `agent_generator` | generator | generator |
| `agent_proximity` | proximity | proximity |
| `agent_critic` | critic | critic |
| `agent_pilot` | pilot | pilot |
| `agent_ranker` | ranker | ranker |
| `agent_evolver` | evolver | evolver |
| `agent_meta_reviewer` | meta_reviewer | meta_reviewer |
| `petri_box` | Petri (geode audit) | Petri (geode audit) |
| `baseline_json` | baseline.json | baseline.json |
| `gen_n` | gen N | 세대 N |
| `gen_n_plus_1` | gen N+1 | 세대 N+1 |

## Co-Scientist ↔ GEODE mapping (visual reminder)

| Co-Scientist (reference) | GEODE (this video) | Stage |
|---|---|---|
| Scientist icon | Engineer icon | Bit 1 |
| Supervisor agent | autoresearch driver (implicit — outer cycle controller) | Bit 12 |
| Generation agent | `generator` | Bit 2-3 |
| Review agent | `critic` + `meta_reviewer` | Bit 2-3 |
| Ranking agent | `pilot` + `ranker` (Elo tournament) | Bit 2-4 |
| Evolution agent | `evolver` | Bit 2-3 |
| Proximity agent | `proximity` (Π1/Π2/Π3 graph + partial-survive + goal-condition) | Bit 2 |
| Meta-Review agent | `meta_reviewer` | Bit 2 |
| Test-time compute × novelty chart | Fitness × generation chart (autoresearch ratchet) | Bit 11-12 + Outro |
| Research ideas tournament | Survivors leaderboard | Bit 4 |
| Final research plan | Promoted wrapper-prompt + baseline.json + commit chain | Outro |

## Build commands

```bash
# Install (one-time)
uv add --dev manim

# Render EN (default lang)
uv run manim -pqh scripts/visualizations/geode_hero.py GeodeSelfImprovingHero

# Render KO (override lang via env)
GEODE_HERO_LANG=ko uv run manim -pqh scripts/visualizations/geode_hero.py GeodeSelfImprovingHero
```

Output paths:
- `media/videos/geode_hero/1080p60/GeodeSelfImprovingHero.mp4`
- Rename to `geode-hero-en.mp4` / `geode-hero-ko.mp4` for distribution.

## Future iterations (post-MVP, separate PRs)

1. **TTS narration** — generate voice-over for EN/KO via TTS API; mux with `ffmpeg -i video.mp4 -i narration.mp3 -c:v copy ...`.
2. **Per-dim drill-down** — replace the abstract 20-cell grid with actual dim names + sample-level evidence.
3. **Real run data** — feed an actual `~/.geode/self-improving-loop/sessions.jsonl` history into the ratchet chart instead of synthetic points.
4. **Interactive web version** — port the same scene to Motion Canvas + GitHub Pages for browser-native playback.
