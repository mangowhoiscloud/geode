"""Tests for project type detection — harness-for-real init.sh pattern."""

from __future__ import annotations

from pathlib import Path

from core.cli.project_detect import (
    ProjectInfo,
    detect_project_type,
    generate_config_toml,
    generate_hooks,
    generate_settings_json_hooks,
)


class TestDetectProjectType:
    """Test project type auto-detection."""

    def test_detect_python_uv(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n")
        info = detect_project_type(tmp_path)
        assert info.project_type == "python-uv"
        assert info.pkg_mgr == "uv"
        assert "uv run pytest" in info.test_cmd
        assert "ruff" in info.lint_cmd

    def test_detect_python_pip(self, tmp_path: Path) -> None:
        (tmp_path / "requirements.txt").write_text("flask\n")
        info = detect_project_type(tmp_path)
        assert info.project_type == "python-pip"
        assert info.pkg_mgr == "pip"
        assert info.test_cmd == "pytest"

    def test_detect_python_pip_setup_py(self, tmp_path: Path) -> None:
        (tmp_path / "setup.py").write_text("from setuptools import setup\n")
        info = detect_project_type(tmp_path)
        assert info.project_type == "python-pip"

    def test_detect_node_npm(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text('{"name": "test"}\n')
        info = detect_project_type(tmp_path)
        assert info.project_type == "node"
        assert info.pkg_mgr == "npm"
        assert "npm" in info.test_cmd

    def test_detect_node_yarn(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text('{"name": "test"}\n')
        (tmp_path / "yarn.lock").write_text("")
        info = detect_project_type(tmp_path)
        assert info.project_type == "node"
        assert info.pkg_mgr == "yarn"

    def test_detect_node_pnpm(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text('{"name": "test"}\n')
        (tmp_path / "pnpm-lock.yaml").write_text("")
        info = detect_project_type(tmp_path)
        assert info.project_type == "node"
        assert info.pkg_mgr == "pnpm"

    def test_detect_node_bun(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text('{"name": "test"}\n')
        (tmp_path / "bun.lockb").write_bytes(b"")
        info = detect_project_type(tmp_path)
        assert info.project_type == "node"
        assert info.pkg_mgr == "bun"

    def test_detect_node_typescript(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text('{"name": "test"}\n')
        (tmp_path / "tsconfig.json").write_text("{}")
        info = detect_project_type(tmp_path)
        assert info.typecheck_cmd != ""
        assert "tsc" in info.typecheck_cmd

    def test_detect_rust(self, tmp_path: Path) -> None:
        (tmp_path / "Cargo.toml").write_text('[package]\nname = "test"\n')
        info = detect_project_type(tmp_path)
        assert info.project_type == "rust"
        assert info.pkg_mgr == "cargo"
        assert "cargo test" in info.test_cmd
        assert "clippy" in info.lint_cmd

    def test_detect_go(self, tmp_path: Path) -> None:
        (tmp_path / "go.mod").write_text("module test\n")
        info = detect_project_type(tmp_path)
        assert info.project_type == "go"
        assert info.pkg_mgr == "go"
        assert "go test" in info.test_cmd

    def test_detect_java_maven(self, tmp_path: Path) -> None:
        (tmp_path / "pom.xml").write_text("<project></project>")
        info = detect_project_type(tmp_path)
        assert info.project_type == "java-maven"
        assert info.pkg_mgr == "mvn"
        assert "mvn test" in info.test_cmd

    def test_detect_java_gradle(self, tmp_path: Path) -> None:
        (tmp_path / "build.gradle").write_text("apply plugin: 'java'")
        info = detect_project_type(tmp_path)
        assert info.project_type == "java-gradle"
        assert info.pkg_mgr == "gradle"
        assert "gradlew" in info.test_cmd

    def test_detect_java_gradle_kts(self, tmp_path: Path) -> None:
        (tmp_path / "build.gradle.kts").write_text("plugins { java }")
        info = detect_project_type(tmp_path)
        assert info.project_type == "java-gradle"

    def test_detect_unknown(self, tmp_path: Path) -> None:
        info = detect_project_type(tmp_path)
        assert info.project_type == "unknown"
        assert info.pkg_mgr == ""
        assert info.build_cmd == ""

    def test_pyproject_takes_priority_over_requirements(self, tmp_path: Path) -> None:
        """pyproject.toml should be detected as python-uv, not python-pip."""
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n")
        (tmp_path / "requirements.txt").write_text("flask\n")
        info = detect_project_type(tmp_path)
        assert info.project_type == "python-uv"


class TestGenerateConfigToml:
    """Test config.toml generation."""

    def test_contains_project_section(self) -> None:
        info = ProjectInfo(project_type="python-uv", pkg_mgr="uv")
        toml = generate_config_toml(info)
        assert "[project]" in toml
        assert 'type = "python-uv"' in toml
        assert 'pkg_mgr = "uv"' in toml

    def test_contains_commands_section(self) -> None:
        info = ProjectInfo(
            project_type="rust",
            pkg_mgr="cargo",
            build_cmd="cargo build",
            test_cmd="cargo test",
            lint_cmd="cargo clippy -- -D warnings",
            typecheck_cmd="cargo check",
        )
        toml = generate_config_toml(info)
        assert "[commands]" in toml
        assert 'build = "cargo build"' in toml
        assert 'test = "cargo test"' in toml

    def test_contains_directories_section(self) -> None:
        info = ProjectInfo(src_dirs=["src/"], test_dirs=["tests/"])
        toml = generate_config_toml(info)
        assert "[directories]" in toml
        assert '"src/"' in toml

    def test_preserves_llm_section(self) -> None:
        info = ProjectInfo()
        toml = generate_config_toml(info)
        assert "[llm]" in toml
        assert "claude-opus" in toml


class TestGenerateHooks:
    """Test hook script generation."""

    def test_generates_two_hooks(self) -> None:
        info = ProjectInfo(
            test_cmd="pytest",
            lint_cmd="ruff check .",
            typecheck_cmd="mypy .",
        )
        hooks = generate_hooks(info)
        assert "backpressure.sh" in hooks
        assert "pre-commit-gate.sh" in hooks

    def test_backpressure_contains_lint(self) -> None:
        info = ProjectInfo(lint_cmd="ruff check .")
        hooks = generate_hooks(info)
        assert "ruff check" in hooks["backpressure.sh"]

    def test_pre_commit_contains_test(self) -> None:
        info = ProjectInfo(test_cmd="cargo test")
        hooks = generate_hooks(info)
        assert "cargo test" in hooks["pre-commit-gate.sh"]

    def test_pre_commit_checks_skip_markers(self) -> None:
        info = ProjectInfo(test_cmd="pytest", src_dirs=["src/"], test_dirs=["tests/"])
        hooks = generate_hooks(info)
        assert "skip" in hooks["pre-commit-gate.sh"].lower()

    def test_hooks_are_executable_scripts(self) -> None:
        info = ProjectInfo()
        hooks = generate_hooks(info)
        for content in hooks.values():
            assert content.startswith("#!/usr/bin/env bash")


class TestGenerateSettingsJsonHooks:
    """Test settings.json hook registration."""

    def test_has_post_tool_use(self) -> None:
        config = generate_settings_json_hooks()
        assert "hooks" in config
        assert "PostToolUse" in config["hooks"]
        assert config["hooks"]["PostToolUse"][0]["matcher"] == "Write|Edit"

    def test_has_pre_tool_use(self) -> None:
        config = generate_settings_json_hooks()
        assert "PreToolUse" in config["hooks"]
        assert "git commit" in config["hooks"]["PreToolUse"][0]["matcher"]
