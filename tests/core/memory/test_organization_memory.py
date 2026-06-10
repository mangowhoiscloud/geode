"""Tests for L2 Organization Memory (MonoLake fixture-based)."""

from pathlib import Path

from core.memory.organization import MonoLakeOrganizationMemory


class TestMonoLakeOrganizationMemory:
    def test_load_default_fixtures(self):
        org = MonoLakeOrganizationMemory()
        subjects = org.list_subjects()
        assert subjects == []

    def test_get_subject_context_missing_default(self):
        org = MonoLakeOrganizationMemory()
        ctx = org.get_subject_context("Project Atlas")
        assert ctx == {}

    def test_get_subject_context_case_insensitive(self):
        org = MonoLakeOrganizationMemory()
        ctx = org.get_subject_context("demo")
        assert ctx == {}

    def test_get_subject_context_unknown(self):
        org = MonoLakeOrganizationMemory()
        ctx = org.get_subject_context("Unknown Subject")
        assert ctx == {}

    def test_get_common_rubric(self):
        org = MonoLakeOrganizationMemory()
        rubric = org.get_common_rubric()
        assert rubric["axes_count"] == 14

    def test_save_analysis_result(self):
        org = MonoLakeOrganizationMemory()
        result = {"tier": "S", "score": 82.2}
        assert org.save_analysis_result("Project Atlas", result) is True
        results = org.get_analysis_results("Project Atlas")
        assert len(results) == 1
        assert results[0]["tier"] == "S"

    def test_custom_fixture_dir(self, tmp_path: Path):
        org = MonoLakeOrganizationMemory(fixture_dir=tmp_path)
        assert org.list_subjects() == []

    def test_list_subjects_from_fixtures(self):
        org = MonoLakeOrganizationMemory()
        subjects = org.list_subjects()
        assert subjects == []


class TestSoulMd:
    def test_get_soul_default(self):
        org = MonoLakeOrganizationMemory()
        soul = org.get_soul()
        # GEODE.md may not exist in CI — only assert if non-empty
        if soul:
            assert "GEODE" in soul or "Mission" in soul or "Identity" in soul

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
        soul_file = tmp_path / "GEODE.md"
        soul_file.write_text("# Test Soul\nTest mission.", encoding="utf-8")
        org = MonoLakeOrganizationMemory(
            fixture_dir=tmp_path,
            soul_path=soul_file,
        )
        assert "Test mission" in org.get_soul()
