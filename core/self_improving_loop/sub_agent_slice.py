"""A.8 (2026-05-25) — sub-agent contract slice helper (PR-21).

Plan ``docs/plans/2026-05-25-p4-parl-swarm-scaffolding.md`` §C4.

PR-14 의 ``propose_swarm`` 가 M sub-agent 를 동일 prompt + temperature
stochasticity 로 호출 — sub-agent diversity 가 의도된 게 아니라 random
seed 의존. A.8 가 그 위 layer: 각 sub-agent 가 **deterministic slice**
의 agent_contract focus 받아 mutation chain 분기.

5-stage slice (sub_agent_count 의 config cap 과 일치):

| idx | Slice name | Focus | Mutation tendency |
|---|---|---|---|
| 0 | ``role`` | ego / self-description | wrapper prompt role section |
| 1 | ``tools`` | tool_policy + tool_descriptions | tool selection policy |
| 2 | ``reflection`` | reflection cycles / critique policy | reflection_policy |
| 3 | ``decomposition`` | task breakdown + plan steps | decomposition_policy |
| 4 | ``interlocutor`` | user model / dialogue framing | wrapper prompt user-model section |

Frontier: Kimi K2.6 PARL 의 post-trained decomposition (M sub-agent
각자 specialized policy slice) — mutator API frozen 라 inference-time
변형 = system prompt hint injection.

본 module = **pure helper**:

- :func:`compute_sub_agent_slice(idx, total)` — deterministic round-robin
  slice name
- :func:`derive_slice_prompt_hint(slice)` — mutator system prompt 에
  prepend 할 한 줄 hint

Caller (propose_swarm) 의 wiring 은 후속 PR — 본 PR scope = helper only.
"""

from __future__ import annotations

from typing import Final

SLICE_NAMES: Final[tuple[str, ...]] = (
    "role",
    "tools",
    "reflection",
    "decomposition",
    "interlocutor",
)
"""5 deterministic slices, ordered by sub_agent_index. config cap = 5
(``AutoresearchConfig.sub_agent_count`` ge=1, le=5) — slice idx 가
count 를 넘으면 round-robin (modulo)."""


_SLICE_PROMPT_HINTS: Final[dict[str, str]] = {
    "role": (
        "Focus this mutation on the wrapper prompt's *role* section — "
        "the agent's ego, self-description, voice."
    ),
    "tools": (
        "Focus this mutation on tool_policy or tool_descriptions — "
        "which tools the agent selects and how it phrases their use."
    ),
    "reflection": (
        "Focus this mutation on reflection_policy — the agent's "
        "self-critique cadence and what it re-examines after errors."
    ),
    "decomposition": (
        "Focus this mutation on decomposition_policy — how the agent "
        "breaks down tasks and orders plan steps."
    ),
    "interlocutor": (
        "Focus this mutation on the wrapper prompt's *user model* "
        "section — how the agent frames the operator's intent and "
        "dialogue conventions."
    ),
}


def compute_sub_agent_slice(idx: int, total: int) -> str:
    """Return slice name for sub-agent at ``idx`` out of ``total`` agents.

    Deterministic round-robin over :data:`SLICE_NAMES` — same idx +
    same total always yields the same slice. Negative idx or total <= 0
    raise ``ValueError``.

    When ``total > len(SLICE_NAMES)`` (i.e. > 5), the assignment wraps
    via modulo — caller (config cap=5) keeps this from happening at
    runtime, but the helper stays defensive.
    """
    if idx < 0:
        raise ValueError(f"sub_agent_index must be >= 0, got {idx}")
    if total <= 0:
        raise ValueError(f"total sub-agents must be >= 1, got {total}")
    return SLICE_NAMES[idx % len(SLICE_NAMES)]


def derive_slice_prompt_hint(slice_name: str) -> str:
    """Return the mutator system-prompt hint for ``slice_name``.

    Unknown slice → empty string (graceful — caller treats as "no hint",
    falls back to the unmodified system prompt).
    """
    return _SLICE_PROMPT_HINTS.get(slice_name, "")


__all__ = [
    "SLICE_NAMES",
    "compute_sub_agent_slice",
    "derive_slice_prompt_hint",
]
