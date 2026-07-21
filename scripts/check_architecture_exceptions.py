#!/usr/bin/env python3
"""Validate GEODE's machine-readable architecture exception ledger.

The ledger closes two otherwise informal escape hatches:

* every ``import-linter`` ignored edge must have owner/age/target/expiry
  metadata;
* every Ruff complexity ceiling witness and every symbol-level override must
  be registered, while configured ceilings remain tight and monotonic.

Ruff is probed one point below each configured ceiling with ``--ignore-noqa``.
That produces only the symbols at the ceiling plus explicit overrides, rather
than serialising every function metric into a second baseline.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import shutil
import subprocess
import sys
import tomllib
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from scripts.git_command import GitExecutableNotFoundError, run_git

REPO_ROOT = Path(__file__).resolve().parents[1]
LEDGER_RELATIVE = Path("docs/architecture/exception-debt.toml")
PYPROJECT_RELATIVE = Path("pyproject.toml")
ROADMAP_RELATIVE = Path("docs/architecture/extensibility-roadmap.md")

_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MODULE_NAME = r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*"
_MODULE_PATTERN = re.compile(rf"^{_MODULE_NAME}$")
_EDGE_PATTERN = re.compile(rf"^{_MODULE_NAME} -> {_MODULE_NAME}$")
_IMPORT_ID_PATTERN = re.compile(r"^IMP-\d{3}$")
_RUFF_ID_PATTERN = re.compile(r"^RUFF-\d{3}$")
_TARGET_PATTERN = re.compile(r"^(?:[A-Z]+-\d{3}|R\d+\.\d+)$")
_SYMBOL_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")
_METRIC_PATTERN = re.compile(r"\((?P<metric>\d+) > \d+\)")
_NOQA_PATTERN = re.compile(
    r"#\s*noqa\s*:\s*(?P<selectors>[A-Z]+\d+(?:\s*,\s*[A-Z]+\d+)*)\b",
    re.IGNORECASE,
)
_RULE_CODE_PATTERN = re.compile(r"\b[A-Z]+\d+\b")

_COMMON_FIELDS = frozenset(
    {
        "owner",
        "reason",
        "created",
        "target",
        "expires_when",
    }
)
_IMPORT_FIELDS = frozenset({"id", "edge", "contracts", *_COMMON_FIELDS})
_RUFF_FIELDS = frozenset(
    {
        "id",
        "rule",
        "mode",
        "path",
        "symbol",
        "observed",
        *_COMMON_FIELDS,
    }
)


@dataclass(frozen=True)
class RuffRuleSpec:
    """One Ruff metric and its pyproject override path."""

    rule: str
    config_path: tuple[str, ...]
    override_key: str


RUFF_RULES: tuple[RuffRuleSpec, ...] = (
    RuffRuleSpec(
        rule="C901",
        config_path=("tool", "ruff", "lint", "mccabe", "max-complexity"),
        override_key="lint.mccabe.max-complexity",
    ),
    RuffRuleSpec(
        rule="PLR0913",
        config_path=("tool", "ruff", "lint", "pylint", "max-args"),
        override_key="lint.pylint.max-args",
    ),
    RuffRuleSpec(
        rule="PLR0912",
        config_path=("tool", "ruff", "lint", "pylint", "max-branches"),
        override_key="lint.pylint.max-branches",
    ),
    RuffRuleSpec(
        rule="PLR0911",
        config_path=("tool", "ruff", "lint", "pylint", "max-returns"),
        override_key="lint.pylint.max-returns",
    ),
    RuffRuleSpec(
        rule="PLR0915",
        config_path=("tool", "ruff", "lint", "pylint", "max-statements"),
        override_key="lint.pylint.max-statements",
    ),
)
_RUFF_RULE_BY_CODE = {spec.rule: spec for spec in RUFF_RULES}


@dataclass(frozen=True)
class ImportEdgeDebt:
    """Metadata for one unique ignored import edge."""

    id: str
    edge: str
    contracts: tuple[str, ...]
    owner: str
    reason: str
    created: str
    target: str
    expires_when: str


@dataclass(frozen=True)
class RuffDebt:
    """Metadata for one measured Ruff ceiling witness or override."""

    id: str
    rule: str
    mode: str
    path: str
    symbol: str
    observed: int
    owner: str
    reason: str
    created: str
    target: str
    expires_when: str


@dataclass(frozen=True)
class ExceptionLedger:
    """Parsed exception ledger."""

    import_edges: tuple[ImportEdgeDebt, ...]
    ruff_debts: tuple[RuffDebt, ...]


@dataclass(frozen=True)
class RuffMeasurement:
    """One Ruff metric at or above the configured ceiling."""

    rule: str
    path: str
    symbol: str
    observed: int
    noqa_row: int


class ExceptionLedgerError(ValueError):
    """Raised when the ledger or one of its source contracts is malformed."""


def _required_string(row: Mapping[str, Any], key: str, *, context: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ExceptionLedgerError(f"{context}: {key} must be a non-empty string")
    return value.strip()


def _validate_common(row: Mapping[str, Any], *, context: str) -> dict[str, str]:
    common = {key: _required_string(row, key, context=context) for key in _COMMON_FIELDS}
    if _MODULE_PATTERN.fullmatch(common["owner"]) is None:
        raise ExceptionLedgerError(f"{context}: owner must be a dotted Python module name")
    if _DATE_PATTERN.fullmatch(common["created"]) is None:
        raise ExceptionLedgerError(f"{context}: created must use YYYY-MM-DD")
    try:
        date.fromisoformat(common["created"])
    except ValueError as exc:
        raise ExceptionLedgerError(f"{context}: created must be a real calendar date") from exc
    if _TARGET_PATTERN.fullmatch(common["target"]) is None:
        raise ExceptionLedgerError(f"{context}: target must name a GAP ID or closure package")
    for key in ("reason", "expires_when"):
        if len(common[key]) < 20:
            raise ExceptionLedgerError(f"{context}: {key} is not meaningful enough")
    return common


def _table_rows(raw: Mapping[str, Any], key: str) -> list[Mapping[str, Any]]:
    rows = raw.get(key)
    if not isinstance(rows, list):
        raise ExceptionLedgerError(f"{key} must be an array of tables")
    if not all(isinstance(row, dict) for row in rows):
        raise ExceptionLedgerError(f"{key} entries must be tables")
    return rows


def _parse_import_edge(row: Mapping[str, Any], index: int) -> ImportEdgeDebt:
    context = f"import_edge[{index}]"
    unknown = set(row) - _IMPORT_FIELDS
    missing = _IMPORT_FIELDS - set(row)
    if unknown or missing:
        raise ExceptionLedgerError(
            f"{context}: schema mismatch; missing={sorted(missing)}, unknown={sorted(unknown)}"
        )
    debt_id = _required_string(row, "id", context=context)
    edge = _required_string(row, "edge", context=context)
    if _IMPORT_ID_PATTERN.fullmatch(debt_id) is None:
        raise ExceptionLedgerError(f"{context}: invalid id {debt_id!r}")
    if _EDGE_PATTERN.fullmatch(edge) is None:
        raise ExceptionLedgerError(f"{context}: invalid edge {edge!r}")
    contracts_raw = row.get("contracts")
    if (
        not isinstance(contracts_raw, list)
        or not contracts_raw
        or not all(isinstance(value, str) and value.strip() for value in contracts_raw)
    ):
        raise ExceptionLedgerError(f"{context}: contracts must be a non-empty string array")
    contracts = tuple(value.strip() for value in contracts_raw)
    if len(set(contracts)) != len(contracts):
        raise ExceptionLedgerError(f"{context}: contracts contains duplicates")
    return ImportEdgeDebt(
        id=debt_id,
        edge=edge,
        contracts=contracts,
        **_validate_common(row, context=context),
    )


def _parse_ruff_debt(row: Mapping[str, Any], index: int) -> RuffDebt:
    context = f"ruff_debt[{index}]"
    unknown = set(row) - _RUFF_FIELDS
    missing = _RUFF_FIELDS - set(row)
    if unknown or missing:
        raise ExceptionLedgerError(
            f"{context}: schema mismatch; missing={sorted(missing)}, unknown={sorted(unknown)}"
        )
    debt_id = _required_string(row, "id", context=context)
    rule = _required_string(row, "rule", context=context)
    mode = _required_string(row, "mode", context=context)
    path = _required_string(row, "path", context=context)
    symbol = _required_string(row, "symbol", context=context)
    observed = row.get("observed")
    if _RUFF_ID_PATTERN.fullmatch(debt_id) is None:
        raise ExceptionLedgerError(f"{context}: invalid id {debt_id!r}")
    if rule not in _RUFF_RULE_BY_CODE:
        raise ExceptionLedgerError(f"{context}: unsupported Ruff rule {rule!r}")
    if mode not in {"ceiling", "override"}:
        raise ExceptionLedgerError(f"{context}: mode must be ceiling or override")
    candidate = Path(path)
    if candidate.is_absolute() or ".." in candidate.parts or candidate.suffix != ".py":
        raise ExceptionLedgerError(f"{context}: path must be a repository-relative Python file")
    if _SYMBOL_PATTERN.fullmatch(symbol) is None:
        raise ExceptionLedgerError(f"{context}: invalid symbol {symbol!r}")
    if not isinstance(observed, int) or isinstance(observed, bool) or observed <= 0:
        raise ExceptionLedgerError(f"{context}: observed must be a positive integer")
    return RuffDebt(
        id=debt_id,
        rule=rule,
        mode=mode,
        path=candidate.as_posix(),
        symbol=symbol,
        observed=observed,
        **_validate_common(row, context=context),
    )


def parse_ledger(raw: Mapping[str, Any]) -> ExceptionLedger:
    """Parse and strictly validate one ledger document."""
    if set(raw) != {"schema_version", "import_edge", "ruff_debt"}:
        raise ExceptionLedgerError(
            "ledger top-level keys must be schema_version, import_edge, and ruff_debt"
        )
    schema_version = raw.get("schema_version")
    if (
        not isinstance(schema_version, int)
        or isinstance(schema_version, bool)
        or schema_version != 1
    ):
        raise ExceptionLedgerError("schema_version must be integer 1")
    imports = tuple(
        _parse_import_edge(row, index)
        for index, row in enumerate(_table_rows(raw, "import_edge"), start=1)
    )
    ruff = tuple(
        _parse_ruff_debt(row, index)
        for index, row in enumerate(_table_rows(raw, "ruff_debt"), start=1)
    )
    ids = [debt.id for debt in imports] + [debt.id for debt in ruff]
    if len(ids) != len(set(ids)):
        raise ExceptionLedgerError("exception IDs must be unique")
    edges = [debt.edge for debt in imports]
    if len(edges) != len(set(edges)):
        raise ExceptionLedgerError("import_edge entries must own unique edges")
    symbols = [(debt.rule, debt.path, debt.symbol) for debt in ruff]
    if len(symbols) != len(set(symbols)):
        raise ExceptionLedgerError("ruff_debt entries must own unique rule/path/symbol tuples")
    return ExceptionLedger(import_edges=imports, ruff_debts=ruff)


def load_ledger(path: Path) -> ExceptionLedger:
    """Load one TOML ledger."""
    with path.open("rb") as handle:
        raw = tomllib.load(handle)
    return parse_ledger(raw)


def _load_pyproject_text(text: str, *, context: str) -> Mapping[str, Any]:
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ExceptionLedgerError(f"{context}: invalid TOML: {exc}") from exc
    if not isinstance(raw, dict):
        raise ExceptionLedgerError(f"{context}: expected a TOML table")
    return raw


def _nested_int(raw: Mapping[str, Any], path: tuple[str, ...]) -> int:
    current: Any = raw
    for key in path:
        if not isinstance(current, dict) or key not in current:
            raise ExceptionLedgerError(f"pyproject missing {'.'.join(path)}")
        current = current[key]
    if not isinstance(current, int) or isinstance(current, bool) or current <= 0:
        raise ExceptionLedgerError(f"pyproject {'.'.join(path)} must be a positive integer")
    return current


def configured_ruff_limits(pyproject: Mapping[str, Any]) -> dict[str, int]:
    """Read every governed Ruff ceiling from pyproject."""
    return {spec.rule: _nested_int(pyproject, spec.config_path) for spec in RUFF_RULES}


def _import_contract_pairs(
    pyproject: Mapping[str, Any],
) -> tuple[set[tuple[str, str]], list[str]]:
    errors: list[str] = []
    try:
        import_linter = pyproject["tool"]["importlinter"]
    except (KeyError, TypeError):
        raise ExceptionLedgerError("pyproject missing tool.importlinter") from None
    contracts = import_linter.get("contracts") if isinstance(import_linter, dict) else None
    if not isinstance(contracts, list):
        raise ExceptionLedgerError("tool.importlinter.contracts must be an array")
    pairs: list[tuple[str, str]] = []
    names: set[str] = set()
    for index, contract in enumerate(contracts, start=1):
        if not isinstance(contract, dict):
            errors.append(f"import-linter contract {index} is not a table")
            continue
        name = contract.get("name")
        ignores = contract.get("ignore_imports", [])
        if not isinstance(name, str) or not name:
            errors.append(f"import-linter contract {index} has no name")
            continue
        if name in names:
            errors.append(f"duplicate import-linter contract name: {name}")
        names.add(name)
        if not isinstance(ignores, list) or not all(isinstance(edge, str) for edge in ignores):
            errors.append(f"{name}: ignore_imports must be a string array")
            continue
        pairs.extend((name, edge) for edge in ignores)
    duplicate_pairs = sorted(pair for pair in set(pairs) if pairs.count(pair) > 1)
    errors.extend(f"duplicate ignored import pair: {pair}" for pair in duplicate_pairs)
    return set(pairs), errors


def _module_exists(root: Path, module: str) -> bool:
    candidate = root.joinpath(*module.split("."))
    return candidate.is_dir() or candidate.with_suffix(".py").is_file()


def validate_import_edges(
    root: Path,
    pyproject: Mapping[str, Any],
    ledger: ExceptionLedger,
) -> list[str]:
    """Require exact parity between import-linter ignores and debt records."""
    configured, errors = _import_contract_pairs(pyproject)
    registered = {
        (contract, debt.edge) for debt in ledger.import_edges for contract in debt.contracts
    }
    for contract, edge in sorted(configured - registered):
        errors.append(f"unregistered import exception: {contract}: {edge}")
    for contract, edge in sorted(registered - configured):
        errors.append(f"stale import exception record: {contract}: {edge}")
    for debt in ledger.import_edges:
        source, target = debt.edge.split(" -> ", maxsplit=1)
        if not _module_exists(root, source):
            errors.append(f"{debt.id}: source module does not exist: {source}")
        if not _module_exists(root, target):
            errors.append(f"{debt.id}: target module does not exist: {target}")
        if not _module_exists(root, debt.owner):
            errors.append(f"{debt.id}: owner module does not exist: {debt.owner}")
    return errors


def _selectors(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, str))


def _selector_covers(selector: str, rule: str) -> bool:
    normalized = selector.strip().upper()
    return normalized == "ALL" or rule.startswith(normalized)


def validate_ruff_selection(pyproject: Mapping[str, Any]) -> list[str]:
    """Reject broad config ignores that would bypass the governed rules."""
    errors: list[str] = []
    try:
        lint = pyproject["tool"]["ruff"]["lint"]
    except (KeyError, TypeError):
        return ["pyproject missing tool.ruff.lint"]
    if not isinstance(lint, dict):
        return ["tool.ruff.lint must be a table"]
    selected = (*_selectors(lint.get("select")), *_selectors(lint.get("extend-select")))
    ignored = (*_selectors(lint.get("ignore")), *_selectors(lint.get("extend-ignore")))
    per_file_settings: list[tuple[str, Mapping[str, Any]]] = []
    for setting in ("per-file-ignores", "extend-per-file-ignores"):
        configured = lint.get(setting, {})
        if not isinstance(configured, dict):
            errors.append(f"tool.ruff.lint.{setting} must be a table")
            continue
        per_file_settings.append((setting, configured))
    for rule in _RUFF_RULE_BY_CODE:
        if not any(_selector_covers(selector, rule) for selector in selected):
            errors.append(f"{rule}: governed Ruff rule is not selected")
        covering_ignore = next(
            (selector for selector in ignored if _selector_covers(selector, rule)),
            None,
        )
        if covering_ignore is not None:
            errors.append(f"{rule}: broad Ruff ignore {covering_ignore!r} bypasses the ratchet")
        for setting, per_file in per_file_settings:
            for pattern, raw_selectors in per_file.items():
                if str(pattern).startswith("tests/"):
                    # The metric probe deliberately governs production/scripts
                    # only; test fixtures retain their existing complexity policy.
                    continue
                if any(_selector_covers(selector, rule) for selector in _selectors(raw_selectors)):
                    errors.append(f"{rule}: {setting} {pattern!r} bypasses the ratchet")
    return errors


def _qualified_symbol(path: Path, line: int) -> str:
    module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    def find(node: ast.AST, prefix: tuple[str, ...]) -> str | None:
        nested_prefix = prefix
        if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            nested_prefix = (*prefix, node.name)
            if node.lineno == line:
                return ".".join(nested_prefix)
        for child in ast.iter_child_nodes(node):
            nested = find(child, nested_prefix)
            if nested is not None:
                return nested
        return None

    symbol = find(module, ())
    if symbol is None:
        raise ExceptionLedgerError(f"{path}: no class/function symbol at Ruff line {line}")
    return symbol


def _ruff_executable() -> str | None:
    sibling = Path(sys.executable).with_name("ruff")
    if sibling.is_file():
        return str(sibling)
    return shutil.which("ruff")


def _production_python_files(root: Path) -> tuple[str, ...]:
    root_resolved = root.resolve()
    files: list[str] = []
    for source_root in ("core", "plugins", "scripts"):
        for candidate in sorted((root / source_root).rglob("*.py")):
            if not candidate.is_file():
                continue
            absolute = candidate.resolve()
            try:
                relative = absolute.relative_to(root_resolved)
            except ValueError as exc:
                raise ExceptionLedgerError(
                    f"production Python file escaped repository: {candidate}"
                ) from exc
            files.append(relative.as_posix())
    if not files:
        raise ExceptionLedgerError("no production Python files found for Ruff metric probe")
    return tuple(files)


def _run_ruff(root: Path, limits: Mapping[str, int]) -> tuple[RuffMeasurement, ...]:
    ruff = _ruff_executable()
    if ruff is None:
        raise ExceptionLedgerError("ruff executable is unavailable")
    args = [
        ruff,
        "check",
        "--isolated",
        "--no-force-exclude",
        "--target-version",
        "py312",
        "--select",
        ",".join(spec.rule for spec in RUFF_RULES),
        "--ignore-noqa",
        "--output-format",
        "json",
        "--exit-zero",
        "--no-cache",
    ]
    for spec in RUFF_RULES:
        probe = max(0, limits[spec.rule] - 1)
        args.extend(("--config", f"{spec.override_key}={probe}"))
    args.extend(_production_python_files(root))
    process = subprocess.run(  # noqa: S603 — resolved executable + fixed repository arguments
        args,
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if process.returncode != 0:
        detail = process.stderr.strip() or f"exit {process.returncode}"
        raise ExceptionLedgerError(f"Ruff metric probe failed: {detail}")
    try:
        diagnostics = json.loads(process.stdout)
    except json.JSONDecodeError as exc:
        raise ExceptionLedgerError(f"Ruff metric probe returned invalid JSON: {exc}") from exc
    if not isinstance(diagnostics, list):
        raise ExceptionLedgerError("Ruff metric probe JSON must be an array")

    measurements: list[RuffMeasurement] = []
    root_resolved = root.resolve()
    for diagnostic in diagnostics:
        if not isinstance(diagnostic, dict):
            raise ExceptionLedgerError("Ruff metric diagnostic must be an object")
        rule = diagnostic.get("code")
        if rule not in _RUFF_RULE_BY_CODE:
            continue
        message = diagnostic.get("message")
        filename = diagnostic.get("filename")
        location = diagnostic.get("location")
        if not isinstance(message, str) or not isinstance(filename, str):
            raise ExceptionLedgerError(f"{rule}: incomplete Ruff diagnostic")
        matched = _METRIC_PATTERN.search(message)
        if matched is None:
            raise ExceptionLedgerError(f"{rule}: cannot parse metric from {message!r}")
        if not isinstance(location, dict) or not isinstance(location.get("row"), int):
            raise ExceptionLedgerError(f"{rule}: diagnostic has no source row")
        absolute = Path(filename).resolve()
        try:
            relative = absolute.relative_to(root_resolved)
        except ValueError as exc:
            raise ExceptionLedgerError(
                f"{rule}: diagnostic escaped repository: {filename}"
            ) from exc
        row = location["row"]
        noqa_row = diagnostic.get("noqa_row", row)
        if not isinstance(noqa_row, int):
            noqa_row = row
        measurements.append(
            RuffMeasurement(
                rule=rule,
                path=relative.as_posix(),
                symbol=_qualified_symbol(absolute, row),
                observed=int(matched.group("metric")),
                noqa_row=noqa_row,
            )
        )
    return tuple(measurements)


def _has_specific_noqa(root: Path, measurement: RuffMeasurement) -> bool:
    path = root / measurement.path
    lines = path.read_text(encoding="utf-8").splitlines()
    if measurement.noqa_row <= 0 or measurement.noqa_row > len(lines):
        return False
    matched = _NOQA_PATTERN.search(lines[measurement.noqa_row - 1])
    if matched is None:
        return False
    selectors = _RULE_CODE_PATTERN.findall(matched.group("selectors").upper())
    return measurement.rule in selectors


def validate_ruff_debt(
    root: Path,
    limits: Mapping[str, int],
    ledger: ExceptionLedger,
    measurements: Sequence[RuffMeasurement],
) -> list[str]:
    """Require exact ceiling-witness/override parity for every Ruff rule."""
    errors: list[str] = []
    measured_by_rule: dict[str, list[RuffMeasurement]] = defaultdict(list)
    debt_by_rule: dict[str, list[RuffDebt]] = defaultdict(list)
    for measurement in measurements:
        measured_by_rule[measurement.rule].append(measurement)
    for debt in ledger.ruff_debts:
        debt_by_rule[debt.rule].append(debt)
        if not (root / debt.path).is_file():
            errors.append(f"{debt.id}: Ruff debt path does not exist: {debt.path}")
        if not _module_exists(root, debt.owner):
            errors.append(f"{debt.id}: owner module does not exist: {debt.owner}")

    for rule, limit in limits.items():
        relevant = measured_by_rule.get(rule, [])
        ceiling = [measurement for measurement in relevant if measurement.observed == limit]
        overrides = [measurement for measurement in relevant if measurement.observed > limit]
        below = [measurement for measurement in relevant if measurement.observed < limit]
        if below:
            errors.append(f"{rule}: Ruff probe returned metrics below its requested floor")
        if not ceiling:
            errors.append(
                f"{rule}: configured ceiling {limit} is stale; "
                "lower it to the current measured maximum"
            )

        expected = {
            (
                measurement.path,
                measurement.symbol,
                measurement.observed,
                "override" if measurement.observed > limit else "ceiling",
            )
            for measurement in (*ceiling, *overrides)
        }
        registered = {
            (debt.path, debt.symbol, debt.observed, debt.mode)
            for debt in debt_by_rule.get(rule, [])
        }
        for item in sorted(expected - registered):
            errors.append(f"{rule}: unregistered Ruff symbol debt: {item}")
        for item in sorted(registered - expected):
            errors.append(f"{rule}: stale Ruff symbol debt: {item}")
        for measurement in overrides:
            if not _has_specific_noqa(root, measurement):
                errors.append(
                    f"{rule}: override {measurement.path}:{measurement.symbol} "
                    "must use a rule-specific noqa"
                )
    return errors


def _valid_targets(root: Path) -> set[str]:
    text = (root / ROADMAP_RELATIVE).read_text(encoding="utf-8")
    gaps = set(re.findall(r"(?m)^\| ([A-Z]+-\d{3}) \|", text))
    packages = set(re.findall(r"(?m)^#### (R\d+\.\d+)(?:\s|$)", text))
    return gaps | packages


def validate_metadata_targets(root: Path, ledger: ExceptionLedger) -> list[str]:
    """Reject debt records that point at no current closure target."""
    valid = _valid_targets(root)
    import_errors = [
        f"{debt.id}: unknown target {debt.target}"
        for debt in ledger.import_edges
        if debt.target not in valid
    ]
    ruff_errors = [
        f"{debt.id}: unknown target {debt.target}"
        for debt in ledger.ruff_debts
        if debt.target not in valid
    ]
    return import_errors + ruff_errors


def validate_threshold_ratchet(
    current: Mapping[str, int],
    base: Mapping[str, int],
) -> list[str]:
    """Reject increases relative to the target branch."""
    return [
        f"{rule}: Ruff ceiling increased {base[rule]} -> {current[rule]}"
        for rule in current
        if current[rule] > base[rule]
    ]


def _git_show(root: Path, ref: str, relative: Path) -> str:
    try:
        process = run_git(["show", f"{ref}:{relative.as_posix()}"], cwd=root)
    except GitExecutableNotFoundError:
        raise ExceptionLedgerError("git is required for base-relative validation") from None
    if process.returncode != 0:
        detail = process.stderr.strip() or f"git show exited {process.returncode}"
        raise ExceptionLedgerError(f"cannot read {relative} from {ref}: {detail}")
    return process.stdout


def check_repository(root: Path, *, base_ref: str | None = None) -> list[str]:
    """Run every exception-debt invariant against ``root``."""
    ledger = load_ledger(root / LEDGER_RELATIVE)
    pyproject_text = (root / PYPROJECT_RELATIVE).read_text(encoding="utf-8")
    pyproject = _load_pyproject_text(pyproject_text, context=str(PYPROJECT_RELATIVE))
    limits = configured_ruff_limits(pyproject)
    errors = [
        *validate_import_edges(root, pyproject, ledger),
        *validate_ruff_selection(pyproject),
        *validate_metadata_targets(root, ledger),
    ]
    measurements = _run_ruff(root, limits)
    errors.extend(validate_ruff_debt(root, limits, ledger, measurements))
    if base_ref is not None:
        base_text = _git_show(root, base_ref, PYPROJECT_RELATIVE)
        base_pyproject = _load_pyproject_text(base_text, context=f"{base_ref}:pyproject.toml")
        errors.extend(
            validate_threshold_ratchet(
                limits,
                configured_ruff_limits(base_pyproject),
            )
        )
    return errors


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="validate without writing")
    parser.add_argument(
        "--base-ref",
        help="optional git ref whose Ruff ceilings may not be increased",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.check:
        print("architecture exceptions: --check is required", file=sys.stderr)
        return 2
    try:
        errors = check_repository(REPO_ROOT, base_ref=args.base_ref)
        ledger = load_ledger(REPO_ROOT / LEDGER_RELATIVE)
    except (ExceptionLedgerError, OSError, tomllib.TOMLDecodeError) as exc:
        print(f"architecture exceptions: {exc}", file=sys.stderr)
        return 2
    if errors:
        print("architecture exceptions FAILED:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    occurrences = sum(len(debt.contracts) for debt in ledger.import_edges)
    ceiling_count = sum(debt.mode == "ceiling" for debt in ledger.ruff_debts)
    override_count = sum(debt.mode == "override" for debt in ledger.ruff_debts)
    print(
        "architecture exceptions OK "
        f"({len(ledger.import_edges)} import edges / {occurrences} contract occurrences; "
        f"{ceiling_count} Ruff ceilings / {override_count} overrides)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
