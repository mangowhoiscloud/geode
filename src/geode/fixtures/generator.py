"""Demo Data Generator — synthetic game/IP data for GEODE demos.

Generates realistic game IP data based on configurable templates
and genre-specific parameters. Used for demo and testing purposes.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Genre parameter defaults (r(genre), LTV_mult ranges)
GENRE_PARAMS: dict[str, dict[str, Any]] = {
    "action_rpg": {"r_genre": 0.12, "ltv_mult_range": (1.2, 2.5), "dau_range": (500, 50000)},
    "dark_fantasy": {"r_genre": 0.15, "ltv_mult_range": (1.5, 3.0), "dau_range": (200, 30000)},
    "mecha": {"r_genre": 0.18, "ltv_mult_range": (1.0, 2.0), "dau_range": (100, 20000)},
    "cyberpunk": {"r_genre": 0.14, "ltv_mult_range": (1.3, 2.8), "dau_range": (300, 40000)},
    "shounen": {"r_genre": 0.10, "ltv_mult_range": (2.0, 4.0), "dau_range": (1000, 100000)},
    "horror": {"r_genre": 0.20, "ltv_mult_range": (0.8, 1.8), "dau_range": (100, 15000)},
    "slice_of_life": {"r_genre": 0.22, "ltv_mult_range": (0.5, 1.5), "dau_range": (50, 10000)},
    "space_opera": {"r_genre": 0.16, "ltv_mult_range": (1.1, 2.2), "dau_range": (150, 25000)},
}

MEDIA_TYPES = ["manga", "anime", "light_novel", "game", "webtoon", "film"]
STUDIOS = [
    "Studio Ghibli",
    "MAPPA",
    "Madhouse",
    "Bones",
    "Sunrise",
    "Wit Studio",
    "Toei Animation",
    "Production I.G",
    "A-1 Pictures",
    "Ufotable",
    "Trigger",
    "CloverWorks",
    "Kyoto Animation",
]

UNDERVALUATION_CAUSES = [
    "undermarketed",
    "conversion_failure",
    "monetization_misfit",
    "niche_gem",
    "timing_mismatch",
    "discovery_failure",
]


@dataclass
class GeneratedIP:
    """A synthetically generated IP dataset."""

    ip_name: str
    genre: str
    media_type: str
    data: dict[str, Any] = field(default_factory=dict)

    def to_fixture(self) -> dict[str, Any]:
        return self.data


def generate_ip(
    ip_name: str,
    *,
    genre: str = "dark_fantasy",
    media_type: str | None = None,
    seed: int | None = None,
) -> GeneratedIP:
    """Generate a synthetic IP dataset.

    Args:
        ip_name: Name of the IP.
        genre: Genre key (from GENRE_PARAMS).
        media_type: Media type override (random if None).
        seed: Random seed for reproducibility.
    """
    if seed is not None:
        random.seed(seed)

    params = GENRE_PARAMS.get(genre, GENRE_PARAMS["dark_fantasy"])
    chosen_media = media_type or random.choice(MEDIA_TYPES)
    studio = random.choice(STUDIOS)
    release_year = random.randint(1985, 2024)

    # MonoLake-style metrics
    dau_min, dau_max = params["dau_range"]
    dau = random.randint(dau_min, dau_max)
    revenue = int(dau * random.uniform(0.5, 5.0) * 365)
    active_games = random.choice([0, 0, 0, 1, 1, 2])  # Most IPs have 0-1 games

    # Signal metrics
    yt_views = random.randint(100_000, 50_000_000)
    reddit_subs = random.randint(500, 200_000)
    fan_art_yoy = random.uniform(-20, 80)
    twitch_hours = random.randint(0, 500_000)

    # PSM covariates
    att_pct = random.uniform(5.0, 45.0)
    z_value = random.uniform(0.5, 4.0)
    rosenbaum_gamma = random.uniform(1.0, 3.0)

    # Analyst scores (1-5 scale)
    scores = {
        "game_mechanics": round(random.uniform(2.0, 5.0), 1),
        "player_experience": round(random.uniform(2.0, 5.0), 1),
        "growth_potential": round(random.uniform(1.5, 5.0), 1),
        "discovery": round(random.uniform(1.5, 5.0), 1),
    }

    avg_score = sum(scores.values()) / len(scores)
    confidence = round(random.uniform(50, 95), 1)

    # Tier calculation
    final_score = round(avg_score * 20 + random.uniform(-5, 5), 1)
    final_score = max(0, min(100, final_score))
    if final_score >= 80:
        tier = "S"
    elif final_score >= 60:
        tier = "A"
    elif final_score >= 40:
        tier = "B"
    else:
        tier = "C"

    ltv_min, ltv_max = params["ltv_mult_range"]

    data: dict[str, Any] = {
        "ip_info": {
            "ip_name": ip_name,
            "genre": genre,
            "media_type": chosen_media,
            "release_year": release_year,
            "studio": studio,
        },
        "monolake": {
            "dau_current": dau,
            "revenue_ltm": revenue,
            "active_game_count": active_games,
        },
        "signals": {
            "youtube_views": yt_views,
            "reddit_subscribers": reddit_subs,
            "fan_art_yoy_pct": round(fan_art_yoy, 1),
            "twitch_hours_monthly": twitch_hours,
        },
        "psm_covariates": {
            "att_pct": round(att_pct, 1),
            "z_value": round(z_value, 2),
            "rosenbaum_gamma": round(rosenbaum_gamma, 1),
        },
        "expected_results": {
            "analyst_scores": scores,
            "analyst_confidence": confidence,
            "final_score": final_score,
            "tier": tier,
            "quality_score": round(random.uniform(40, 90), 1),
            "momentum_score": round(random.uniform(30, 85), 1),
            "undervaluation_cause": random.choice(UNDERVALUATION_CAUSES),
        },
        "genre_params": {
            "r_genre": params["r_genre"],
            "ltv_mult": round(random.uniform(ltv_min, ltv_max), 2),
        },
    }

    return GeneratedIP(ip_name=ip_name, genre=genre, media_type=chosen_media, data=data)


def generate_batch(
    count: int = 5,
    *,
    genre: str | None = None,
    seed: int | None = None,
) -> list[GeneratedIP]:
    """Generate multiple synthetic IPs."""
    if seed is not None:
        random.seed(seed)

    sample_names = [
        "Vinland Saga",
        "Trigun",
        "Akira",
        "Claymore",
        "Blame!",
        "Dorohedoro",
        "Vagabond",
        "Gantz",
        "Parasyte",
        "Basilisk",
        "Ergo Proxy",
        "Texhnolyze",
        "Serial Experiments Lain",
        "Planetes",
        "Monster",
        "20th Century Boys",
        "Pluto",
        "Rainbow",
        "Beck",
        "Nana",
    ]

    names = random.sample(sample_names, min(count, len(sample_names)))
    genres = list(GENRE_PARAMS.keys())

    results = []
    for name in names:
        g = genre or random.choice(genres)
        results.append(generate_ip(name, genre=g))

    return results


def save_fixture(ip: GeneratedIP, output_dir: Path) -> Path:
    """Save a generated IP as a fixture JSON file."""
    filename = ip.ip_name.lower().replace(" ", "_") + ".json"
    path = output_dir / filename
    path.write_text(json.dumps(ip.to_fixture(), indent=2, ensure_ascii=False), encoding="utf-8")
    return path
