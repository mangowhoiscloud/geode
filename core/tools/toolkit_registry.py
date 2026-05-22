"""Toolkit registry — resolve named tool bundles for sub-agents (CSP-1).

A toolkit is a named bundle of tool ids declared in
``core/tools/toolkits.toml``. Sub-agents reference toolkits via the
``toolkit:`` key in their AgentDefinition frontmatter
(`.claude/agents/<name>.md`). The worker subprocess
(`core/agent/worker.py:filter_handlers`) consults this registry to
expand the toolkit name into a concrete tool allowlist at spawn time.

Resolution priority (applied by ``filter_handlers``):

1. ``toolkit: <name>`` declared → expand via :meth:`ToolkitRegistry.resolve`
2. ``tools: [...]`` declared (legacy) → use as-is
3. Neither → fall back to ``_default`` toolkit

Composition: a toolkit can pull tools from other toolkits via
``includes = ["other_kit", ...]``. Cycles raise
:class:`ToolkitCompositionError`.

Why a separate registry (vs. inlining the lookup in worker.py)?

- The TOML manifest is the SoT for what a sub-agent can touch — separate
  from the handler factory (`core/cli/tool_handlers._build_tool_handlers`)
  which owns *instantiation*. Keeping them apart lets a future plugin
  ship its own ``toolkits.toml`` without touching core handler code.
- Testable in isolation — composition + fallback semantics are pure
  string-set algebra over the parsed TOML, no AgenticLoop bootstrap
  required.

Frontier prior art:

- LangChain ``agent_toolkits`` (resource-sharing tool groups).
- Hermes ``toolsets.py`` (``includes:`` composition).
- open-coscientist ``config/registry.get_tools_for_workflow`` (workflow-
  scoped whitelist).
"""

from __future__ import annotations

import logging
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_TOOLKIT",
    "DEFAULT_TOOLKITS_PATH",
    "Toolkit",
    "ToolkitCompositionError",
    "ToolkitRegistry",
    "load_default_registry",
]


DEFAULT_TOOLKIT = "_default"

# Resolved at import time so callers can either pass a custom path or
# rely on the bundled SoT under ``core/tools/toolkits.toml``.
DEFAULT_TOOLKITS_PATH = Path(__file__).parent / "toolkits.toml"


class ToolkitCompositionError(ValueError):
    """A toolkit's ``includes`` graph is malformed (cycle / missing target)."""


@dataclass(frozen=True)
class Toolkit:
    """One row from ``toolkits.toml``.

    ``tools`` is the directly-declared tool id list; ``includes`` is the
    list of sibling toolkit names whose ``tools`` (recursively) should be
    merged in. The registry only owns the *declared* shape; expansion is
    performed lazily in :meth:`ToolkitRegistry.resolve` so cycles can be
    reported with the full call chain.
    """

    name: str
    description: str = ""
    tools: tuple[str, ...] = field(default_factory=tuple)
    includes: tuple[str, ...] = field(default_factory=tuple)


class ToolkitRegistry:
    """In-memory store of parsed ``toolkits.toml`` rows.

    The registry is constructed from a dict (``from_dict``) or from disk
    (``load``). It does not hold any handler instances — it only owns
    the static name → declaration mapping. Expansion via
    :meth:`resolve` returns a frozenset of tool ids ready to hand to
    ``filter_handlers``.
    """

    def __init__(self, toolkits: dict[str, Toolkit]) -> None:
        self._toolkits = dict(toolkits)

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> ToolkitRegistry:
        """Build from a parsed TOML mapping (test-friendly).

        ``data`` may be either the full TOML mapping
        (``{"toolkits": {"name": {...}, ...}}``) or just the inner
        ``toolkits`` dict; both shapes are accepted so tests can hand a
        flat dict without re-wrapping.
        """
        raw = data.get("toolkits") if isinstance(data.get("toolkits"), dict) else data
        if not isinstance(raw, dict):
            raise ToolkitCompositionError(
                "toolkits.toml: top-level [toolkits] table missing or not a table"
            )
        parsed: dict[str, Toolkit] = {}
        for name, body in raw.items():
            if not isinstance(body, dict):
                raise ToolkitCompositionError(
                    f"toolkits.{name}: row must be a table, got {type(body).__name__}"
                )
            # CSP-1 fix-up (Codex MCP LOW #1) — reject scalar values for
            # ``tools`` / ``includes`` (e.g. ``tools = "read_document"``
            # would otherwise iterate per-character and yield bogus
            # 1-letter tool ids).
            tools_raw = body.get("tools", []) or []
            if not isinstance(tools_raw, list):
                raise ToolkitCompositionError(
                    f"toolkits.{name}.tools must be a list of strings, "
                    f"got {type(tools_raw).__name__}"
                )
            includes_raw = body.get("includes", []) or []
            if not isinstance(includes_raw, list):
                raise ToolkitCompositionError(
                    f"toolkits.{name}.includes must be a list of strings, "
                    f"got {type(includes_raw).__name__}"
                )
            parsed[name] = Toolkit(
                name=name,
                description=str(body.get("description", "")),
                tools=tuple(str(t) for t in tools_raw),
                includes=tuple(str(i) for i in includes_raw),
            )
        return cls(parsed)

    @classmethod
    def load(cls, path: Path | None = None) -> ToolkitRegistry:
        """Load from disk. Missing file → empty registry (silent)."""
        target = path or DEFAULT_TOOLKITS_PATH
        if not target.is_file():
            log.debug("toolkit_registry: %s missing — returning empty registry", target)
            return cls({})
        with target.open("rb") as fh:
            data = tomllib.load(fh)
        return cls.from_dict(data)

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def names(self) -> list[str]:
        return sorted(self._toolkits)

    def has(self, name: str) -> bool:
        return name in self._toolkits

    def get(self, name: str) -> Toolkit | None:
        return self._toolkits.get(name)

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------

    def resolve(self, name: str) -> frozenset[str]:
        """Expand ``name`` into a frozenset of tool ids.

        Recursively pulls in tools from every ``includes`` member. Unknown
        toolkit names raise :class:`KeyError`; cycles raise
        :class:`ToolkitCompositionError` with the offending path.

        Empty toolkit (no ``tools`` AND no ``includes``) returns an empty
        frozenset — callers (the worker) decide whether to fall through to
        ``_default``.
        """
        if name not in self._toolkits:
            raise KeyError(f"toolkit {name!r} not in registry; known: {self.names()}")
        return self._expand(name, chain=())

    def _expand(self, name: str, *, chain: tuple[str, ...]) -> frozenset[str]:
        if name in chain:
            cycle = " → ".join((*chain, name))
            raise ToolkitCompositionError(f"toolkit cycle detected: {cycle}")
        kit = self._toolkits.get(name)
        if kit is None:
            # An `includes:` target that doesn't exist — surface clearly
            # rather than silently dropping its tools. Calls to
            # ``resolve(name)`` already validate ``name`` itself; this
            # branch only fires for missing transitive includes.
            raise ToolkitCompositionError(
                f"toolkit {name!r} listed in includes but not declared "
                f"(chain: {' → '.join(chain) or '<root>'})"
            )
        acc: set[str] = set(kit.tools)
        for inc in kit.includes:
            acc |= self._expand(inc, chain=(*chain, name))
        return frozenset(acc)

    def resolve_with_fallback(self, name: str | None) -> frozenset[str]:
        """Resolve ``name`` if present and known, else ``_default``, else empty.

        Convenience for the worker: a sub-agent may declare a toolkit
        that doesn't exist (typo / refactor lag). Rather than crashing
        the spawn, we log a WARNING and fall through to ``_default`` so
        the agent still has its minimal read-only safety net.
        """
        if name and self.has(name):
            return self.resolve(name)
        if name:
            log.warning(
                "toolkit_registry: agent requested toolkit=%r which is not "
                "declared in toolkits.toml; falling back to %r.",
                name,
                DEFAULT_TOOLKIT,
            )
        if self.has(DEFAULT_TOOLKIT):
            return self.resolve(DEFAULT_TOOLKIT)
        return frozenset()


# ----------------------------------------------------------------------
# Module-level convenience
# ----------------------------------------------------------------------


_cached_registry: ToolkitRegistry | None = None


def load_default_registry(*, force_reload: bool = False) -> ToolkitRegistry:
    """Return a process-cached registry loaded from ``DEFAULT_TOOLKITS_PATH``.

    The worker subprocess calls this once per spawn — caching avoids
    re-parsing the TOML on every ``filter_handlers`` call. Tests can
    pass ``force_reload=True`` to bypass the cache after writing a
    temporary manifest.
    """
    global _cached_registry
    if _cached_registry is None or force_reload:
        _cached_registry = ToolkitRegistry.load()
    return _cached_registry
