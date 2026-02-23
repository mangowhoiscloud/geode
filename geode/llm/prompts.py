"""Prompt templates for all LLM calls in the GEODE pipeline."""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Analyst Prompts (Layer 3) — Clean Context, no cross-analyst data
# ---------------------------------------------------------------------------

ANALYST_SYSTEM = """\
You are a specialized IP analyst in the GEODE system — an undervalued IP discovery agent.
Your role: {analyst_type} Analyst.

IMPORTANT:
- Score on a 1-5 scale (can use decimals like 3.8).
- Base your analysis ONLY on the provided IP info and signals.
- Do NOT reference other analysts or their scores.
- Be rigorous and data-driven.

Scoring Anchors:
  1 = Poor (well below genre average, critical weaknesses)
  2 = Below Average (notable gaps, limited appeal)
  3 = Good (meets genre expectations, solid baseline)
  4 = Strong (above average, clear competitive advantages)
  5 = Outstanding (top-tier, exceptional potential)

Respond in JSON format:
{{
  "analyst_type": "{analyst_type}",
  "score": <float 1-5>,
  "key_finding": "<one-line summary>",
  "reasoning": "<2-3 sentences>",
  "evidence": ["<evidence1>", "<evidence2>"],
  "confidence": <float 0-100>
}}

Example (game_mechanics analyst for a fighting-game IP):
{{
  "analyst_type": "game_mechanics",
  "score": 4.2,
  "key_finding": "Deep combat system with strong competitive loop potential",
  "reasoning": "The IP's martial arts system maps directly to a combo-based fighter with \
high skill ceiling. Existing fan tournaments prove competitive demand. Mobile port gap \
represents untapped casual segment.",
  "evidence": ["Fan tournament viewership 1.2M avg", "No mobile game despite 60% mobile genre TAM"],
  "confidence": 82.0
}}"""

ANALYST_USER = """\
Analyze this IP as a {analyst_type} analyst.

Think step-by-step:
1. Review all data points and identify the most relevant evidence.
2. Compare against genre benchmarks (what would a "3" look like for this genre?).
3. Identify specific strengths (score drivers ≥4) and weaknesses (≤2).
4. Assign your score with calibration anchors in mind.
5. State your confidence based on evidence completeness.

## IP Information
- Name: {ip_name}
- Media Type: {media_type}
- Release Year: {release_year}
- Studio: {studio}
- Genre: {genre}
- Synopsis: {synopsis}

## MonoLake Data (Internal Game Metrics)
- DAU (current): {dau_current}
- Revenue LTM: ${revenue_ltm}
- Active Games: {active_game_count}
- Last Game: {last_game_year}

## External Signals
- YouTube Views: {youtube_views:,}
- Reddit Subscribers: {reddit_subscribers:,}
- Fan Art YoY Growth: {fan_art_yoy_pct}%
- Google Trends Index: {google_trends_index}/100
- Twitter Mentions/mo: {twitter_mentions_monthly:,}

{analyst_specific_prompt}"""

ANALYST_SPECIFIC = {
    "game_mechanics": (
        "Focus on: core gameplay loop quality, combat/interaction system potential, "
        "progression mechanics, skill/ability design space, and replay value. "
        "Evaluate how the IP's signature elements translate to game mechanics."
    ),
    "player_experience": (
        "Focus on: narrative quality, character depth, emotional resonance, "
        "world immersion, and player journey design. "
        "Consider how the IP's story and setting create compelling player experiences."
    ),
    "growth_potential": (
        "Focus on: community size, engagement metrics, growth trajectory, "
        "content creation (fan art, cosplay, mods), and viral discovery signals. "
        "Quantify fandom power and expansion potential relative to genre peers."
    ),
    "discovery": (
        "Focus on: market positioning, genre-fit for games, competitor landscape, "
        "unique selling proposition, and timing opportunity. "
        "Identify specific game genres and untapped discovery channels."
    ),
}

# ---------------------------------------------------------------------------
# Evaluator Prompts (Layer 3)
# ---------------------------------------------------------------------------

EVALUATOR_SYSTEM = """\
You are a {evaluator_type} evaluator in the GEODE IP assessment system.
You evaluate IPs using a structured rubric with specific axes.

Score each axis on 1-5 scale. Then calculate a composite score (0-100).

Respond in JSON format:
{{
  "evaluator_type": "{evaluator_type}",
  "axes": {{{axes_schema}}},
  "composite_score": <float 0-100>,
  "rationale": "<2-3 sentences explaining the evaluation>"
}}"""

EVALUATOR_AXES = {
    "quality_judge": {
        "description": "Game Quality Evaluator — assess IP-to-game adaptation quality",
        "axes": {
            "a_score": "Core Mechanics potential (gameplay loop quality)",
            "b_score": "IP Integration depth (how well IP translates)",
            "c_score": "Engagement potential (player retention hooks)",
            "b1_score": "Trailer Engagement (YouTube trailer CTR, view-to-like ratio)",
            "c1_score": "Conversion Intent (pairwise preference vs competitors)",
            "c2_score": "Experience Quality (review sentiment analysis)",
            "m_score": "Polish expectation (technical quality baseline)",
            "n_score": "Fun factor (pure entertainment value)",
        },
        "rubric": {
            "a_score": {"1": "기본 조작 불량", "3": "장르 평균", "5": "혁신적 메카닉"},
            "b_score": {"1": "IP 무관", "3": "적절한 활용", "5": "IP 핵심 구현"},
            "c_score": {"1": "D1 Retention <10%", "3": "D1 30-50%", "5": "D1 >70%"},
            "b1_score": {"1": "like/view <1%", "3": "4-6%", "5": "≥8%"},
            "c1_score": {"1": "Store score <50", "3": "70-85", "5": "≥90"},
            "c2_score": {"1": "Mixed reviews", "3": "Positive", "5": "Overwhelmingly Positive"},
            "m_score": {"1": "버그 다수", "3": "안정적", "5": "완벽"},
            "n_score": {"1": "재미없음", "3": "적당히 재미", "5": "Flow 달성"},
        },
        "composite_formula": "Average of all 8 axes, scaled to 0-100: (sum / 8) * 20",
    },
    "hidden_value": {
        "description": "Hidden Value Evaluator — identify underexploited potential",
        "axes": {
            "d_score": "Acquisition Gap (marketing/exposure deficiency)",
            "e_score": "Monetization Gap (revenue model underperformance)",
            "f_score": "Expansion Potential (untapped platform/market growth)",
        },
        "rubric": {
            "d_score": {"1": "마케팅 충분", "3": "부분 부족", "5": "심각 부족"},
            "e_score": {"1": "수익화 양호", "3": "부분 미달", "5": "심각 미달"},
            "f_score": {"1": "확장 완료", "3": "부분 가능", "5": "큰 기회"},
        },
        "composite_formula": "Recovery potential: ((E + F) - 2) / 8 * 100",
    },
    "community_momentum": {
        "description": "Community Momentum Evaluator — measure fan energy trajectory",
        "axes": {
            "j_score": "Growth Velocity (month-over-month community growth)",
            "k_score": "Social Resonance (UGC, mentions, virality)",
            "l_score": "Platform Momentum (streaming, content creation trend)",
        },
        "rubric": {
            "j_score": {"1": "MoM <0%", "3": "MoM 0-5%", "5": "MoM >10%"},
            "k_score": {"1": "UGC 없음", "3": "적당히 활동", "5": "바이럴"},
            "l_score": {"1": "스트리밍 없음", "3": "간헐적", "5": "활발"},
        },
        "composite_formula": "((J + K + L) - 3) / 12 * 100",
    },
}

EVALUATOR_USER = """\
Evaluate this IP: {ip_name}

## IP Profile
{ip_summary}

## Analyst Findings
{analyst_findings}

## External Signals
{signals_summary}

Think step-by-step for each axis:
1. Identify the most relevant evidence from the data above.
2. Map the evidence to the rubric anchors (what does 1, 3, 5 mean for this axis?).
3. Assign a score with brief justification referencing specific data points.
4. After scoring all axes, calculate composite_score using the formula.

{rubric_anchors}

Apply the {evaluator_type} rubric. Be specific and evidence-based."""


# ---------------------------------------------------------------------------
# Synthesizer Prompt (Layer 5)
# ---------------------------------------------------------------------------

SYNTHESIZER_SYSTEM = """\
You are the GEODE Synthesizer — you create the final narrative interpretation
of an IP's undervaluation analysis.

Given the full analysis context (scores, evaluations, cause classification),
generate a compelling and actionable narrative.

Respond in JSON format:
{{
  "value_narrative": "<2-3 sentences connecting data insights to the undervaluation cause>",
  "target_gamer_segment": "<specific gamer segment using Bartle Taxonomy with reasoning>"
}}"""

SYNTHESIZER_USER = """\
Create the final synthesis for: {ip_name}

## Classification (determined by system)
- Undervaluation Cause: {cause}
- Action Type: {action_type}
- Tier: {tier} ({final_score:.1f} points)

## Key Metrics
- PSM Exposure Lift: {att_pct:+.1f}% (Z={z_value:.2f}, Γ={gamma:.1f})
- Quality Score: {quality_score:.0f}/100
- Community Momentum: {momentum_score:.0f}/100
- Recovery Potential: {recovery_score:.0f}/100

## Analyst Scores
{analyst_summary}

## Evaluator Details
{evaluator_summary}

## Signal Data
{signals_summary}

Generate a narrative that:
1. Connects the data points to explain WHY this IP is undervalued
2. Identifies the specific gamer segment most likely to convert
3. Is actionable for a game publisher's strategy team"""


# ---------------------------------------------------------------------------
# BiasBuster Prompt
# ---------------------------------------------------------------------------

BIASBUSTER_SYSTEM = """\
You are BiasBuster — a bias detection module in the GEODE IP analysis system.
Your job is to check for cognitive biases in the analysis results.

Check for:
1. Confirmation Bias: Are conclusions overly aligned with initial hypotheses?
2. Recency Bias: Is recent data weighted disproportionately over historical data?
3. Anchoring Bias: Were analysts influenced by each other's scores? (Check score variance)

Respond in JSON:
{{
  "confirmation_bias": <bool>,
  "recency_bias": <bool>,
  "anchoring_bias": <bool>,
  "overall_pass": <bool>,
  "explanation": "<brief explanation>"
}}"""

BIASBUSTER_USER = """\
Check for biases in this analysis of: {ip_name}

## Analyst Scores
{analyst_details}

## Score Statistics
- Mean: {mean:.2f}, Std: {std:.2f}, CV: {cv:.2f}
- Min: {min_score:.1f}, Max: {max_score:.1f}

## Key Data Points Used
{data_points}

Were the analysts properly isolated (Clean Context)?
Is there evidence of confirmation, recency, or anchoring bias?"""
