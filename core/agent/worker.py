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
    timeout_s: float = 120.0
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
            timeout_s=data.get("timeout_s", 120.0),
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
        )


@dataclass
class WorkerResult:
    """Serializable result from worker subprocess to parent process."""

    task_id: str
    success: bool
    output: str = ""  # Full AgenticLoop response text
    summary: str = ""  # Truncated summary (max 500 chars)
    error: str | None = None
    duration_ms: float = 0.0

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
    )

    # 7. Build prompt
    prompt = request.description
    if request.args:
        prompt += f"\n\nParameters: {json.dumps(request.args, ensure_ascii=False)}"

    # 8. Run
    agentic_result = run_process_coroutine(loop.arun(prompt))

    elapsed_ms = (time.time() - started) * 1000
    success, summary, text = _resolve_worker_outcome(agentic_result)

    return WorkerResult(
        task_id=request.task_id,
        success=success,
        output=text,
        summary=summary,
        duration_ms=elapsed_ms,
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
    # ``core.wiring.container._build_llm_adapters`` (the parent's wiring
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

        from core.self_improving_loop.run_transcript import (
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
