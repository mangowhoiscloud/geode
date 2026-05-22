"""Custom Agent System — load agent definitions from YAML/markdown files.

Layer 5 extensibility component for defining and managing sub-agents
that can be loaded from .claude/agents/*.md (YAML frontmatter + markdown body).
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from core.config import ANTHROPIC_SECONDARY
from core.skills._frontmatter import parse_yaml_frontmatter

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class AgentDefinition(BaseModel):
    """Definition of a custom sub-agent."""

    name: str
    role: str
    system_prompt: str
    tools: list[str] = Field(default_factory=list)
    # CSP-1 (2026-05-22) — named tool bundle declared in the agent's
    # ``toolkit:`` frontmatter. When present it takes precedence over
    # ``tools`` at spawn time (see
    # ``core/agent/worker.py:filter_handlers``). Empty string preserves
    # the pre-CSP-1 behaviour for AgentDefinitions that still use the
    # flat ``tools:`` list.
    toolkit: str = ""
    model: str = ANTHROPIC_SECONDARY

    def to_system_message(self) -> str:
        """Format as a system message combining role and prompt."""
        return f"You are a {self.role}.\n\n{self.system_prompt}"


# ---------------------------------------------------------------------------
# Default agents
# ---------------------------------------------------------------------------

# CSP-1 (2026-05-22) — the bundled default agents migrated from flat
# ``tools:`` whitelists to named ``toolkit`` declarations against
# ``core/tools/toolkits.toml``. The legacy ``tools`` field is dropped
# (an empty list) since the agent's effective allowlist now comes from
# the toolkit expansion in ``filter_handlers``. Toolkit choice also
# fixes the pre-CSP-1 ``"web_search"`` reference, which never resolved
# to a real handler — ``core/tools/definitions.json`` exposes the tool
# as ``general_web_search`` and the ``web_research`` toolkit lists it
# under its canonical name.
_DEFAULT_AGENTS: list[dict[str, Any]] = [
    {
        "name": "research_assistant",
        "role": "Research Specialist",
        "system_prompt": (
            "You are a research specialist. Gather and synthesize information "
            "from multiple sources — web, documents, and databases. "
            "Provide well-structured summaries with key findings and evidence."
        ),
        "tools": [],
        "toolkit": "web_research",
        "model": ANTHROPIC_SECONDARY,
    },
    {
        "name": "data_analyst",
        "role": "Data Analysis Specialist",
        "system_prompt": (
            "You are a data analyst. Analyze datasets, identify trends and patterns, "
            "compute statistics, and generate visualizations. "
            "Provide data-driven insights with clear methodology."
        ),
        "tools": [],
        "toolkit": "data_analysis",
        "model": ANTHROPIC_SECONDARY,
    },
    {
        "name": "web_researcher",
        "role": "Web Research & Monitoring Specialist",
        "system_prompt": (
            "You are a web researcher specializing in monitoring trends, "
            "tracking updates, and aggregating information from online sources. "
            "Provide timely summaries with source attribution."
        ),
        "tools": [],
        "toolkit": "web_research",
        "model": ANTHROPIC_SECONDARY,
    },
]


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class AgentRegistry:
    """Registry for managing agent definitions."""

    def __init__(self) -> None:
        self._agents: dict[str, AgentDefinition] = {}

    def register(self, agent: AgentDefinition) -> None:
        """Register an agent. Raises ValueError if name already registered."""
        if agent.name in self._agents:
            raise ValueError(f"Agent '{agent.name}' already registered")
        self._agents[agent.name] = agent

    def get(self, name: str) -> AgentDefinition | None:
        """Get an agent by name. Returns None if not found."""
        return self._agents.get(name)

    def list_agents(self) -> list[str]:
        """List all registered agent names."""
        return list(self._agents.keys())

    def unregister(self, name: str) -> None:
        """Remove an agent. Raises KeyError if not found."""
        if name not in self._agents:
            raise KeyError(f"Agent '{name}' not found in registry")
        del self._agents[name]

    def load_defaults(self) -> None:
        """Load the three default agents (research_assistant, data_analyst, web_researcher)."""
        for agent_dict in _DEFAULT_AGENTS:
            agent = AgentDefinition(**agent_dict)
            if agent.name not in self._agents:
                self._agents[agent.name] = agent

    def __len__(self) -> int:
        return len(self._agents)

    def __contains__(self, name: str) -> bool:
        return name in self._agents


# ---------------------------------------------------------------------------
# YAML frontmatter parser (delegated to shared module)
# ---------------------------------------------------------------------------

# Re-export for backward compatibility
_parse_yaml_frontmatter = parse_yaml_frontmatter


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


class SubagentLoader:
    """Load agent definitions from agent-prompt directories.

    Each markdown file should have YAML frontmatter with agent metadata
    and a markdown body that becomes the system_prompt.

    Two search roots, scanned in this order:

    1. ``.claude/agents/*.md`` — operator-local overrides + ad-hoc agents.
    2. ``plugins/*/agents/*.md`` — plugin-shipped agent definitions
       (e.g. ``plugins/seed_generation/agents/critic.md``).

    When the same filename appears in both, the ``.claude/agents/`` copy
    wins (operator override takes precedence over plugin defaults).
    The dedup key is the file basename, so a plugin agent named
    ``critic.md`` can be overridden by dropping a same-named file into
    ``.claude/agents/``.

    Example file format:
        ---
        name: research_assistant
        role: Research Specialist
        tools: [web_search, web_fetch, read_document]
        model: claude-sonnet-4-5-20250929
        ---
        You are a research specialist...
    """

    def __init__(
        self,
        agents_dir: str | Path | None = None,
        *,
        agents_dirs: Sequence[str | Path] | None = None,
    ) -> None:
        if agents_dir is not None and agents_dirs is not None:
            raise ValueError("pass either agents_dir (single) or agents_dirs (list), not both")
        if agents_dirs is not None:
            self._agents_dirs: list[Path] = [Path(d) for d in agents_dirs]
        elif agents_dir is not None:
            self._agents_dirs = [Path(agents_dir)]
        else:
            self._agents_dirs = self._default_agent_dirs()

    @staticmethod
    def _default_agent_dirs() -> list[Path]:
        """Return ``[.claude/agents, plugins/*/agents]`` relative to cwd.

        Operator overrides (``.claude/agents/``) come first so they win
        the filename-dedup race against plugin-shipped defaults. Callers
        that need absolute-path anchoring (e.g. ``geode serve`` launched
        from $HOME) should construct the list via :func:`core.paths.get_project_root`
        and pass ``agents_dirs=``.
        """
        dirs: list[Path] = [Path(".claude/agents")]
        plugins_root = Path("plugins")
        if plugins_root.exists():
            for plugin_agents in sorted(plugins_root.glob("*/agents")):
                if plugin_agents.is_dir():
                    dirs.append(plugin_agents)
        return dirs

    @property
    def agents_dir(self) -> Path:
        """Primary directory (first entry of :attr:`agents_dirs`).

        Backward-compat accessor for callers that predate multi-source
        discovery. Always returns the first dir in scan order — which
        is ``.claude/agents`` under the default config.
        """
        return self._agents_dirs[0]

    @property
    def agents_dirs(self) -> list[Path]:
        """All directories scanned by :meth:`discover`, in scan order."""
        return list(self._agents_dirs)

    def discover(self) -> list[Path]:
        """Find all .md files across configured agent directories.

        Dedup is by file basename — when the same filename appears in
        multiple search roots, the first occurrence wins (operator
        override semantics). Returns paths in scan order so two
        operator overrides of differently-named plugin agents both
        load.
        """
        seen_names: set[str] = set()
        result: list[Path] = []
        for agents_dir in self._agents_dirs:
            if not agents_dir.exists():
                continue
            for path in sorted(agents_dir.glob("*.md")):
                if path.name in seen_names:
                    continue
                seen_names.add(path.name)
                result.append(path)
        return result

    def load_file(self, path: Path) -> AgentDefinition:
        """Load a single agent definition from a markdown file.

        Raises:
            FileNotFoundError: If file doesn't exist.
            ValueError: If required fields are missing.
        """
        if not path.exists():
            raise FileNotFoundError(f"Agent file not found: {path}")

        text = path.read_text(encoding="utf-8")
        metadata, body = _parse_yaml_frontmatter(text)

        name = metadata.get("name")
        if not name:
            # Fall back to filename without extension
            name = path.stem

        role = metadata.get("role")
        if not role:
            raise ValueError(f"Agent file {path} missing required 'role' field")

        tools_raw = metadata.get("tools", [])
        if isinstance(tools_raw, str):
            tools = [t.strip() for t in tools_raw.split(",")]
        else:
            tools = list(tools_raw)

        model = metadata.get("model", ANTHROPIC_SECONDARY)
        # CSP-1 — optional ``toolkit:`` frontmatter (string). Empty when
        # the agent still uses the legacy flat ``tools:`` list.
        toolkit_raw = metadata.get("toolkit", "")
        toolkit = str(toolkit_raw) if toolkit_raw else ""

        return AgentDefinition(
            name=name,
            role=role,
            system_prompt=body.strip(),
            tools=tools,
            toolkit=toolkit,
            model=model,
        )

    def load_all(self, registry: AgentRegistry | None = None) -> list[AgentDefinition]:
        """Discover and load all agent definitions.

        If a registry is provided, agents are automatically registered.
        """
        agents: list[AgentDefinition] = []
        for path in self.discover():
            agent = self.load_file(path)
            agents.append(agent)
            if registry is not None:
                registry.register(agent)
        return agents
