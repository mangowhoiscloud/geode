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
from collections import Counter
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_FILE = REPO_ROOT / "site" / "src" / "data" / "geode" / "architecture-baseline.json"
AGENTS_FILE = REPO_ROOT / "AGENTS.md"
ROADMAP_FILE = REPO_ROOT / "docs" / "architecture" / "extensibility-roadmap.md"
CONTEXT_VAR_LIFECYCLES = Path("docs/architecture/context-var-lifecycles.json")
CONTEXT_VAR_PROPAGATION_TEST = (
    "tests/scripts/test_architecture_baseline.py::test_context_var_inventory_propagates_and_resets"
)
CONTEXT_VAR_CLASSIFICATIONS = (
    "request_identity",
    "request_local_mutable_state",
    "diagnostic_scope",
    "cache",
    "service_locator",
)
CONTEXT_VAR_LIFECYCLE_FIELDS = (
    "classification",
    "owner",
    "setter",
    "resetter",
    "lifetime",
    "teardown",
)
CONTEXT_LOCAL_DEFINING_MODULE_CONSTRUCTORS = {
    "core.ui.context_local": {"ContextLocal": "ContextLocal"}
}

AGENTS_START = "<!-- generated:architecture-baseline:start -->"
AGENTS_END = "<!-- generated:architecture-baseline:end -->"
ROADMAP_START = "<!-- generated:architecture-baseline:start -->"
ROADMAP_END = "<!-- generated:architecture-baseline:end -->"

PACKAGE_ROOTS: tuple[str, ...] = ("core", "geode_product", "plugins", "tests")
PRODUCT_MODULE_ROOTS = ("geode_product", "plugins")
PRODUCT_MODULE_REFERENCE_RE = re.compile(
    r"^(?:geode_product|plugins)(?:\.[A-Za-z_][A-Za-z0-9_]*)+(?::[A-Za-z_][A-Za-z0-9_]*)?$"
)
SELF_IMPROVING_FACADE_TARGETS = {
    "core/self_improving/__init__.py": "geode_product.self_improving",
    "core/self_improving/campaign.py": "geode_product.self_improving.campaign",
    "core/self_improving/prepare.py": "geode_product.self_improving.prepare",
    "core/self_improving/train.py": "geode_product.self_improving.train",
    "core/self_improving/watch_campaign.py": "geode_product.self_improving.watch_campaign",
}


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
    node = _class_node(path, "RuntimeEvent")
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


def _module_scope_nodes(module: ast.Module) -> Iterator[tuple[ast.stmt, str]]:
    def walk(node: ast.AST, owner: str = "") -> Iterator[tuple[ast.stmt, str]]:
        if isinstance(node, ast.stmt):
            yield node, owner
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
            return
        if isinstance(node, ast.ClassDef):
            for statement in node.body:
                yield from walk(statement, f"{owner}{node.name}.")
            return
        for child in ast.iter_child_nodes(node):
            yield from walk(child, owner)

    for node in module.body:
        yield from walk(node)


def _scope_calls(
    node: ast.AST,
    *,
    include_annotations: bool = False,
) -> Iterator[ast.Call]:
    """Yield calls evaluated now, excluding deferred function and lambda bodies."""

    if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
        expressions = [*node.decorator_list, *node.args.defaults, *node.args.kw_defaults]
        if include_annotations:
            expressions.extend(
                argument.annotation
                for argument in (
                    *node.args.posonlyargs,
                    *node.args.args,
                    *node.args.kwonlyargs,
                    node.args.vararg,
                    node.args.kwarg,
                )
                if argument is not None
            )
            expressions.append(node.returns)
        for expression in expressions:
            if expression is not None:
                yield from _scope_calls(expression, include_annotations=include_annotations)
        return
    if isinstance(node, ast.Lambda):
        for expression in [*node.args.defaults, *node.args.kw_defaults]:
            if expression is not None:
                yield from _scope_calls(expression, include_annotations=include_annotations)
        return
    if isinstance(node, ast.AnnAssign):
        if include_annotations:
            yield from _scope_calls(node.annotation, include_annotations=True)
        if node.value is not None:
            yield from _scope_calls(node.value, include_annotations=include_annotations)
        return
    if isinstance(node, ast.GeneratorExp):
        if node.generators:
            yield from _scope_calls(
                node.generators[0].iter, include_annotations=include_annotations
            )
        return
    if isinstance(node, ast.Starred) and isinstance(node.value, ast.GeneratorExp):
        yield from _scope_calls(node.value.elt, include_annotations=include_annotations)
        for generator in node.value.generators:
            yield from _scope_calls(generator.iter, include_annotations=include_annotations)
            for condition in generator.ifs:
                yield from _scope_calls(condition, include_annotations=include_annotations)
    if isinstance(node, ast.ClassDef):
        for expression in [*node.decorator_list, *node.bases]:
            yield from _scope_calls(expression, include_annotations=include_annotations)
        for keyword in node.keywords:
            yield from _scope_calls(keyword.value, include_annotations=include_annotations)
        for statement in node.body:
            yield from _scope_calls(statement, include_annotations=include_annotations)
        return
    if isinstance(node, ast.Call):
        yield node
        if isinstance(node.func, ast.Lambda):
            yield from _scope_calls(node.func.body, include_annotations=include_annotations)
        for argument in [*node.args, *(keyword.value for keyword in node.keywords)]:
            if isinstance(argument, ast.GeneratorExp):
                yield from _scope_calls(argument.elt, include_annotations=include_annotations)
                for comprehension in argument.generators:
                    yield from _scope_calls(
                        comprehension.iter, include_annotations=include_annotations
                    )
                    for condition in comprehension.ifs:
                        yield from _scope_calls(condition, include_annotations=include_annotations)
    for child in ast.iter_child_nodes(node):
        yield from _scope_calls(child, include_annotations=include_annotations)


def _module_scope_calls(module: ast.Module) -> Iterator[ast.Call]:
    """Yield calls evaluated while defining a module or class, not function bodies."""

    postponed_annotations = any(
        isinstance(node, ast.ImportFrom)
        and node.module == "__future__"
        and any(alias.name == "annotations" for alias in node.names)
        for node in module.body
    )
    for node in module.body:
        yield from _scope_calls(node, include_annotations=not postponed_annotations)


def _dotted_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _dotted_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else None
    return None


def _imported_module(node: ast.ImportFrom, package: tuple[str, ...]) -> str:
    if node.level == 0:
        return node.module or ""
    keep = len(package) - (node.level - 1)
    if keep < 0:
        return ""
    relative_parts = tuple(filter(None, (node.module or "").split(".")))
    return ".".join((*package[:keep], *relative_parts))


def _context_constructor_exports(
    parsed_modules: dict[Path, tuple[ast.Module, tuple[str, ...]]],
    module_names: dict[Path, str],
) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, str]]]:
    """Resolve direct, aliased, and core-re-exported context constructors."""

    known_modules = set(module_names.values())
    exports: dict[str, dict[str, str]] = {name: {} for name in known_modules}
    module_exports: dict[str, dict[str, str]] = {name: {} for name in known_modules}
    while True:
        changed = False
        for path, (module, package_parts) in parsed_modules.items():
            module_name = module_names[path]
            exported = dict(exports[module_name])
            module_aliases = dict(module_exports[module_name])
            for node, owner in _module_scope_nodes(module):
                if owner:
                    continue
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name in {"contextvars", "core.ui.context_local"} or (
                            alias.name in known_modules
                        ):
                            module_aliases[alias.asname or alias.name] = alias.name
                elif isinstance(node, ast.ImportFrom):
                    source = _imported_module(node, package_parts)
                    for alias in node.names:
                        local_name = alias.asname or alias.name
                        if source == "contextvars" and alias.name == "ContextVar":
                            exported[local_name] = "ContextVar"
                        elif source == "core.ui.context_local" and alias.name == "ContextLocal":
                            exported[local_name] = "ContextLocal"
                        elif implementation := exports.get(source, {}).get(alias.name):
                            exported[local_name] = implementation
                        elif imported_module := module_exports.get(source, {}).get(alias.name):
                            module_aliases[local_name] = imported_module
                        elif f"{source}.{alias.name}" in known_modules:
                            module_aliases[local_name] = f"{source}.{alias.name}"

            while True:
                aliases_changed = False
                for node, owner in _module_scope_nodes(module):
                    if owner:
                        continue
                    target: ast.expr | None = None
                    value: ast.expr | None = None
                    if isinstance(node, ast.Assign) and len(node.targets) == 1:
                        target, value = node.targets[0], node.value
                    elif isinstance(node, ast.AnnAssign):
                        target, value = node.target, node.value
                    if not isinstance(target, ast.Name) or value is None:
                        continue
                    dotted = _dotted_name(
                        value.value if isinstance(value, ast.Subscript) else value
                    )
                    implementation = exported.get(dotted or "")
                    if implementation is None and dotted:
                        for alias_name, imported_name in module_aliases.items():
                            prefix = f"{alias_name}."
                            if dotted.startswith(prefix):
                                imported_symbol = dotted.removeprefix(prefix)
                                if (
                                    imported_name == "contextvars"
                                    and imported_symbol == "ContextVar"
                                ):
                                    implementation = "ContextVar"
                                elif (
                                    imported_name == "core.ui.context_local"
                                    and imported_symbol == "ContextLocal"
                                ):
                                    implementation = "ContextLocal"
                                else:
                                    implementation = exports.get(imported_name, {}).get(
                                        imported_symbol
                                    )
                                break
                    if implementation is not None and target.id not in exported:
                        exported[target.id] = implementation
                        aliases_changed = True
                    if dotted in module_aliases and target.id not in module_aliases:
                        module_aliases[target.id] = module_aliases[dotted]
                        aliases_changed = True
                if not aliases_changed:
                    break
            if exported != exports[module_name]:
                exports[module_name] = exported
                changed = True
            if module_aliases != module_exports[module_name]:
                module_exports[module_name] = module_aliases
                changed = True
        if not changed:
            return exports, module_exports


def _exported_context_constructor_paths(
    module_path: str,
    constructor_exports: dict[str, dict[str, str]],
    module_exports: dict[str, dict[str, str]],
    seen: frozenset[str] = frozenset(),
) -> dict[str, str]:
    if module_path == "contextvars":
        return {"ContextVar": "ContextVar"}
    if module_path == "core.ui.context_local":
        return {"ContextLocal": "ContextLocal"}
    if module_path in seen:
        return {}
    paths = dict(constructor_exports.get(module_path, {}))
    for name, imported in module_exports.get(module_path, {}).items():
        paths.update(
            {
                f"{name}.{nested}": implementation
                for nested, implementation in _exported_context_constructor_paths(
                    imported,
                    constructor_exports,
                    module_exports,
                    seen | {module_path},
                ).items()
            }
        )
    return paths


def _context_constructor_module_path(
    expression: ast.expr,
    aliases: dict[str, str],
    constructor_exports: dict[str, dict[str, str]],
    module_exports: dict[str, dict[str, str]],
) -> str | None:
    dotted = _dotted_name(expression.value if isinstance(expression, ast.Subscript) else expression)
    if dotted is None:
        return None
    if dotted in aliases:
        module_path = aliases[dotted]
        return (
            module_path
            if _exported_context_constructor_paths(module_path, constructor_exports, module_exports)
            else None
        )
    for alias_name, imported_name in aliases.items():
        if not dotted.startswith(f"{alias_name}."):
            continue
        module_path = imported_name
        for part in dotted.removeprefix(f"{alias_name}.").split("."):
            module_path = module_exports.get(module_path, {}).get(part) or (
                candidate if (candidate := f"{module_path}.{part}") in constructor_exports else ""
            )
            if not module_path:
                break
        if module_path and _exported_context_constructor_paths(
            module_path, constructor_exports, module_exports
        ):
            return module_path
    return None


def _context_alias_assignment(
    node: ast.stmt,
    *,
    path: Path,
    constructor_reference: Callable[[ast.expr], str | None],
    module_reference: Callable[[ast.expr], bool],
) -> tuple[ast.Name, ast.expr] | None:
    def container_values(value: ast.expr) -> Iterator[ast.expr]:
        children: Iterable[ast.expr | None]
        if isinstance(value, ast.Dict):
            children = (*value.keys, *value.values)
        elif isinstance(value, ast.List | ast.Set | ast.Tuple):
            children = value.elts
        else:
            yield value
            return
        for child in children:
            if child is not None:
                yield from container_values(child)

    target: ast.expr | None = None
    value: ast.expr | None = None
    if isinstance(node, ast.Assign):
        value = node.value
        if len(node.targets) == 1:
            target = node.targets[0]
    elif isinstance(node, ast.AnnAssign):
        target, value = node.target, node.value
    elif isinstance(node, ast.AugAssign):
        if any(
            constructor_reference(expression) is not None or module_reference(expression)
            for expression in ast.walk(node.value)
            if isinstance(expression, ast.expr)
        ):
            raise ValueError(
                f"{path}:{node.lineno}: ContextVar constructors must not be stored in containers"
            )
        return None
    if value is None:
        return None
    if isinstance(target, ast.Name):
        if (
            isinstance(value, ast.Subscript)
            and constructor_reference(value) is None
            and any(
                constructor_reference(expression) is not None or module_reference(expression)
                for expression in ast.walk(value.value)
                if isinstance(expression, ast.expr)
            )
        ):
            raise ValueError(f"{path}:{node.lineno}: ContextVar constructors must assign directly")
        if isinstance(value, ast.Dict | ast.List | ast.Set | ast.Tuple) and any(
            constructor_reference(expression) is not None or module_reference(expression)
            for expression in container_values(value)
        ):
            raise ValueError(
                f"{path}:{node.lineno}: ContextVar constructors must not be stored in containers"
            )
        if isinstance(value, ast.BinOp) and any(
            constructor_reference(expression) is not None or module_reference(expression)
            for expression in ast.walk(value)
            if isinstance(expression, ast.expr)
        ):
            raise ValueError(
                f"{path}:{node.lineno}: ContextVar constructors must not be stored in containers"
            )
        if isinstance(value, ast.IfExp | ast.BoolOp) and any(
            constructor_reference(expression) is not None or module_reference(expression)
            for expression in ast.walk(value)
            if isinstance(expression, ast.expr) and expression is not value
        ):
            raise ValueError(
                f"{path}:{node.lineno}: ContextVar constructor aliases must reference "
                "one constructor directly"
            )
        return target, value
    values = container_values(value)
    if any(constructor_reference(item) is not None or module_reference(item) for item in values):
        raise ValueError(
            f"{path}:{node.lineno}: ContextVar constructor aliases must assign "
            "one module/class name"
        )
    return None


def _unsupported_context_alias(
    node: ast.AST,
    constructor_reference: Callable[[ast.expr], str | None],
    module_reference: Callable[[ast.expr], bool],
) -> bool:
    if isinstance(node, ast.Attribute) and node.attr == "__dict__" and module_reference(node.value):
        return True
    if isinstance(node, ast.NamedExpr):
        return any(
            constructor_reference(candidate) is not None or module_reference(candidate)
            for candidate in ast.walk(node.value)
            if isinstance(candidate, ast.expr)
        )
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Subscript)
        and constructor_reference(node.func) is None
    ):
        return any(
            constructor_reference(candidate) is not None or module_reference(candidate)
            for candidate in ast.walk(node.func.value)
            if isinstance(candidate, ast.expr)
        )
    if isinstance(node, ast.Match | ast.comprehension) or (
        isinstance(node, ast.For | ast.AsyncFor) and not isinstance(node.iter, ast.GeneratorExp)
    ):
        source = (
            node.iter
            if isinstance(node, ast.For | ast.AsyncFor | ast.comprehension)
            else node.subject
        )
        return any(
            constructor_reference(candidate) is not None or module_reference(candidate)
            for candidate in ast.walk(source)
            if isinstance(candidate, ast.expr)
        )
    return isinstance(node, ast.ClassDef) and any(
        constructor_reference(base) == "ContextLocal" for base in node.bases
    )


def _runtime_expressions(
    node: ast.AST,
    *,
    include_annotations: bool = True,
) -> Iterator[ast.expr]:
    """Yield expressions Python evaluates, optionally including annotations."""

    if isinstance(node, ast.Assign | ast.AnnAssign | ast.AugAssign):
        value = node.value
        if value is not None:
            yield from _runtime_expressions(value, include_annotations=include_annotations)
        return
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
        expressions: list[ast.expr | None] = [
            *node.decorator_list,
            *node.args.defaults,
            *node.args.kw_defaults,
        ]
        if include_annotations:
            expressions.extend(
                argument.annotation
                for argument in (
                    *node.args.posonlyargs,
                    *node.args.args,
                    *node.args.kwonlyargs,
                    node.args.vararg,
                    node.args.kwarg,
                )
                if argument is not None
            )
            expressions.append(node.returns)
        for expression in expressions:
            if expression is not None:
                yield from _runtime_expressions(
                    expression,
                    include_annotations=include_annotations,
                )
        for statement in node.body:
            yield from _runtime_expressions(
                statement,
                include_annotations=include_annotations,
            )
        return
    if isinstance(node, ast.Lambda):
        for expression in (*node.args.defaults, *node.args.kw_defaults, node.body):
            if expression is not None:
                yield from _runtime_expressions(
                    expression,
                    include_annotations=include_annotations,
                )
        return
    if isinstance(node, ast.expr):
        yield node
    for child in ast.iter_child_nodes(node):
        yield from _runtime_expressions(child, include_annotations=include_annotations)


def _reject_context_factories(
    path: Path,
    module_nodes: Sequence[tuple[ast.stmt, str]],
    constructor_reference: Callable[[ast.expr], str | None],
    module_reference: Callable[[ast.expr], bool],
    is_context_import: Callable[[ast.stmt], bool],
) -> None:
    postponed_annotations = any(
        isinstance(node, ast.ImportFrom)
        and node.module == "__future__"
        and any(alias.name == "annotations" for alias in node.names)
        for node, owner in module_nodes
        if not owner
    )

    def contains_context_module(expression: ast.expr) -> bool:
        if module_reference(expression):
            return True
        children: Iterable[ast.expr | None]
        if isinstance(expression, ast.Dict):
            children = (*expression.keys, *expression.values)
        elif isinstance(expression, ast.List | ast.Set | ast.Tuple):
            children = expression.elts
        else:
            return False
        return any(child is not None and contains_context_module(child) for child in children)

    for node, owner in module_nodes:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            if path.parts[-3:] == ("core", "ui", "context_local.py") and (
                owner,
                node.name,
            ) == ("ContextLocal.", "__init__"):
                context_calls = [
                    child
                    for child in ast.walk(node)
                    if isinstance(child, ast.Call) and constructor_reference(child.func) is not None
                ]
                backing_calls = [
                    child
                    for child in ast.walk(node)
                    if isinstance(child, ast.Call)
                    and _dotted_name(child.func) == "object.__setattr__"
                    and len(child.args) >= 3
                    and isinstance(child.args[1], ast.Constant)
                    and child.args[1].value == "_ctx"
                    and child.args[2] in context_calls
                ]
                if len(context_calls) != 1 or len(backing_calls) != 1:
                    raise ValueError(
                        f"{path}:{node.lineno}: ContextLocal must own exactly one "
                        "direct _ctx ContextVar backing"
                    )
                continue
            if any(
                is_context_import(child)
                for child in ast.walk(node)
                if isinstance(child, ast.Import | ast.ImportFrom)
            ):
                raise ValueError(
                    f"{path}:{node.lineno}: ContextVar constructors must be imported "
                    "at module scope"
                )
            hides_constructor = (
                any(
                    constructor_reference(expression) is not None
                    for expression in _runtime_expressions(
                        node,
                        include_annotations=not postponed_annotations,
                    )
                )
                or any(
                    module_reference(child.value)
                    for child in ast.walk(node)
                    if isinstance(child, ast.Assign | ast.AnnAssign)
                    if child.value is not None
                )
                or any(
                    child.value is not None and contains_context_module(child.value)
                    for child in ast.walk(node)
                    if isinstance(child, ast.Return | ast.Yield | ast.YieldFrom)
                )
            )
            if hides_constructor:
                raise ValueError(f"{path}:{node.lineno}: ContextVar factories must assign directly")
            definition_inputs = (
                *node.decorator_list,
                *node.args.defaults,
                *node.args.kw_defaults,
            )
            if any(
                module_reference(expression)
                for expression in definition_inputs
                if expression is not None
            ):
                raise ValueError(f"{path}:{node.lineno}: ContextVar factories must assign directly")
            _reject_forwarded_context_modules(
                path,
                (
                    call
                    for child in node.body
                    for call in ast.walk(child)
                    if isinstance(call, ast.Call)
                ),
                module_reference,
            )
        for deferred in (child for child in ast.walk(node) if isinstance(child, ast.Lambda)):
            if any(
                constructor_reference(expression) is not None
                for expression in _runtime_expressions(deferred)
            ):
                raise ValueError(
                    f"{path}:{deferred.lineno}: ContextVar factories must assign directly"
                )
            if any(
                module_reference(expression)
                for expression in (*deferred.args.defaults, *deferred.args.kw_defaults)
                if expression is not None
            ):
                raise ValueError(
                    f"{path}:{deferred.lineno}: ContextVar factories must assign directly"
                )


def _reject_deferred_context_generators(
    path: Path,
    module_nodes: Sequence[tuple[ast.stmt, str]],
    constructor_type: Callable[[ast.Call], str | None],
) -> None:
    def evaluated_generators(node: ast.AST) -> Iterator[ast.GeneratorExp]:
        if isinstance(node, ast.Lambda | ast.FunctionDef | ast.AsyncFunctionDef):
            return
        if isinstance(node, ast.GeneratorExp):
            yield node
            return
        for child in ast.iter_child_nodes(node):
            yield from evaluated_generators(child)

    for node, _owner in module_nodes:
        for generator in evaluated_generators(node):
            if any(
                constructor_type(call) is not None
                for call in ast.walk(generator)
                if isinstance(call, ast.Call)
            ):
                raise ValueError(
                    f"{path}:{generator.lineno}: ContextVar generators must not be deferred"
                )


def _reject_forwarded_context_constructors(
    path: Path,
    calls: Iterable[ast.Call],
    context_reference: Callable[[ast.expr], bool],
) -> None:
    for call in calls:
        arguments = (*call.args, *(keyword.value for keyword in call.keywords))
        if any(
            context_reference(expression)
            for argument in arguments
            for expression in ast.walk(argument)
            if isinstance(expression, ast.expr)
        ):
            raise ValueError(
                f"{path}:{call.lineno}: ContextVar constructors must not be passed "
                "through factories"
            )


def _reject_forwarded_context_modules(
    path: Path,
    calls: Iterable[ast.Call],
    module_reference: Callable[[ast.expr], bool],
) -> None:
    for call in calls:
        arguments = (*call.args, *(keyword.value for keyword in call.keywords))
        if any(module_reference(argument) for argument in arguments):
            raise ValueError(
                f"{path}:{call.lineno}: ContextVar constructor modules must not be passed "
                "through factories"
            )


def _reject_context_keyword_unpacking(path: Path, calls: Iterable[ast.Call]) -> None:
    for call in calls:
        if any(keyword.arg is None for keyword in call.keywords):
            raise ValueError(
                f"{path}:{call.lineno}: ContextVar constructors must not unpack keywords"
            )


def _context_vars(root: Path) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    parsed_modules = {
        path: (_parse_python(path), path.relative_to(root).parent.parts)
        for package in ("core", *PRODUCT_MODULE_ROOTS)
        for path in _python_files(root, package)
    }

    module_names = {
        path: path.relative_to(root)
        .with_suffix("")
        .as_posix()
        .replace("/", ".")
        .removesuffix(".__init__")
        for path in parsed_modules
    }
    known_modules = set(module_names.values())
    constructor_exports, constructor_module_exports = _context_constructor_exports(
        parsed_modules, module_names
    )

    for path, (module, package_parts) in parsed_modules.items():
        module_nodes = tuple(_module_scope_nodes(module))
        module_name = module_names[path]

        def is_context_import(
            node: ast.stmt,
            package: tuple[str, ...] = package_parts,
        ) -> bool:
            if isinstance(node, ast.Import):
                return any(
                    alias.name in {"contextvars", "core.ui.context_local"}
                    or bool(constructor_exports.get(alias.name))
                    or bool(constructor_module_exports.get(alias.name))
                    for alias in node.names
                )
            if not isinstance(node, ast.ImportFrom):
                return False
            source = _imported_module(node, package)
            return (
                (
                    source == "contextvars"
                    and any(alias.name == "ContextVar" for alias in node.names)
                )
                or (
                    source == "core.ui.context_local"
                    and any(alias.name == "ContextLocal" for alias in node.names)
                )
                or (
                    source == "core.ui"
                    and any(alias.name == "context_local" for alias in node.names)
                )
                or any(
                    alias.name in constructor_exports.get(source, {})
                    or alias.name in constructor_module_exports.get(source, {})
                    or bool(constructor_exports.get(f"{source}.{alias.name}"))
                    for alias in node.names
                )
            )

        for node, owner in module_nodes:
            if not owner:
                continue
            if is_context_import(node):
                raise ValueError(
                    f"{path}:{node.lineno}: ContextVar constructors must be imported "
                    "at module scope"
                )

        constructors = {
            alias.asname or alias.name: "ContextVar"
            for node, owner in module_nodes
            if not owner
            if isinstance(node, ast.ImportFrom) and node.module == "contextvars"
            for alias in node.names
            if alias.name == "ContextVar"
        }
        constructors.update(CONTEXT_LOCAL_DEFINING_MODULE_CONSTRUCTORS.get(module_name, {}))
        constructors.update(constructor_exports[module_name])
        constructors.update(
            {
                alias.asname or alias.name: "ContextLocal"
                for node, owner in module_nodes
                if not owner
                if isinstance(node, ast.ImportFrom)
                and _imported_module(node, package_parts) == "core.ui.context_local"
                for alias in node.names
                if alias.name == "ContextLocal"
            }
        )
        module_aliases = {
            alias.asname or alias.name: alias.name
            for node, owner in module_nodes
            if not owner
            if isinstance(node, ast.Import)
            for alias in node.names
            if alias.name in {"contextvars", "core.ui.context_local"} or alias.name in known_modules
        }
        module_aliases.update(
            {
                alias.name.partition(".")[0]: alias.name.partition(".")[0]
                for node, owner in module_nodes
                if not owner
                if isinstance(node, ast.Import)
                for alias in node.names
                if alias.asname is None
                if "." in alias.name
                if alias.name.partition(".")[0] in known_modules
            }
        )
        module_aliases.update(
            {
                alias.asname or alias.name: "core.ui.context_local"
                for node, owner in module_nodes
                if not owner
                if isinstance(node, ast.ImportFrom)
                and _imported_module(node, package_parts) == "core.ui"
                for alias in node.names
                if alias.name == "context_local"
            }
        )
        module_aliases.update(
            {
                alias.asname or alias.name: candidate
                for node, owner in module_nodes
                if not owner
                if isinstance(node, ast.ImportFrom)
                for source in (_imported_module(node, package_parts),)
                for alias in node.names
                for candidate in (f"{source}.{alias.name}",)
                if candidate in known_modules
            }
        )
        module_aliases.update(
            {
                alias.asname or alias.name: constructor_module_exports[source][alias.name]
                for node, owner in module_nodes
                if not owner
                if isinstance(node, ast.ImportFrom)
                for source in (_imported_module(node, package_parts),)
                for alias in node.names
                if alias.name in constructor_module_exports.get(source, {})
            }
        )
        qualified_constructors: dict[str, str] = {}

        def constructor_reference(
            function: ast.expr,
            direct: dict[str, str] = constructors,
            qualified: dict[str, str] = qualified_constructors,
        ) -> str | None:
            if isinstance(function, ast.Subscript):
                function = function.value
            if isinstance(function, ast.Name):
                return direct.get(function.id)
            dotted = _dotted_name(function)
            return qualified.get(dotted) if dotted else None

        def module_path_reference(
            expression: ast.expr,
            aliases: dict[str, str] = module_aliases,
        ) -> str | None:
            return _context_constructor_module_path(
                expression,
                aliases,
                constructor_exports,
                constructor_module_exports,
            )

        def module_reference(expression: ast.expr) -> bool:
            return module_path_reference(expression) is not None

        while True:
            for name, module_path in module_aliases.items():
                qualified_constructors.update(
                    {
                        f"{name}.{exported_name}": constructor
                        for exported_name, constructor in _exported_context_constructor_paths(
                            module_path, constructor_exports, constructor_module_exports
                        ).items()
                    }
                )
            constructor_aliases: dict[str, str] = {}
            new_module_aliases: dict[str, str] = {}
            for node, owner in module_nodes:
                assignment = _context_alias_assignment(
                    node,
                    path=path,
                    constructor_reference=constructor_reference,
                    module_reference=module_reference,
                )
                if assignment is None:
                    continue
                alias_target, alias_value = assignment
                implementation = constructor_reference(alias_value)
                resolved_module = module_path_reference(alias_value)
                if owner and (implementation is not None or resolved_module is not None):
                    raise ValueError(
                        f"{path}:{node.lineno}: ContextVar constructor aliases must be "
                        "module-scoped"
                    )
                if owner:
                    continue
                if implementation is not None and alias_target.id not in constructors:
                    constructor_aliases[alias_target.id] = implementation
                if resolved_module is not None and alias_target.id not in module_aliases:
                    new_module_aliases[alias_target.id] = resolved_module
            if not constructor_aliases and not new_module_aliases:
                break
            constructors.update(constructor_aliases)
            module_aliases.update(new_module_aliases)

        unsupported_alias = next(
            (
                expression
                for expression in ast.walk(module)
                if _unsupported_context_alias(expression, constructor_reference, module_reference)
            ),
            None,
        )
        if unsupported_alias is not None:
            raise ValueError(
                f"{path}:{getattr(unsupported_alias, 'lineno', 0)}: "
                "ContextVar-backed constructors must "
                "assign directly"
            )

        def constructor_type(
            candidate: ast.Call,
            resolve: Callable[[ast.expr], str | None] = constructor_reference,
        ) -> str | None:
            return resolve(candidate.func)

        _reject_context_factories(
            path,
            module_nodes,
            constructor_reference,
            module_reference,
            is_context_import,
        )
        _reject_forwarded_context_constructors(
            path,
            _module_scope_calls(module),
            lambda expression: constructor_reference(expression) is not None,
        )
        _reject_forwarded_context_modules(
            path,
            _module_scope_calls(module),
            module_reference,
        )
        _reject_deferred_context_generators(path, module_nodes, constructor_type)

        module_context_calls = {
            id(candidate): candidate
            for candidate in _module_scope_calls(module)
            if constructor_type(candidate) is not None
        }
        _reject_context_keyword_unpacking(path, module_context_calls.values())
        assigned_context_calls: set[int] = set()
        for node, owner in module_nodes:
            symbol: str | None = None
            value: ast.expr | None = None
            unsupported_assignment = False
            if isinstance(node, ast.Assign):
                value = node.value
                if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                    symbol = f"{owner}{node.targets[0].id}"
                else:
                    unsupported_assignment = True
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                symbol = f"{owner}{node.target.id}"
                value = node.value
            context_var_calls: list[tuple[ast.Call, str]] = []
            for candidate in _scope_calls(value) if value is not None else ():
                implementation = constructor_type(candidate)
                if implementation is not None:
                    context_var_calls.append((candidate, implementation))
            if not context_var_calls:
                continue
            if (
                not isinstance(value, ast.Call)
                or len(context_var_calls) != 1
                or context_var_calls[0][0] is not value
                or unsupported_assignment
                or symbol is None
            ):
                raise ValueError(
                    f"{path}:{node.lineno}: ContextVar-backed state must assign "
                    "one module/class name"
                )
            context_name = ""
            if value.args and isinstance(value.args[0], ast.Constant):
                raw_name = value.args[0].value
                if isinstance(raw_name, str):
                    context_name = raw_name
            assigned_context_calls.add(id(value))
            items.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "line": node.lineno,
                    "symbol": symbol,
                    "context_name": context_name,
                    "has_default": context_var_calls[0][1] == "ContextLocal"
                    or any(keyword.arg == "default" for keyword in value.keywords),
                    "implementation": context_var_calls[0][1],
                }
            )
        unsupported_calls = module_context_calls.keys() - assigned_context_calls
        if unsupported_calls:
            first = min(unsupported_calls, key=lambda key: module_context_calls[key].lineno)
            call = module_context_calls[first]
            raise ValueError(
                f"{path}:{call.lineno}: ContextVar-backed state must assign one module/class name"
            )
    items.sort(key=lambda item: (item["path"], item["line"], item["symbol"]))
    lifecycle_path = root / CONTEXT_VAR_LIFECYCLES

    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result = dict(pairs)
        if len(result) != len(pairs):
            raise ValueError(f"{lifecycle_path}: duplicate JSON object key")
        return result

    try:
        lifecycles = json.loads(
            lifecycle_path.read_text(encoding="utf-8"), object_pairs_hook=unique_object
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read ContextVar lifecycle inventory: {lifecycle_path}") from exc
    if not isinstance(lifecycles, dict):
        raise ValueError(f"{lifecycle_path}: expected a JSON object")

    measured_key_list = [f"{item['path']}:{item['symbol']}" for item in items]
    duplicate_keys = sorted(key for key, count in Counter(measured_key_list).items() if count > 1)
    if duplicate_keys:
        raise ValueError(f"duplicate ContextVar lifecycle declarations: {duplicate_keys}")
    measured_keys = set(measured_key_list)
    declared_keys = set(lifecycles)
    if measured_keys != declared_keys:
        missing = sorted(measured_keys - declared_keys)
        stale = sorted(declared_keys - measured_keys)
        raise ValueError(f"ContextVar lifecycle drift: missing={missing}; stale={stale}")

    counts = dict.fromkeys(CONTEXT_VAR_CLASSIFICATIONS, 0)
    for item in items:
        key = f"{item['path']}:{item['symbol']}"
        lifecycle = lifecycles[key]
        if not isinstance(lifecycle, dict):
            raise ValueError(f"{lifecycle_path}: {key} must be an object")
        if set(lifecycle) != set(CONTEXT_VAR_LIFECYCLE_FIELDS):
            raise ValueError(
                f"{lifecycle_path}: {key} fields must be {list(CONTEXT_VAR_LIFECYCLE_FIELDS)}"
            )
        if any(
            not isinstance(lifecycle[field], str) or not lifecycle[field].strip()
            for field in lifecycle
        ):
            raise ValueError(f"{lifecycle_path}: {key} fields must be non-empty strings")
        classification = lifecycle["classification"]
        if classification not in counts:
            raise ValueError(
                f"{lifecycle_path}: {key} has unknown classification {classification!r}"
            )
        counts[classification] += 1
        item.update(lifecycle)
        item["async_propagation_test"] = CONTEXT_VAR_PROPAGATION_TEST

    return {
        "count": len(items),
        "classification_counts": counts,
        "service_locator_count": counts["service_locator"],
        "lifecycle_source": CONTEXT_VAR_LIFECYCLES.as_posix(),
        "items": items,
    }


def _self_improving_facades(root: Path) -> dict[str, Any]:
    """Verify the publication-gated legacy facade without opening deep aliases."""
    facade_root = root / "core" / "self_improving"
    actual = {
        path.relative_to(root).as_posix()
        for path in facade_root.rglob("*.py")
        if "state" not in path.relative_to(facade_root).parts
    }
    expected = set(SELF_IMPROVING_FACADE_TARGETS)
    if actual != expected:
        raise ValueError(
            "self-improving facade drift: "
            f"missing={sorted(expected - actual)}, unexpected={sorted(actual - expected)}"
        )

    items: list[dict[str, str]] = []
    for relative, target in sorted(SELF_IMPROVING_FACADE_TARGETS.items()):
        module = _parse_python(root / relative)
        if any(
            isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
            for node in module.body
        ):
            raise ValueError(f"{relative}: compatibility facade defines executable objects")
        references = {
            node.value
            for node in ast.walk(module)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value.startswith("geode_product.self_improving")
        }
        references.update(
            node.module
            for node in ast.walk(module)
            if isinstance(node, ast.ImportFrom)
            and node.module is not None
            and node.module.startswith("geode_product.self_improving")
        )
        if references != {target}:
            raise ValueError(f"{relative}: expected only {target!r}, found {sorted(references)!r}")
        items.append({"path": relative, "target": target})
    return {"count": len(items), "items": items}


def _product_imports(
    root: Path,
    *,
    allowed_facades: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    sites: list[dict[str, Any]] = []
    for path in _python_files(root, "core"):
        if path.relative_to(root).as_posix() in allowed_facades:
            continue
        for node in ast.walk(_parse_python(path)):
            modules: list[str] = []
            site_line = 0
            if isinstance(node, ast.Import):
                modules = [
                    alias.name
                    for alias in node.names
                    if alias.name in PRODUCT_MODULE_ROOTS
                    or alias.name.startswith(tuple(f"{root}." for root in PRODUCT_MODULE_ROOTS))
                ]
                site_line = node.lineno
            elif (
                isinstance(node, ast.ImportFrom)
                and node.module is not None
                and (
                    node.module in PRODUCT_MODULE_ROOTS
                    or node.module.startswith(tuple(f"{root}." for root in PRODUCT_MODULE_ROOTS))
                )
            ):
                modules = [node.module]
                site_line = node.lineno
            elif (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and PRODUCT_MODULE_REFERENCE_RE.fullmatch(node.value)
            ):
                modules = [node.value]
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
    from geode_product.tool_handlers import product_handler_groups

    handler_catalog = _build_tool_handler_catalog(extra_groups=product_handler_groups())
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
    self_improving_facades = _self_improving_facades(root)
    return {
        "schema_version": 4,
        "packages": packages,
        "tools": _tool_inventory(root),
        "hook_events": _hook_events(root),
        "built_in_adapters": _built_in_adapters(root),
        "context_vars": _context_vars(root),
        "core_to_product_imports": _product_imports(
            root,
            allowed_facades=frozenset(SELF_IMPROVING_FACADE_TARGETS),
        ),
        "self_improving_facades": self_improving_facades,
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
    production_files = sum(
        packages[name]["python_files"] for name in ("core", "geode_product", "plugins")
    )
    return "\n".join(
        (
            AGENTS_START,
            "The generated architecture inventory lives at",
            "`site/src/data/geode/architecture-baseline.json`. Refresh it with",
            "`uv run python scripts/architecture_baseline.py --update`; CI uses `--check`.",
            f"The current snapshot records {_number(production_files)} production Python files,",
            f"{_number(packages['tests']['python_files'])} test Python files,",
            f"{_number(tools['definition_count'])} tool definitions, and",
            f"{_number(baseline['hook_events']['count'])} `RuntimeEvent` members.",
            AGENTS_END,
        )
    )


def render_roadmap_block(baseline: dict[str, Any]) -> str:
    packages = baseline["packages"]
    tools = baseline["tools"]
    imports = baseline["core_to_product_imports"]
    import_linter = baseline["import_linter"]
    coordinators = baseline["coordinators"]
    thresholds = baseline["complexity_thresholds"]
    production_files = sum(
        packages[name]["python_files"] for name in ("core", "geode_product", "plugins")
    )
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
            (
                "| Production Python files (`core/` + `geode_product/` + `plugins/`) "
                f"| {_number(production_files)} |"
            ),
            f"| Test Python files | {_number(packages['tests']['python_files'])} |",
            f"| `core/` Python LOC | {_number(packages['core']['python_loc'])} |",
            f"| `geode_product/` Python LOC | {_number(packages['geode_product']['python_loc'])} |",
            f"| `plugins/` Python LOC | {_number(packages['plugins']['python_loc'])} |",
            f"| Test Python LOC | {_number(packages['tests']['python_loc'])} |",
            (
                f"| Tool definitions / executable registrations / valid schemas "
                f"| {_number(tools['definition_count'])} / "
                f"{_number(tools['execution_registration_count'])} / "
                f"{_number(tools['schema_count'])} ({parity}) |"
            ),
            f"| `RuntimeEvent` members | {_number(baseline['hook_events']['count'])} |",
            f"| Built-in LLM adapters | {_number(baseline['built_in_adapters']['count'])} |",
            (
                "| Module/class-scoped `ContextVar`-backed bindings in production packages | "
                f"{_number(baseline['context_vars']['count'])} |"
            ),
            (
                f"| `core` → product import sites | {_number(imports['site_count'])} "
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
