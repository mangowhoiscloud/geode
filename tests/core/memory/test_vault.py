"""Tests for Vault — V0 purpose-routed artifact storage."""

from __future__ import annotations

import json

from core.memory.vault import Vault, classify_artifact


class TestClassifyArtifact:
    def test_profile_by_filename(self):
        assert classify_artifact("signal-report.md") == "profile"

    def test_profile_by_content(self):
        assert classify_artifact("report.md", "이력서 경력 요약") == "profile"

    def test_research_by_filename(self):
        assert classify_artifact("ai-market-research.md") == "research"

    def test_research_by_content(self):
        assert classify_artifact("doc.md", "시장 조사 보고서") == "research"

    def test_applications_by_filename(self):
        assert classify_artifact("cover-letter.md") == "applications"

    def test_applications_by_content(self):
        assert classify_artifact("doc.md", "자기소개서 초안") == "applications"

    def test_general_fallback(self):
        assert classify_artifact("random-notes.txt") == "general"

    def test_explicit_hint(self):
        assert classify_artifact("doc.md", hint="profile") == "profile"
        assert classify_artifact("doc.md", hint="research analysis") == "research"

    def test_hint_overrides_content(self):
        # Content says "research" but hint says "profile"
        assert classify_artifact("report.md", "market research", hint="profile") == "profile"


class TestVault:
    def test_ensure_structure(self, tmp_path):
        vault = Vault(tmp_path / "vault")
        vault.ensure_structure()
        assert (tmp_path / "vault" / "profile").is_dir()
        assert (tmp_path / "vault" / "research").is_dir()
        assert (tmp_path / "vault" / "applications").is_dir()
        assert (tmp_path / "vault" / "general").is_dir()

    def test_save_auto_classify(self, tmp_path):
        vault = Vault(tmp_path / "vault")
        path = vault.save("signal-report.md", "# Signal Analysis Report")
        assert "profile" in str(path)
        assert path.exists()

    def test_save_explicit_category(self, tmp_path):
        vault = Vault(tmp_path / "vault")
        path = vault.save("doc.md", "content", category="research")
        assert "research" in str(path)

    def test_save_application_with_company(self, tmp_path):
        vault = Vault(tmp_path / "vault")
        path = vault.save(
            "cover-letter.md",
            "Dear Hiring Manager...",
            category="applications",
            company="Anthropic",
            metadata={"position": "Senior ML Engineer", "status": "draft"},
        )
        assert "applications/anthropic" in str(path)
        assert path.exists()

        # Check meta.json created
        meta_path = path.parent / "meta.json"
        assert meta_path.exists()
        meta = json.loads(meta_path.read_text())
        assert meta["position"] == "Senior ML Engineer"
        assert "cover-letter" in meta["files"][0]

    def test_save_date_suffix(self, tmp_path):
        vault = Vault(tmp_path / "vault")
        path = vault.save("report.md", "content", category="general")
        # Should have date in filename
        import re

        assert re.search(r"\d{4}-\d{2}-\d{2}", path.name)

    def test_save_version_collision(self, tmp_path):
        vault = Vault(tmp_path / "vault")
        p1 = vault.save("report.md", "v1", category="general")
        p2 = vault.save("report.md", "v2", category="general")
        assert p1 != p2
        assert p1.read_text() == "v1"
        assert p2.read_text() == "v2"

    def test_load(self, tmp_path):
        vault = Vault(tmp_path / "vault")
        path = vault.save("test.md", "hello world", category="general")
        relative = str(path.relative_to(tmp_path / "vault"))
        content = vault.load(relative)
        assert content == "hello world"

    def test_load_nonexistent(self, tmp_path):
        vault = Vault(tmp_path / "vault")
        assert vault.load("nonexistent.md") is None

    def test_list_artifacts(self, tmp_path):
        vault = Vault(tmp_path / "vault")
        vault.save("profile-report.md", "profile content", category="profile")
        vault.save("market-research.md", "research content", category="research")

        all_arts = vault.list_artifacts()
        assert len(all_arts) == 2

        profile_arts = vault.list_artifacts("profile")
        assert len(profile_arts) == 1
        assert profile_arts[0]["category"] == "profile"

    def test_list_artifacts_limit(self, tmp_path):
        vault = Vault(tmp_path / "vault")
        for i in range(10):
            vault.save(f"doc-{i}.md", f"content {i}", category="general")

        limited = vault.list_artifacts("general", limit=3)
        assert len(limited) == 3

    def test_get_context_summary_empty(self, tmp_path):
        vault = Vault(tmp_path / "vault")
        vault.ensure_structure()
        assert vault.get_context_summary() == ""

    def test_get_context_summary_with_data(self, tmp_path):
        vault = Vault(tmp_path / "vault")
        vault.save("report.md", "x", category="profile")
        vault.save("research.md", "y", category="research")
        vault.save("letter.md", "z", category="applications", company="Anthropic")

        summary = vault.get_context_summary()
        assert "Vault:" in summary
        assert "profile" in summary
        assert "research" in summary
        assert "anthropic" in summary.lower()

    def test_invalid_category_falls_to_general(self, tmp_path):
        vault = Vault(tmp_path / "vault")
        path = vault.save("doc.md", "content", category="invalid_cat")
        assert "general" in str(path)
