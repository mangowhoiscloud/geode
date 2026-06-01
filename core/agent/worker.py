"""Subprocess worker for isolated sub-agent execution.

Spawned by IsolatedRunner._execute_subprocess() as:
    python -m core.agent.worker

Protocol:
    stdin  → single JSON line (WorkerRequest)
    stdout → single JSON line (WorkerResult)
    stderr → log output (captured by parent for debugging)

The worker bootstraps a minimal GEODE runtime, runs an AgenticLoop
with the given prompt, and writes the result to stdout. It never
spawns child sub-agents (depth=1 enforced, matching Claude Code).
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any

from core.async_runtime import run_process_coroutine
from core.paths import GLOBAL_WORKERS_DIR

if TYPE_CHECKING:
    from core.agent.loop.models import AgenticResult

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data contracts
# ---------------------------------------------------------------------------

WORKER_DIR = GLOBAL_WORKERS_DIR  # P2 — was `Path.home() / ".geode" / "workers"`


@dataclass
class WorkerRequest:
    """Serializable request from parent process to worker subprocess."""

    task_id: str
    task_type: str = ""
    description: str = ""  # Prompt text
    args: dict[str, Any] = field(default_factory=dict)
    denied_tools: list[str] = field(default_factory=list)
    model: str = "claude-opus-4-6"
    provider: str = "anthropic"
    # PR-CHECKPOINT-RESUME-TIMEBUDGET (2026-05-25, S6) — default raised
    # 120 → 600 to match SubAgentManager default (env-tunable via
    # ``GEODE_SUBAGENT_TIMEOUT_S``). Smoke 16 evolver hit 122s in
    # plan.decompose_async on the prior cap.
    timeout_s: float = 600.0
    time_budget_s: float = 0.0  # 0 = inherit parent's budget
    thinking_budget: int = 0  # 0 = disabled; >0 = thinking tokens per call (legacy)
    effort: str = "high"  # "low" | "medium" | "high" | "max" | "xhigh" (v0.56.0)
    isolation: str = ""  # Reserved for Phase 3: "worktree" etc.
    # Agent context (S2-wire, 2026-05-18):
    # When ``agent_name`` is non-empty the parent has resolved an
    # AgentDefinition (``.claude/agents/<agent_name>.md``) and pre-
    # populated the role/system prompt/tools/model overrides. The
    # worker applies these to the spawned AgenticLoop so the spawn
    # actually behaves as the named agent rather than the generic
    # default. ``agent_allowed_tools`` is a *whitelist* that the worker
    # translates into a denied set against the full tool list; empty
    # means the agent inherits the parent's denied set unchanged.
    agent_name: str = ""
    agent_system_prompt: str = ""
    agent_allowed_tools: list[str] = field(default_factory=list)
    # CSP-1 (2026-05-22) — named tool bundle the agent declared in its
    # frontmatter (``toolkit:`` key). Resolved by
    # ``filter_handlers`` against ``core/tools/toolkits.toml``. When
    # both ``toolkit`` and ``agent_allowed_tools`` are set, ``toolkit``
    # takes precedence; the legacy list path stays available for
    # AgentDefinitions that haven't migrated yet (backwards compat).
    toolkit: str = ""
    # Sub-agent lineage (2026-05-21) — parent's routing key + uuid
    # threaded into the child loop so its Episodes carry both for
    # cross-session attribution. Empty strings = top-level spawn.
    parent_session_key: str = ""
    parent_session_id: str = ""
    # v0.99.40 Follow-up A — adapter source for the new
    # :class:`core.llm.adapters.LLMAdapter` registry. Concrete value
    # (``"payg"`` / ``"subscription"`` / ``"adapter"``) when the parent's
    # picker / orchestrator resolved a specific path; empty string is
    # normalised to ``"payg"`` by ``AgenticLoop.__init__``
    # (PR-MAINPATH-67 deleted the legacy ``resolve_agentic_adapter``
    # fallback route — all dispatch now goes through Path-B).
    source: str = ""
    # PR-JSON-WIRE (2026-05-25) — per-task JSON Schema for
    # structured-output forcing on the spawned LLM call. Threads
    # through ``AgenticLoop.response_schema`` →
    # ``AdapterCallRequest.response_schema`` → claude-cli
    # ``--json-schema`` / codex-cli ``--output-schema``. ``None``
    # preserves back-compat (caller without a schema gets free-form
    # text). Per-role schemas live in
    # ``plugins/seed_generation/json_schemas.py`` and are wired in
    # each role's ``_build_tasks``.
    response_schema: dict[str, Any] | None = None
    # PR-Q (2026-05-24) chose to carry the orchestrator's active run_dir
    # across the parent → worker boundary via the ``GEODE_RUN_DIR``
    # environment variable (see
    # ``core.observability.run_dir.RUN_DIR_ENV`` +
    # ``IsolatedRunner._aexecute_subprocess``). The worker's
    # ``main()`` re-binds the ContextVar from that env on entry, so
    # every observability writer reads the live value via
    # ``get_active_run_dir()``. The earlier ``run_dir: str = ""``
    # field on this dataclass was orphaned dead code — no producer
    # ever populated it, only ``from_dict`` echoed its missing-default
    # — and a dual-SoT trap for the next reader (see
    # PR-CLEANUP-WORKER-REQUEST-RUN-DIR, 2026-05-25). Removed.

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkerRequest:
        return cls(
            task_id=data["task_id"],
            task_type=data.get("task_type", ""),
            description=data.get("description", ""),
            args=data.get("args", {}),
            denied_tools=data.get("denied_tools", []),
            model=data.get("model", "claude-opus-4-6"),
            provider=data.get("provider", "anthropic"),
            timeout_s=data.get("timeout_s", 600.0),
            # v0.55.0 R5 — reasoning depth fields were declared on the
            # dataclass since v0.50.x but never deserialised, so every
            # sub-agent ran at the dataclass defaults regardless of
            # what the parent put on the wire. Hermes / Claude Code
            # both inherit reasoning depth into spawned children
            # (delegate_tool.py:608, loadAgentsDir.ts:116).
            time_budget_s=data.get("time_budget_s", 0.0),
            thinking_budget=data.get("thinking_budget", 0),
            effort=data.get("effort", "high"),
            isolation=data.get("isolation", ""),
            agent_name=data.get("agent_name", ""),
            agent_system_prompt=data.get("agent_system_prompt", ""),
            agent_allowed_tools=data.get("agent_allowed_tools", []),
            toolkit=data.get("toolkit", ""),
            parent_session_key=data.get("parent_session_key", ""),
            parent_session_id=data.get("parent_session_id", ""),
            source=data.get("source", ""),
            response_schema=data.get("response_schema"),
        )


@dataclass
class WorkerResult:
    """Serializable result from worker subprocess to parent process.

    PR-SEEDGEN-TOKENS (2026-05-30) — carry per-call LLM usage across the
    worker IPC boundary so the seed-generation pipeline can roll up
    per-agent / per-phase / run-level token + cost. The sub-agent's
    ``AgenticResult.usage`` (captured via ``TokenTracker.delta_since`` in
    ``core/agent/loop/_lifecycle.py``) was previously dropped here because
    ``WorkerResult`` had no usage fields, so everything serialized to the
    parent reported zeros.

    HARD LIMITATION: subscription / CLI-routed calls (claude-cli,
    codex-cli) return an empty ``UsageSummary()`` — the subscription path
    does not expose token usage (see ``core/llm/adapters/claude_cli.py``
    and ``core/llm/adapters/codex_cli.py``). For those calls these fields
    are honestly left at 0; only API-key / payg calls populate real
    numbers. We never fabricate counts.
    """

    task_id: str
    success: bool
    output: str = ""  # Full AgenticLoop response text
    summary: str = ""  # Truncated summary (max 500 chars)
    error: str | None = None
    duration_ms: float = 0.0
    # LLM usage for this sub-agent invocation (0 for subscription calls).
    prompt_tokens: int = 0
    completion_tokens: int = 0
    usd_spent: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkerResult:
        return cls(
            task_id=data["task_id"],
            success=data["success"],
            output=data.get("output", ""),
            summary=data.get("summary", ""),
            error=data.get("error"),
            duration_ms=data.get("duration_ms", 0.0),
            prompt_tokens=data.get("prompt_tokens", 0),
            completion_tokens=data.get("completion_tokens", 0),
            usd_spent=data.get("usd_spent", 0.0),
        )


# ---------------------------------------------------------------------------
# Worker bootstrap and execution
# ---------------------------------------------------------------------------


def filter_handlers(
    *,
    handlers: dict[str, Any],
    denied_tools: list[str],
    agent_allowed_tools: list[str],
    toolkit: str = "",
    toolkit_registry: Any | None = None,
) -> dict[str, Any]:
    """Apply denied-set + agent toolkit/whitelist to the tool handler map.

    Pure function — testable without the worker's AgenticLoop bootstrap.

    Resolution priority (CSP-1, 2026-05-22):

    1. **toolkit** — if non-empty AND ``toolkit_registry`` is provided,
       the registry expands the name (with ``includes`` recursion) into
       a tool allowlist. Unknown toolkit names fall through to
       ``_default`` (with a WARNING) so a typo cannot zero out the
       agent's capability.
    2. **agent_allowed_tools** — legacy flat whitelist from the
       AgentDefinition's ``tools:`` frontmatter. Used when no toolkit
       is declared (backwards compat with pre-CSP-1 AgentDefs).
    3. **_default** — when neither is set AND the registry has a
       ``_default`` toolkit, that fallback is applied. This means a
       sub-agent that declares neither ``toolkit:`` nor ``tools:`` gets
       a minimal read-only safety net rather than inheriting the full
       parent surface.

    Invariants regardless of which branch applied:

    - ``delegate_task`` is always denied (depth=1 enforcement).
    - Whitelist entries that don't match any handler emit a WARNING so
      typos in frontmatter (e.g. ``foo_typo``) don't silently degrade
      the agent's capability to zero tools (S2-fix, 2026-05-18).
    """
    denied = set(denied_tools)
    denied.add("delegate_task")
    allowed: set[str] | None = None
    if toolkit and toolkit_registry is not None:
        # Tier 1 — named toolkit takes precedence. The registry already
        # handles missing-toolkit fallback to ``_default`` with a WARNING.
        allowed = set(toolkit_registry.resolve_with_fallback(toolkit))
    elif toolkit and toolkit_registry is None:
        # CSP-1 fix-up (Codex MCP MEDIUM #2) — fail closed when the
        # caller explicitly declared a toolkit but no registry was
        # supplied. Silently routing to ``agent_allowed_tools`` or to
        # the full surface would let a misconfigured spawn quietly
        # ignore the operator's whitelist intent.
        log.warning(
            "filter_handlers: agent declared toolkit=%r but no "
            "toolkit_registry was provided — failing closed (no tools "
            "allowed). Pass ``toolkit_registry=load_default_registry()`` "
            "if you want the named toolkit applied.",
            toolkit,
        )
        allowed = set()
    elif agent_allowed_tools:
        # Tier 2 — legacy ``tools:`` frontmatter list (backwards compat).
        allowed = set(agent_allowed_tools)
    elif toolkit_registry is not None:
        # Tier 3 — no declaration at all → ``_default`` safety net.
        # CSP-1 fix-up (Codex MCP HIGH #2) — fail closed even when the
        # ``_default`` toolkit is missing or empty. Pre-fix this branch
        # left ``allowed = None`` so a registry without ``_default``
        # silently re-opened the full handler surface — the inverse of
        # the "minimal read-only safety net" claim.
        allowed = set(toolkit_registry.resolve_with_fallback(None))
    if allowed is not None:
        unknown = allowed - set(handlers)
        if unknown:
            log.warning(
                "filter_handlers: agent allowlist references tool names "
                "not in the handler registry — %s. The agent will run "
                "without these tools. Check the agent's toolkit / "
                "frontmatter for typos.",
                sorted(unknown),
            )
        for tool_name in list(handlers):
            if tool_name not in allowed:
                denied.add(tool_name)
    if denied:
        return {k: v for k, v in handlers.items() if k not in denied}
    return handlers


def _save_result_backup(result: WorkerResult) -> None:
    """Persist the WorkerResult JSON for crash debugging.

    PR-Q (2026-05-24) — when an active run_dir is bound (the parent
    orchestrator opened a :func:`run_dir_scope` and the env carrier
    propagated it into this subprocess) the backup lands under
    ``<run_dir>/sub_agents/<task_id>/result.json`` so a single cycle's
    artifacts stay co-located. Otherwise falls back to the legacy
    global ``~/.geode/workers/<task_id>.result.json`` pool.
    """
    from core.observability.run_dir import resolve_sub_agent_path

    try:
        result_path = resolve_sub_agent_path(result.task_id, "result.json")
        if result_path is None:
            WORKER_DIR.mkdir(parents=True, exist_ok=True)
            result_path = WORKER_DIR / f"{result.task_id}.result.json"
        result_path.write_text(
            json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        log.debug("Failed to save result backup for %s", result.task_id, exc_info=True)


def _run_agentic(request: WorkerRequest) -> WorkerResult:
    """Bootstrap minimal GEODE runtime and run AgenticLoop."""
    started = time.time()

    # PR-RESUME-NO-PERSIST-FIX (2026-05-25) — bind a per-task isolated
    # working directory so claude-cli's cwd-keyed session cache
    # (``~/.claude/projects/<cwd-hash>/sessions/``) is unique per
    # ``task_id``. This replaces the blunt ``--no-session-persistence``
    # flag from PR-PERMS-FLAG-FIX B (which disabled ALL persistence and
    # broke PR-V's intra-task ``--resume`` path). Cross-sub-agent leak
    # via cwd-cache auto-pickup is now prevented because each task_id
    # has its own cache pool; within-task continuity still works
    # because turn N+1 sees the same cwd as turn N.
    #
    # PR-CLEANUP-WORKER-REQUEST-RUN-DIR (2026-05-25) — the first cut
    # of this binding read ``request.run_dir`` (a dead field on
    # ``WorkerRequest`` that no producer ever populated), so the
    # guard never fired and the mkdir never ran. Smoke 11 confirmed
    # the wiring gap (no ``cwd/`` subdir in ``sub_agents/<task_id>/``).
    # The live SoT for an orchestrator-bound run_dir at the worker
    # side is :func:`core.observability.run_dir.get_active_run_dir`
    # — ``worker.main()`` already re-binds the ContextVar from the
    # ``GEODE_RUN_DIR`` env var on entry, so by the time
    # ``_run_agentic`` runs the value is available.
    from core.observability.run_dir import get_active_run_dir

    active_run_dir = get_active_run_dir()
    if active_run_dir is not None and request.task_id:
        from core.agent.task_isolation import set_task_isolated_cwd

        task_cwd_path = active_run_dir / "sub_agents" / request.task_id / "cwd"
        task_cwd_path.mkdir(parents=True, exist_ok=True)
        set_task_isolated_cwd(task_cwd_path)

    # 1. Build tool handlers (same factory as CLI)
    from core.cli.tool_handlers import _build_tool_handlers

    handlers = _build_tool_handlers(verbose=False)

    # 2. Filter tools — CSP-1 (2026-05-22): consult the toolkit registry
    # so the agent's declared ``toolkit:`` frontmatter expands into the
    # allowlist (with ``_default`` fallback when undeclared).
    from core.tools.toolkit_registry import load_default_registry

    handlers = filter_handlers(
        handlers=handlers,
        denied_tools=request.denied_tools,
        agent_allowed_tools=request.agent_allowed_tools,
        toolkit=request.toolkit,
        toolkit_registry=load_default_registry(),
    )
    # CSP-1 (2026-05-22) — the resulting handler key set is also the
    # set of tool names the model should see. Pass it through to
    # AgenticLoop so the tool schemas advertised to the LLM match the
    # executor's allowlist (otherwise denied tools would be visible to
    # the model and only fail at execution time as "Unknown tool").
    allowed_tool_names = set(handlers)

    # 3. Build ToolExecutor (auto_approve=True for sub-agents)
    from core.agent.tool_executor import ToolExecutor

    executor = ToolExecutor(
        action_handlers=handlers,
        auto_approve=True,  # Sub-agents skip HITL prompts
    )

    # 4. Build ConversationContext
    from core.agent.conversation import ConversationContext

    conversation = ConversationContext(max_turns=200)

    # 5. Build AgenticLoop
    from core.agent.loop import AgenticLoop

    # S2-wire (2026-05-18): propagate AgentDefinition.system_prompt into the
    # spawned loop so AgentDefinition-driven sub-agents (seed_generator etc.)
    # actually behave as the named agent rather than running GEODE's generic
    # default. Worker carries the resolved prompt over the IPC boundary so
    # the subprocess does not need its own AgentRegistry lookup.
    system_prompt_override: str | None = request.agent_system_prompt or None

    loop = AgenticLoop(
        conversation,
        executor,
        max_rounds=0,  # unlimited — controlled by timeout_s from parent
        max_tokens=32768,
        model=request.model,
        provider=request.provider,
        # v0.55.0 R5 — propagate reasoning depth + time budget into the
        # sub-agent's loop. Pre-fix every sub-agent ran at the
        # AgenticLoop defaults (effort="high", thinking_budget=0,
        # time_budget_s=0.0) because the kwargs were never threaded
        # through, even though WorkerRequest carried them. Mirrors
        # Hermes ``delegate_tool.py:607-636`` (parent-inherit + per-child
        # config override) and Claude Code ``loadAgentsDir.ts:116``
        # (agent-level effort frontmatter).
        thinking_budget=request.thinking_budget,
        effort=request.effort,
        time_budget_s=request.time_budget_s,
        system_prompt_override=system_prompt_override,
        parent_session_key=request.parent_session_key,
        parent_session_id=request.parent_session_id,
        quiet=True,  # Suppress spinner — parent handles UI
        allowed_tool_names=allowed_tool_names,
        source=request.source,
        # PR-Q.5 (2026-05-24, single-anchor invariant I1 in
        # docs/plans/2026-05-24-transcript-standardization-and-claude-resume.md):
        # the sub-agent's task_id becomes the AgenticLoop's session_id so
        # the worker's SessionTranscript (dialogue.jsonl) lands in the
        # SAME ``<run_dir>/sub_agents/<task_id>/`` directory as
        # result.json + stderr.log. Without this the AgenticLoop generates
        # a fresh ``s-<uuid>`` and dialogue.jsonl falls into a sibling
        # directory that the operator cannot reach from the timeline's
        # ``details.task_id`` reference.
        session_id=request.task_id,
        # PR-JSON-WIRE (2026-05-25) — thread the per-task JSON Schema
        # to the AgenticLoop so every spawned adapter call carries
        # ``AdapterCallRequest.response_schema``. Empty / None
        # preserves legacy free-form text responses for callers that
        # didn't declare a schema (REPL, gateway, ad-hoc CLI).
        response_schema=request.response_schema,
        # PR-GENERATOR-PLAN-LEAK-FIX (2026-05-26) — disable goal
        # decomposition for sub-agents. Sub-agents are specialised
        # executors driven by an AgentDefinition + supervisor-built
        # task description; the parent orchestrator already performed
        # whatever decomposition was needed. Leaving it on caused a
        # silent partial-write defect (smoke 20, 2/15 generator spawns):
        # the per-task description contained natural English
        # connectors ("frontmatter fields ... AND tags",
        # "call ``seed_debate_turn`` ... then turn=2") that tripped
        # ``_has_compound_indicators`` → ``decompose_async`` fired with
        # the decomposer system prompt → claude-cli cached that prompt
        # under the sub-agent's session_id → ``_persist_session_id``
        # stamped it as the resume target → the next ``_call_llm``
        # turn (now carrying the *generator* system prompt) was
        # dispatched with ``resume_session_id`` set, which makes
        # ``build_subprocess_stdin`` SKIP the system prompt block
        # ("already cached"). claude-cli resumed the decomposer
        # conversation, the model stayed in decomposition mode, and
        # emitted a ``DecompositionResult``-shape JSON instead of
        # calling ``seed_debate_turn`` / ``write_file``. Worker
        # reported ``success=True`` (non-empty text, no error,
        # ``termination_reason="unknown"``) but no seed markdown was
        # written; downstream ranker hit FileNotFoundError and the
        # PR-VOTER-PROMPT-ANTI-PHANTOM UNAVAILABLE sentinel kicked in.
        # Evidence: ``state/seed-generation/gen1-redundant_tool_invocation/
        # sub_agents/gen-gen1-000-fe17d6c5/result.json`` — output is a
        # verbatim ``DecompositionResult`` JSON.
        enable_goal_decomposition=False,
    )

    # 7. Build prompt
    prompt = request.description
    if request.args:
        prompt += f"\n\nParameters: {json.dumps(request.args, ensure_ascii=False)}"

    # 8. Run
    agentic_result = run_process_coroutine(loop.arun(prompt))

    # PR-WORKER-SCHEMA-AWARE-RETRY (2026-05-26) — when the caller declared
    # a ``response_schema`` (PR-JSON-WIRE wired per-role schemas through
    # ``WorkerRequest`` → ``AgenticLoop``) but the first run produced
    # empty / unparseable / schema-missing-keys output, the prompt-level
    # PR-HANDOFF-SCHEMAS gate already failed for this task. Inject the
    # validator's verdict as a follow-up user turn (paperclip + open-
    # scientist validation-feedback pattern) and re-issue the loop once.
    # Cap at exactly one retry — a third pass would burn budget without
    # changing the underlying behaviour (the role contract is the same).
    #
    # Codex MCP review (2026-05-26) caught two pre-merge issues, both
    # patched below:
    #
    # 1. ``AgenticLoop.arun`` resets ``_loop_start_time`` on every call
    #    (``agent_loop.py:1463``), so the second pass would get another
    #    full ``time_budget_s`` rather than the remainder. Guard the
    #    retry on ``elapsed_before_retry < 0.5 * request.timeout_s`` so
    #    a worker pegged near its wall-clock cap doesn't get pushed past
    #    it (the subprocess ``asyncio.wait_for`` would kill the retry
    #    mid-flight, leaving the parent with no usable signal).
    # 2. The no-retry success exits (``input_blocked`` / ``user_cancelled``
    #    / ``user_clarification_needed``) carry intentional non-JSON text
    #    that the parent expects to surface as-is. The earlier guard would
    #    have fired the retry on these because they aren't in
    #    ``_FAILURE_TERMINATION_REASONS``; ``_needs_schema_retry`` now
    #    checks ``_NO_RETRY_TERMINATION_REASONS`` (see helper below).
    elapsed_before_retry = time.time() - started
    if (
        request.response_schema is not None
        and _needs_schema_retry(agentic_result, request.response_schema)
        and elapsed_before_retry < 0.5 * request.timeout_s
    ):
        feedback_prompt = _build_schema_retry_prompt(request.response_schema, agentic_result)
        log.warning(
            "worker.schema_retry task_id=%s reason=empty_or_malformed "
            "first_text_len=%d elapsed=%.1fs cap=%.1fs — re-issuing with "
            "validator feedback",
            request.task_id,
            len(agentic_result.text) if agentic_result else 0,
            elapsed_before_retry,
            request.timeout_s,
        )
        agentic_result = run_process_coroutine(loop.arun(feedback_prompt))
    elif request.response_schema is not None and _needs_schema_retry(
        agentic_result, request.response_schema
    ):
        # Same trigger fired, but the elapsed-time gate vetoed the retry.
        # Observability: surface why so an operator reading the worker
        # log can correlate "no retry" with "out of budget".
        log.warning(
            "worker.schema_retry_skipped task_id=%s elapsed=%.1fs cap=%.1fs "
            "— retry would push past 50%% of wall-clock cap",
            request.task_id,
            elapsed_before_retry,
            request.timeout_s,
        )

    elapsed_ms = (time.time() - started) * 1000
    success, summary, text = _resolve_worker_outcome(agentic_result)

    # PR-SEEDGEN-TOKENS (2026-05-30) — surface the sub-agent's per-arun
    # usage to the parent. ``agentic_result.usage`` is an ``LLMUsage``
    # aggregate (or None when the loop made no LLM call); subscription /
    # CLI calls leave it empty so the fields stay 0 — never fabricated.
    prompt_tokens = 0
    completion_tokens = 0
    usd_spent = 0.0
    usage = agentic_result.usage if agentic_result is not None else None
    if usage is not None:
        prompt_tokens = usage.input_tokens
        completion_tokens = usage.output_tokens
        usd_spent = usage.cost_usd

    return WorkerResult(
        task_id=request.task_id,
        success=success,
        output=text,
        summary=summary,
        duration_ms=elapsed_ms,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        usd_spent=usd_spent,
    )


# PR-DEFECT-AB (2026-05-24) — propagate AgenticLoop failures past the
# sub-agent IPC boundary. Pre-fix ``success=bool(text)`` returned True
# whenever the loop produced any string at all, including the
# ``_build_model_action_result`` fallback UI text
# ("! Unexpected error. Auto-retrying.") that agent_loop emits when
# every retry attempt has failed but the orchestrator still needs a
# non-empty payload to keep the timeline coherent. Downstream phase
# agents (proximity / critic) then ingested that fallback as
# legitimate content and produced malformed JSON.
#
# The fallback path always sets ``termination_reason`` to one of the
# explicit failure sentinels below — gate ``success`` on the absence of
# those plus the absence of ``error``. Sentinels enumerated from
# ``agent_loop.py`` (search ``termination_reason="``):
#
# * Failure exits (text is fallback / diagnostic UI, NOT a real answer):
#   ``model_action_required``, ``context_exhausted``, ``llm_error``,
#   ``billing_error``, ``cost_budget_exceeded``, ``convergence_detected``
#   (loop bailed after detecting a repeating error pattern — see
#   ``agent_loop.py`` ~1828 where ``error="convergence_detected"`` is
#   set alongside termination_reason).
# * Success exits (text IS the legitimate output):
#   ``unknown`` (default success exit), ``input_blocked`` (text is the
#   block diagnostic that the parent expects to surface),
#   ``user_clarification_needed`` (text IS the follow-up question),
#   ``user_cancelled`` (operator-requested halt — text is "Interrupted.").
_FAILURE_TERMINATION_REASONS: frozenset[str] = frozenset(
    {
        "model_action_required",
        "context_exhausted",
        "llm_error",
        "billing_error",
        "cost_budget_exceeded",
        "convergence_detected",
    }
)

# PR-WORKER-SCHEMA-AWARE-RETRY (2026-05-26) — termination reasons whose
# text is intentional non-JSON and MUST NOT be re-issued to the loop
# even when a ``response_schema`` is set:
#
# * ``input_blocked`` — policy filter rejected the prompt. Retrying with
#   stronger schema language wouldn't change the input that got blocked.
# * ``user_cancelled`` — operator pressed cancel. The "Interrupted."
#   marker is the legitimate output (see ``agent_loop.py:705``); a
#   retry would override the cancel intent.
# * ``user_clarification_needed`` — overthinking detected; text IS the
#   follow-up question. Retrying re-burns the budget that the loop
#   bailed out of in the first place.
#
# Sourced from ``_resolve_worker_outcome``'s success-exit catalogue
# (worker.py ~480-490 docstring) — anything classified as success there
# must stay success here, otherwise the retry would invalidate the
# parent's classification.
_NO_RETRY_TERMINATION_REASONS: frozenset[str] = frozenset(
    {
        "input_blocked",
        "user_cancelled",
        "user_clarification_needed",
    }
)


def _needs_schema_retry(
    agentic_result: AgenticResult | None,
    response_schema: dict[str, Any],
) -> bool:
    """Return True when a structured-output task's first attempt missed.

    PR-WORKER-SCHEMA-AWARE-RETRY (2026-05-26) — the role's prompt-level
    PR-HANDOFF-SCHEMAS gate ("FINAL response must be ONLY the JSON
    object … Start with `{` and end with `}`") is best-effort; smoke 17
    showed Codex + sub-agent runs occasionally finishing with empty
    output_text or with prose surrounding the JSON. Worker-side this is
    the last safety net before the parent orchestrator records
    ``phase_failed`` and the run aborts. Returns True iff:

    * ``agentic_result`` is missing or carries an explicit failure
      ``error`` / ``termination_reason`` — the loop already gave up;
    * the loop's text is empty / whitespace-only;
    * the text does not contain a balanced ``{...}`` block that parses
      under ``json.loads`` (free-form prose, codeblock fence noise);
    * the parsed object is missing any ``required`` key declared on
      ``response_schema`` (the loop emitted *a* JSON, but not the role's
      schema — e.g. ``{}`` or a partial echo).

    The function deliberately does NOT validate property types or
    ``enum`` membership — that strictness belongs in the parent
    orchestrator's parser. Retrying for soft mismatches would just burn
    budget on the same prompt.

    Codex MCP review (2026-05-26) — the no-retry success exits
    (``input_blocked``, ``user_cancelled``, ``user_clarification_needed``)
    carry intentional non-JSON text that the parent expects to surface
    as-is. ``_resolve_worker_outcome`` already classifies them as
    ``success=True``. Returning ``True`` here would re-call the loop on
    a cancelled / blocked / clarification task — wasted budget and
    semantically wrong. The ``_NO_RETRY_TERMINATION_REASONS`` check
    below short-circuits those before the text-parse branch.
    """
    if agentic_result is None:
        return True
    if agentic_result.termination_reason in _NO_RETRY_TERMINATION_REASONS:
        return False
    if agentic_result.error:
        return True
    if agentic_result.termination_reason in _FAILURE_TERMINATION_REASONS:
        return True

    text = (agentic_result.text or "").strip()
    if not text:
        return True

    # Local import — keep core/agent/worker.py free of a hard sub_agent
    # dependency at module import time (worker.py is the IPC entry point;
    # we want it to bootstrap with the minimum import surface).
    from core.agent.sub_agent import _last_balanced_json_object

    candidate = _last_balanced_json_object(text)
    if candidate is None:
        # No balanced + parseable object anywhere in the body.
        return True

    try:
        parsed = json.loads(candidate)
    except (json.JSONDecodeError, ValueError):
        return True

    if not isinstance(parsed, dict):
        return True

    required = response_schema.get("required") if isinstance(response_schema, dict) else None
    if isinstance(required, list) and required:
        missing = [k for k in required if k not in parsed]
        if missing:
            return True

    return False


def _build_schema_retry_prompt(
    response_schema: dict[str, Any],
    agentic_result: AgenticResult | None,
) -> str:
    """Construct the validator-feedback follow-up turn for the retry.

    PR-WORKER-SCHEMA-AWARE-RETRY (2026-05-26) — pattern mirrors paperclip
    session replay + open-scientist ``validate_and_retry`` (llm.py:437):
    state the verdict, restate the contract, then ask for the JSON
    object only. The schema is emitted inline (truncated at 4096 chars
    so a giant role schema doesn't blow the context budget on the
    retry turn).
    """
    schema_text = json.dumps(response_schema, ensure_ascii=False, indent=2)
    if len(schema_text) > 4096:
        schema_text = schema_text[:4096] + "\n…(schema truncated; full version pinned upstream)"

    first_text = ""
    if agentic_result is not None and agentic_result.text:
        first_text = agentic_result.text.strip()
    if len(first_text) > 800:
        first_text = first_text[:800] + "…(truncated)"

    if not first_text:
        prior_diag = "Your previous response was empty."
    else:
        prior_diag = (
            "Your previous response did not parse as the required JSON object. "
            f"Excerpt: {first_text!r}"
        )

    return (
        f"{prior_diag}\n\n"
        "You MUST emit ONLY the JSON object matching this schema as your final message. "
        "No prose, no explanation, no markdown fences — start with `{` and end with `}`. "
        f"Required keys: {response_schema.get('required', [])}.\n\n"
        f"Schema:\n{schema_text}"
    )


# PR-GENERATOR-PLAN-LEAK-FIX (2026-05-26) — defence-in-depth detector
# for the ``DecompositionResult``-shape JSON leak documented at the
# ``enable_goal_decomposition=False`` site above. The structural fix is
# in ``_run_agentic`` (no decomposer call → no cached prompt to resume
# from); this helper is the last safety net before a ``success=True``
# row with a planner-shape body slips past into the orchestrator. The
# three-key shape (``is_compound`` bool + ``goals`` list + ``reasoning``
# string) matches ``core.agent.plan.DecompositionResult`` *exactly* —
# no real sub-agent role emits that triple (seed_generator writes
# markdown via ``write_file``; ranker / critic / proximity emit role
# schemas with ``candidate_id`` / ``score`` / ``reason`` keys).
_DECOMPOSITION_RESULT_KEYS: frozenset[str] = frozenset({"is_compound", "goals", "reasoning"})


def _looks_like_decomposition_result(text: str) -> bool:
    """Return True iff ``text``'s last balanced JSON object is a planner
    ``DecompositionResult`` echo (the leak documented at the
    ``enable_goal_decomposition=False`` worker call site).

    Conservative: requires the parsed object to be a ``dict`` containing
    ALL THREE planner keys with their canonical types (``is_compound``
    bool + ``goals`` list + ``reasoning`` string). Single-key overlaps
    (e.g. a role schema happening to include ``reasoning``) do not
    match.
    """
    if not text or not text.strip():
        return False
    # Local import to keep ``worker.py``'s module-level import surface
    # small (the IPC entry point should bootstrap without dragging in
    # the SubAgentManager).
    from core.agent.sub_agent import _last_balanced_json_object

    candidate = _last_balanced_json_object(text)
    if candidate is None:
        return False
    try:
        parsed = json.loads(candidate)
    except (json.JSONDecodeError, ValueError):
        return False
    if not isinstance(parsed, dict):
        return False
    if not _DECOMPOSITION_RESULT_KEYS.issubset(parsed.keys()):
        return False
    return (
        isinstance(parsed.get("is_compound"), bool)
        and isinstance(parsed.get("goals"), list)
        and isinstance(parsed.get("reasoning"), str)
    )


def _resolve_worker_outcome(
    agentic_result: AgenticResult | None,
) -> tuple[bool, str, str]:
    """Translate an :class:`AgenticResult` into ``(success, summary, text)``.

    Extracted from :func:`_run_agentic` so tests can pin the
    failure-propagation contract without spinning up the full sub-agent
    bootstrap pipeline.
    """
    text = agentic_result.text if agentic_result else ""
    termination_reason = agentic_result.termination_reason if agentic_result else "unknown"
    error = agentic_result.error if agentic_result else None

    success = bool(text) and not error and termination_reason not in _FAILURE_TERMINATION_REASONS

    # PR-GENERATOR-PLAN-LEAK-FIX (2026-05-26) — defence-in-depth: even
    # when the loop reports a clean termination with non-empty text, a
    # ``DecompositionResult``-shape body means the sub-agent never
    # executed its role tools (no ``seed_debate_turn`` / ``write_file``
    # for a generator; no schema-keyed output for evaluator roles).
    # Downgrade to ``success=False`` so the parent surfaces the defect
    # in the timeline instead of accepting a phantom seed.
    plan_leak = False
    if success and _looks_like_decomposition_result(text):
        success = False
        plan_leak = True

    # Summary surfaces the actual failure cause when ``success`` is False so
    # parent timeline rows ("Tool returned: ...") explain WHY the sub-agent
    # produced no usable output instead of echoing the fallback UI string.
    # The legacy "No response from sub-agent" string is reserved for the
    # "no signal at all" case (empty text + no error + no failure
    # termination) so existing graders/log-greppers keep working.
    cause_bits: list[str] = []
    if not success and agentic_result is not None:
        if error:
            cause_bits.append(error)
        if termination_reason and termination_reason != "unknown":
            cause_bits.append(f"termination_reason={termination_reason}")
        if plan_leak:
            cause_bits.append(
                "decomposition_result_leak (planner JSON emitted instead of tool calls)"
            )

    if cause_bits:
        summary = "Sub-agent failed: " + "; ".join(cause_bits)
    elif text:
        summary = text[:500]
    else:
        summary = "No response from sub-agent"

    return success, summary, text


def main() -> None:
    """Worker entry point. Reads request from stdin, writes result to stdout."""
    logging.basicConfig(
        level=logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,  # Logs go to stderr; stdout reserved for result JSON
    )

    # Post-MAINPATH-1 (#1572) the AgenticLoop's main body resolves the LLM
    # call site through Path-B ``core.llm.adapters.registry.resolve_for``.
    # The worker subprocess does not go through
    # ``core.runtime.GeodeRuntime._build_core`` (the parent's wiring
    # bootstrap), so without an explicit ``bootstrap_builtins()`` here
    # the worker's registry is empty and every sub-agent call crashes
    # with ``AdapterNotFoundError: Known pairs: []``. Idempotent — safe
    # to call even when the registry is already populated.
    from core.llm.adapters.registry import bootstrap_builtins

    bootstrap_builtins()

    # PR-Q (2026-05-24) — re-bind the parent's active run_dir into this
    # subprocess's ContextVar so observability writers
    # (``_save_result_backup``, ``SessionTranscript``) land their output
    # under ``<run_dir>/sub_agents/<task_id>/`` instead of the legacy
    # global pools. The parent forwarded the binding via the
    # :data:`RUN_DIR_ENV` env var (see ``IsolatedRunner._aexecute_subprocess``).
    # Empty / unset env = no orchestrator-bound run_dir = legacy
    # behaviour (writers use ``~/.geode/workers/`` + ``~/.geode/transcripts/``).
    from core.observability.run_dir import RUN_DIR_ENV, set_active_run_dir

    inherited_run_dir = os.environ.get(RUN_DIR_ENV, "")
    if inherited_run_dir:
        set_active_run_dir(inherited_run_dir)
        # PR-U (2026-05-24, Codex MCP catch of #1584) — ContextVars do
        # NOT cross subprocess boundaries. The parent's
        # ``run_transcript_scope(journal)`` binding is invisible here, so
        # ``SessionTranscript._mirror_to_run_transcript`` would silently
        # no-op for every worker-side agent event. Re-create a thin
        # ``RunTranscript`` instance that points at the SAME
        # ``<run_dir>/transcript.jsonl`` the parent's RunTranscript
        # writes to, and bind it to this subprocess's ContextVar so the
        # mirror path actually appends. JSONL row size (≤ 800 bytes) is
        # well under PIPE_BUF (4 KiB on macOS/Linux), so cross-process
        # append-to-same-file is line-atomic. ``session_id`` /
        # ``gen_tag`` / ``component`` on this child-side instance are
        # cosmetic — the actual row classification comes from the
        # mirror's explicit ``actor_type="agent"`` / ``action=...``
        # kwargs which override the orchestrator defaults.
        from pathlib import Path

        from core.self_improving.loop.run_transcript import (
            RunTranscript,
            set_current_run_transcript,
        )

        run_dir_path = Path(inherited_run_dir)
        worker_run_transcript = RunTranscript(
            session_id=run_dir_path.name,
            gen_tag="",
            component="seed-generation",
            path=run_dir_path / "transcript.jsonl",
        )
        # No need to capture the reset token — subprocess process exits
        # at the bottom of main(); the OS reclaims the ContextVar.
        set_current_run_transcript(worker_run_transcript)

    result: WorkerResult | None = None
    try:
        # Read request from stdin (single JSON line)
        raw = sys.stdin.readline()
        if not raw.strip():
            result = WorkerResult(
                task_id="unknown",
                success=False,
                error="Empty stdin — no request received",
            )
        else:
            request = WorkerRequest.from_dict(json.loads(raw))
            result = _run_agentic(request)
    except json.JSONDecodeError as exc:
        result = WorkerResult(
            task_id="unknown",
            success=False,
            error=f"Invalid JSON on stdin: {exc}",
        )
    except Exception as exc:
        task_id = "unknown"
        with contextlib.suppress(Exception):
            task_id = json.loads(raw).get("task_id", "unknown")
        result = WorkerResult(
            task_id=task_id,
            success=False,
            error=f"Worker crash: {type(exc).__name__}: {exc}",
        )

    # Write result to stdout (single JSON line)
    sys.stdout.write(json.dumps(result.to_dict(), ensure_ascii=False) + "\n")
    sys.stdout.flush()

    # Backup for crash debugging
    _save_result_backup(result)


if __name__ == "__main__":
    main()
