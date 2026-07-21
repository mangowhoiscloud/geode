"""Tests for the machine-readable architecture exception ratchet."""

from __future__ import annotations

import copy
import tomllib
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from scripts import check_architecture_exceptions as checker

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_WORKFLOW = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
PRECOMMIT_CONFIG = (REPO_ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")


def _pyproject() -> dict[str, Any]:
    with (REPO_ROOT / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)


def test_live_repository_exception_ledger_is_consistent() -> None:
    assert checker.check_repository(REPO_ROOT) == []


def test_ci_and_precommit_run_exception_checker() -> None:
    command = "scripts/check_architecture_exceptions.py"

    assert "Architecture exception debt" in CI_WORKFLOW
    assert command in CI_WORKFLOW
    assert '--base-ref "$base_ref"' in CI_WORKFLOW
    assert "id: architecture-exception-debt" in PRECOMMIT_CONFIG
    assert f"uv run --frozen python {command} --check" in PRECOMMIT_CONFIG


def test_ledger_schema_fails_closed_on_missing_metadata() -> None:
    with (REPO_ROOT / checker.LEDGER_RELATIVE).open("rb") as handle:
        raw = tomllib.load(handle)
    del raw["import_edge"][0]["expires_when"]

    with pytest.raises(checker.ExceptionLedgerError, match="schema mismatch"):
        checker.parse_ledger(raw)


def test_ledger_schema_accepts_zero_remaining_debt() -> None:
    ledger = checker.parse_ledger({"schema_version": 1, "import_edge": [], "ruff_debt": []})

    assert ledger == checker.ExceptionLedger(import_edges=(), ruff_debts=())


@pytest.mark.parametrize("schema_version", [True, 1.0, "1"])
def test_ledger_schema_requires_integer_version(schema_version: object) -> None:
    raw = {"schema_version": schema_version, "import_edge": [], "ruff_debt": []}

    with pytest.raises(checker.ExceptionLedgerError, match="must be integer 1"):
        checker.parse_ledger(raw)


def test_ledger_schema_rejects_invalid_calendar_date() -> None:
    with (REPO_ROOT / checker.LEDGER_RELATIVE).open("rb") as handle:
        raw = tomllib.load(handle)
    raw["import_edge"][0]["created"] = "2026-02-30"

    with pytest.raises(checker.ExceptionLedgerError, match="real calendar date"):
        checker.parse_ledger(raw)


@pytest.mark.parametrize("owner", [".", "/external/module", "core..agent", "core/agent"])
def test_ledger_schema_rejects_non_module_owner(owner: str) -> None:
    with (REPO_ROOT / checker.LEDGER_RELATIVE).open("rb") as handle:
        raw = tomllib.load(handle)
    raw["import_edge"][0]["owner"] = owner

    with pytest.raises(checker.ExceptionLedgerError, match="dotted Python module name"):
        checker.parse_ledger(raw)


def test_import_linter_ignore_without_record_is_rejected() -> None:
    ledger = checker.load_ledger(REPO_ROOT / checker.LEDGER_RELATIVE)
    missing_first = replace(ledger, import_edges=ledger.import_edges[1:])

    errors = checker.validate_import_edges(REPO_ROOT, _pyproject(), missing_first)

    assert any("unregistered import exception" in error for error in errors)


def test_governed_ruff_rule_cannot_be_globally_ignored() -> None:
    pyproject = copy.deepcopy(_pyproject())
    pyproject["tool"]["ruff"]["lint"]["ignore"].append("PLR0911")

    errors = checker.validate_ruff_selection(pyproject)

    assert "PLR0911: broad Ruff ignore 'PLR0911' bypasses the ratchet" in errors


def test_governed_ruff_rule_cannot_be_extended_per_file_ignored() -> None:
    pyproject = copy.deepcopy(_pyproject())
    pyproject["tool"]["ruff"]["lint"]["extend-per-file-ignores"] = {"core/example.py": ["PLR0911"]}

    errors = checker.validate_ruff_selection(pyproject)

    assert "PLR0911: extend-per-file-ignores 'core/example.py' bypasses the ratchet" in errors


def test_ruff_metric_probe_ignores_project_path_suppressions(tmp_path: Path) -> None:
    source = tmp_path / "core" / "sample.py"
    source.parent.mkdir()
    source.write_text(
        "def sample(first, second, third):\n    return first + second + third\n",
        encoding="utf-8",
    )
    (tmp_path / "pyproject.toml").write_text(
        "[tool.ruff]\n"
        "force-exclude = true\n"
        'extend-exclude = ["core/sample.py"]\n'
        "\n"
        "[tool.ruff.lint]\n"
        'exclude = ["core/sample.py"]\n'
        'extend-per-file-ignores = {"core/sample.py" = ["PLR0913"]}\n',
        encoding="utf-8",
    )
    limits = {spec.rule: 100 for spec in checker.RUFF_RULES}
    limits["PLR0913"] = 2

    measurements = checker._run_ruff(tmp_path, limits)

    assert (
        checker.RuffMeasurement(
            rule="PLR0913",
            path="core/sample.py",
            symbol="sample",
            observed=3,
            noqa_row=1,
        )
        in measurements
    )


def test_threshold_ratchet_rejects_increase_but_allows_decrease() -> None:
    base = {"C901": 54, "PLR0913": 23}

    assert (
        checker.validate_threshold_ratchet(
            {"C901": 53, "PLR0913": 23},
            base,
        )
        == []
    )
    assert checker.validate_threshold_ratchet(
        {"C901": 55, "PLR0913": 23},
        base,
    ) == ["C901: Ruff ceiling increased 54 -> 55"]


def test_symbol_override_requires_rule_specific_noqa(tmp_path: Path) -> None:
    source = tmp_path / "core" / "sample.py"
    source.parent.mkdir()
    source.write_text(
        "def ceiling():\n    return None\n\ndef override():  # noqa: C901\n    return None\n",
        encoding="utf-8",
    )
    common = {
        "owner": "core",
        "reason": "Fixture metadata is intentionally long enough for validation.",
        "created": "2026-07-18",
        "target": "R0.3",
        "expires_when": "The fixture expires when this unit test completes successfully.",
    }
    ledger = checker.ExceptionLedger(
        import_edges=(),
        ruff_debts=(
            checker.RuffDebt(
                id="RUFF-901",
                rule="C901",
                mode="ceiling",
                path="core/sample.py",
                symbol="ceiling",
                observed=10,
                **common,
            ),
            checker.RuffDebt(
                id="RUFF-902",
                rule="C901",
                mode="override",
                path="core/sample.py",
                symbol="override",
                observed=11,
                **common,
            ),
        ),
    )
    measurements = (
        checker.RuffMeasurement("C901", "core/sample.py", "ceiling", 10, 1),
        checker.RuffMeasurement("C901", "core/sample.py", "override", 11, 4),
    )

    assert checker.validate_ruff_debt(tmp_path, {"C901": 10}, ledger, measurements) == []

    source.write_text(source.read_text(encoding="utf-8").replace("  # noqa: C901", ""))
    errors = checker.validate_ruff_debt(tmp_path, {"C901": 10}, ledger, measurements)
    assert any("must use a rule-specific noqa" in error for error in errors)


@pytest.mark.parametrize(
    "directive",
    [
        "# noqa: PLR091",
        "# noqa: F401 (PLR0913 debt is tracked separately)",
    ],
)
def test_symbol_override_rejects_non_ruff_selector_text(
    tmp_path: Path,
    directive: str,
) -> None:
    source = tmp_path / "core" / "sample.py"
    source.parent.mkdir()
    source.write_text(
        f"def sample(first, second, third):  {directive}\n    return first + second + third\n",
        encoding="utf-8",
    )
    measurement = checker.RuffMeasurement(
        rule="PLR0913",
        path="core/sample.py",
        symbol="sample",
        observed=3,
        noqa_row=1,
    )

    assert checker._has_specific_noqa(tmp_path, measurement) is False


def test_qualified_symbol_includes_class_ownership(tmp_path: Path) -> None:
    source = tmp_path / "sample.py"
    source.write_text(
        "class Example:\n    def method(self):\n        return None\n",
        encoding="utf-8",
    )

    assert checker._qualified_symbol(source, 2) == "Example.method"


def test_qualified_symbol_traverses_control_flow_blocks(tmp_path: Path) -> None:
    source = tmp_path / "sample.py"
    source.write_text(
        "class Example:\n"
        "    if True:\n"
        "        try:\n"
        "            def nested(self):\n"
        "                return None\n"
        "        except RuntimeError:\n"
        "            pass\n",
        encoding="utf-8",
    )

    assert checker._qualified_symbol(source, 4) == "Example.nested"


def test_valid_targets_only_reads_ledger_rows_and_package_headings(tmp_path: Path) -> None:
    roadmap = tmp_path / checker.ROADMAP_RELATIVE
    roadmap.parent.mkdir(parents=True)
    roadmap.write_text(
        "Prose mentions GAP-999 and R9.9 but does not register them.\n"
        "| ID | Audit |\n"
        "|---|---|\n"
        "| GOV-004 | `PARTIAL` |\n"
        "\n"
        "#### R0.3 Exception debt ledger\n",
        encoding="utf-8",
    )

    assert checker._valid_targets(tmp_path) == {"GOV-004", "R0.3"}
