"""Tests for L2 Organization Memory (MonoLake fixture-based)."""

from pathlib import Path

from geode.memory.organization import MonoLakeOrganizationMemory


class TestMonoLakeOrganizationMemory:
    def test_load_default_fixtures(self):
        org = MonoLakeOrganizationMemory()
        ips = org.list_ips()
        assert len(ips) >= 1  # At least berserk.json

    def test_get_ip_context_berserk(self):
        org = MonoLakeOrganizationMemory()
        ctx = org.get_ip_context("Berserk")
        assert "ip_info" in ctx
        assert ctx["ip_info"]["ip_name"] == "Berserk"

    def test_get_ip_context_case_insensitive(self):
        org = MonoLakeOrganizationMemory()
        ctx = org.get_ip_context("berserk")
        assert "ip_info" in ctx

    def test_get_ip_context_unknown(self):
        org = MonoLakeOrganizationMemory()
        ctx = org.get_ip_context("Unknown IP")
        assert ctx == {}

    def test_get_common_rubric(self):
        org = MonoLakeOrganizationMemory()
        rubric = org.get_common_rubric()
        assert rubric["axes_count"] == 14
        assert rubric["scale"] == "1-5"
        assert rubric["confidence_threshold"] == 0.7
        assert "S" in rubric["tier_mapping"]

    def test_save_analysis_result(self):
        org = MonoLakeOrganizationMemory()
        result = {"tier": "S", "score": 82.2}
        assert org.save_analysis_result("Berserk", result) is True
        results = org.get_analysis_results("Berserk")
        assert len(results) == 1
        assert results[0]["tier"] == "S"

    def test_custom_fixture_dir(self, tmp_path: Path):
        org = MonoLakeOrganizationMemory(fixture_dir=tmp_path)
        assert org.list_ips() == []

    def test_list_ips_from_fixtures(self):
        org = MonoLakeOrganizationMemory()
        ips = org.list_ips()
        ip_names_lower = [ip.lower() for ip in ips]
        assert "berserk" in ip_names_lower


class TestSoulMd:
    def test_get_soul_default(self):
        org = MonoLakeOrganizationMemory()
        soul = org.get_soul()
        # SOUL.md exists at project root
        assert "GEODE" in soul
        assert "Mission" in soul or "Identity" in soul

    def test_get_soul_cached(self):
        org = MonoLakeOrganizationMemory()
        s1 = org.get_soul()
        s2 = org.get_soul()
        assert s1 is s2  # Same object (cached)

    def test_get_soul_missing(self, tmp_path: Path):
        org = MonoLakeOrganizationMemory(
            fixture_dir=tmp_path,
            soul_path=tmp_path / "nonexistent.md",
        )
        assert org.get_soul() == ""

    def test_get_soul_custom_path(self, tmp_path: Path):
        soul_file = tmp_path / "SOUL.md"
        soul_file.write_text("# Test Soul\nTest mission.", encoding="utf-8")
        org = MonoLakeOrganizationMemory(
            fixture_dir=tmp_path,
            soul_path=soul_file,
        )
        assert "Test mission" in org.get_soul()
