"""Project type detection — harness-for-real init.sh pattern in Python.

Auto-detects project type, package manager, and build/test/lint commands
by inspecting files in the project root directory.

Supported project types:
  node (npm/yarn/pnpm/bun), python-uv, python-pip, rust, go, java-maven, java-gradle
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ProjectInfo:
    """Detected project information."""

    project_type: str = "unknown"
    pkg_mgr: str = ""
    build_cmd: str = ""
    test_cmd: str = ""
    lint_cmd: str = ""
    typecheck_cmd: str = ""
    src_dirs: list[str] = field(default_factory=lambda: ["src/", "lib/"])
    test_dirs: list[str] = field(default_factory=lambda: ["tests/", "test/"])


def detect_project_type(root: Path | None = None) -> ProjectInfo:
    """Detect project type from files in the given directory.

    Mirrors harness-for-real init.sh detection logic:
    - package.json → node (auto-detect npm/yarn/pnpm/bun)
    - pyproject.toml → python-uv
    - requirements.txt / setup.py → python-pip
    - Cargo.toml → rust
    - go.mod → go
    - pom.xml → java-maven
    - build.gradle / build.gradle.kts → java-gradle

    Args:
        root: Project root directory. Defaults to CWD.

    Returns:
        ProjectInfo with detected type and commands.
    """
    root = root or Path(".")

    # Node.js
    if (root / "package.json").exists():
        pkg_mgr = _detect_node_pkg_mgr(root)
        return ProjectInfo(
            project_type="node",
            pkg_mgr=pkg_mgr,
            build_cmd=f"{pkg_mgr} run build",
            test_cmd=f"{pkg_mgr} test",
            lint_cmd=f"{pkg_mgr} run lint",
            typecheck_cmd=(
                f"{pkg_mgr} run tsc --noEmit" if (root / "tsconfig.json").exists() else ""
            ),
            src_dirs=["src/", "lib/", "app/", "components/"],
            test_dirs=["tests/", "test/", "__tests__/", "spec/"],
        )

    # Python (uv)
    if (root / "pyproject.toml").exists():
        return ProjectInfo(
            project_type="python-uv",
            pkg_mgr="uv",
            build_cmd="uv build",
            test_cmd="uv run pytest",
            lint_cmd="uv run ruff check .",
            typecheck_cmd="uv run mypy . 2>/dev/null || true",
            src_dirs=["src/", "lib/"],
            test_dirs=["tests/", "test/"],
        )

    # Python (pip)
    if (root / "requirements.txt").exists() or (root / "setup.py").exists():
        return ProjectInfo(
            project_type="python-pip",
            pkg_mgr="pip",
            build_cmd="pip install -e .",
            test_cmd="pytest",
            lint_cmd="ruff check . 2>/dev/null || flake8 . 2>/dev/null || true",
            typecheck_cmd="mypy . 2>/dev/null || true",
            src_dirs=["src/", "lib/"],
            test_dirs=["tests/", "test/"],
        )

    # Rust
    if (root / "Cargo.toml").exists():
        return ProjectInfo(
            project_type="rust",
            pkg_mgr="cargo",
            build_cmd="cargo build",
            test_cmd="cargo test",
            lint_cmd="cargo clippy -- -D warnings",
            typecheck_cmd="cargo check",
            src_dirs=["src/"],
            test_dirs=["tests/"],
        )

    # Go
    if (root / "go.mod").exists():
        return ProjectInfo(
            project_type="go",
            pkg_mgr="go",
            build_cmd="go build ./...",
            test_cmd="go test ./...",
            lint_cmd="golangci-lint run 2>/dev/null || true",
            typecheck_cmd="go vet ./...",
            src_dirs=["cmd/", "internal/", "pkg/"],
            test_dirs=[],
        )

    # Java (Maven)
    if (root / "pom.xml").exists():
        return ProjectInfo(
            project_type="java-maven",
            pkg_mgr="mvn",
            build_cmd="mvn compile",
            test_cmd="mvn test",
            lint_cmd="mvn checkstyle:check 2>/dev/null || true",
            typecheck_cmd="mvn compile",
            src_dirs=["src/main/"],
            test_dirs=["src/test/"],
        )

    # Java (Gradle)
    if (root / "build.gradle").exists() or (root / "build.gradle.kts").exists():
        return ProjectInfo(
            project_type="java-gradle",
            pkg_mgr="gradle",
            build_cmd="./gradlew build",
            test_cmd="./gradlew test",
            lint_cmd="./gradlew check",
            typecheck_cmd="./gradlew compileJava",
            src_dirs=["src/main/"],
            test_dirs=["src/test/"],
        )

    return ProjectInfo()


def _detect_node_pkg_mgr(root: Path) -> str:
    """Detect Node.js package manager from lock files."""
    if (root / "bun.lockb").exists() or (root / "bun.lock").exists():
        return "bun"
    if (root / "pnpm-lock.yaml").exists():
        return "pnpm"
    if (root / "yarn.lock").exists():
        return "yarn"
    return "npm"


def generate_config_toml(info: ProjectInfo) -> str:
    """Generate .geode/config.toml content with detected project info.

    Extends the default TOML template with [project], [commands], [directories].
    """
    lines = [
        "# GEODE config.toml",
        "# Priority: CLI > env > .geode/config.toml > ~/.geode/config.toml > defaults",
        "#",
        "# Uncomment and edit values to override defaults.",
        "",
        "[llm]",
        '# primary_model = "claude-opus-4-6"',
        '# secondary_model = "gpt-5.4"',
        '# router_model = "claude-opus-4-6"',
        "",
        "[output]",
        "# verbose = false",
        "",
        "[pipeline]",
        "# confidence_threshold = 0.7",
        "# max_iterations = 5",
        "",
        "[project]",
        f'type = "{info.project_type}"',
        f'pkg_mgr = "{info.pkg_mgr}"',
        "",
        "[commands]",
    ]

    if info.build_cmd:
        lines.append(f'build = "{info.build_cmd}"')
    if info.test_cmd:
        lines.append(f'test = "{info.test_cmd}"')
    if info.lint_cmd:
        lines.append(f'lint = "{info.lint_cmd}"')
    if info.typecheck_cmd:
        lines.append(f'typecheck = "{info.typecheck_cmd}"')

    lines.append("")
    lines.append("[directories]")

    src_str = ", ".join(f'"{d}"' for d in info.src_dirs)
    test_str = ", ".join(f'"{d}"' for d in info.test_dirs)
    lines.append(f"src = [{src_str}]")
    lines.append(f"test = [{test_str}]")
    lines.append("")

    return "\n".join(lines)


def generate_hooks(info: ProjectInfo) -> dict[str, str]:
    """Generate hook script contents based on detected project info.

    Returns a dict: filename → script content.
    """
    lines = [
        "#!/usr/bin/env bash",
        "# Post-tool backpressure hook — lint + typecheck on Write/Edit",
        "# Exit 0 = success (silent), Exit 2 = error (agent re-enters)",
        "# Source: harness-for-real pattern",
        "",
        'cd "${CLAUDE_PROJECT_DIR:-.}"',
        'ERRORS=""',
    ]

    if info.typecheck_cmd:
        lines.append("")
        lines.append("# Typecheck")
        cmd = info.typecheck_cmd
        lines.append(
            f"OUTPUT=$(timeout 60 bash -c '{cmd}' 2>&1)"
            ' || ERRORS="$ERRORS\\n=== TypeCheck ===\\n$OUTPUT\\n"'
        )

    if info.lint_cmd:
        lines.append("")
        lines.append("# Lint")
        cmd = info.lint_cmd
        lines.append(
            f"OUTPUT=$(timeout 60 bash -c '{cmd}' 2>&1)"
            ' || ERRORS="$ERRORS\\n=== Lint ===\\n$OUTPUT\\n"'
        )

    lines.extend(
        [
            "",
            'if [ -n "$ERRORS" ]; then',
            '  echo -e "$ERRORS" >&2',
            "  exit 2",
            "fi",
            "exit 0",
            "",
        ]
    )
    backpressure = "\n".join(lines)

    gate_lines = [
        "#!/usr/bin/env bash",
        "# Pre-commit gate — test suite + skip marker check",
        "# Exit 0 = allow commit, Exit 2 = block (agent must fix)",
        "# Source: harness-for-real pattern",
        "",
        'cd "${CLAUDE_PROJECT_DIR:-.}"',
        'echo "[gate] Running pre-commit checks..."',
    ]

    if info.test_cmd:
        gate_lines.append("")
        gate_lines.append("# Run tests")
        cmd = info.test_cmd
        gate_lines.append(
            f"timeout 120 bash -c '{cmd}' 2>&1 || {{ echo \"[gate] Tests failed\" >&2; exit 2; }}"
        )

    # Skip marker check
    all_dirs = " ".join(info.src_dirs + info.test_dirs)
    gate_lines.extend(
        [
            "",
            "# Check for skip markers",
            'EXISTING_DIRS=""',
            f"for d in {all_dirs}; do",
            '  [ -d "$d" ] && EXISTING_DIRS="$EXISTING_DIRS $d"',
            "done",
            "",
            'if [ -n "$EXISTING_DIRS" ]; then',
            "  # shellcheck disable=SC2086",
            "  SKIP_MARKERS=$(grep -rn "
            "'it\\.skip\\|describe\\.skip\\|@pytest\\.mark\\.skip"
            "\\|@Disabled\\|@Ignore'"
            " $EXISTING_DIRS 2>/dev/null | head -5)",
            '  if [ -n "$SKIP_MARKERS" ]; then',
            '    echo "[gate] ERROR: Skipped tests found:" >&2',
            '    echo "$SKIP_MARKERS" >&2',
            "    exit 2",
            "  fi",
            "fi",
            "",
            'echo "[gate] All checks passed"',
            "exit 0",
            "",
        ]
    )
    pre_commit = "\n".join(gate_lines)

    return {
        "backpressure.sh": backpressure,
        "pre-commit-gate.sh": pre_commit,
    }


def generate_settings_json_hooks() -> dict[str, Any]:
    """Generate Claude Code settings.json hooks section.

    Returns a dict to merge into .claude/settings.json.
    """
    return {
        "hooks": {
            "PostToolUse": [
                {
                    "matcher": "Write|Edit",
                    "command": "timeout 90 bash .claude/hooks/backpressure.sh",
                }
            ],
            "PreToolUse": [
                {
                    "matcher": "Bash(git commit*)",
                    "command": "timeout 180 bash .claude/hooks/pre-commit-gate.sh",
                }
            ],
        }
    }
