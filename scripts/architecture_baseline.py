#!/usr/bin/env python3
"""Generate and verify GEODE's deterministic architecture inventory.

The committed JSON artifact is the machine-readable source for the public site.
Two small generated Markdown blocks consume the same in-memory snapshot:

* ``AGENTS.md`` — the code-root orientation summary;
* ``docs/architecture/extensibility-roadmap.md`` §2.1 — the program baseline.

No timestamp or git commit is embedded, so equal source trees produce byte-for-
byte equal output.  ``--check`` never writes and exits non-zero on drift;
``--update`` refreshes all three consumers in one operation.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_FILE = REPO_ROOT / "site" / "src" / "data" / "geode" / "architecture-baseline.json"
AGENTS_FILE = REPO_ROOT / "AGENTS.md"
ROADMAP_FILE = REPO_ROOT / "docs" / "architecture" / "extensibility-roadmap.md"

AGENTS_START = "<!-- generated:architecture-baseline:start -->"
AGENTS_END = "<!-- generated:architecture-baseline:end -->"
ROADMAP_START = "<!-- generated:architecture-baseline:start -->"
ROADMAP_END = "<!-- generated:architecture-baseline:end -->"

PACKAGE_ROOTS: tuple[str, ...] = ("core", "plugins", "tests")


@dataclass(frozen=True)
class PythonInventory:
    """Python file and physical-line counts for one repository subtree."""

    files: int
    loc: int


def _python_files(root: Path, relative: str) -> list[Path]:
    """Return deterministic Python paths, excluding generated cache trees."""
    base = root / relative
    return sorted(
        path
        for path in base.rglob("*.py")
        if "__pycache__" not in path.parts and ".venv" not in path.parts
    )


def measure_python_inventory(root: Path, relative: str) -> PythonInventory:
    """Count Python files and physical lines beneath ``relative``."""
    paths = _python_files(root, relative)
    return PythonInventory(
        files=len(paths),
        loc=sum(len(path.read_text(encoding="utf-8").splitlines()) for path in paths),
    )


def _parse_python(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _class_node(path: Path, class_name: str) -> ast.ClassDef:
    module = _parse_python(path)
    for node in module.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return node
    raise ValueError(f"{path}: class {class_name!r} not found")


def _constructor_arg_count(node: ast.ClassDef) -> int:
    init = next(
        (
            child
            for child in node.body
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef)
            and child.name == "__init__"
        ),
        None,
    )
    if init is None:
        return 0
    args = [*init.args.posonlyargs, *init.args.args, *init.args.kwonlyargs]
    if args and args[0].arg in {"self", "cls"}:
        args = args[1:]
    return len(args)


def _coordinator_metrics(root: Path) -> dict[str, dict[str, int | str]]:
    specs = (
        ("AgenticLoop", "core/agent/loop/agent_loop.py"),
        ("SubAgentManager", "core/agent/sub_agent.py"),
    )
    result: dict[str, dict[str, int | str]] = {}
    for class_name, relative in specs:
        path = root / relative
        node = _class_node(path, class_name)
        methods = [
            child
            for child in node.body
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef)
        ]
        result[class_name] = {
            "path": relative,
            "file_loc": len(path.read_text(encoding="utf-8").splitlines()),
            "method_count": len(methods),
            "constructor_arg_count": _constructor_arg_count(node),
        }

    runtime_path = root / "core/runtime.py"
    runtime_node = _class_node(runtime_path, "RuntimeCoreConfig")
    result["RuntimeCoreConfig"] = {
        "path": "core/runtime.py",
        "field_count": sum(isinstance(child, ast.AnnAssign) for child in runtime_node.body),
    }
    return result


def _hook_events(root: Path) -> dict[str, Any]:
    path = root / "core/hooks/system.py"
    node = _class_node(path, "HookEvent")
    members: list[str] = []
    for child in node.body:
        if isinstance(child, ast.Assign):
            members.extend(target.id for target in child.targets if isinstance(target, ast.Name))
        elif isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name):
            members.append(child.target.id)
    return {"count": len(members), "members": members}


def _built_in_adapters(root: Path) -> dict[str, Any]:
    path = root / "core/llm/adapters/registry.py"
    module = _parse_python(path)
    bootstrap = next(
        (
            node
            for node in module.body
            if isinstance(node, ast.FunctionDef) and node.name == "bootstrap_builtins"
        ),
        None,
    )
    if bootstrap is None:
        raise ValueError(f"{path}: bootstrap_builtins() not found")

    classes: list[str] = []
    for node in ast.walk(bootstrap):
        if not isinstance(node, ast.For):
            continue
        if not isinstance(node.target, ast.Name) or node.target.id != "adapter_cls":
            continue
        if not isinstance(node.iter, ast.Tuple):
            continue
        classes.extend(item.id for item in node.iter.elts if isinstance(item, ast.Name))
    if not classes:
        raise ValueError(f"{path}: built-in adapter tuple not found")
    return {"count": len(classes), "classes": classes}


def _context_vars(root: Path) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for path in _python_files(root, "core"):
        module = _parse_python(path)
        for node in module.body:
            symbol: str | None = None
            value: ast.expr | None = None
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                target = node.targets[0]
                if isinstance(target, ast.Name):
                    symbol = target.id
                    value = node.value
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                symbol = node.target.id
                value = node.value
            if symbol is None or not isinstance(value, ast.Call):
                continue
            function = value.func
            is_context_var = (isinstance(function, ast.Name) and function.id == "ContextVar") or (
                isinstance(function, ast.Attribute)
                and isinstance(function.value, ast.Name)
                and function.value.id == "contextvars"
                and function.attr == "ContextVar"
            )
            if not is_context_var:
                continue
            context_name = ""
            if value.args and isinstance(value.args[0], ast.Constant):
                raw_name = value.args[0].value
                if isinstance(raw_name, str):
                    context_name = raw_name
            items.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "line": node.lineno,
                    "symbol": symbol,
                    "context_name": context_name,
                    "has_default": any(keyword.arg == "default" for keyword in value.keywords),
                }
            )
    items.sort(key=lambda item: (item["path"], item["line"], item["symbol"]))
    return {"count": len(items), "items": items}


def _plugins_imports(root: Path) -> dict[str, Any]:
    sites: list[dict[str, Any]] = []
    for path in _python_files(root, "core"):
        for node in ast.walk(_parse_python(path)):
            modules: list[str] = []
            site_line = 0
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names if alias.name.startswith("plugins")]
                site_line = node.lineno
            elif (
                isinstance(node, ast.ImportFrom)
                and node.module is not None
                and node.module.startswith("plugins")
            ):
                modules = [node.module]
                site_line = node.lineno
            for module in modules:
                sites.append(
                    {
                        "path": path.relative_to(root).as_posix(),
                        "line": site_line,
                        "module": module,
                    }
                )
    sites.sort(key=lambda item: (item["path"], item["line"], item["module"]))
    return {
        "site_count": len(sites),
        "file_count": len({item["path"] for item in sites}),
        "sites": sites,
    }


def _import_linter(root: Path) -> dict[str, Any]:
    with (root / "pyproject.toml").open("rb") as handle:
        config = tomllib.load(handle)
    raw_contracts = config["tool"]["importlinter"].get("contracts", [])
    contracts: list[dict[str, Any]] = []
    for raw in raw_contracts:
        ignores = raw.get("ignore_imports", [])
        contracts.append(
            {
                "name": str(raw["name"]),
                "ignored_edges": sorted(str(edge) for edge in ignores),
            }
        )
    return {
        "contract_count": len(contracts),
        "ignored_edge_count": sum(len(item["ignored_edges"]) for item in contracts),
        "contracts": contracts,
    }


def _complexity_thresholds(root: Path) -> dict[str, int]:
    with (root / "pyproject.toml").open("rb") as handle:
        config = tomllib.load(handle)
    lint = config["tool"]["ruff"]["lint"]
    pylint = lint["pylint"]
    return {
        "max_complexity": int(lint["mccabe"]["max-complexity"]),
        "max_args": int(pylint["max-args"]),
        "max_branches": int(pylint["max-branches"]),
        "max_returns": int(pylint["max-returns"]),
        "max_statements": int(pylint["max-statements"]),
    }


def _schema_errors(definition: object) -> list[str]:
    if not isinstance(definition, dict):
        return ["entry is not an object"]
    name = definition.get("name", "<unknown>")
    errors: list[str] = []
    for key in ("name", "description", "category", "cost_tier"):
        if not isinstance(definition.get(key), str) or not definition[key]:
            errors.append(f"{name}: {key} must be a non-empty string")
    schema = definition.get("input_schema")
    if not isinstance(schema, dict):
        return [*errors, f"{name}: input_schema must be an object"]
    errors.extend(f"{name}: {error}" for error in _json_schema_errors(schema))
    if schema.get("type") != "object":
        errors.append(f"{name}: input_schema.type must be 'object'")
    properties = schema.get("properties")
    if properties is None:
        errors.append(f"{name}: input_schema.properties must be an object")
    required = schema.get("required")
    if required is None:
        errors.append(f"{name}: input_schema.required must be a string array")
    return errors


def _json_schema_errors(schema: dict[str, Any], path: str = "input_schema") -> list[str]:
    """Validate the JSON-Schema subset used by native tool definitions."""
    errors: list[str] = []
    allowed_types = {"null", "boolean", "object", "array", "number", "integer", "string"}
    schema_type = schema.get("type")
    declared_types: set[str] = set()
    if schema_type is not None:
        if isinstance(schema_type, str):
            declared_types = {schema_type}
        elif (
            isinstance(schema_type, list)
            and schema_type
            and all(isinstance(value, str) for value in schema_type)
        ):
            declared_types = set(schema_type)
        else:
            errors.append(f"{path}.type must be a string or non-empty string array")
        unknown_types = sorted(declared_types - allowed_types)
        if unknown_types:
            errors.append(f"{path}.type has unsupported values: {unknown_types}")

    properties = schema.get("properties")
    if properties is not None:
        if not isinstance(properties, dict):
            errors.append(f"{path}.properties must be an object")
        else:
            for property_name, property_schema in properties.items():
                property_path = f"{path}.properties.{property_name}"
                if not isinstance(property_schema, dict):
                    errors.append(f"{property_path} must be an object")
                else:
                    errors.extend(_json_schema_errors(property_schema, property_path))

    required = schema.get("required")
    if required is not None:
        if not isinstance(required, list) or not all(isinstance(item, str) for item in required):
            errors.append(f"{path}.required must be a string array")
        else:
            duplicate_required = sorted(item for item in set(required) if required.count(item) > 1)
            if duplicate_required:
                errors.append(f"{path}.required contains duplicates: {duplicate_required}")
            if isinstance(properties, dict):
                unknown_required = sorted(set(required) - set(properties))
                if unknown_required:
                    errors.append(
                        f"{path}.required keys absent from properties: {unknown_required}"
                    )

    items = schema.get("items")
    if items is not None:
        if not isinstance(items, dict):
            errors.append(f"{path}.items must be an object")
        else:
            errors.extend(_json_schema_errors(items, f"{path}.items"))
        if declared_types and "array" not in declared_types:
            errors.append(f"{path}.items requires type 'array'")

    additional = schema.get("additionalProperties")
    if additional is not None and not isinstance(additional, bool | dict):
        errors.append(f"{path}.additionalProperties must be a boolean or object")
    elif isinstance(additional, dict):
        errors.extend(_json_schema_errors(additional, f"{path}.additionalProperties"))

    enum = schema.get("enum")
    if enum is not None:
        if not isinstance(enum, list) or not enum:
            errors.append(f"{path}.enum must be a non-empty array")
        elif len({json.dumps(value, sort_keys=True) for value in enum}) != len(enum):
            errors.append(f"{path}.enum contains duplicate values")

    for bound in ("minimum", "maximum"):
        value = schema.get(bound)
        if value is not None and (not isinstance(value, int | float) or isinstance(value, bool)):
            errors.append(f"{path}.{bound} must be numeric")
    minimum = schema.get("minimum")
    maximum = schema.get("maximum")
    if (
        isinstance(minimum, int | float)
        and not isinstance(minimum, bool)
        and isinstance(maximum, int | float)
        and not isinstance(maximum, bool)
        and minimum > maximum
    ):
        errors.append(f"{path}.minimum exceeds maximum")

    pattern = schema.get("pattern")
    if pattern is not None:
        if not isinstance(pattern, str):
            errors.append(f"{path}.pattern must be a string")
        else:
            try:
                re.compile(pattern)
            except re.error:
                errors.append(f"{path}.pattern is not a valid regular expression")
    if "format" in schema and not isinstance(schema["format"], str):
        errors.append(f"{path}.format must be a string")
    return errors


def _tool_inventory(root: Path) -> dict[str, Any]:
    definitions_raw = json.loads((root / "core/tools/definitions.json").read_text(encoding="utf-8"))
    if not isinstance(definitions_raw, list):
        raise ValueError("core/tools/definitions.json must contain a list")

    definition_names = [
        str(item.get("name", "")) for item in definitions_raw if isinstance(item, dict)
    ]
    duplicate_names = sorted(
        name for name in set(definition_names) if definition_names.count(name) > 1
    )
    schema_errors = [
        error for definition in definitions_raw for error in _schema_errors(definition)
    ]
    schema_names = sorted(
        str(definition["name"])
        for definition in definitions_raw
        if isinstance(definition, dict) and not _schema_errors(definition)
    )

    # These imports resolve the actual runtime composition path.  They do not
    # instantiate tools or touch credentials; builders return handler closures.
    from core.agent.tool_executor.executor import SPECIAL_EXECUTION_BINDINGS
    from core.cli.tool_handlers import _build_tool_handler_catalog
    from core.llm.tool_defer import TOOL_SEARCH_ALWAYS_LOADED

    handler_catalog = _build_tool_handler_catalog()
    handler_names = sorted(handler_catalog.handlers)
    execution_names = sorted(set(handler_names) | set(SPECIAL_EXECUTION_BINDINGS))
    definitions = set(definition_names)
    schemas = set(schema_names)
    executions = set(execution_names)
    always_loaded = set(TOOL_SEARCH_ALWAYS_LOADED)
    definition_only = sorted(definitions - executions)
    invalid_schemas = sorted(definitions - schemas)
    unknown_always_loaded = sorted(always_loaded - definitions)

    fatal_errors: list[str] = []
    if duplicate_names:
        fatal_errors.append(f"duplicate definitions: {duplicate_names}")
    if schema_errors:
        fatal_errors.append(f"invalid schemas: {schema_errors}")
    if definition_only:
        fatal_errors.append(f"definitions without execution bindings: {definition_only}")
    if invalid_schemas:
        fatal_errors.append(f"definitions without valid schemas: {invalid_schemas}")
    if unknown_always_loaded:
        fatal_errors.append(f"unknown always-loaded tools: {unknown_always_loaded}")
    if fatal_errors:
        raise ValueError("tool inventory invariant failed; " + "; ".join(fatal_errors))

    return {
        "definition_count": len(definition_names),
        "definition_names": sorted(definition_names),
        "duplicate_definition_names": duplicate_names,
        "schema_count": len(schema_names),
        "schema_names": schema_names,
        "schema_errors": schema_errors,
        "handler_registration_count": len(handler_names),
        "handler_registration_names": handler_names,
        "handler_registration_origins": {
            name: handler_catalog.origins[name] for name in handler_names
        },
        "special_execution_bindings": sorted(SPECIAL_EXECUTION_BINDINGS),
        "execution_registration_count": len(execution_names),
        "execution_registration_names": execution_names,
        "definition_only": definition_only,
        "execution_only": sorted(executions - definitions),
        "definition_without_valid_schema": invalid_schemas,
        "schema_without_definition": sorted(schemas - definitions),
        "exact_parity": definitions == executions == schemas and not duplicate_names,
        "deferred_loading": {
            "always_loaded_count": len(always_loaded),
            "always_loaded_names": sorted(always_loaded),
            "unknown_always_loaded_names": unknown_always_loaded,
        },
    }


def build_baseline(root: Path = REPO_ROOT) -> dict[str, Any]:
    """Measure every R0.2 inventory surface from one source tree."""
    packages = {
        relative: {
            "python_files": inventory.files,
            "python_loc": inventory.loc,
        }
        for relative in PACKAGE_ROOTS
        if (inventory := measure_python_inventory(root, relative))
    }
    return {
        "schema_version": 1,
        "packages": packages,
        "tools": _tool_inventory(root),
        "hook_events": _hook_events(root),
        "built_in_adapters": _built_in_adapters(root),
        "context_vars": _context_vars(root),
        "core_to_plugins_imports": _plugins_imports(root),
        "import_linter": _import_linter(root),
        "coordinators": _coordinator_metrics(root),
        "complexity_thresholds": _complexity_thresholds(root),
    }


def serialize_baseline(baseline: dict[str, Any]) -> str:
    return json.dumps(baseline, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _number(value: int) -> str:
    return f"{value:,}"


def render_agents_block(baseline: dict[str, Any]) -> str:
    packages = baseline["packages"]
    tools = baseline["tools"]
    production_files = packages["core"]["python_files"] + packages["plugins"]["python_files"]
    return "\n".join(
        (
            AGENTS_START,
            "The generated architecture inventory lives at",
            "`site/src/data/geode/architecture-baseline.json`. Refresh it with",
            "`uv run python scripts/architecture_baseline.py --update`; CI uses `--check`.",
            f"The current snapshot records {_number(production_files)} production Python files,",
            f"{_number(packages['tests']['python_files'])} test Python files,",
            f"{_number(tools['definition_count'])} tool definitions, and",
            f"{_number(baseline['hook_events']['count'])} `HookEvent` members.",
            AGENTS_END,
        )
    )


def render_roadmap_block(baseline: dict[str, Any]) -> str:
    packages = baseline["packages"]
    tools = baseline["tools"]
    imports = baseline["core_to_plugins_imports"]
    import_linter = baseline["import_linter"]
    coordinators = baseline["coordinators"]
    thresholds = baseline["complexity_thresholds"]
    production_files = packages["core"]["python_files"] + packages["plugins"]["python_files"]
    parity = (
        "exact"
        if tools["exact_parity"]
        else (
            f"definition-only {len(tools['definition_only'])}; "
            f"execution-only {len(tools['execution_only'])}; "
            f"invalid schema {len(tools['definition_without_valid_schema'])}"
        )
    )
    return "\n".join(
        (
            ROADMAP_START,
            "Generated by `scripts/architecture_baseline.py`; the canonical",
            "machine-readable artifact is",
            "`site/src/data/geode/architecture-baseline.json`.",
            "",
            "| Measure | Current tree |",
            "|---|---:|",
            f"| Production Python files (`core/` + `plugins/`) | {_number(production_files)} |",
            f"| Test Python files | {_number(packages['tests']['python_files'])} |",
            f"| `core/` Python LOC | {_number(packages['core']['python_loc'])} |",
            f"| `plugins/` Python LOC | {_number(packages['plugins']['python_loc'])} |",
            f"| Test Python LOC | {_number(packages['tests']['python_loc'])} |",
            (
                f"| Tool definitions / executable registrations / valid schemas "
                f"| {_number(tools['definition_count'])} / "
                f"{_number(tools['execution_registration_count'])} / "
                f"{_number(tools['schema_count'])} ({parity}) |"
            ),
            f"| `HookEvent` members | {_number(baseline['hook_events']['count'])} |",
            f"| Built-in LLM adapters | {_number(baseline['built_in_adapters']['count'])} |",
            (
                "| Module-level `ContextVar` declarations under `core/` | "
                f"{_number(baseline['context_vars']['count'])} |"
            ),
            (
                f"| `core` → `plugins` import sites | {_number(imports['site_count'])} "
                f"across {_number(imports['file_count'])} files |"
            ),
            (
                f"| Import-linter contracts / ignored edges | "
                f"{_number(import_linter['contract_count'])} / "
                f"{_number(import_linter['ignored_edge_count'])} |"
            ),
            (
                f"| `AgenticLoop` file LOC / methods / constructor args | "
                f"{_number(coordinators['AgenticLoop']['file_loc'])} / "
                f"{_number(coordinators['AgenticLoop']['method_count'])} / "
                f"{_number(coordinators['AgenticLoop']['constructor_arg_count'])} |"
            ),
            (
                f"| `SubAgentManager` file LOC / methods / constructor args | "
                f"{_number(coordinators['SubAgentManager']['file_loc'])} / "
                f"{_number(coordinators['SubAgentManager']['method_count'])} / "
                f"{_number(coordinators['SubAgentManager']['constructor_arg_count'])} |"
            ),
            (
                f"| `RuntimeCoreConfig` fields | "
                f"{_number(coordinators['RuntimeCoreConfig']['field_count'])} |"
            ),
            (
                "| Global Ruff ratchets | "
                f"complexity {thresholds['max_complexity']}; "
                f"args {thresholds['max_args']}; "
                f"branches {thresholds['max_branches']}; "
                f"returns {thresholds['max_returns']}; "
                f"statements {thresholds['max_statements']} |"
            ),
            ROADMAP_END,
        )
    )


def replace_managed_block(
    text: str,
    *,
    start_marker: str,
    end_marker: str,
    replacement: str,
    path: Path,
) -> str:
    """Replace exactly one generated block, failing closed on malformed prose."""
    start_count = text.count(start_marker)
    end_count = text.count(end_marker)
    if start_count != 1 or end_count != 1:
        raise ValueError(
            f"{path}: expected exactly one {start_marker!r}/{end_marker!r} block "
            f"(found {start_count}/{end_count})"
        )
    start = text.index(start_marker)
    end = text.index(end_marker, start) + len(end_marker)
    return f"{text[:start]}{replacement}{text[end:]}"


def expected_files(
    baseline: dict[str, Any],
    *,
    agents_file: Path = AGENTS_FILE,
    roadmap_file: Path = ROADMAP_FILE,
) -> dict[Path, str]:
    agents = replace_managed_block(
        agents_file.read_text(encoding="utf-8"),
        start_marker=AGENTS_START,
        end_marker=AGENTS_END,
        replacement=render_agents_block(baseline),
        path=agents_file,
    )
    roadmap = replace_managed_block(
        roadmap_file.read_text(encoding="utf-8"),
        start_marker=ROADMAP_START,
        end_marker=ROADMAP_END,
        replacement=render_roadmap_block(baseline),
        path=roadmap_file,
    )
    return {
        OUTPUT_FILE: serialize_baseline(baseline),
        agents_file: agents,
        roadmap_file: roadmap,
    }


def _drifted(expected: dict[Path, str]) -> list[Path]:
    return [
        path
        for path, content in expected.items()
        if not path.is_file() or path.read_text(encoding="utf-8") != content
    ]


def _write_all(expected: dict[Path, str]) -> None:
    for path, content in expected.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="fail when committed output drifts")
    mode.add_argument("--update", action="store_true", help="refresh every generated consumer")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        baseline = build_baseline()
        expected = expected_files(baseline)
    except (OSError, ValueError, KeyError, json.JSONDecodeError, tomllib.TOMLDecodeError) as error:
        print(f"architecture baseline: {error}", file=sys.stderr)
        return 2

    if args.update:
        _write_all(expected)
        print(
            "architecture baseline updated: "
            + ", ".join(path.relative_to(REPO_ROOT).as_posix() for path in expected)
        )
        return 0

    drifted = _drifted(expected)
    if drifted:
        print("architecture baseline drift:", file=sys.stderr)
        for path in drifted:
            print(f"  - {path.relative_to(REPO_ROOT).as_posix()}", file=sys.stderr)
        print(
            "run: uv run python scripts/architecture_baseline.py --update",
            file=sys.stderr,
        )
        return 1
    print("architecture baseline OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
