"""Structured scoring axes and rubric data for evaluators and analysts.

These are configuration data structures, not prompt templates.
Prompt templates live in .md files loaded by the prompts package.
"""

from __future__ import annotations

ANALYST_SPECIFIC: dict[str, str] = {
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

EVALUATOR_AXES: dict[str, dict[str, object]] = {
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
            "a_score": {
                "1": "기본 조작 불량",
                "2": "장르 이하",
                "3": "장르 평균",
                "4": "장르 이상",
                "5": "혁신적 메카닉",
            },
            "b_score": {
                "1": "IP 무관",
                "2": "피상적 활용",
                "3": "적절한 활용",
                "4": "깊은 활용",
                "5": "IP 핵심 구현",
            },
            "c_score": {
                "1": "D1 Retention <10%",
                "2": "D1 10-30%",
                "3": "D1 30-50%",
                "4": "D1 50-70%",
                "5": "D1 >70%",
            },
            "b1_score": {
                "1": "like/view <1%",
                "2": "1-4%",
                "3": "4-6%",
                "4": "6-8%",
                "5": ">=8%",
            },
            "c1_score": {
                "1": "Store score <50",
                "2": "50-70",
                "3": "70-85",
                "4": "85-90",
                "5": ">=90",
            },
            "c2_score": {
                "1": "Mixed reviews",
                "2": "Mostly Negative",
                "3": "Positive",
                "4": "Very Positive",
                "5": "Overwhelmingly Positive",
            },
            "m_score": {
                "1": "버그 다수",
                "2": "불안정",
                "3": "안정적",
                "4": "잘 다듬어짐",
                "5": "완벽",
            },
            "n_score": {
                "1": "재미없음",
                "2": "약간 재미",
                "3": "적당히 재미",
                "4": "매우 재미",
                "5": "Flow 달성",
            },
        },
        "composite_formula": "Normalized 8-axis sum to 0-100: (axes_sum - 8) / 32 * 100",
    },
    "hidden_value": {
        "description": "Hidden Value Evaluator — identify underexploited potential",
        "axes": {
            "d_score": "Acquisition Gap (marketing/exposure deficiency)",
            "e_score": "Monetization Gap (revenue model underperformance)",
            "f_score": "Expansion Potential (untapped platform/market growth)",
        },
        "rubric": {
            "d_score": {
                "1": "마케팅 충분",
                "2": "소폭 부족",
                "3": "부분 부족",
                "4": "상당 부족",
                "5": "심각 부족",
            },
            "e_score": {
                "1": "수익화 양호",
                "2": "소폭 미달",
                "3": "부분 미달",
                "4": "상당 미달",
                "5": "심각 미달",
            },
            "f_score": {
                "1": "확장 완료",
                "2": "소폭 가능",
                "3": "부분 가능",
                "4": "상당 가능",
                "5": "큰 기회",
            },
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
            "j_score": {
                "1": "MoM <0%",
                "2": "MoM 0-2%",
                "3": "MoM 0-5%",
                "4": "MoM 5-10%",
                "5": "MoM >10%",
            },
            "k_score": {
                "1": "UGC 없음",
                "2": "소수 활동",
                "3": "적당히 활동",
                "4": "활발",
                "5": "바이럴",
            },
            "l_score": {
                "1": "스트리밍 없음",
                "2": "드물게",
                "3": "간헐적",
                "4": "정기적",
                "5": "활발",
            },
        },
        "composite_formula": "((J + K + L) - 3) / 12 * 100",
    },
}

PROSPECT_EVALUATOR_AXES: dict[str, dict[str, object]] = {
    "prospect_judge": {
        "description": (
            "Prospect IP Evaluator — assess non-gamified IP"
            " game adaptation potential (9 axes)"
        ),
        "axes": {
            "g_score": "World-Building Depth (lore richness, spatial design potential)",
            "h_score": "Character Roster (playable character breadth and diversity)",
            "i_score": "Narrative Arc Adaptability (story-to-quest mapping quality)",
            "o_score": "Visual Identity Strength (art style distinctiveness for game translation)",
            "p_score": "Audience Crossover Potential (existing fanbase -> gamer overlap)",
            "q_score": "Merchandise/Transmedia Track Record (proven cross-media monetization)",
            "r_score": "Competitive Landscape Gap (unoccupied genre niche opportunity)",
            "s_score": "Technology Readiness (UE5/Unity feasibility of core IP elements)",
            "t_score": "Licensing Complexity Inverse (simpler rights = higher score)",
        },
        "rubric": {
            "g_score": {
                "1": "세계관 빈약",
                "2": "기본적 세계관",
                "3": "적절한 세계관",
                "4": "풍부한 세계관",
                "5": "압도적 세계관",
            },
            "h_score": {
                "1": "캐릭터 1-2명",
                "2": "3-5명",
                "3": "6-10명",
                "4": "11-20명",
                "5": "20명+",
            },
            "i_score": {
                "1": "단선적 서사",
                "2": "분기 가능 약간",
                "3": "적절한 분기",
                "4": "풍부한 분기",
                "5": "멀티 엔딩 잠재력",
            },
            "o_score": {
                "1": "비주얼 미약",
                "2": "일반적 비주얼",
                "3": "개성적 비주얼",
                "4": "강한 아이덴티티",
                "5": "아이코닉 비주얼",
            },
            "p_score": {
                "1": "겹침 <5%",
                "2": "5-15%",
                "3": "15-30%",
                "4": "30-50%",
                "5": ">50%",
            },
            "q_score": {
                "1": "트랜스미디어 없음",
                "2": "소규모 상품화",
                "3": "중간 규모",
                "4": "활발한 상품화",
                "5": "글로벌 프랜차이즈",
            },
            "r_score": {
                "1": "레드오션",
                "2": "경쟁 심화",
                "3": "적정 경쟁",
                "4": "블루오션 접근",
                "5": "블루오션",
            },
            "s_score": {
                "1": "기술적 난제 다수",
                "2": "일부 난제",
                "3": "구현 가능",
                "4": "효율적 구현",
                "5": "즉시 적용 가능",
            },
            "t_score": {
                "1": "라이선스 극히 복잡",
                "2": "복잡",
                "3": "보통",
                "4": "단순",
                "5": "단일 권리자",
            },
        },
        "composite_formula": "Prospect Final Score: (axes_sum - 9) / 36 * 100",
    },
}
