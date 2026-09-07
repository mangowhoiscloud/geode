"""Sub-agent request construction and result validation."""

from __future__ import annotations

import dataclasses
import json
import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from core.agent.cognitive_state_ctx import get_session_id
from core.config.policy_source import PolicySourceBundle, encode_policy_sources
from core.orchestration.isolated_execution import IsolationResult

if TYPE_CHECKING:
    from core.agent.worker import WorkerRequest
    from core.skills.agents import AgentRegistry

log = logging.getLogger(__name__)

_JSON_CODEBLOCK_RE = re.compile(r"```(?:json|JSON)?\s*\n?(.*?)\n?\s*```", re.DOTALL)
_TYPE_AGENT_MAP: dict[str, str] = {
    "analyze": "data_analyst",
    "search": "web_researcher",
    "compare": "data_analyst",
}


@dataclass
class SubTask:
    """One task delegated to a depth-one worker."""

    task_id: str
    description: str
    task_type: str
    args: dict[str, Any] = field(default_factory=dict)
    agent: str | None = None
    role: str = ""
    source: str = ""
    model: str = ""
    response_schema: dict[str, Any] | None = None
    effort: str = ""


@dataclass
class SubResult:
    """Result and usage returned by one sub-agent."""

    task_id: str
    description: str
    success: bool
    output: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    duration_ms: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    usd_spent: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {key: value for key, value in dataclasses.asdict(self).items() if value is not None}


@dataclass
class SubagentRunRecord:
    """Ephemeral identity for one child execution."""

    run_id: str
    task_id: str
    child_session_key: str
    parent_session_key: str


def _strip_json_codeblock(text: str) -> str:
    match = _JSON_CODEBLOCK_RE.search(text)
    return text if match is None else match.group(1).strip()


def _last_balanced_json_object(text: str) -> str | None:
    """Return the last balanced JSON object embedded in text."""
    if "{" not in text:
        return None
    candidates: list[tuple[int, int]] = []
    depth = 0
    in_string = False
    escape = False
    start = -1
    for index, char in enumerate(text):
        if escape:
            escape = False
            continue
        if char == "\\" and in_string:
            escape = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == "{":
            if depth == 0:
                start = index
            depth += 1
        elif char == "}" and depth > 0:
            depth -= 1
            if depth == 0 and start >= 0:
                candidates.append((start, index + 1))
                start = -1
    for start, end in reversed(candidates):
        candidate = text[start:end]
        try:
            json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
        return candidate
    return None


@dataclass(slots=True)
class SubagentProtocol:
    """Build worker requests and validate worker results."""

    denied_tools: set[str]
    timeout_s: float
    time_budget_s: float
    agent_registry: AgentRegistry | None
    parent_session_key: str
    policy_sources: PolicySourceBundle

    def resolve_agent(self, task: SubTask) -> dict[str, Any] | None:
        """Resolve explicit agent, role, then task-type default."""
        if self.agent_registry is None:
            return None
        agent_name = task.agent or (None if task.role else _TYPE_AGENT_MAP.get(task.task_type))
        if agent_name is None:
            return None
        agent_def = self.agent_registry.get(agent_name)
        if agent_def is None:
            log.debug("Agent '%s' not found in registry", agent_name)
            return None
        from core.agent.agent_contracts_policy import (
            _load_agent_contracts_override,
            apply_agent_contracts_policy,
        )

        agent_def = apply_agent_contracts_policy(
            agent_def,
            _load_agent_contracts_override(sources=self.policy_sources.get("agent_contracts")),
        )
        return {
            "agent_name": agent_def.name,
            "role": agent_def.role,
            "system_prompt": agent_def.system_prompt,
            "tools": agent_def.tools,
            "toolkit": agent_def.toolkit,
            "model": agent_def.model,
        }

    def build_worker_request(
        self,
        task: SubTask,
        *,
        default_model: str = "",
        emit_activity: bool = False,
        resume: bool = False,
    ) -> WorkerRequest:
        """Build the subprocess request from the frozen task and live policy."""
        from core.agent.subagent_roles import (
            SUBAGENT_ROLES,
            get_role,
            output_schema_line,
            role_denied_tools,
        )
        from core.agent.worker import WorkerRequest
        from core.config import _resolve_provider, settings
        from core.tools.base import load_all_tool_definitions

        denied = set(self.denied_tools)
        role = get_role(task.role) if task.role else None
        if task.role and role is None:
            log.warning(
                "delegate_task: unknown sub-agent role %r — running with the "
                "default tool surface (known roles: %s)",
                task.role,
                sorted(SUBAGENT_ROLES),
            )
        if role is not None:
            denied |= role_denied_tools(
                role, [definition["name"] for definition in load_all_tool_definitions()]
            )

        difficulty = getattr(task, "difficulty", "medium")
        effort = {"low": "low", "medium": "medium", "high": "high"}.get(
            difficulty, settings.agentic_effort
        )
        if task.effort:
            effort = task.effort

        agent = self.resolve_agent(task)
        agent_name = ""
        system_prompt = ""
        allowed_tools: list[str] = []
        toolkit = ""
        model = default_model or settings.model
        if agent is not None:
            agent_name = str(agent.get("agent_name", ""))
            system_prompt = str(agent.get("system_prompt", ""))
            allowed_tools = [str(name) for name in agent.get("tools") or []]
            if agent.get("toolkit"):
                toolkit = str(agent["toolkit"])
            if agent.get("model"):
                model = str(agent["model"])
        if task.model:
            model = task.model

        description = task.description
        if role is not None:
            if role.role == "reviewer":
                from core.llm.prompts import REVIEWER_SYSTEM

                system_prompt = "\n\n".join(filter(None, (system_prompt, REVIEWER_SYSTEM)))
            if not toolkit and not allowed_tools:
                allowed_tools = list(role.tools)
            schema_line = output_schema_line(role)
            if schema_line:
                description = f"{description}\n\n{schema_line}"

        parent_session_id = get_session_id()
        return WorkerRequest(
            task_id=task.task_id,
            task_type=task.task_type,
            description=description,
            args=task.args,
            denied_tools=list(denied),
            model=model,
            provider=_resolve_provider(model),
            timeout_s=self.timeout_s,
            time_budget_s=self.time_budget_s,
            thinking_budget=settings.agentic_thinking_budget,
            subagent_max_tokens=settings.subagent_max_tokens,
            effort=effort,
            agent_name=agent_name,
            agent_system_prompt=system_prompt,
            agent_allowed_tools=allowed_tools,
            toolkit=toolkit,
            parent_session_key=self.parent_session_key or parent_session_id,
            parent_session_id=parent_session_id,
            source=task.source,
            policy_sources=encode_policy_sources(self.policy_sources),
            response_schema=task.response_schema,
            emit_activity=emit_activity,
            resume=resume,
        )

    def to_sub_result(self, task: SubTask, isolation: IsolationResult | None) -> SubResult:
        """Validate and normalize one isolation result."""
        if isolation is None:
            return SubResult(
                task_id=task.task_id,
                description=task.description,
                success=False,
                error=f"Timeout after {self.timeout_s}s",
            )
        if not isolation.success:
            return SubResult(
                task_id=task.task_id,
                description=task.description,
                success=False,
                error=isolation.error,
                duration_ms=isolation.duration_ms,
                prompt_tokens=isolation.prompt_tokens,
                completion_tokens=isolation.completion_tokens,
                usd_spent=isolation.usd_spent,
            )

        raw_text = isolation.output or ""
        if task.role:
            from core.agent.subagent_roles import get_role, validate_role_output

            role = get_role(task.role)
            if role is not None:
                output = validate_role_output(role, raw_text)
                if output is not None:
                    valid = output.get("validated") is True
                    return SubResult(
                        task_id=task.task_id,
                        description=task.description,
                        success=valid,
                        output=output,
                        error=None if valid else str(output.get("error", "")),
                        duration_ms=isolation.duration_ms,
                        prompt_tokens=isolation.prompt_tokens,
                        completion_tokens=isolation.completion_tokens,
                        usd_spent=isolation.usd_spent,
                    )

        candidate = _strip_json_codeblock(raw_text) if raw_text else raw_text
        try:
            parsed = json.loads(candidate) if candidate else {}
            output = parsed if isinstance(parsed, dict) else {"raw": parsed}
        except (json.JSONDecodeError, RecursionError):
            embedded = _last_balanced_json_object(raw_text)
            if embedded is None:
                output = {"raw": raw_text}
            else:
                try:
                    parsed = json.loads(embedded)
                    output = parsed if isinstance(parsed, dict) else {"raw": raw_text}
                except (json.JSONDecodeError, RecursionError):
                    output = {"raw": raw_text}
        return SubResult(
            task_id=task.task_id,
            description=task.description,
            success=True,
            output=output,
            duration_ms=isolation.duration_ms,
            prompt_tokens=isolation.prompt_tokens,
            completion_tokens=isolation.completion_tokens,
            usd_spent=isolation.usd_spent,
        )


__all__ = [
    "SubResult",
    "SubTask",
    "SubagentProtocol",
    "SubagentRunRecord",
]
