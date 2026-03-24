"""Tests for Demo Data Generator (P1-9)."""

from __future__ import annotations

from pathlib import Path

from core.domains.game_ip.fixtures.generator import (
    GENRE_PARAMS,
    generate_batch,
    generate_ip,
    save_fixture,
)


class TestGenerateIP:
    def test_basic_generation(self):
        ip = generate_ip("Test IP", seed=42)
        assert ip.ip_name == "Test IP"
        assert ip.genre == "dark_fantasy"
        assert isinstance(ip.data, dict)

    def test_fixture_structure(self):
        ip = generate_ip("Test IP", seed=42)
        data = ip.to_fixture()

        # Required top-level keys
        assert "ip_info" in data
        assert "monolake" in data
        assert "signals" in data
        assert "psm_covariates" in data
        assert "expected_results" in data
        assert "genre_params" in data

    def test_ip_info_fields(self):
        ip = generate_ip("My Game", genre="cyberpunk", seed=42)
        info = ip.data["ip_info"]
        assert info["ip_name"] == "My Game"
        assert info["genre"] == "cyberpunk"
        assert info["media_type"] in [
            "manga",
            "anime",
            "light_novel",
            "game",
            "webtoon",
            "film",
        ]
        assert 1985 <= info["release_year"] <= 2024

    def test_monolake_fields(self):
        ip = generate_ip("Test", seed=42)
        monolake = ip.data["monolake"]
        assert "dau_current" in monolake
        assert "revenue_ltm" in monolake
        assert "active_game_count" in monolake
        assert monolake["dau_current"] > 0

    def test_signals_fields(self):
        ip = generate_ip("Test", seed=42)
        signals = ip.data["signals"]
        assert "youtube_views" in signals
        assert "reddit_subscribers" in signals
        assert "fan_art_yoy_pct" in signals

    def test_expected_results(self):
        ip = generate_ip("Test", seed=42)
        results = ip.data["expected_results"]
        assert "analyst_scores" in results
        assert "final_score" in results
        assert "tier" in results
        assert results["tier"] in ("S", "A", "B", "C")
        assert 0 <= results["final_score"] <= 100

    def test_genre_params(self):
        ip = generate_ip("Test", genre="mecha", seed=42)
        params = ip.data["genre_params"]
        assert "r_genre" in params
        assert "ltv_mult" in params
        assert params["r_genre"] == GENRE_PARAMS["mecha"]["r_genre"]

    def test_reproducibility(self):
        ip1 = generate_ip("Test", seed=42)
        ip2 = generate_ip("Test", seed=42)
        assert ip1.data == ip2.data

    def test_different_seeds(self):
        ip1 = generate_ip("Test", seed=1)
        ip2 = generate_ip("Test", seed=2)
        assert ip1.data != ip2.data

    def test_all_genres(self):
        for genre in GENRE_PARAMS:
            ip = generate_ip("Test", genre=genre, seed=42)
            assert ip.genre == genre

    def test_media_type_override(self):
        ip = generate_ip("Test", media_type="anime", seed=42)
        assert ip.data["ip_info"]["media_type"] == "anime"
        assert ip.media_type == "anime"


class TestGenerateBatch:
    def test_default_count(self):
        batch = generate_batch(seed=42)
        assert len(batch) == 5

    def test_custom_count(self):
        batch = generate_batch(3, seed=42)
        assert len(batch) == 3

    def test_genre_filter(self):
        batch = generate_batch(3, genre="mecha", seed=42)
        assert all(ip.genre == "mecha" for ip in batch)

    def test_unique_names(self):
        batch = generate_batch(10, seed=42)
        names = [ip.ip_name for ip in batch]
        assert len(names) == len(set(names))

    def test_reproducibility(self):
        b1 = generate_batch(3, seed=42)
        b2 = generate_batch(3, seed=42)
        assert [ip.ip_name for ip in b1] == [ip.ip_name for ip in b2]


class TestSaveFixture:
    def test_save_creates_file(self, tmp_path: Path):
        ip = generate_ip("Test Game", seed=42)
        path = save_fixture(ip, tmp_path)
        assert path.exists()
        assert path.name == "test_game.json"

    def test_save_valid_json(self, tmp_path: Path):
        import json

        ip = generate_ip("Test Game", seed=42)
        path = save_fixture(ip, tmp_path)
        data = json.loads(path.read_text())
        assert data["ip_info"]["ip_name"] == "Test Game"
