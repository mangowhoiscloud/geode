"""External half-duplex boundary between GEODE turns and tau2 simulations."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _jsonish(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except TypeError:
        return str(value)


@dataclass
class GeodeTau2State:
    loop: Any
    messages_seen: int = 0
    deadline_at: float | None = None


class _Tau2TurnDeadlineError(RuntimeError):
    """A participant call exhausted the evaluator-owned simulation deadline."""


def _message_to_prompt(message: Any, *, recipient: str) -> str:
    raw_role = getattr(message, "role", "user") or "user"
    role = str(getattr(raw_role, "value", raw_role) or "user").lower()
    if "." in role:
        role = role.rsplit(".", 1)[-1]
    tool_messages = getattr(message, "tool_messages", None)
    if tool_messages:
        payload = [
            {
                "id": getattr(tool_message, "id", ""),
                "requestor": getattr(tool_message, "requestor", ""),
                "content": getattr(tool_message, "content", ""),
                "error": getattr(tool_message, "error", False),
            }
            for tool_message in tool_messages
        ]
        return f"Tool results to {recipient} from tau2 orchestrator:\n{_jsonish(payload)}"
    content = str(getattr(message, "content", "") or "").strip()
    if content:
        if role == "tool":
            return f"Tool result to {recipient} from tau2 orchestrator:\n{content}"
        return f"Message to {recipient} from {role}:\n{content}"
    tool_calls = getattr(message, "tool_calls", None)
    if tool_calls:
        return (
            f"Message to {recipient} from {role} containing tool calls:\n"
            f"{_jsonish([tc.model_dump() for tc in tool_calls])}"
        )
    return f"Message to {recipient} from {role}: [empty]"


def _tool_mutates_state(tool: Any) -> bool:
    """Read tau2's decorated mutability marker; unknown tools fail safe."""

    marker = getattr(getattr(tool, "_func", None), "__mutates_state__", None)
    return marker if isinstance(marker, bool) else True


_AGENT_POLICY_PATH = Path(__file__).with_name("tau2_agent_policy.md")


def _agent_policy() -> str:
    """Load the candidate-owned agent policy from one bounded regular file."""

    info = _AGENT_POLICY_PATH.lstat()
    if not _AGENT_POLICY_PATH.is_file() or _AGENT_POLICY_PATH.is_symlink():
        raise RuntimeError("tau2 agent policy must be a regular file")
    if info.st_size > 16 * 1024:
        raise RuntimeError("tau2 agent policy exceeds 16384 bytes")
    policy = _AGENT_POLICY_PATH.read_text(encoding="utf-8").strip()
    if not policy:
        raise RuntimeError("tau2 agent policy must not be empty")
    return policy


def _agent_system_prompt(domain_policy: str) -> str:
    return (
        "Agent: GEODE running inside tau2-bench.\n"
        f"{_agent_policy()}\n\n"
        "<policy>\n"
        f"{domain_policy}\n"
        "</policy>"
    )


def _user_system_prompt(
    instructions: str | None,
    *,
    use_tools: bool,
) -> str:
    from tau2.user.user_simulator import get_global_user_sim_guidelines

    guidelines = get_global_user_sim_guidelines(use_tools=use_tools)
    return (
        "Role: simulated tau2 benchmark user running through GEODE.\n"
        "Boundary: not the assistant; customer/user in the scenario.\n"
        "Follow the scenario and simulator guidelines exactly. If the task is "
        "complete or the conversation should end, use tau2's required stop token "
        "when the guidelines call for it.\n\n"
        f"{guidelines}\n\n"
        "<scenario>\n"
        f"{instructions or ''}\n"
        "</scenario>"
    )


def _usage_dict(result: Any) -> dict[str, Any] | None:
    result_usage = getattr(result, "usage", None)
    if result_usage is None:
        return None
    to_dict = getattr(result_usage, "to_dict", None)
    if callable(to_dict):
        maybe_dict = to_dict()
        if isinstance(maybe_dict, Mapping):
            return {str(key): value for key, value in maybe_dict.items()}
        return None
    raw = getattr(result_usage, "__dict__", None)
    return {str(key): value for key, value in raw.items()} if isinstance(raw, dict) else None


def _tau2_tool_calls(result: Any, *, requestor: str) -> list[Any]:
    entries = getattr(result, "tool_calls", []) or []
    if not isinstance(entries, list):
        raise RuntimeError("GEODE tau2 tool log must be a list")
    from tau2.data_model.message import ToolCall

    calls = []
    for idx, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        result_payload = entry.get("result")
        if isinstance(result_payload, dict) and result_payload.get("error"):
            continue
        tool_name = str(entry.get("tool", "") or "")
        tool_input = entry.get("input")
        if not tool_name or not isinstance(tool_input, dict):
            continue
        projected_args = {key: value for key, value in tool_input.items() if value is not None}
        calls.append(
            ToolCall(
                id=str(entry.get("tool_use_id") or f"geode_{requestor}_{idx}"),
                name=tool_name,
                arguments=projected_args,
                requestor=requestor,
            )
        )
    return calls


def _tau2_terminal_token(result: Any) -> str | None:
    """Map a generic GEODE convergence stop to tau2's native terminal token."""

    if getattr(result, "termination_reason", None) == "repeated_success_no_progress":
        return "###STOP###"
    return None


def _run_geode_turn(state: GeodeTau2State, prompt: str) -> Any:
    """Run one GEODE turn under the absolute tau2 simulation deadline."""

    if state.deadline_at is None:
        return asyncio.run(state.loop.arun(prompt))
    remaining = state.deadline_at - time.monotonic()
    if remaining <= 0:
        raise _Tau2TurnDeadlineError("tau2 simulation deadline elapsed")

    async def run() -> Any:
        return await asyncio.wait_for(state.loop.arun(prompt), timeout=remaining)

    try:
        return asyncio.run(run())
    except TimeoutError as exc:
        raise _Tau2TurnDeadlineError("tau2 simulation deadline elapsed") from exc
