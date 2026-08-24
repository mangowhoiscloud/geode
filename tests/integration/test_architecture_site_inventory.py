"""Contract between the generated architecture snapshot and its public page."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SYSTEM_INDEX = (
    REPO_ROOT / "site" / "src" / "app" / "docs" / "architecture" / "system-index" / "page.tsx"
)
CI_WORKFLOW = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
PAGES_WORKFLOW = (REPO_ROOT / ".github" / "workflows" / "pages.yml").read_text(encoding="utf-8")


def test_system_index_renders_the_generated_architecture_snapshot() -> None:
    source = SYSTEM_INDEX.read_text(encoding="utf-8")

    assert 'import architectureBaseline from "@/data/geode/architecture-baseline.json";' in source
    assert "<code>site/src/data/geode/architecture-baseline.json</code>" in source
    assert "blob/main/site/src/data/geode/architecture-baseline.json" not in source
    for selector in (
        "architectureBaseline.packages.core.python_files",
        "architectureBaseline.tools.definition_count",
        "architectureBaseline.tools.model_execution_registration_count",
        "architectureBaseline.tools.policy_registration_count",
        "architectureBaseline.hook_events.count",
        "architectureBaseline.built_in_adapters.count",
        "architectureBaseline.context_vars.count",
        "architectureBaseline.core_to_outer_imports.site_count",
        "architectureBaseline.import_linter.ignored_edge_count",
    ):
        assert selector in source
    assert '<ArchitectureBaselineTable locale="ko" />' in source
    assert '<ArchitectureBaselineTable locale="en" />' in source


def test_public_architecture_consumers_cannot_bypass_generated_drift_gates() -> None:
    for path_filter in (
        "site/scripts/**",
        "site/src/**",
        "site/public/llms-full.txt",
    ):
        assert f"- '{path_filter}'" in CI_WORKFLOW

    assert "Verify committed public-doc generators are current" in PAGES_WORKFLOW
    assert "git diff --exit-code --" in PAGES_WORKFLOW
    assert "public/llms-full.txt" in PAGES_WORKFLOW
    assert "- 'CHANGELOG.md'" in CI_WORKFLOW
    assert '- "CHANGELOG.md"' in PAGES_WORKFLOW


def test_ci_exposes_every_r7_1_architecture_gate() -> None:
    for contract in (
        "Architecture import contracts",
        "uv run lint-imports --no-cache",
        "Architecture behavior contracts",
        "Architecture performance baseline",
        "scripts/check_architecture_performance.py --check",
        "Extension change-surface contracts",
        "tests/integration/test_extension_change_surfaces.py",
        "tests/core/agent/test_loop_architecture_budget.py",
        "tests/core/agent/test_loop_state_machine.py",
        "tests/core/agent/test_approval_fsm.py",
        "tests/core/agent/test_google_workspace_consent.py",
        "tests/core/agent/test_subagent_architecture_budget.py",
        "tests/core/agent/test_tool_plan_runtime_policy.py",
        "tests/core/llm/test_retry_policy.py",
        "tests/core/observability/test_event_store.py",
        "tests/core/test_ipc_protocol.py",
        "tests/core/tools/test_tool_plan.py",
        "tests/integration/test_namespace_composition.py",
        "Official documentation drift",
        "scripts/check_official_docs.py --skip-build",
    ):
        assert contract in CI_WORKFLOW
