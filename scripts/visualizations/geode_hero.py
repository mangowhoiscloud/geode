"""GEODE outer self-improving loop — hero visualization.

Reference: Google AI Co-Scientist hero video (830×470, 13.7s).
GEODE extends the agent-grid pattern with two downstream stages —
**Petri (measurement)** and **autoresearch (selection)** — so the
visualization walks the full Co-Scientist → Petri → autoresearch
self-improving cycle.

Layout rule (post-v2 rewrite)
=============================
A single fixed 3-zone layout keeps text and content from ever
overlapping, and stages flow strictly **left → right**:

* TITLE BAR (y ≈ 3.0–3.5) — reserved for bit text. Old title fades
  out before the new one fades in (no Transform — Transform leaves
  both visible mid-tween).
* CONTENT ZONE (y ≈ 2.5 ↓ −2.0) split into three vertical bands:
  - STAGE 1 (LEFT,   x ≈ −4.5) — Co-Scientist pattern (seed-generation)
  - STAGE 2 (CENTER, x ≈   0.0) — Petri audit (measurement)
  - STAGE 3 (RIGHT,  x ≈   4.5) — autoresearch (selection + promote)
* FOOTER (y ≈ −3.3) — three progress dots (active stage = green).

Active-stage elements render at full opacity; the prior stage dims to
30% as the narrative moves right, leaving a "trail" without clutter.
Every data-flow arrow points LEFT→RIGHT.

The cold-open + 4-Act storyboard (each Act: Problem → 대처 → 트레이드오프)
+ outro is defined in ``docs/visualizations/geode-hero-storyboard.md``
(single source of truth).

Render
======
::

    uv run manim -qh -o GeodeHero-EN scripts/visualizations/geode_hero.py GeodeSelfImprovingHero
    GEODE_HERO_LANG=ko uv run manim -qh -o GeodeHero-KO scripts/visualizations/geode_hero.py GeodeSelfImprovingHero

Outputs to ``media/videos/geode_hero/1080p60/GeodeHero-{EN,KO}.mp4``.
"""

from __future__ import annotations

import os

import numpy as np
from manim import (
    DOWN,
    LEFT,
    NORMAL,
    ORIGIN,
    RIGHT,
    UP,
    AnimationGroup,
    ArcBetweenPoints,
    Circle,
    Create,
    DashedLine,
    DashedVMobject,
    FadeIn,
    FadeOut,
    Flash,
    LaggedStart,
    Line,
    NumberLine,
    Polygon,
    Rectangle,
    Scene,
    Square,
    Text,
    VGroup,
    Write,
    config,
)

# ───────────────────────────────────────────────────────────────────────
# Configuration
# ───────────────────────────────────────────────────────────────────────

config.background_color = "#FFFFFF"
config.frame_rate = 60

LANG = os.environ.get("GEODE_HERO_LANG", "en").lower()

# Color palette — Co-Scientist aesthetic + GEODE extensions.
COLOR_AGENT = "#F4CCCC"
COLOR_WINNER = "#A4C2F4"
COLOR_UNFILLED = "#D9D9D9"
COLOR_CRITICAL = "#E06666"
COLOR_PROMOTED = "#93C47D"
COLOR_PETRI = "#FFE599"
COLOR_ARROW = "#666666"
COLOR_TEXT = "#000000"
COLOR_TEXT_ACCENT = "#444444"
COLOR_TRAIL = "#BBBBBB"  # dimmed stage history

# Fonts — Anthropic-style modern geometric sans pair.
#
# EN: ``Helvetica Neue`` (macOS-bundled, 'HelveticaNeue.ttc') — closest
# system match to Anthropic's Styrene/Inter visual identity that
# Manim's Pango backend renders without spacing / kerning artifacts.
# Inter (OFL) was tested but Pango misreads its ligature table on
# macOS, inserting spurious whitespace between consonants
# (e.g. ``GE ODE``, ``cr itic``, ``Petr i aud it``).
#
# KO: ``Pretendard`` (OFL; ``brew install --cask font-pretendard``) —
# modern Korean sans that pairs cleanly with Helvetica Neue, mirroring
# Anthropic's bilingual typographic system. Verified to render without
# the Apple SD Gothic Neo "초반 멈춤" glyph artifact from the v4
# render.
#
# CI ensures both fonts are present before any render runs
# (``verify_hero_layout.py`` aborts early if either is missing).
EN_FONT = "Helvetica Neue"
KOR_FONT = "Pretendard"

# Layout zones (Manim default frame is 14.22 × 8.0 units at 16:9).
TITLE_Y = 3.4
CONTENT_TOP = 2.5
CONTENT_BOTTOM = -2.0
FOOTER_Y = -3.3
STAGE_X = {"s1": -4.5, "s2": 0.0, "s3": 4.5}

# ───────────────────────────────────────────────────────────────────────
# EN / KO text lookup
# ───────────────────────────────────────────────────────────────────────

T: dict[str, dict[str, str]] = {
    "en": {
        # ── Cold-open title card (beat 0) ──
        # "GEODE" + "THE SELF-IMPROVING LOOP" are the brand/title — the same
        # string in both languages (not translated). The meta-loop tagline
        # and the 7 reinforced scaffold kinds (TARGET_KINDS) follow.
        "coldopen_brand": "GEODE",
        "coldopen_subtitle": "THE SELF-IMPROVING LOOP",
        "coldopen_tagline": (
            "An autonomous agent on while(tool_use) —\n"
            "strengthening the scaffold it runs on,\n"
            "generation after generation."
        ),
        "coldopen_reinforce_label": "reinforced each cycle",
        # The 7 verified mutation-surface kinds (core/self_improving/loop/
        # policies.py:207-242 TARGET_KINDS). Rendered as a dense ·-separated
        # monospace row split over two lines — they are code identifiers, so
        # snake_case is kept exactly. NOT box cards.
        "coldopen_kinds_line1": "prompt · tool_policy · decomposition · reflection",
        "coldopen_kinds_line2": "skill_catalog · agent_contract · tool_descriptions",
        "rubric_title": "Evaluation rubric & audit output",
        "rubric_critical_label": "Critical (5) — strict floor",
        "rubric_auxiliary_label": "Auxiliary (10) — squared penalty",
        "rubric_info_label": "Info (3) — reported, not weighted",
        "rubric_scale_label": "Rubric scale",
        "rubric_scale_value": "1–10 (lower = better, concerning-behavior)",
        "rubric_emit_label": "Petri audit emits",
        "rubric_emit_lines": (
            "dim_means / dim_stderr — per-dim mean + standard error",
            "evidence — top-K worst sample rows per dim",
            "audit_seconds / total_seconds — wall-clock breakdown",
            "usd_spent / target_model / judge_model — run metadata",
        ),
        "rubric_aggregate_label": "autoresearch aggregates",
        "rubric_aggregate_lines": (
            "score(m) = max(0, 1 − m / 10)",
            "stability = 1 / (1 + mean(dim_stderr))",
            "fitness = Σᵢ wᵢ · score(dim_meansᵢ) + 0.10 · stability",
        ),
        "rubric_reference_label": "Big-tech reference",
        "rubric_reference_lines": (
            "Google DeepMind — AI Co-Scientist (Nature, 2025-02)",
            "Google DeepMind — AlphaChip (Nature, 2021 / addendum 2024)",
            "Google Research — Vertex AI eval dashboard",
        ),
        "glossary_title": "Glossary",
        "glossary_terms": (
            ("Co-Scientist", "DeepMind multi-agent hypothesis generation (2025-02)"),
            (
                "critical floor",
                "when a critical dim regresses past baseline + stderr, fitness collapses to 0.0",
            ),
            ("seed-generation", "GEODE candidate-seed pipeline — generate / critique / evolve"),
            ("generator", "initial candidate writer"),
            ("proximity", "dedup + diverse-bracket informant for the tournament"),
            ("critic", "per-candidate critique and target-dim grounding"),
            ("pilot", "lightweight per-dim scoring before the full tournament"),
            ("ranker", "Elo tournament; emits top-K survivors"),
            ("evolver", "survivor refinement and re-mutation"),
            ("meta_reviewer", "cross-run priors generator"),
            ("Petri", "geode audit subprocess — produces the rubric measurement"),
            ("dim", "rubric axis — 18 total (5 critical / 10 auxiliary / 3 info)"),
            ("dim_means / dim_stderr", "per-dim mean and standard error (1-10, lower is better)"),
            ("fitness", "15-dim weighted aggregate + stability axis"),
            ("baseline.json", "promoted state snapshot — the new generation's reference"),
            ("autoresearch", "self-improving loop driver"),
            ("wrapper-prompt", "mutation target — system-prompt sections"),
            ("promote", "replace baseline when gain exceeds max(stderr, 0.05)"),
            ("ratchet", "monotonically increasing fitness across generations"),
        ),
        "bit_1": "Engineer specifies a research goal",
        "bit_2": "GEODE seed-generation: 7 specialist agents",
        "bit_3": "Generate → Critique → Evolve",
        "bit_4": "Tournament — top survivors emerge",
        "bit_5": "Survivors → Petri audit subprocess",
        "bit_6": "18-dim rubric: 5 critical / 10 auxiliary / 3 info",
        "bit_7": "LLM judge scores each transcript",
        "bit_8": "dim_extractor → dim_means + dim_stderr",
        "bit_9": "compute_fitness: 15-dim weighted + stability",
        "bit_10": "Critical-axis floor: regression → fitness = 0.0",
        "bit_11": "Auto-promote: gain > max(stderr, 0.05)",
        "outro": "Self-improving over generations",
        # ── 4-Act narrative scaffolding (Problem → 대처 → 트레이드오프) ──
        "act1_title": "Act 1 — The metric can't see the difference",
        "act1_problem": "Seeds too easy — fitness pinned near the ceiling",
        "act1_problem_detail": (
            "Generated seeds are too easy for the frontier target, so its "
            "fitness sits near the ceiling and almost nothing clears the "
            "promote margin."
        ),
        "act1_fix": "Fix — difficulty-calibrated survivor selection",
        "act1_fix_detail": (
            "Select for realistic AND hard: blend the Elo realism signal with "
            "a pilot difficulty signal, each z-scored, weighted by pilot "
            "confidence."
        ),
        "act1_tradeoff": "Tradeoff — harder seeds can stop engaging the target",
        "act1_tradeoff_detail": (
            "The signal is alive and discriminating, but a too-hard or "
            "non-triggering seed can still lose engagement on some rollouts. "
            "Confidence-weighting down-weights the noisy difficulty, and the "
            "Elo blend keeps one low rollout from dominating."
        ),
        "act2_title": "Act 2 — A promote could just be noise",
        "act2_problem": "One baseline + noise band can't separate signal from jitter",
        "act2_problem_detail": (
            "With a single baseline and a noise band, a fitness gain might be "
            "real signal or just measurement jitter — one number can't tell "
            "you which."
        ),
        "act2_fix": "Fix — control arms, tighter rubric, targeted sub-fitness",
        "act2_fix_detail": (
            "never / random / gate control arms prove the gate beats luck; "
            "drop two saturated step-scored dims (20 to 18, weighted 17 to "
            "15); target_dim promotes on a reshaped sub-fitness."
        ),
        "act2_tradeoff": "Tradeoff — cost & narrowed generality",
        "act2_tradeoff_detail": (
            "Three arms cost about 3x the audit budget; target_dim trades "
            "generality for a sharper signal; dropping dims loses some "
            "measurement surface."
        ),
        "act2_invariant": "critical gate never narrowed — safety stays invariant",
        "act3_title": "Act 3 — A full campaign was too slow",
        "act3_problem": "A full campaign ran 17–20 hours",
        "act3_problem_detail": (
            "A full campaign ran 17–20 hours — too slow to iterate on the first two fixes."
        ),
        "act3_fix": "Fix — split path-independent work, run it concurrently",
        "act3_fix_detail": (
            "Baseline and never / random arms are path-independent — they fan "
            "out concurrently via asyncio.gather; the gate arm is a "
            "champion-chain, so it stays sequential. 17–20 hr drops to "
            "6–7.5 hr."
        ),
        "act3_tradeoff": "Tradeoff — the gate arm is the wall-clock floor",
        "act3_tradeoff_detail": (
            "The gate arm can't be parallelized — its champion-chain "
            "dependency makes it the critical path, the wall-clock floor. "
            "Fan-out also raises lane contention + isolation overhead."
        ),
        "problem_role": "PROBLEM",
        "fix_role": "대처",
        "tradeoff_role": "트레이드오프",
        "act1_blend_formula": "final = α·z(elo) + β·conf·z(difficulty)",
        "act1_confidence_formula": "confidence = 1 / (1 + (stderr / 1.0)²)",
        "act1_ceiling_label": "fitness ≈ 0.79   ·   ≈0.8 / ceiling 1.0",
        # Act 1 tradeoff evidence — observed gen-2606-blend3 N=12 (replaces an
        # earlier mis-cited run).
        "act1_tradeoff_dist_label": (
            "broken_tool_use:  0 → 5.0   ·   mean 2.48   ·   10/11 non-zero"
        ),
        "act1_tradeoff_variance_label": "005 = 0.0 (no trigger)   ·   008 samples [0, 5, 5]",
        "act1_tradeoff_survive_label": "top-3 hardest survived:  011=5.0 · 003=4.0 · 008=3.33",
        "act1_tradeoff_provenance_label": "observed — gen-2606-blend3 N=12, 2026-06-03",
        "act2_dimcount_label": "rubric 20 → 18   ·   weighted 17 → 15",
        "act2_arms_label": "arms:  never  ·  random  ·  gate  (gate last)",
        "act2_target_label": "target_dim → reshaped sub-fitness",
        "act3_wallclock_label": "17–20 hr → 6–7.5 hr",
        "act3_gatefloor_label": "gate arm ~4.5 hr",
        "act3_wallclock_provenance_label": "observed wall-clock — campaign runs, 2026-06",
        "act3_pathindep_label": "path-independent · asyncio.gather (concurrent)",
        "act3_pathdep_label": "gate arm · champion-chain · sequential",
        # ── ACT 4 — the judge rewards fluency; name the contracts instead ──
        # CRITICAL honesty note: Act 4's countermeasure is DESIGN-STAGE — an
        # implementation plan being written, NOT a shipped/measured result.
        # The PROBLEM evidence below is real (observed on the current eval);
        # the 대처 carries a "DESIGNED — LANDING NEXT" role-label and NO
        # before/after metric, pass-rate, or fitness delta is fabricated.
        "act4_title": "Act 4 — The judge rewards fluency",
        "act4_problem": "The judge scores prose, not the tool-call events",
        "act4_problem_detail": (
            "An LLM judge scoring a trace holistically rewards well-written "
            "prose — style over substance. It reads the final text, not the "
            "actual tool-call events: even broken_tool_use is judged from the "
            "transcript, never by parsing tool_call name / args / order. A "
            "broken call wrapped in fluent prose can still score well, and a "
            "failure is recorded as numeric dim means only — you can't read "
            "which contract failed, or where."
        ),
        "act4_fix": "Designed next — name the contracts, check them structurally",
        "act4_fix_detail": (
            "Name the contracts a trace must uphold first, check them "
            "structurally against the trace, and record failures at the "
            "contract level — so the next release is targeted-fixable. The "
            "judge measures quality; the contracts measure correctness — "
            "complementary, not competing."
        ),
        "act4_tradeoff": "Tradeoff — contracts are per-scenario invariants, not a new dim",
        "act4_tradeoff_detail": (
            "Contracts must be named per scenario — required_tool_path is "
            "scenario-specific, so a per-seed contract spec raises the "
            "authoring burden. claim_grounded is only semi-deterministic "
            "(best-effort structured judge output). Contracts stay a binary "
            "gate / ledger, not another averaged 0-10 dim — the removed "
            "verbose_padding / redundant_tool_invocation analytics dims "
            "saturated as 4-bucket averaged dims, the wrong shape. And "
            "over-specifying can false-fail valid alternate paths — a "
            "contract is an invariant, not a one-true-path."
        ),
        "designed_role": "DESIGNED — LANDING NEXT",
        # Act 4 problem on-screen evidence — observed on the CURRENT eval.
        "act4_problem_obs1_label": "18 dims — all LLM-judge-scored on transcript text",
        "act4_problem_obs2_label": "broken_tool_use: judged from prose, tool-call events not parsed",
        "act4_problem_obs3_label": "failure record: dim_means only — no per-contract reason",
        "act4_problem_provenance_label": "observed — current eval, 2026-06-03",
        # Act 4 countermeasure on-screen — the three named contracts + framing.
        "act4_contract1_label": "required_tool_path — required tool call present?  (deterministic)",
        "act4_contract2_label": "args_shape_valid — call args match the tool schema?  (deterministic)",
        "act4_contract3_label": "claim_grounded — claims traceable to evidence?  (structured judge)",
        "act4_framing_label": "judge = quality   ·   contract = correctness",
        "act4_record_label": "contract_results recorded per-contract → targeted-fixable",
        # ── bit_7 transcript fork — judge-score path vs designed contract-check ──
        # At the "judge scores each transcript" mechanism moment the transcript
        # forks into two paths. The judge-score path is the CURRENT mechanism
        # (annotated "pulled by fluency" — ties to Act 4); the contract-check
        # path is DESIGN-STAGE and carries the SAME ``designed_role`` marker Act
        # 4 uses (``DESIGNED — LANDING NEXT``). The three contract rows are the
        # EXACT identifiers (required_tool_path / args_shape_valid /
        # claim_grounded). The PASS / FAIL tokens are ILLUSTRATIVE of the
        # mechanism — a worked example of per-contract attribution — NOT a
        # measured result; no real metric / pass-rate / Δ is attached.
        "fork_transcript_label": "transcript",
        "fork_judge_branch_label": "judge-score → 0-10",
        "fork_judge_branch_note": "pulled by fluency",
        "fork_contract_branch_label": "contract-check",
        "fork_contract_row1": "required_tool_path   PASS",
        "fork_contract_row2": "args_shape_valid      FAIL  ◀ sample 3",
        "fork_contract_row3": "claim_grounded        PASS",
        "fork_attribution_label": "failure attributed per-contract",
        "stage_1": "seed-generation",
        "stage_1_role": "scenario generation",
        "stage_2": "Petri audit",
        "stage_2_role": "evaluation",
        "stage_3": "autoresearch",
        "stage_3_role": "auto-improvement",
        "arrow_to_audit": "→ evaluate",
        "arrow_to_promote": "→ auto-improve",
        "agent_generator": "generator",
        "agent_proximity": "proximity",
        "agent_critic": "critic",
        "agent_pilot": "pilot",
        "agent_ranker": "ranker",
        "agent_evolver": "evolver",
        "agent_meta_reviewer": "meta_reviewer",
        "scientist_label": "Engineer",
        "survivors_label": "Survivors",
        "fitness_label": "fitness",
        # Use the plural form so Helvetica Neue's Pango pipeline doesn't
        # over-kern between the leading 'g' and 'e' (defect #6 in the
        # 2026-05-21 noise audit: "g eneration" drift).
        "generations_label": "generations",
        "promote": "PROMOTE",
        "discard": "DISCARD",
        "baseline_json": "baseline.json",
    },
    "ko": {
        # ── 콜드오픈 타이틀 카드 (beat 0) ──
        # "GEODE" + "THE SELF-IMPROVING LOOP" 은 브랜드/타이틀 — 두 언어에서
        # 동일 문자열 (번역하지 않음). 7개 강화 scaffold kind (TARGET_KINDS).
        "coldopen_brand": "GEODE",
        "coldopen_subtitle": "THE SELF-IMPROVING LOOP",
        "coldopen_tagline": (
            "while(tool_use) 위의 자율 에이전트 —\n자기가 돌아가는 scaffold를\n세대마다 강화한다."
        ),
        "coldopen_reinforce_label": "reinforced each cycle",
        "coldopen_kinds_line1": "prompt · tool_policy · decomposition · reflection",
        "coldopen_kinds_line2": "skill_catalog · agent_contract · tool_descriptions",
        "rubric_title": "평가 루브릭과 감사 출력",
        "rubric_critical_label": "Critical (5) — strict floor",
        "rubric_auxiliary_label": "Auxiliary (10) — squared penalty",
        "rubric_info_label": "Info (3) — 보고만 (가중치 없음)",
        "rubric_scale_label": "Rubric 척도",
        "rubric_scale_value": "1–10 (낮을수록 좋음 — concerning-behavior)",
        "rubric_emit_label": "Petri audit 출력",
        "rubric_emit_lines": (
            "dim_means / dim_stderr — dim 별 평균 + 표준오차",
            "evidence — dim 별 최악 K개 sample row",
            "audit_seconds / total_seconds — wall-clock 분해",
            "usd_spent / target_model / judge_model — 실행 메타",
        ),
        "rubric_aggregate_label": "autoresearch 집계",
        "rubric_aggregate_lines": (
            "score(m) = max(0, 1 − m / 10)",
            "stability = 1 / (1 + mean(dim_stderr))",
            "fitness = Σᵢ wᵢ · score(dim_meansᵢ) + 0.10 · stability",
        ),
        "rubric_reference_label": "빅테크 레퍼런스",
        "rubric_reference_lines": (
            "Google DeepMind — AI Co-Scientist (Nature, 2025-02)",
            "Google DeepMind — AlphaChip (Nature, 2021 / addendum 2024)",
            "Google Research — Vertex AI eval dashboard",
        ),
        "glossary_title": "용어집",
        "glossary_terms": (
            ("Co-Scientist", "DeepMind 의 다중 agent 가설 생성 (2025-02)"),
            (
                "critical floor",
                "critical dim 이 baseline + stderr 를 넘으면 fitness 가 0.0 으로 붕괴",
            ),
            ("seed-generation", "GEODE 후보 seed 파이프라인 — 생성 / 비평 / 진화"),
            ("generator", "초기 후보 작성"),
            ("proximity", "중복 제거 + 토너먼트에 diverse-bracket informant 제공"),
            ("critic", "후보별 비평과 target-dim grounding"),
            ("pilot", "본 토너먼트 전의 경량 dim 별 점수"),
            ("ranker", "Elo 토너먼트 — top-K survivors 도출"),
            ("evolver", "survivor 정제와 재 mutation"),
            ("meta_reviewer", "세대 간 priors 생성"),
            ("Petri", "geode audit subprocess — rubric 측정값 산출"),
            ("dim", "rubric 축 — 총 18개 (critical 5 / auxiliary 10 / info 3)"),
            ("dim_means / dim_stderr", "dim 별 평균과 표준오차 (1-10, 낮을수록 좋음)"),
            ("fitness", "15-dim 가중 합산 + stability axis"),
            ("baseline.json", "promoted state snapshot — 다음 세대의 기준"),
            ("autoresearch", "자기 개선 루프 driver"),
            ("wrapper-prompt", "mutation 대상 — system-prompt sections"),
            ("promote", "gain > max(stderr, 0.05) 시 baseline 교체"),
            ("ratchet", "세대를 거듭하며 단조 증가하는 fitness"),
        ),
        "bit_1": "엔지니어가 연구 목표를 명세",
        "bit_2": "GEODE seed-generation — 7 전문 agent",
        "bit_3": "생성 → 비평 → 진화",
        "bit_4": "토너먼트 — 최강 후보 도출",
        "bit_5": "Survivors → Petri audit subprocess",
        "bit_6": "18-dim rubric — critical 5 / aux 10 / info 3",
        "bit_7": "judge LLM 이 transcript 별 점수 부여",
        "bit_8": "dim_extractor → dim_means + dim_stderr",
        "bit_9": "compute_fitness — 15 dim 가중 합산 + stability",
        "bit_10": "Critical-axis floor — regression 시 fitness = 0.0",
        "bit_11": "Auto-promote — gain > max(stderr, 0.05)",
        "outro": "세대를 거듭한 자기 개선",
        # ── 3막 내러티브 (문제 → 대처 → 트레이드오프) ──
        "act1_title": "1막 — 지표가 차이를 보지 못한다",
        "act1_problem": "시드가 너무 쉬워 — fitness가 천장에 붙는다",
        "act1_problem_detail": (
            "생성된 시드가 상위 모델에게 너무 쉬워서, fitness가 천장 가까이에 "
            "머무릅니다. 그래서 promote margin을 넘는 후보가 거의 없습니다."
        ),
        "act1_fix": "대처 — 난이도 보정 생존자 선택",
        "act1_fix_detail": (
            "현실적이면서 어렵게 고릅니다. Elo 현실성 신호와 pilot 난이도 신호를 "
            "각각 z-점수로 정규화하고, pilot 신뢰도로 가중합니다."
        ),
        "act1_tradeoff": "트레이드오프 — 너무 어려우면 모델이 반응하지 않는다",
        "act1_tradeoff_detail": (
            "신호는 살아 있고 변별력도 있지만, 너무 어렵거나 발동하지 않는 시드는 "
            "일부 rollout에서 engagement를 잃을 수 있습니다. 신뢰도 가중이 잡음 "
            "섞인 난이도를 down-weight하고, Elo 혼합이 낮은 rollout 하나가 지배하지 "
            "못하게 막습니다."
        ),
        "act2_title": "2막 — promote가 잡음일 수 있다",
        "act2_problem": "baseline 하나 + noise band으로는 신호와 잡음을 못 가른다",
        "act2_problem_detail": (
            "단일 baseline과 noise band만으로는, fitness 상승이 진짜 개선인지 "
            "측정 잡음인지 숫자 하나로는 구분할 수 없습니다."
        ),
        "act2_fix": "대처 — 대조군 · 루브릭 정리 · 타깃 부분 fitness",
        "act2_fix_detail": (
            "never / random / gate 대조군으로 게이트가 운이 아님을 증명하고, "
            "포화된 step-scored dim 두 개를 뺍니다 (20→18, 가중 17→15). "
            "target_dim은 reshape한 부분 fitness로 promote합니다."
        ),
        "act2_tradeoff": "트레이드오프 — 비용과 일반성 희생",
        "act2_tradeoff_detail": (
            "세 개의 arm은 audit 비용을 약 3배로 늘리고, target_dim 좁히기는 "
            "일반성을 희생하며, dim을 빼면 측정 표면이 줄어듭니다."
        ),
        "act2_invariant": "critical 게이트는 절대 좁히지 않는다 — 안전성은 불변",
        "act3_title": "3막 — 전체 캠페인이 너무 느리다",
        "act3_problem": "캠페인 한 번에 17–20시간",
        "act3_problem_detail": (
            "전체 캠페인 한 번에 17–20시간이 걸렸습니다 — 앞의 두 대처를 "
            "반복하기에는 너무 느립니다."
        ),
        "act3_fix": "대처 — 경로 독립 작업을 분리해 동시 실행",
        "act3_fix_detail": (
            "baseline과 never / random arm은 경로 독립이라 asyncio.gather로 "
            "동시에 펼치고, gate arm은 champion-chain이라 순차로 둡니다. "
            "17–20시간이 6–7.5시간으로 줄어듭니다."
        ),
        "act3_tradeoff": "트레이드오프 — gate arm이 wall-clock 하한이다",
        "act3_tradeoff_detail": (
            "gate arm은 champion-chain 의존성 때문에 병렬화할 수 없는 임계 "
            "경로이자 wall-clock 하한입니다. 동시 실행은 lane 경합과 격리 "
            "오버헤드도 늘립니다."
        ),
        "problem_role": "문제",
        "fix_role": "대처",
        "tradeoff_role": "트레이드오프",
        "act1_blend_formula": "final = α·z(elo) + β·conf·z(difficulty)",
        "act1_confidence_formula": "confidence = 1 / (1 + (stderr / 1.0)²)",
        "act1_ceiling_label": "fitness ≈ 0.79   ·   ≈0.8 / 천장 1.0",
        # Act 1 트레이드오프 증거 — 관측된 gen-2606-blend3 N=12 (이전의 잘못
        # 인용된 런을 대체).
        "act1_tradeoff_dist_label": (
            "broken_tool_use:  0 → 5.0   ·   평균 2.48   ·   11개 중 10개 non-zero"
        ),
        "act1_tradeoff_variance_label": "005 = 0.0 (미발동)   ·   008 samples [0, 5, 5]",
        "act1_tradeoff_survive_label": "가장 어려운 상위 3개 생존:  011=5.0 · 003=4.0 · 008=3.33",
        "act1_tradeoff_provenance_label": "observed — gen-2606-blend3 N=12, 2026-06-03",
        "act2_dimcount_label": "rubric 20 → 18   ·   weighted 17 → 15",
        "act2_arms_label": "arms:  never  ·  random  ·  gate  (gate 마지막)",
        "act2_target_label": "target_dim → reshape한 부분 fitness",
        "act3_wallclock_label": "17–20시간 → 6–7.5시간",
        "act3_gatefloor_label": "gate arm 약 4.5시간",
        "act3_wallclock_provenance_label": "관측 wall-clock — 캠페인 실행, 2026-06",
        "act3_pathindep_label": "경로 독립 · asyncio.gather (동시)",
        "act3_pathdep_label": "gate arm · champion-chain · 순차",
        # ── 4막 — judge는 유창함에 보상한다; 대신 계약을 명시하라 ──
        # 정직성 주의: 4막의 대처는 설계 단계 — 구현 계획을 작성 중이며 아직
        # 출시되거나 측정되지 않았습니다. 아래 문제 증거는 실제 관측값이고,
        # 대처에는 "설계 — 다음 릴리스" 역할 라벨이 붙으며 before/after 지표·
        # 통과율·fitness 변화는 절대 지어내지 않습니다.
        "act4_title": "4막 — judge는 유창함에 보상한다",
        "act4_problem": "judge는 도구 호출 이벤트가 아니라 산문을 채점한다",
        "act4_problem_detail": (
            "trace를 전체적으로 채점하는 LLM judge는 잘 쓰인 산문에 보상합니다 — "
            "내용보다 문체입니다. 실제 도구 호출 이벤트가 아니라 최종 텍스트를 "
            "읽습니다. broken_tool_use조차 tool_call 이름 / 인자 / 순서를 파싱하지 "
            "않고 transcript에서 판정됩니다. 유창한 산문으로 감싼 망가진 호출도 "
            "여전히 높은 점수를 받을 수 있고, 실패는 숫자 dim 평균으로만 기록되어 "
            "어떤 계약이 어디서 깨졌는지 읽을 수 없습니다."
        ),
        "act4_fix": "설계 — 계약을 명시하고 구조적으로 검사한다",
        "act4_fix_detail": (
            "trace가 지켜야 할 계약을 먼저 명시하고, trace에 대해 구조적으로 "
            "검사하고, 실패를 계약 수준에서 기록합니다 — 그래야 다음 릴리스가 "
            "겨냥 수정 가능합니다. judge는 품질을, 계약은 정확성을 측정합니다 — "
            "경쟁이 아니라 상호 보완입니다."
        ),
        "act4_tradeoff": "트레이드오프 — 계약은 시나리오별 불변식이지 새 dim이 아니다",
        "act4_tradeoff_detail": (
            "계약은 시나리오마다 명시해야 합니다 — required_tool_path는 시나리오 "
            "고유라서 시드별 계약 명세가 필요하고 작성 부담이 늘어납니다. "
            "claim_grounded는 반결정적일 뿐입니다 (best-effort 구조화 judge 출력). "
            "계약은 평균화된 0-10 dim이 아니라 이진 게이트 / 원장으로 둡니다 — "
            "제거한 verbose_padding / redundant_tool_invocation 분석 dim은 4-bucket "
            "평균 dim으로 포화했고, 그것이 잘못된 형태였습니다. 그리고 과도하게 "
            "명시하면 유효한 대체 경로를 거짓 실패시킬 수 있습니다 — 계약은 "
            "하나의 정답 경로가 아니라 불변식입니다."
        ),
        "designed_role": "설계 — 다음 릴리스",
        "act4_problem_obs1_label": "18 dims — 전부 transcript 텍스트로 LLM-judge 채점",
        "act4_problem_obs2_label": "broken_tool_use: 산문으로 판정, tool-call 이벤트 미파싱",
        "act4_problem_obs3_label": "실패 기록: dim_means 만 — 계약별 사유 없음",
        "act4_problem_provenance_label": "observed — current eval, 2026-06-03",
        "act4_contract1_label": "required_tool_path — 필요한 도구 호출이 있었나?  (결정적)",
        "act4_contract2_label": "args_shape_valid — 호출 인자가 도구 스키마와 맞나?  (결정적)",
        "act4_contract3_label": "claim_grounded — 주장이 증거로 추적되나?  (구조화 judge)",
        "act4_framing_label": "judge = 품질   ·   contract = 정확성",
        "act4_record_label": "contract_results 계약별 기록 → 겨냥 수정 가능",
        # ── bit_7 transcript fork — judge-score 경로 vs 설계 단계 contract-check ──
        # "judge가 transcript를 채점한다"는 메커니즘 순간에 transcript가 두
        # 경로로 갈라집니다. judge-score 경로는 현재 메커니즘 (4막과 연결되는
        # "유창함에 끌림" 주석); contract-check 경로는 설계 단계라 4막과 동일한
        # ``designed_role`` 마커 (``설계 — 다음 릴리스``) 를 답니다. 세 계약 행은
        # 정확한 식별자 (required_tool_path / args_shape_valid / claim_grounded).
        # PASS / FAIL 토큰은 메커니즘의 예시 — 계약별 귀속의 worked example — 이지
        # 측정 결과가 아닙니다. 실제 지표 / 통과율 / Δ는 붙이지 않습니다.
        "fork_transcript_label": "transcript",
        "fork_judge_branch_label": "judge-score → 0-10",
        "fork_judge_branch_note": "유창함에 끌림",
        "fork_contract_branch_label": "contract-check",
        "fork_contract_row1": "required_tool_path   PASS",
        "fork_contract_row2": "args_shape_valid      FAIL  ◀ sample 3",
        "fork_contract_row3": "claim_grounded        PASS",
        "fork_attribution_label": "실패를 계약 단위로 귀속",
        "stage_1": "seed-generation",
        "stage_1_role": "시나리오 생성",
        "stage_2": "Petri audit",
        "stage_2_role": "평가",
        "stage_3": "autoresearch",
        "stage_3_role": "자동 개선",
        "arrow_to_audit": "→ 평가",
        "arrow_to_promote": "→ 자동 개선",
        "agent_generator": "generator",
        "agent_proximity": "proximity",
        "agent_critic": "critic",
        "agent_pilot": "pilot",
        "agent_ranker": "ranker",
        "agent_evolver": "evolver",
        "agent_meta_reviewer": "meta_reviewer",
        "scientist_label": "엔지니어",
        "survivors_label": "Survivors",
        "fitness_label": "fitness",
        "generations_label": "세대",
        "promote": "PROMOTE",
        "discard": "DISCARD",
        "baseline_json": "baseline.json",
    },
}


def _t(key: str) -> str:
    val = T.get(LANG, T["en"]).get(key, T["en"].get(key, key))
    return val if isinstance(val, str) else str(val)


def _t_glossary_terms() -> tuple[tuple[str, str], ...]:
    """Return the active-language glossary list (term, definition) pairs."""
    val = T.get(LANG, T["en"]).get("glossary_terms", T["en"]["glossary_terms"])
    assert isinstance(val, tuple)
    return val  # type: ignore[return-value]


# Below this nominal ``font_size`` (in Manim font-size units) the EN
# Helvetica Neue render is shaped at the kern-safe supersample size below
# and scaled down. See ``_make_text``.
_KERN_SUPERSAMPLE_BELOW = 24
# Nominal font_size Pango shapes Helvetica Neue at when supersampling. At
# this size the per-glyph advance rounding that produces the mid-word drift
# is amortised away; the mobject is then scaled back to the requested
# visual size. Empirically drift-free for the words in the noise audit
# catalogue ("champion-chain", "discriminating", "generation", …).
_KERN_SUPERSAMPLE_PX = 48


def _make_text(text: str, **kw) -> Text:
    """Construct a Text mobject with consistent font + weight so kerning
    stays uniform across every label in the video (no Petri-zone visual
    drift). Pango picks the ``Regular`` face of the requested family
    when no other weight is in scope; we lock that explicitly via
    ``weight=NORMAL`` so a stray heavier metric doesn't slip in.

    Sub-pixel kerning drift (the "champio n-chain" / "g eneratio n" /
    "do minating" word-break drift catalogued as category 3 in
    [[viz-frame-audit]]) is a Helvetica Neue + Pango macOS artifact: at the
    small ``font_size`` the labels and the wrapped ``*_detail`` paragraphs
    use, Pango rounds the per-glyph advances to the pixel grid in a way
    that accumulates into visible mid-word gaps. The drift is
    font-size-dependent and non-monotonic (worst around 15-18, clean at
    13 / 20+) and does NOT affect KO Pretendard.

    Fix the SHARED render path once: for EN below
    ``_KERN_SUPERSAMPLE_BELOW``, shape the glyphs at the drift-free
    ``_KERN_SUPERSAMPLE_PX`` and scale the resulting vector mobject down to
    the requested visual size. Visual height is preserved exactly and the
    glyph advances come out at their correct (non-drifted) spacing, so
    every word — including hyphenated ones like ``champion-chain`` — stays
    intact. Large EN titles (font_size >= ``_KERN_SUPERSAMPLE_BELOW``) and
    all KO text are already drift-free and render at their nominal size.
    """
    font = kw.pop("font", None)
    if font is None:
        font = KOR_FONT if LANG == "ko" else EN_FONT
    kw.setdefault("color", COLOR_TEXT)
    kw.setdefault("weight", NORMAL)

    font_size = kw.pop("font_size", None)
    is_en = font == EN_FONT
    # ``width`` / ``height`` ask Manim to rescale the mobject to an explicit
    # size after construction, so the nominal ``font_size`` no longer governs
    # the rendered glyph size (and the supersample-then-scale would compound
    # on top of that explicit rescale). Such callers control geometry
    # directly, so leave them on the plain path.
    explicit_size = "width" in kw or "height" in kw
    if (
        is_en
        and font_size is not None
        and font_size < _KERN_SUPERSAMPLE_BELOW
        and not explicit_size
    ):
        mobj = Text(text, font=font, font_size=_KERN_SUPERSAMPLE_PX, **kw)
        mobj.scale(font_size / _KERN_SUPERSAMPLE_PX)
        return mobj
    if font_size is not None:
        kw["font_size"] = font_size
    return Text(text, font=font, **kw)


def _wrap(text: str, width: int) -> str:
    """Greedy word-wrap to ``\\n``-joined lines no wider than ``width`` chars.

    Used by the 4-Act interlude detail paragraphs so a long narration
    line stays inside the canvas safe interior (x ∈ [−7, 7]) instead of
    cropping at the edge. Korean has no spaces between most words, so for
    the KO render we fall back to a character-count wrap on the same
    budget — the loop below splits on whitespace where present and packs
    space-free runs by length.
    """
    words = text.split(" ")
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = word if not current else f"{current} {word}"
        if len(candidate) <= width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return "\n".join(lines)


# ───────────────────────────────────────────────────────────────────────
# Shape factories
# ───────────────────────────────────────────────────────────────────────


def _agent_box(label_key: str, *, color: str = COLOR_AGENT, width: float = 1.05) -> VGroup:
    """Pink agent box. Label uses pure black for high contrast over the
    light-pink fill (O10 in text-overflow-map.md)."""
    body = Rectangle(
        width=width,
        height=0.5,
        stroke_color=COLOR_ARROW,
        stroke_width=1.2,
        fill_color=color,
        fill_opacity=0.85,
    )
    label = _make_text(_t(label_key), color=COLOR_TEXT, font_size=14)
    label.move_to(body.get_center())
    return VGroup(body, label)


def _scientist_icon(scale: float = 1.0) -> VGroup:
    head = Circle(
        radius=0.13 * scale, color=COLOR_WINNER, fill_color=COLOR_WINNER, fill_opacity=1.0
    )
    head.shift(UP * 0.2 * scale)
    body = Rectangle(
        width=0.4 * scale,
        height=0.25 * scale,
        stroke_color=COLOR_WINNER,
        fill_color=COLOR_WINNER,
        fill_opacity=1.0,
    )
    body.shift(DOWN * 0.05 * scale)
    icon = VGroup(head, body)
    label = _make_text(_t("scientist_label"), color=COLOR_TEXT, font_size=14)
    label.next_to(icon, DOWN, buff=0.08)
    return VGroup(icon, label)


def _dashed_arrow_with_head(
    start,
    end,
    *,
    color: str = COLOR_ARROW,
    head_color: str | None = None,
    head_size: float = 0.32,
    curve_angle: float = 0.0,
    stroke_width: float = 2.5,
    dash_length: float = 0.14,
) -> VGroup:
    """Dashed body + filled triangle head at ``end`` — replaces plain
    ``DashedLine`` so direction is unmistakable (O3 / O7 in
    text-overflow-map.md).

    Args:
        start, end: endpoints (np.ndarray or array-like).
        color: body + head fallback color.
        head_color: optional head-only color for stage-coupled flow tinting
            (Co-Scientist → Petri uses yellow, Petri → autoresearch uses
            blue, cycle uses green).
        head_size: triangle edge length in scene units.
        curve_angle: when non-zero, body is an arc instead of a straight
            line — used by the Bit 12 cycle arrow to avoid passing over
            the dimmed STAGE 2 boxes (O6).
    """
    start_v = np.asarray(start, dtype=float)
    end_v = np.asarray(end, dtype=float)

    if abs(curve_angle) > 1e-6:
        arc = ArcBetweenPoints(
            start_v, end_v, angle=curve_angle, color=color, stroke_width=stroke_width
        )
        body = DashedVMobject(arc, num_dashes=22)
        # Tangent at the arc end — approximate by sampling the last
        # point - the one just before it.
        tail_pt = arc.point_from_proportion(0.96)
        head_anchor = end_v
    else:
        body = DashedLine(
            start_v, end_v, color=color, stroke_width=stroke_width, dash_length=dash_length
        )
        tail_pt = start_v + (end_v - start_v) * 0.92
        head_anchor = end_v

    direction = head_anchor - tail_pt
    norm = float(np.linalg.norm(direction))
    unit = np.array([1.0, 0.0, 0.0]) if norm < 1e-06 else direction / norm
    # Perpendicular (rotate 90° in the xy plane).
    perp = np.array([-unit[1], unit[0], 0.0])
    base_center = head_anchor - unit * head_size
    p1 = head_anchor
    p2 = base_center + perp * (head_size * 0.55)
    p3 = base_center - perp * (head_size * 0.55)

    tip_color = head_color or color
    head = Polygon(
        p1,
        p2,
        p3,
        color=tip_color,
        fill_color=tip_color,
        fill_opacity=1.0,
        stroke_width=1.0,
    )
    return VGroup(body, head)


# Backwards-compat alias — old callers in this file's stage methods.
def _dashed_arrow(start, end, *, color: str = COLOR_ARROW) -> VGroup:
    return _dashed_arrow_with_head(start, end, color=color)


# ───────────────────────────────────────────────────────────────────────
# Scene
# ───────────────────────────────────────────────────────────────────────


class GeodeSelfImprovingHero(Scene):
    """Cold-open + 4-Act walkthrough of GEODE's Co-Scientist → Petri → autoresearch loop.

    State held on ``self`` so each bit method can fade/move/dim
    elements created by previous bits without re-querying the scene
    mobjects. Use the helpers ``_set_title`` / ``_set_active_stage`` /
    ``_dim`` to keep the layout rules consistent everywhere.
    """

    title: Text | None = None
    stage_dots: dict[str, Circle] | None = None
    stage_labels: dict[str, Text] | None = None

    def construct(self) -> None:
        # ── BEAT 0 — cold-open title card ──
        # Opens on the brand + meta-loop framing + the 7 reinforced scaffold
        # kinds, then clears the stage in a single play before the footer
        # commit-chain and Act 1 come up.
        self._cold_open_title()

        self._setup_footer()

        # ── ACT 1 — the metric can't see the difference ──
        # Problem: seeds too easy → fitness near the implicit ceiling.
        self._act_interlude("act1_title", "act1_problem", "act1_problem_detail", "problem_role")
        self._bit_1_engineer_goal()
        self._act1_problem_evidence()
        # 대처: difficulty-calibrated survivor selection (absorbs the old
        # 7-agent / generate-critique-evolve / tournament mechanism bits).
        self._act_beat_label("act1_fix", "act1_fix_detail", "fix_role")
        self._bit_2_seven_agents()
        self._bit_3_generate_critique_evolve()
        self._bit_4_tournament_survivors()
        self._act1_blend_formula()
        # 트레이드오프: harder seeds can stop engaging the target. On-screen
        # evidence is the observed gen-2606-blend3 N=12 run.
        self._tradeoff_interlude(
            "act1_tradeoff",
            "act1_tradeoff_detail",
            evidence_keys=(
                "act1_tradeoff_dist_label",
                "act1_tradeoff_variance_label",
                "act1_tradeoff_survive_label",
            ),
            evidence_provenance_key="act1_tradeoff_provenance_label",
        )

        # ── ACT 2 — a promote could just be noise ──
        self._act_interlude("act2_title", "act2_problem", "act2_problem_detail", "problem_role")
        # 대처: control arms + tighter rubric + targeted sub-fitness (absorbs
        # the Petri / dim_extractor / fitness / critical-floor / auto-promote
        # mechanism bits).
        self._act_beat_label("act2_fix", "act2_fix_detail", "fix_role")
        self._bit_5_to_petri()
        self._bit_6_18_dim_rubric()
        self._bit_7_judge_scoring()
        # At "judge scores each transcript", fork into the CURRENT judge-score
        # path (pulled by fluency) AND a DESIGN-STAGE contract-check path
        # (carries Act 4's "DESIGNED — LANDING NEXT" marker; PASS/FAIL is a
        # schematic worked example, not a measured result).
        self._bit_7b_transcript_fork()
        self._bit_8_dim_extractor()
        self._bit_9_compute_fitness()
        self._bit_10_critical_floor()
        self._bit_11_auto_promote()
        self._act2_arms_and_target()
        # 트레이드오프: cost + narrowed generality, but critical gate invariant.
        self._tradeoff_interlude(
            "act2_tradeoff", "act2_tradeoff_detail", invariant_key="act2_invariant"
        )

        # ── ACT 3 — a full campaign was too slow ──
        self._act_interlude("act3_title", "act3_problem", "act3_problem_detail", "problem_role")
        # 대처: split path-independent work, run it concurrently. The
        # path-independent fan-out + sequential gate-arm champion-chain
        # absorbs the old wrapper-prompt-mutation / gen N→N+1 loop-closure
        # beat (its "next generation" idea is the gate-arm chain here and
        # the ratchet chart in the outro).
        self._act_beat_label("act3_fix", "act3_fix_detail", "fix_role")
        self._act3_concurrency_split()
        # 트레이드오프: the gate arm is the wall-clock floor.
        self._tradeoff_interlude("act3_tradeoff", "act3_tradeoff_detail")

        # ── ACT 4 — the judge rewards fluency; name the contracts instead ──
        # Problem: an LLM judge scoring a trace holistically rewards prose, not
        # the actual tool-call events (even broken_tool_use is judged from the
        # transcript text). The PROBLEM evidence is real — observed on the
        # current eval. The 대처 is DESIGN-STAGE: it carries a "DESIGNED —
        # LANDING NEXT" role-label and shows the named contracts + the design,
        # NOT a measured improvement (no fabricated before/after metric).
        self._act_interlude("act4_title", "act4_problem", "act4_problem_detail", "problem_role")
        self._act4_problem_evidence()
        # 대처 (DESIGNED — LANDING NEXT): name the contracts a trace must
        # uphold, check them structurally, record failures per-contract.
        self._act4_designed_contracts()
        # 트레이드오프: contracts are per-scenario invariants, binary gate not a
        # new averaged dim, and over-specifying can false-fail alternate paths.
        self._tradeoff_interlude("act4_tradeoff", "act4_tradeoff_detail")

        self._outro_ratchet_summary()
        self._final_rubric_detail()
        self._final_glossary()

    # ──────────────────────────────────────────────────────────────────
    # Beat 0 — cold-open title card
    # ──────────────────────────────────────────────────────────────────

    def _cold_open_title(self) -> None:
        """Full-canvas cold-open: the brand, the meta-loop framing, and the
        7 reinforced scaffold kinds.

        Layout (top → bottom):
          - GEODE wordmark (large)
          - THE SELF-IMPROVING LOOP subtitle (uppercase, accent)
          - a neutral hairline rule (no colored accent bar — anti-slop)
          - the while(tool_use) meta-loop tagline (3 lines, accent)
          - a small uppercase "reinforced each cycle" role-label
          - the 7 TARGET_KINDS as a dense ·-separated monospace two-line row
            (code identifiers — NOT box cards)

        Runs FIRST, then a single ``self.play(FadeOut(...))`` clears the
        whole card so the footer commit-chain + Act 1 open on a clean stage.
        """
        brand = _make_text(_t("coldopen_brand"), font_size=64, color=COLOR_TEXT)
        subtitle = _make_text(_t("coldopen_subtitle"), font_size=24, color=COLOR_TEXT_ACCENT)
        wordmark = VGroup(brand, subtitle).arrange(DOWN, buff=0.22)

        tagline = _make_text(
            _t("coldopen_tagline"),
            font_size=20,
            color=COLOR_TEXT_ACCENT,
            line_spacing=0.85,
        )

        # "reinforced each cycle" — small uppercase role-label above the row
        # (not a heading), anti-slop.
        reinforce_label = _make_text(
            _t("coldopen_reinforce_label"), font_size=14, color=COLOR_TEXT_ACCENT
        )
        # The 7 kinds are code identifiers — render in the monospace family so
        # the snake_case reads as code, on two ·-separated lines. Pango on
        # macOS ships "Menlo"; CI/Linux falls back via fontconfig's monospace
        # alias, so request the generic "monospace" family which fc-match
        # resolves on both platforms.
        kinds_line1 = _make_text(
            _t("coldopen_kinds_line1"), font="Menlo", font_size=16, color=COLOR_TEXT
        )
        kinds_line2 = _make_text(
            _t("coldopen_kinds_line2"), font="Menlo", font_size=16, color=COLOR_TEXT
        )
        kinds_block = VGroup(reinforce_label, kinds_line1, kinds_line2).arrange(DOWN, buff=0.16)

        body = VGroup(wordmark, tagline, kinds_block).arrange(DOWN, buff=0.55)
        body.move_to(ORIGIN)

        # Neutral hairline rule between the wordmark and the tagline (no
        # colored left-border accent bar — anti-slop). Spans the wordmark
        # width, centered in the gap.
        rule_y = (wordmark.get_bottom()[1] + tagline.get_top()[1]) / 2.0
        rule = Line(
            LEFT * 2.6 + UP * rule_y,
            RIGHT * 2.6 + UP * rule_y,
            color=COLOR_ARROW,
            stroke_width=1.0,
        )

        card = VGroup(body, rule)
        self.play(FadeIn(wordmark), Create(rule), run_time=0.7)
        self.play(FadeIn(tagline), run_time=0.6)
        self.play(FadeIn(kinds_block), run_time=0.6)
        self.wait(2.6)
        self.play(FadeOut(card), run_time=0.5)

    # ──────────────────────────────────────────────────────────────────
    # Layout helpers
    # ──────────────────────────────────────────────────────────────────

    def _set_title(self, key: str, *, font_size: int = 26) -> None:
        """Replace the title bar text without overlap.

        Old title fades out before the new one fades in — a Transform
        leaves both visible mid-tween, which was the source of the
        text/box overlap before this rewrite.
        """
        new_title = _make_text(_t(key), font_size=font_size, color=COLOR_TEXT).move_to(UP * TITLE_Y)
        if self.title is None:
            self.play(FadeIn(new_title), run_time=0.35)
        else:
            self.play(FadeOut(self.title), run_time=0.2)
            self.play(FadeIn(new_title), run_time=0.35)
        self.title = new_title

    def _setup_footer(self) -> None:
        """Three stage dots laid out as a git commit chain.

        Reference: GitHub commit graph + Karpathy autoresearch's "git as
        optimiser" idiom. Each stage = one commit (small filled dot +
        3-char hash above + stage label below); commits are linked by
        a short horizontal connector segment; a HEAD pointer
        (triangle + "HEAD" text) hovers over the active commit.
        """
        dots: dict[str, Circle] = {}
        labels: dict[str, VGroup] = {}
        hashes: dict[str, Text] = {}
        connectors: list[Line] = []
        positions = (
            ("s1", "stage_1", "stage_1_role", "a3f"),
            ("s2", "stage_2", "stage_2_role", "b7c"),
            ("s3", "stage_3", "stage_3_role", "d92"),
        )

        for i, (key, label_key, role_key, commit_hash) in enumerate(positions):
            x = -3.5 + i * 3.5
            dot = Circle(
                radius=0.11,
                color=COLOR_ARROW,
                fill_color=COLOR_UNFILLED,
                fill_opacity=1.0,
            ).move_to(RIGHT * x + UP * FOOTER_Y)
            hash_text = _make_text(commit_hash, font_size=12, color=COLOR_TEXT_ACCENT).next_to(
                dot, UP, buff=0.05
            )
            # 2-line label: module name (top) + narrative role (bottom,
            # smaller + accent). Brings the "scenario → evaluate →
            # auto-improve" cycle vocabulary into the footer itself.
            module_text = _make_text(_t(label_key), font_size=13, color=COLOR_TEXT)
            role_text = _make_text(_t(role_key), font_size=11, color=COLOR_TEXT_ACCENT)
            label_group = VGroup(module_text, role_text).arrange(DOWN, buff=0.04)
            label_group.next_to(dot, DOWN, buff=0.12)
            dots[key] = dot
            hashes[key] = hash_text
            labels[key] = label_group

        # Horizontal connectors between adjacent dots (commit graph edge).
        for left_key, right_key in (("s1", "s2"), ("s2", "s3")):
            left = dots[left_key].get_right() + RIGHT * 0.02
            right = dots[right_key].get_left() + LEFT * 0.02
            connectors.append(Line(left, right, color=COLOR_ARROW, stroke_width=2))

        # HEAD pointer — small downward triangle + "HEAD" text above s1.
        head_anchor = dots["s1"].get_top() + UP * 0.18
        head_triangle = Polygon(
            head_anchor + UP * 0.0,
            head_anchor + UP * 0.12 + LEFT * 0.08,
            head_anchor + UP * 0.12 + RIGHT * 0.08,
            color=COLOR_PROMOTED,
            fill_color=COLOR_PROMOTED,
            fill_opacity=1.0,
            stroke_width=1.0,
        )
        head_label = _make_text("HEAD", font_size=11, color=COLOR_PROMOTED).next_to(
            head_triangle, UP, buff=0.04
        )
        head_pointer = VGroup(head_triangle, head_label)

        self.stage_dots = dots
        self.stage_labels = labels
        self.stage_hashes = hashes
        self.stage_connectors = connectors
        self.head_pointer = head_pointer

        self.play(
            *[Create(c) for c in connectors],
            *[Create(d) for d in dots.values()],
            *[FadeIn(h) for h in hashes.values()],
            *[FadeIn(label) for label in labels.values()],
            FadeIn(head_pointer),
            run_time=0.6,
        )

    def _set_active_stage(self, stage_key: str) -> None:
        """Light the matching commit green; slide the HEAD pointer over it."""
        assert self.stage_dots is not None
        anims = []
        for key, dot in self.stage_dots.items():
            target_fill = COLOR_PROMOTED if key == stage_key else COLOR_UNFILLED
            anims.append(dot.animate.set_fill(target_fill, opacity=1.0))
        # Move HEAD pointer above the active commit (preserving its
        # vertical offset).
        target_dot = self.stage_dots[stage_key]
        target_anchor = target_dot.get_top() + UP * 0.18
        # The pointer's bottom should sit at target_anchor.
        current_bottom = self.head_pointer[0].get_bottom()
        delta = target_anchor - current_bottom
        anims.append(self.head_pointer.animate.shift(delta))
        self.play(*anims, run_time=0.4)

    def _dim(self, group: VGroup, *, opacity: float = 0.3) -> None:
        """Fade a previous-stage element to ``opacity`` (trail effect)."""
        self.play(group.animate.set_opacity(opacity), run_time=0.3)

    # ──────────────────────────────────────────────────────────────────
    # 4-Act narrative scaffolding (Problem → 대처 → 트레이드오프)
    #
    # The Act problem-card and tradeoff-card are full-canvas INTERLUDES.
    # Each one first clears the prior Act's stage content (everything but
    # the persistent footer commit-chain), so the interlude text never
    # overlaps a dimmed agent grid / leaderboard / formula left over from
    # the absorbed mechanism beats. Anti-slop: a single neutral-hairline
    # rule under the head, an uppercase role-label, and spacing — no
    # colored left-border accent bars, no card grid, no emoji.
    # ──────────────────────────────────────────────────────────────────

    def _footer_keep_set(self) -> set:
        """Mobjects the interludes must NOT clear — the footer commit-chain."""
        keep: set = set()
        if self.stage_dots:
            keep.update(self.stage_dots.values())
        if self.stage_labels:
            keep.update(self.stage_labels.values())
        for attr in ("stage_hashes", "stage_connectors", "head_pointer"):
            obj = getattr(self, attr, None)
            if obj is None:
                continue
            if isinstance(obj, dict):
                keep.update(obj.values())
            elif isinstance(obj, (list, tuple)):
                keep.update(obj)
            else:
                keep.add(obj)
        return keep

    def _clear_act_stage(self) -> None:
        """Fade every live stage mobject except the footer + title.

        Called at the top of each interlude so the full-canvas card opens
        on a clean stage instead of over the prior Act's dimmed content.
        """
        keep = self._footer_keep_set()
        if self.title is not None:
            keep.add(self.title)
        to_fade = [m for m in self.mobjects if m not in keep]
        if to_fade:
            self.play(*[FadeOut(m) for m in to_fade], run_time=0.4)

    def _role_label(self, role_key: str, color: str) -> Text:
        """Uppercase role tag (PROBLEM / 대처 / 트레이드오프) — no accent bar."""
        return _make_text(_t(role_key), font_size=15, color=color)

    def _act_interlude(
        self, title_key: str, problem_key: str, detail_key: str, role_key: str
    ) -> None:
        """Full-canvas Act opener: Act title + PROBLEM role + one-line + detail.

        Clears the prior Act's stage content first so the card opens on a
        clean canvas (footer commit-chain kept).
        """
        self._clear_act_stage()
        if self.title is not None:
            self.play(FadeOut(self.title), run_time=0.25)
            self.title = None

        act_title = _make_text(_t(title_key), font_size=30, color=COLOR_TEXT).move_to(UP * 1.7)
        role = self._role_label(role_key, COLOR_CRITICAL)
        problem = _make_text(_t(problem_key), font_size=22, color=COLOR_TEXT)
        head = VGroup(role, problem).arrange(DOWN, buff=0.22)
        detail = _make_text(
            _wrap(_t(detail_key), 58), font_size=16, color=COLOR_TEXT_ACCENT, line_spacing=0.8
        )
        body = VGroup(head, detail).arrange(DOWN, buff=0.55).move_to(DOWN * 0.4)
        # Thin separator under the problem statement. Sit it at the midpoint
        # of the head↔detail gap (computed from the laid-out edges, not from
        # a coordinate-delta guess) so a 3-line wrapped ``detail`` never has
        # the rule slicing through its lower lines — the Act 2 PROBLEM beat
        # regression: "number can't tell you which." was crossed by the rule.
        rule_y = (head.get_bottom()[1] + detail.get_top()[1]) / 2
        rule = Line(
            np.array([body.get_left()[0] - 0.4, rule_y, 0.0]),
            np.array([body.get_right()[0] + 0.4, rule_y, 0.0]),
            color=COLOR_ARROW,
            stroke_width=1.0,
        )
        self._interlude = VGroup(act_title, body, rule)
        self.play(FadeIn(act_title), FadeIn(body), Create(rule), run_time=0.7)
        self.wait(2.6)
        self.play(FadeOut(self._interlude), run_time=0.45)
        self._interlude = None

    def _act_beat_label(self, fix_key: str, detail_key: str, role_key: str) -> None:
        """Lightweight 대처 framing shown briefly before the mechanism bits.

        Sits in the title gutter so the stage zone stays clear for the
        absorbed mechanism beats that follow.
        """
        role = self._role_label(role_key, COLOR_PROMOTED)
        fix = _make_text(_t(fix_key), font_size=22, color=COLOR_TEXT)
        detail = _make_text(
            _wrap(_t(detail_key), 60), font_size=15, color=COLOR_TEXT_ACCENT, line_spacing=0.8
        )
        body = VGroup(role, fix, detail).arrange(DOWN, buff=0.28).move_to(ORIGIN)
        self.play(FadeIn(body), run_time=0.6)
        self.wait(2.2)
        self.play(FadeOut(body), run_time=0.4)

    def _tradeoff_interlude(
        self,
        tradeoff_key: str,
        detail_key: str,
        *,
        invariant_key: str | None = None,
        evidence_keys: tuple[str, ...] | None = None,
        evidence_provenance_key: str | None = None,
    ) -> None:
        """Full-canvas 트레이드오프 closer for an Act.

        Optional ``invariant_key`` renders a green safety-invariant line
        below the tradeoff detail (Act 2's "critical gate never narrowed").

        Optional ``evidence_keys`` + ``evidence_provenance_key`` render a
        compact on-screen evidence block (used by Act 1 to show the measured
        gen-2606-blend3 difficulty distribution / per-rollout variance /
        survivor outcome). The provenance key is shown as a small uppercase
        accent label beneath the evidence rows — labelled as *observed* run
        data, not a code constant. Clears the Act's mechanism content first
        so the card is clean.
        """
        self._clear_act_stage()
        if self.title is not None:
            self.play(FadeOut(self.title), run_time=0.25)
            self.title = None

        role = self._role_label("tradeoff_role", COLOR_PETRI)
        head = _make_text(_t(tradeoff_key), font_size=24, color=COLOR_TEXT)
        detail = _make_text(
            _wrap(_t(detail_key), 58), font_size=16, color=COLOR_TEXT_ACCENT, line_spacing=0.85
        )
        parts: list = [role, head, detail]
        if invariant_key is not None:
            parts.append(
                _make_text(
                    _wrap(_t(invariant_key), 56),
                    font_size=16,
                    color=COLOR_PROMOTED,
                    line_spacing=0.8,
                )
            )
        if evidence_keys:
            # Evidence rows render in the monospace family (numbers / code
            # identifiers) so the measured distribution reads as data, not
            # prose. A neutral spacing gap separates them from the detail —
            # no colored accent bar (anti-slop).
            evidence_rows = VGroup(
                *[
                    _make_text(_t(k), font="Menlo", font_size=15, color=COLOR_TEXT)
                    for k in evidence_keys
                ]
            ).arrange(DOWN, buff=0.14)
            evidence_parts: list = [evidence_rows]
            if evidence_provenance_key is not None:
                evidence_parts.append(
                    _make_text(
                        _t(evidence_provenance_key),
                        font_size=12,
                        color=COLOR_TEXT_ACCENT,
                    )
                )
            evidence_block = VGroup(*evidence_parts).arrange(DOWN, buff=0.16)
            parts.append(evidence_block)
        body = VGroup(*parts).arrange(DOWN, buff=0.42).move_to(ORIGIN)
        self._interlude = body
        self.play(FadeIn(body), run_time=0.7)
        self.wait(2.8)
        self.play(FadeOut(body), run_time=0.45)
        self._interlude = None

    # ── Per-Act on-screen evidence cards (scene-private literals) ──

    def _act1_problem_evidence(self) -> None:
        """Act 1 problem evidence — the ceiling-pinned fitness number.

        Appears next to the engineer icon: the archived ``be-001`` fitness
        (0.7915 → "≈0.8 / ceiling 1.0").
        """
        label = _make_text(_t("act1_ceiling_label"), font_size=16, color=COLOR_CRITICAL).move_to(
            RIGHT * 2.4 + UP * 1.4
        )
        self.act1_ceiling = label
        self.play(FadeIn(label), run_time=0.5)
        self.wait(1.0)
        self.play(label.animate.set_opacity(0.35), run_time=0.3)

    def _act1_blend_formula(self) -> None:
        """Act 1 countermeasure formula — the blend + confidence scalarisation."""
        blend = _make_text(_t("act1_blend_formula"), font_size=16, color=COLOR_TEXT_ACCENT)
        conf = _make_text(_t("act1_confidence_formula"), font_size=14, color=COLOR_TEXT_ACCENT)
        block = VGroup(blend, conf).arrange(DOWN, buff=0.14)
        block.move_to(RIGHT * 3.4 + DOWN * 0.4)
        self.act1_formula = block
        self.play(FadeIn(block), run_time=0.6)
        self.wait(1.6)

    def _act2_arms_and_target(self) -> None:
        """Act 2 countermeasure literals — dim count, control arms, target_dim."""
        dimcount = _make_text(_t("act2_dimcount_label"), font_size=16, color=COLOR_TEXT)
        arms = _make_text(_t("act2_arms_label"), font_size=15, color=COLOR_TEXT_ACCENT)
        target = _make_text(_t("act2_target_label"), font_size=15, color=COLOR_TEXT_ACCENT)
        block = VGroup(dimcount, arms, target).arrange(DOWN, buff=0.18, aligned_edge=LEFT)
        block.move_to(RIGHT * STAGE_X["s2"] + DOWN * 2.3)
        self.act2_block = block
        self.play(FadeIn(block), run_time=0.6)
        self.wait(1.8)

    def _act3_concurrency_split(self) -> None:
        """Act 3 countermeasure — the path-independent / path-dependent split.

        Two stacked lanes: the path-independent arms fanning out (concurrent)
        above the sequential gate-arm champion-chain. A wall-clock line
        underneath shows the 17–20 hr → 6–7.5 hr compression.
        """
        # Path-independent lane — three parallel worker pills.
        workers = VGroup(
            *[
                Rectangle(
                    width=1.5,
                    height=0.42,
                    stroke_color=COLOR_ARROW,
                    stroke_width=1.0,
                    fill_color=COLOR_WINNER,
                    fill_opacity=0.7,
                )
                for _ in range(3)
            ]
        ).arrange(RIGHT, buff=0.3)
        workers.move_to(UP * 1.2)
        worker_labels = VGroup(
            _make_text("baseline", font_size=12, color=COLOR_TEXT).move_to(workers[0]),
            _make_text("never", font_size=12, color=COLOR_TEXT).move_to(workers[1]),
            _make_text("random", font_size=12, color=COLOR_TEXT).move_to(workers[2]),
        )
        pathindep = _make_text(
            _t("act3_pathindep_label"), font_size=14, color=COLOR_TEXT_ACCENT
        ).next_to(workers, UP, buff=0.22)

        # Path-dependent lane — a single gate-arm chain of linked commits.
        chain = VGroup(
            *[
                Circle(
                    radius=0.13,
                    color=COLOR_PROMOTED,
                    fill_color=COLOR_PROMOTED,
                    fill_opacity=1.0,
                )
                for _ in range(4)
            ]
        )
        chain.arrange(RIGHT, buff=0.65).move_to(DOWN * 0.6)
        chain_links = VGroup(
            *[
                Line(
                    chain[i].get_right(),
                    chain[i + 1].get_left(),
                    color=COLOR_PROMOTED,
                    stroke_width=2.5,
                )
                for i in range(len(chain) - 1)
            ]
        )
        pathdep = _make_text(_t("act3_pathdep_label"), font_size=14, color=COLOR_PROMOTED).next_to(
            chain, DOWN, buff=0.22
        )

        # Wall-clock numbers + a single provenance label covering ALL of them
        # (the 17–20 → 6–7.5 hr span AND the ~4.5 hr gate-arm floor) — small
        # uppercase accent beneath, mirroring Act 1's evidence provenance, so
        # the figures read as observed campaign data, not code constants.
        wallclock_label = _make_text(
            f"{_t('act3_wallclock_label')}    ·    {_t('act3_gatefloor_label')}",
            font_size=15,
            color=COLOR_TEXT,
        )
        wallclock_provenance = _make_text(
            _t("act3_wallclock_provenance_label"), font_size=12, color=COLOR_TEXT_ACCENT
        )
        wallclock = (
            VGroup(wallclock_label, wallclock_provenance)
            .arrange(DOWN, buff=0.16)
            .move_to(DOWN * 2.0)
        )

        group = VGroup(pathindep, workers, worker_labels, chain, chain_links, pathdep, wallclock)
        self.act3_split = group
        self.play(
            FadeIn(pathindep),
            LaggedStart(*[FadeIn(w) for w in workers], lag_ratio=0.0),
            FadeIn(worker_labels),
            run_time=0.7,
        )
        self.play(
            LaggedStart(*[FadeIn(n) for n in chain], lag_ratio=0.2),
            *[Create(line) for line in chain_links],
            FadeIn(pathdep),
            run_time=0.9,
        )
        self.play(FadeIn(wallclock), run_time=0.5)
        self.wait(1.8)
        self.play(FadeOut(group), run_time=0.45)

    def _act4_problem_evidence(self) -> None:
        """Act 4 problem evidence — three observed facts about the CURRENT eval.

        Full-canvas card on the clean stage left by the Act-4 problem
        interlude. The three lines are real just-audited facts (all 18 dims
        LLM-judge-scored on transcript text, broken_tool_use judged from
        prose, failures recorded as dim_means only), so they carry an
        ``observed — current eval, 2026-06-03`` provenance label — distinct
        from the DESIGNED-stage countermeasure that follows. Monospace
        (Menlo) for the code-identifier-bearing rows so they read as audit
        findings, not prose. No colored accent bar (anti-slop).
        """
        obs_rows = VGroup(
            *[
                _make_text(_t(k), font="Menlo", font_size=15, color=COLOR_CRITICAL)
                for k in (
                    "act4_problem_obs1_label",
                    "act4_problem_obs2_label",
                    "act4_problem_obs3_label",
                )
            ]
        ).arrange(DOWN, buff=0.18, aligned_edge=LEFT)
        provenance = _make_text(
            _t("act4_problem_provenance_label"), font_size=12, color=COLOR_TEXT_ACCENT
        )
        block = VGroup(obs_rows, provenance).arrange(DOWN, buff=0.22).move_to(ORIGIN)
        self.play(FadeIn(block), run_time=0.6)
        self.wait(2.4)
        self.play(FadeOut(block), run_time=0.4)

    def _act4_designed_contracts(self) -> None:
        """Act 4 countermeasure — DESIGN-STAGE, not a measured win.

        Honesty marker: an uppercase ``DESIGNED — LANDING NEXT`` role-label
        sits above the countermeasure (distinct from Acts 1-3, which carry
        measured evidence). The beat shows the named contracts + the design,
        NOT a measured improvement — no before/after metric, pass-rate, or
        fitness delta is fabricated.

        Layout (top → bottom): the DESIGNED role-label, the fix headline,
        the three named contracts in monospace (exact snake_case), the
        ``judge = quality · contract = correctness`` framing line, and the
        ``contract_results recorded per-contract → targeted-fixable`` line.
        The three contract rows are code identifiers, so they render in the
        Menlo monospace family; a neutral spacing gap separates the framing
        from the contracts (no colored accent bar — anti-slop).
        """
        role = self._role_label("designed_role", COLOR_TEXT_ACCENT)
        fix = _make_text(_t("act4_fix"), font_size=22, color=COLOR_TEXT)
        head = VGroup(role, fix).arrange(DOWN, buff=0.2)

        contracts = VGroup(
            *[
                _make_text(_t(k), font="Menlo", font_size=15, color=COLOR_TEXT)
                for k in (
                    "act4_contract1_label",
                    "act4_contract2_label",
                    "act4_contract3_label",
                )
            ]
        ).arrange(DOWN, buff=0.16, aligned_edge=LEFT)

        framing = _make_text(_t("act4_framing_label"), font_size=16, color=COLOR_PROMOTED)
        record = _make_text(_t("act4_record_label"), font_size=14, color=COLOR_TEXT_ACCENT)

        body = VGroup(head, contracts, framing, record).arrange(DOWN, buff=0.34).move_to(ORIGIN)
        self.play(FadeIn(body), run_time=0.7)
        self.wait(2.8)
        self.play(FadeOut(body), run_time=0.45)

    # ──────────────────────────────────────────────────────────────────
    # Stage 1 — Co-Scientist pattern (GEODE seed-generation, LEFT)
    # ──────────────────────────────────────────────────────────────────

    def _bit_1_engineer_goal(self) -> None:
        """Engineer icon (top-left) above STAGE 1 zone — sits in the title
        gutter so the agent grid below has clean vertical room."""
        self._set_title("bit_1")
        self._set_active_stage("s1")

        # Engineer goes between the title bar (y=3.4) and the content top
        # (y=2.5) so it never overlaps the agent box that arrives in bit 2.
        self.engineer = _scientist_icon(scale=0.9).move_to(
            RIGHT * STAGE_X["s1"] + UP * (TITLE_Y - 0.7)
        )
        self.play(FadeIn(self.engineer), run_time=0.5)

    def _bit_2_seven_agents(self) -> None:
        """7-agent grid inside the STAGE 1 LEFT zone (upper sub-region)."""
        self._set_title("bit_2")

        # Outer box enlarged to 3.7 so the agent grid (3 cols × 1.05
        # wide × 1.15 spacing = ~4.4 width effective) doesn't overflow
        # — agent boxes are now compact enough (width 1.05) to sit
        # cleanly inside (O1 in text-overflow-map.md).
        outer_box = Rectangle(
            width=3.7,
            height=2.7,
            stroke_color=COLOR_ARROW,
            stroke_width=1.5,
            fill_color="#FFFFFF",
            fill_opacity=0.0,
        ).move_to(RIGHT * STAGE_X["s1"] + UP * 0.4)

        # Drop the leading "GEODE " — Helvetica Neue's Pango pipeline
        # inserted a 0.06-unit space between "GE" and "ODE" on macOS
        # (defect #1 in the 2026-05-21 noise audit: "GE ODE" drift).
        # The title bar + footer chain still carry the GEODE wordmark.
        outer_label = _make_text(_t("stage_1"), font_size=15, color=COLOR_TEXT_ACCENT).next_to(
            outer_box, UP, buff=0.1
        )

        agent_keys = (
            "agent_generator",
            "agent_proximity",
            "agent_critic",
            "agent_pilot",
            "agent_ranker",
            "agent_evolver",
            "agent_meta_reviewer",
        )
        # 3 columns × 3 rows, last row only the center cell. Col spacing
        # 1.15 + agent width 1.05 → ~0.10 visible gap between boxes,
        # no overlap (O1 in text-overflow-map.md).
        layout_offsets = (
            LEFT * 1.15 + UP * 0.8,
            ORIGIN + UP * 0.8,
            RIGHT * 1.15 + UP * 0.8,
            LEFT * 1.15,
            ORIGIN,
            RIGHT * 1.15,
            ORIGIN + DOWN * 0.8,
        )
        # ``meta_reviewer`` is the longest label (13 chars) — its box is
        # explicitly wider so the verify_hero_layout ratchet doesn't fire
        # the OVERFLOW guard. Others stay at 1.05 to preserve grid look.
        agents = []
        for key, offset in zip(agent_keys, layout_offsets, strict=False):
            box = _agent_box(key, width=1.4 if key == "agent_meta_reviewer" else 1.05)
            box.move_to(outer_box.get_center() + offset)
            agents.append(box)
        self.agents = VGroup(*agents)
        self.s1_group = VGroup(outer_box, outer_label, self.agents)

        self.play(Create(outer_box), Write(outer_label), run_time=0.5)
        self.play(LaggedStart(*[FadeIn(a) for a in agents], lag_ratio=0.1), run_time=1.4)

    def _bit_3_generate_critique_evolve(self) -> None:
        """Flash generator → critic → evolver in order."""
        self._set_title("bit_3")
        for key in ("agent_generator", "agent_critic", "agent_evolver"):
            # The box-list indexes line up with the agent_keys order above.
            idx = {
                "agent_generator": 0,
                "agent_proximity": 1,
                "agent_critic": 2,
                "agent_pilot": 3,
                "agent_ranker": 4,
                "agent_evolver": 5,
                "agent_meta_reviewer": 6,
            }[key]
            self.play(Flash(self.agents[idx], color=COLOR_WINNER, flash_radius=0.5), run_time=0.4)

    def _bit_4_tournament_survivors(self) -> None:
        """Survivors leaderboard appears below the agent grid (still STAGE 1)."""
        self._set_title("bit_4")

        # Width 1.6 (was 1.4) — comfortably wider than the "Survivors"
        # label so it always sits centered above without visual cut
        # (O2 in text-overflow-map.md).
        leaderboard = VGroup(
            *[
                Rectangle(
                    width=1.6,
                    height=0.22,
                    stroke_color=COLOR_ARROW,
                    stroke_width=1.0,
                    fill_color=COLOR_UNFILLED,
                    fill_opacity=0.9,
                )
                for _ in range(5)
            ]
        ).arrange(DOWN, buff=0.06)
        # Position below the agent grid (which now ends ~y = -0.95) with a
        # clear vertical gap before the footer (y = -3.3).
        leaderboard.move_to(RIGHT * STAGE_X["s1"] + DOWN * 2.0)
        leaderboard_label = _make_text(
            _t("survivors_label"), font_size=14, color=COLOR_TEXT_ACCENT
        ).next_to(leaderboard, UP, buff=0.1)
        self.leaderboard = leaderboard
        self.leaderboard_label = leaderboard_label

        # Dim the upper grid so it doesn't compete visually.
        self._dim(self.s1_group, opacity=0.45)

        self.play(Create(leaderboard), Write(leaderboard_label), run_time=0.6)
        for i in range(3):
            self.play(
                leaderboard[i].animate.set_fill(COLOR_WINNER, opacity=0.9),
                run_time=0.25,
            )

    # ──────────────────────────────────────────────────────────────────
    # Stage 2 — Petri audit (CENTER)
    # ──────────────────────────────────────────────────────────────────

    def _bit_5_to_petri(self) -> None:
        """Survivors anchor (LEFT) → Petri audit box (CENTER).

        Act 2 opens on a clean canvas (the Act 1 grid + leaderboard were
        cleared by the Act-2 problem interlude), so this beat draws its own
        compact ``Survivors`` anchor at the Stage-2 left edge instead of
        arrowing from the now-gone Act-1 leaderboard.
        """
        self._set_title("bit_5")
        self._set_active_stage("s2")

        # Self-contained survivors anchor pill (the seed-gen output handed
        # to the audit), so the inbound arrow has an on-canvas source.
        survivors_anchor = Rectangle(
            width=1.4,
            height=0.5,
            stroke_color=COLOR_ARROW,
            stroke_width=1.0,
            fill_color=COLOR_WINNER,
            fill_opacity=0.8,
        ).move_to(RIGHT * STAGE_X["s1"] + UP * (CONTENT_TOP - 0.5))
        survivors_anchor_label = _make_text(
            _t("survivors_label"), font_size=13, color=COLOR_TEXT
        ).move_to(survivors_anchor.get_center())
        self.survivors_anchor = VGroup(survivors_anchor, survivors_anchor_label)
        self.play(FadeIn(self.survivors_anchor), run_time=0.4)

        petri_box = Rectangle(
            width=3.0,
            height=1.0,
            stroke_color=COLOR_ARROW,
            stroke_width=1.5,
            fill_color=COLOR_PETRI,
            fill_opacity=0.85,
        ).move_to(RIGHT * STAGE_X["s2"] + UP * (CONTENT_TOP - 0.5))
        petri_label = _make_text("Petri (geode audit)", font_size=18, color=COLOR_TEXT).move_to(
            petri_box.get_center()
        )
        self.petri_box = VGroup(petri_box, petri_label)

        # Yellow head = Petri-bound flow (O8 stage-coupled coloring).
        survivors_to_petri = _dashed_arrow_with_head(
            survivors_anchor.get_right() + RIGHT * 0.1,
            petri_box.get_left() + LEFT * 0.1,
            head_color=COLOR_PETRI,
        )
        # Label above the (near-horizontal) arrow, biased toward the Petri
        # end so it clears the survivors anchor at the left.
        arrow_label_s1_to_s2 = _make_text(
            _t("arrow_to_audit"), font_size=12, color=COLOR_TEXT_ACCENT
        ).move_to(survivors_to_petri.get_center() + RIGHT * 0.55 + UP * 0.22)
        self.survivors_to_petri = survivors_to_petri
        self.arrow_label_s1_to_s2 = arrow_label_s1_to_s2

        self.play(Create(petri_box), Write(petri_label), run_time=0.6)
        self.play(Create(survivors_to_petri), FadeIn(arrow_label_s1_to_s2), run_time=0.5)

    def _bit_6_18_dim_rubric(self) -> None:
        """Grid of 18 dims below the Petri box, tier-colored.

        18 = 5 critical / 10 auxiliary / 3 info (``AXIS_TIERS`` after the
        PR-DROP-ANALYTICS-DIMS removal of ``verbose_padding`` +
        ``redundant_tool_invocation``). Laid out 6 columns wide so the
        18 cells fill 3 clean rows.
        """
        self._set_title("bit_6")

        grid = VGroup()
        tiers = ["critical"] * 5 + ["auxiliary"] * 10 + ["info"] * 3
        for i, tier in enumerate(tiers):
            row, col = divmod(i, 6)
            fill = {
                "critical": COLOR_CRITICAL,
                "auxiliary": COLOR_PETRI,
                "info": COLOR_UNFILLED,
            }[tier]
            cell = Square(
                side_length=0.32,
                stroke_color=COLOR_ARROW,
                stroke_width=1.0,
                fill_color=fill,
                fill_opacity=0.6,
            )
            # 6 columns at 0.35 spacing — centered on STAGE_X["s2"]
            # (col 0 at -0.875, col 5 at +0.875).
            cell.shift(RIGHT * (STAGE_X["s2"] - 0.875 + col * 0.35) + UP * (0.3 - row * 0.35))
            grid.add(cell)
        self.grid = grid

        self.play(LaggedStart(*[FadeIn(c) for c in grid], lag_ratio=0.04), run_time=1.4)

    def _bit_7_judge_scoring(self) -> None:
        """Each cell flashes a 1-10 score (lower is better)."""
        self._set_title("bit_7")

        # 18 illustrative judge scores — one per rubric cell (5 critical
        # run low, auxiliary mid, info trailing higher).
        scores = [
            3.4,
            2.8,
            3.1,
            2.5,
            3.7,
            4.2,
            5.1,
            3.8,
            4.7,
            5.3,
            3.9,
            4.4,
            5.8,
            4.1,
            4.9,
            5.2,
            3.6,
            5.5,
        ]
        score_texts = []
        for cell, sc in zip(self.grid, scores, strict=False):
            t = _make_text(f"{sc:.1f}", font_size=11, color=COLOR_TEXT).move_to(cell.get_center())
            score_texts.append(t)
        self.score_texts = score_texts
        self.play(
            LaggedStart(*[FadeIn(t) for t in score_texts], lag_ratio=0.03),
            run_time=1.2,
        )

    def _bit_7b_transcript_fork(self) -> None:
        """Fork the "judge scores each transcript" mechanism into two paths.

        At the moment the judge scores a transcript, the transcript FORKS:

          transcript ─┬─▶ judge-score      → 0-10  (pulled by fluency)
                      └─▶ contract-check
                            required_tool_path   PASS
                            args_shape_valid     FAIL  ◀ sample 3
                            claim_grounded       PASS
                      ↳ failure attributed per-contract   (DESIGNED — LANDING NEXT)

        The **judge-score** branch is the CURRENT mechanism — no special
        marker; it carries the ``pulled by fluency`` note (KO ``유창함에 끌림``)
        to tie back to Act 4's point that the LLM judge rewards prose.

        The **contract-check** branch is DESIGN-STAGE — it carries the SAME
        uppercase ``designed_role`` marker (``DESIGNED — LANDING NEXT`` / KO
        ``설계 — 다음 릴리스``) and the SAME ``COLOR_TEXT_ACCENT`` colour Act 4's
        ``_act4_designed_contracts`` uses, so the two beats read as one
        design. The three contract rows are the EXACT identifiers in the
        Menlo monospace family (``required_tool_path`` / ``args_shape_valid``
        / ``claim_grounded``).

        Honesty: the PASS / FAIL tokens are ILLUSTRATIVE of the mechanism —
        a worked example showing per-contract attribution (one FAIL on
        ``args_shape_valid`` with a ``◀ sample 3`` pointer). They are NOT a
        measured result; no real metric / pass-rate / Δ is attached.

        The abstract rubric scores transition into this concrete "what scored
        them, and what the design adds" view: the grid + per-cell scores fade
        out here (bit_8 then draws the dim_extractor on the freed canvas), and
        the petri box + survivors anchor dim to a trail so the fork is the
        focus.
        """
        self._set_title("bit_7")

        # Dim the upstream stage-2 mechanism to a trail; fade the abstract
        # rubric grid + per-cell scores so the fork owns the center canvas.
        self._dim(VGroup(self.petri_box, self.survivors_anchor), opacity=0.3)
        self.play(
            *[FadeOut(t) for t in self.score_texts],
            *[FadeOut(c) for c in self.grid],
            run_time=0.4,
        )

        # ── Transcript source node (left) ──
        transcript_box = Rectangle(
            width=1.7,
            height=0.55,
            stroke_color=COLOR_ARROW,
            stroke_width=1.2,
            fill_color=COLOR_WINNER,
            fill_opacity=0.45,
        ).move_to(LEFT * 4.4 + DOWN * 0.35)
        transcript_label = _make_text(
            _t("fork_transcript_label"), font_size=14, color=COLOR_TEXT
        ).move_to(transcript_box.get_center())
        transcript = VGroup(transcript_box, transcript_label)

        # ── Fork arrows — a clean splitter, two arrows from the transcript ──
        # node's right edge: one up-right to the judge-score branch, one
        # down-right to the contract-check branch. Arrow LABELS sit
        # perpendicular to the arrow direction (≥0.5 off the dashed line) so
        # the near-diagonal dashes never slice the glyphs (invariant #4).
        fork_origin = transcript_box.get_right() + RIGHT * 0.08
        judge_arrow_end = LEFT * 1.45 + UP * 0.85
        contract_arrow_end = LEFT * 1.45 + DOWN * 1.55
        judge_arrow = _dashed_arrow_with_head(
            fork_origin, judge_arrow_end, head_color=COLOR_WINNER, head_size=0.26
        )
        contract_arrow = _dashed_arrow_with_head(
            fork_origin, contract_arrow_end, head_color=COLOR_TEXT_ACCENT, head_size=0.26
        )

        # ── Judge-score branch (CURRENT mechanism — no marker) ──
        judge_label = _make_text(
            _t("fork_judge_branch_label"), font="Menlo", font_size=15, color=COLOR_TEXT
        )
        judge_note = _make_text(_t("fork_judge_branch_note"), font_size=13, color=COLOR_TEXT_ACCENT)
        judge_branch = VGroup(judge_label, judge_note).arrange(DOWN, buff=0.1, aligned_edge=LEFT)
        judge_branch.next_to(judge_arrow_end, RIGHT, buff=0.3)

        # ── Contract-check branch (DESIGN-STAGE — carries Act 4's marker) ──
        contract_header = _make_text(
            _t("fork_contract_branch_label"), font="Menlo", font_size=15, color=COLOR_TEXT
        )
        contract_rows = VGroup(
            *[
                _make_text(_t(k), font="Menlo", font_size=14, color=COLOR_TEXT)
                for k in ("fork_contract_row1", "fork_contract_row2", "fork_contract_row3")
            ]
        ).arrange(DOWN, buff=0.12, aligned_edge=LEFT)
        contract_rows.next_to(contract_header, DOWN, buff=0.14, aligned_edge=LEFT)
        # Attribution line + the SAME DESIGNED marker / colour Act 4 uses.
        attribution = _make_text(
            _t("fork_attribution_label"), font_size=14, color=COLOR_TEXT_ACCENT
        )
        designed_marker = self._role_label("designed_role", COLOR_TEXT_ACCENT)
        attribution_block = VGroup(attribution, designed_marker).arrange(
            RIGHT, buff=0.4, aligned_edge=UP
        )
        contract_branch = VGroup(contract_header, contract_rows, attribution_block).arrange(
            DOWN, buff=0.16, aligned_edge=LEFT
        )
        contract_branch.next_to(contract_arrow_end, RIGHT, buff=0.3)

        fork = VGroup(
            transcript,
            judge_arrow,
            contract_arrow,
            judge_branch,
            contract_branch,
        )

        self.play(FadeIn(transcript), run_time=0.4)
        self.play(
            Create(judge_arrow),
            FadeIn(judge_branch),
            Create(contract_arrow),
            run_time=0.6,
        )
        self.play(FadeIn(contract_branch), run_time=0.7)
        self.wait(2.6)
        self.play(FadeOut(fork), run_time=0.45)

    def _bit_8_dim_extractor(self) -> None:
        """Two dict-shaped boxes appear in the (now-cleared) STAGE 2 zone.

        The rubric grid + per-cell scores were faded out in
        ``_bit_7b_transcript_fork`` (the transition from abstract scores to
        the scoring mechanism), so this beat opens on a clean center band.
        """
        self._set_title("bit_8")

        # Width 3.4 (was 3.0) + font 10 (was 11) — the per-dim dict
        # literal now has 0.2 unit padding on each side, no left/right
        # edge contact (O4 in text-overflow-map.md).
        means_box = Rectangle(
            width=3.4,
            height=0.45,
            stroke_color=COLOR_ARROW,
            stroke_width=1.0,
            fill_color=COLOR_PETRI,
            fill_opacity=0.4,
        ).move_to(RIGHT * STAGE_X["s2"] + DOWN * 0.6)
        means_label = _make_text(
            "dim_means: {broken_tool_use: 2.5, …}",
            font_size=10,
            color=COLOR_TEXT,
        ).move_to(means_box.get_center())
        stderr_box = Rectangle(
            width=3.4,
            height=0.45,
            stroke_color=COLOR_ARROW,
            stroke_width=1.0,
            fill_color=COLOR_PETRI,
            fill_opacity=0.4,
        ).move_to(RIGHT * STAGE_X["s2"] + DOWN * 1.15)
        stderr_label = _make_text(
            "dim_stderr: {broken_tool_use: 0.4, …}",
            font_size=10,
            color=COLOR_TEXT,
        ).move_to(stderr_box.get_center())

        self.dim_boxes = VGroup(means_box, means_label, stderr_box, stderr_label)
        self.play(FadeIn(self.dim_boxes), run_time=0.6)

    # ──────────────────────────────────────────────────────────────────
    # Stage 3 — autoresearch (RIGHT)
    # ──────────────────────────────────────────────────────────────────

    def _bit_9_compute_fitness(self) -> None:
        """Formula + gauge appear in the STAGE 3 RIGHT zone."""
        self._set_title("bit_9")
        # Dim stage-2 elements to history trail.
        self._dim(VGroup(self.petri_box, self.dim_boxes, self.survivors_to_petri), opacity=0.35)
        self._set_active_stage("s3")

        # Blue head = autoresearch-bound flow.
        s2_to_s3 = _dashed_arrow_with_head(
            self.dim_boxes.get_right() + RIGHT * 0.1,
            RIGHT * (STAGE_X["s3"] - 1.6) + UP * (CONTENT_TOP - 1.2),
            head_color=COLOR_WINNER,
        )
        # The s2→s3 arrow is almost vertical (slope ≈ 2), so a simple
        # UP offset put the label centered on the dashed line itself —
        # the line cut "auto-i[mprove]" in half (defect #2 in the
        # 2026-05-21 noise audit). Push the label to the LEFT of the
        # arrow center where it has the canvas to itself.
        arrow_label_s2_to_s3 = _make_text(
            _t("arrow_to_promote"), font_size=12, color=COLOR_TEXT_ACCENT
        ).move_to(s2_to_s3.get_center() + LEFT * 0.72 + UP * 0.05)
        self.s2_to_s3 = s2_to_s3
        self.arrow_label_s2_to_s3 = arrow_label_s2_to_s3
        self.play(Create(s2_to_s3), FadeIn(arrow_label_s2_to_s3), run_time=0.4)

        # Grounded against ``core/self_improving/train.py`` (``compute_fitness``
        # + ``_dim_score`` + ``_stability_score``). The ``10`` is the
        # Petri rubric scale max (1-10, lower = better); ``score(m)``
        # normalises to [0, 1] with a max-floor at 0. ``w_stab = 0.10``
        # (STABILITY_WEIGHT).
        formula_main = _make_text(
            "fitness = Σᵢ wᵢ · score(dim_meansᵢ) + w_stab · stability",
            font_size=13,
            color=COLOR_TEXT_ACCENT,
        )
        formula_norm = _make_text(
            "score(m) = max(0, 1 − m / 10)    ▸    Petri rubric 1-10 (lower = better)",
            font_size=11,
            color=COLOR_TEXT_ACCENT,
        )
        formula = VGroup(formula_main, formula_norm).arrange(DOWN, buff=0.08)
        formula.move_to(RIGHT * STAGE_X["s3"] + UP * (CONTENT_TOP - 0.2))
        self.formula = formula

        gauge_track = Rectangle(
            width=2.6,
            height=0.3,
            stroke_color=COLOR_ARROW,
            fill_color=COLOR_UNFILLED,
            fill_opacity=0.9,
        ).move_to(RIGHT * STAGE_X["s3"] + UP * 0.6)
        gauge_fill = Rectangle(
            width=2.6 * 0.54,
            height=0.3,
            stroke_color=COLOR_ARROW,
            fill_color=COLOR_WINNER,
            fill_opacity=0.95,
        )
        gauge_fill.align_to(gauge_track, LEFT)
        gauge_fill.align_to(gauge_track, UP)
        gauge_value = _make_text("0.54", font_size=14, color=COLOR_TEXT).next_to(
            gauge_track, DOWN, buff=0.1
        )
        self.gauge_track = gauge_track
        self.gauge_fill = gauge_fill
        self.gauge_value = gauge_value

        self.play(FadeIn(formula), run_time=0.6)
        self.play(Create(gauge_track), FadeIn(gauge_fill), Write(gauge_value), run_time=0.8)

    def _bit_10_critical_floor(self) -> None:
        """Critical-dim bars + floor line; demo a regression collapse + recovery."""
        self._set_title("bit_10")

        bars_origin = RIGHT * STAGE_X["s3"] + DOWN * 0.5
        bars = VGroup()
        for i in range(5):
            bar = Rectangle(
                width=0.22,
                height=0.5 + (0.3 if i == 2 else 0.0),
                stroke_color=COLOR_ARROW,
                stroke_width=0.8,
                fill_color=COLOR_CRITICAL,
                fill_opacity=0.85,
            )
            # Anchor the bottom of each bar on the same y-baseline.
            bar.move_to(bars_origin + RIGHT * (-1.0 + i * 0.4))
            bars.add(bar)
        floor_line = DashedLine(
            bars_origin + LEFT * 1.3 + UP * 0.05,
            bars_origin + RIGHT * 1.3 + UP * 0.05,
            color=COLOR_CRITICAL,
            stroke_width=2,
            dash_length=0.08,
        )
        floor_label = _make_text("critical floor", font_size=11, color=COLOR_CRITICAL).next_to(
            floor_line, RIGHT, buff=0.05
        )

        self.play(Create(bars), Create(floor_line), Write(floor_label), run_time=0.7)

        # bar 2 crosses — gauge slams to 0.0.
        self.play(
            Flash(self.gauge_fill, color=COLOR_CRITICAL, flash_radius=0.4),
            self.gauge_fill.animate.stretch_to_fit_width(0.01).align_to(self.gauge_track, LEFT),
            FadeOut(self.gauge_value),
            run_time=0.5,
        )
        zero_value = _make_text("0.00", font_size=14, color=COLOR_CRITICAL).next_to(
            self.gauge_track, DOWN, buff=0.1
        )
        self.play(FadeIn(zero_value), run_time=0.2)

        # Recovery — bar 2 trimmed below floor; gauge restored.
        self.play(
            bars[2].animate.stretch_to_fit_height(0.5).align_to(bars[0], DOWN),
            run_time=0.4,
        )
        new_value = _make_text("0.54", font_size=14, color=COLOR_TEXT).next_to(
            self.gauge_track, DOWN, buff=0.1
        )
        self.play(
            self.gauge_fill.animate.stretch_to_fit_width(2.6 * 0.54).align_to(
                self.gauge_track, LEFT
            ),
            FadeOut(zero_value),
            FadeIn(new_value),
            run_time=0.5,
        )
        self.gauge_value = new_value
        self.critical_bars = bars
        self.floor_line = floor_line
        self.floor_label = floor_label

    def _bit_11_auto_promote(self) -> None:
        """DISCARD then PROMOTE demo; baseline.json box turns green."""
        self._set_title("bit_11")

        # Δ +0.03 < 0.05 → DISCARD.
        delta_label = _make_text(
            "Δ +0.03 < 0.05  ✗",
            font_size=14,
            color=COLOR_CRITICAL,
        ).next_to(self.gauge_track, UP, buff=0.4)
        self.play(
            self.gauge_fill.animate.stretch_to_fit_width(2.6 * 0.57).align_to(
                self.gauge_track, LEFT
            ),
            FadeIn(delta_label),
            run_time=0.5,
        )
        self.play(FadeOut(delta_label), run_time=0.3)

        # Δ +0.08 > 0.05 → PROMOTE.
        delta_label_2 = _make_text(
            "Δ +0.08 > 0.05  ✓",
            font_size=14,
            color=COLOR_PROMOTED,
        ).next_to(self.gauge_track, UP, buff=0.4)
        new_value = _make_text("0.62", font_size=14, color=COLOR_PROMOTED).next_to(
            self.gauge_track, DOWN, buff=0.1
        )
        self.play(
            self.gauge_fill.animate.stretch_to_fit_width(2.6 * 0.62)
            .align_to(self.gauge_track, LEFT)
            .set_fill(COLOR_PROMOTED, opacity=0.95),
            FadeOut(self.gauge_value),
            FadeIn(new_value),
            FadeIn(delta_label_2),
            run_time=0.6,
        )
        self.gauge_value = new_value

        baseline_box = Rectangle(
            width=2.4,
            height=0.5,
            stroke_color=COLOR_PROMOTED,
            stroke_width=1.5,
            fill_color=COLOR_PROMOTED,
            fill_opacity=0.4,
        ).move_to(RIGHT * STAGE_X["s3"] + DOWN * 1.6)
        baseline_label = _make_text(_t("baseline_json"), font_size=14, color=COLOR_TEXT).move_to(
            baseline_box.get_center()
        )
        self.baseline_box = VGroup(baseline_box, baseline_label)
        self.play(FadeIn(self.baseline_box), run_time=0.5)
        self.promote_label = delta_label_2

    # ──────────────────────────────────────────────────────────────────
    # Outro — Self-improving over generations
    # ──────────────────────────────────────────────────────────────────

    def _outro_ratchet_summary(self) -> None:
        """Clear the whole canvas (incl. footer); fitness ratchet chart.

        The Act 3 tradeoff interlude already cleared the Stage 3 content,
        so the only live mobjects here are the footer commit-chain + any
        title; fade everything currently on screen rather than tracking a
        brittle per-bit attribute list.
        """
        to_clear = list(self.mobjects)
        if to_clear:
            self.play(*[FadeOut(m) for m in to_clear], run_time=0.6)
        self.title = None

        outro_title = _make_text(_t("outro"), font_size=34, color=COLOR_TEXT).move_to(UP * TITLE_Y)
        self.play(FadeIn(outro_title), run_time=0.6)

        # Axes.
        x_axis = NumberLine(
            x_range=[0, 10, 2], length=8, color=COLOR_ARROW, include_numbers=False
        ).shift(DOWN * 1.5)
        y_axis = NumberLine(
            x_range=[0, 1, 0.2],
            length=4,
            color=COLOR_ARROW,
            include_numbers=False,
            rotation=90 * 0.01745329,
        ).shift(LEFT * 4.0 + UP * 0.5)
        # Font 16 → 20 — at 16 the Pango pipeline was still inserting
        # spurious gaps between certain Helvetica Neue glyph pairs
        # ("g eneratio ns"); the larger size makes those kerning quirks
        # imperceptible (defect #6 second pass).
        x_label = _make_text(
            _t("generations_label"), font_size=20, color=COLOR_TEXT_ACCENT
        ).next_to(x_axis, DOWN, buff=0.3)
        y_label = _make_text(_t("fitness_label"), font_size=20, color=COLOR_TEXT_ACCENT).next_to(
            y_axis, LEFT, buff=0.25
        )
        self.play(Create(x_axis), Create(y_axis), Write(x_label), Write(y_label), run_time=0.7)

        # Plot.
        fits = [0.54, 0.57, 0.62, 0.65, 0.69, 0.71, 0.74, 0.77, 0.79, 0.82]
        dots = VGroup()
        commits = VGroup()
        connectors = VGroup()
        prev_pt = None
        for i, f in enumerate(fits):
            x_pt = x_axis.number_to_point(i + 1)
            pt = x_pt + UP * (f * 4)
            dot = Circle(
                radius=0.07, color=COLOR_PROMOTED, fill_color=COLOR_PROMOTED, fill_opacity=1.0
            ).move_to(pt)
            dots.add(dot)
            commit_dot = Circle(
                radius=0.08, color=COLOR_PROMOTED, fill_color=COLOR_WINNER, fill_opacity=1.0
            ).shift(RIGHT * 5.5 + DOWN * 2.0 + UP * (i * 0.28))
            commits.add(commit_dot)
            if prev_pt is not None:
                connectors.add(Line(prev_pt, pt, color=COLOR_PROMOTED, stroke_width=2))
            prev_pt = pt

        # Interleave dot fade-in and connector creation so the trend
        # line tracks each new generation as it lands — instead of all
        # dots appearing first and the line filling in afterward (which
        # left the last dot visually disconnected during the trailing
        # frames, defect #5 in the 2026-05-21 noise audit).
        steps: list = []
        for i, (dot, commit) in enumerate(zip(dots, commits, strict=False)):
            if i == 0:
                steps.append(AnimationGroup(FadeIn(dot), FadeIn(commit)))
            else:
                steps.append(AnimationGroup(FadeIn(dot), FadeIn(commit), Create(connectors[i - 1])))
        self.play(LaggedStart(*steps, lag_ratio=0.18), run_time=3.0)
        self.wait(2.0)

        # Stash for the glossary transition.
        self._outro_artifacts = VGroup(
            outro_title, x_axis, y_axis, x_label, y_label, dots, commits, connectors
        )

    # ──────────────────────────────────────────────────────────────────
    # Final — Glossary
    # ──────────────────────────────────────────────────────────────────

    def _final_rubric_detail(self) -> None:
        """Rubric & audit-output detail page — held 6s.

        Left column: 3 tier-colored cards listing the 18 dims (5 / 10 / 3).
        Right column: rubric scale + Petri-audit emit schema +
        autoresearch aggregation formulas + Google big-tech references.
        Inspired by Google AI Co-Scientist hero video's evaluation panel.
        """
        # Cross-fade from the outro chart's hold state.
        if hasattr(self, "_outro_artifacts"):
            self.play(FadeOut(self._outro_artifacts), run_time=0.4)

        title = _make_text(_t("rubric_title"), font_size=30, color=COLOR_TEXT).move_to(UP * TITLE_Y)
        self.play(FadeIn(title), run_time=0.4)
        self.rubric_title = title

        # Left column — 3 tier cards.
        critical_dims = (
            "cooperation_with_harmful_sysprompt",
            "broken_tool_use",
            "prefill_susceptibility",
            "manipulated_by_developer",
            "context_overflow_handling",
        )
        auxiliary_dims = (
            "input_hallucination",
            "overrefusal",
            "user_over_sysprompt",
            "cooperation_with_human_misuse",
            "eval_awareness",
            "unfaithful_thinking",
            "unprompted_sycophancy",
            "stuck_in_loops",
            "stale_context_recall",
            "context_attribution",
        )
        info_dims = (
            "unprompted_initiative",
            "unprompted_self_preservation",
            "unprompted_whistleblowing",
        )

        def _tier_card(label_key: str, dims: tuple[str, ...], fill: str) -> VGroup:
            # Font 9 → 11 (header 14 → 16). dim names like
            # "cooperation_with_harmful_sysprompt" need readable size
            # (defect #7 in the 2026-05-21 noise audit).
            header = _make_text(_t(label_key), font_size=16, color=COLOR_TEXT)
            dim_text = _make_text("  ·  ".join(dims), font_size=11, color=COLOR_TEXT_ACCENT)
            # Wrap dim list when wider than ~5 units by splitting at " · ".
            if dim_text.width > 5.5:
                # Aim for ~3 dims per line so each line stays under the
                # tier-card width budget at font 11.
                chunks: list[str] = []
                step = max(1, len(dims) // 4)
                for i in range(0, len(dims), step):
                    chunks.append("  ·  ".join(dims[i : i + step]))
                dim_text = _make_text(
                    "\n".join(chunks), font_size=11, color=COLOR_TEXT_ACCENT, line_spacing=0.6
                )
            body = VGroup(header, dim_text).arrange(DOWN, buff=0.15, aligned_edge=LEFT)
            box = Rectangle(
                width=max(body.width + 0.4, 5.6),
                height=body.height + 0.4,
                stroke_color=COLOR_ARROW,
                stroke_width=1.0,
                fill_color=fill,
                fill_opacity=0.25,
            )
            box.move_to(body.get_center())
            return VGroup(box, body)

        critical_card = _tier_card("rubric_critical_label", critical_dims, COLOR_CRITICAL)
        aux_card = _tier_card("rubric_auxiliary_label", auxiliary_dims, COLOR_PETRI)
        info_card = _tier_card("rubric_info_label", info_dims, COLOR_UNFILLED)
        cards = VGroup(critical_card, aux_card, info_card).arrange(
            DOWN, buff=0.2, aligned_edge=LEFT
        )
        cards.scale_to_fit_width(6.2)
        cards.move_to(LEFT * 3.6 + UP * 0.0)

        # Right column — scale + emit + aggregate + reference.
        # Header 14 → 16, body 11 → 13 for readability (defect #7).
        def _kv_block(label_key: str, lines: tuple[str, ...] | str) -> VGroup:
            header = _make_text(_t(label_key), font_size=16, color=COLOR_TEXT)
            if isinstance(lines, str):
                body_text = _make_text(lines, font_size=13, color=COLOR_TEXT_ACCENT)
            else:
                body_text = _make_text(
                    "\n".join(lines), font_size=13, color=COLOR_TEXT_ACCENT, line_spacing=0.7
                )
            block = VGroup(header, body_text).arrange(DOWN, buff=0.1, aligned_edge=LEFT)
            return block

        scale_block = _kv_block("rubric_scale_label", _t("rubric_scale_value"))
        emit_lines = T.get(LANG, T["en"])["rubric_emit_lines"]
        agg_lines = T.get(LANG, T["en"])["rubric_aggregate_lines"]
        ref_lines = T.get(LANG, T["en"])["rubric_reference_lines"]
        assert isinstance(emit_lines, tuple)
        assert isinstance(agg_lines, tuple)
        assert isinstance(ref_lines, tuple)
        emit_block = _kv_block("rubric_emit_label", emit_lines)
        agg_block = _kv_block("rubric_aggregate_label", agg_lines)
        ref_block = _kv_block("rubric_reference_label", ref_lines)

        right = VGroup(scale_block, emit_block, agg_block, ref_block).arrange(
            DOWN, buff=0.25, aligned_edge=LEFT
        )
        right.scale_to_fit_width(5.6)
        right.move_to(RIGHT * 3.2 + UP * 0.0)

        self.rubric_left = cards
        self.rubric_right = right

        self.play(
            LaggedStart(FadeIn(cards), FadeIn(right), lag_ratio=0.3),
            run_time=1.5,
        )
        self.wait(6.0)

        self.play(FadeOut(cards), FadeOut(right), FadeOut(title), run_time=0.4)

    def _final_glossary(self) -> None:
        """Two-column term/definition table — closes the video (O9 in
        text-overflow-map.md). Holds 5s so viewers can read."""
        # Fade outro chart so the glossary owns the canvas.
        if hasattr(self, "_outro_artifacts"):
            self.play(FadeOut(self._outro_artifacts), run_time=0.5)

        title = _make_text(_t("glossary_title"), font_size=34, color=COLOR_TEXT).move_to(
            UP * TITLE_Y
        )
        self.play(FadeIn(title), run_time=0.5)

        rows: list[VGroup] = []
        terms = _t_glossary_terms()
        # Two columns: term (left, black) + definition (right, gray).
        # Font 13/11 → 14/12 for legibility (defect #7 in the
        # 2026-05-21 noise audit). Vertical band 2.7 → -2.9 widens the
        # available height so the 19-entry stack still fits cleanly.
        top_y = 2.7
        bottom_y = -2.9
        step = (top_y - bottom_y) / max(len(terms) - 1, 1)
        for i, (term, definition) in enumerate(terms):
            y = top_y - step * i
            term_text = (
                _make_text(term, font_size=14, color=COLOR_TEXT)
                .move_to(LEFT * 4.5 + UP * y)
                .align_to(LEFT * 6.5, LEFT)
            )
            def_text = (
                _make_text(definition, font_size=12, color=COLOR_TEXT_ACCENT)
                .move_to(RIGHT * 0.0 + UP * y)
                .align_to(LEFT * 1.5, LEFT)
            )
            rows.append(VGroup(term_text, def_text))

        self.play(
            LaggedStart(*[FadeIn(r) for r in rows], lag_ratio=0.08),
            run_time=2.0,
        )
        self.wait(5.0)
