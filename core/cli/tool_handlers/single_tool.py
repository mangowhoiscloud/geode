"""Tool handlers that each wrap exactly one tool class.

Absorbed from six sibling files in PR-CLEANUP-5 (2026-05-23):
``data.py`` (synthetic data generation), ``notification.py`` (push
notifications), ``output.py`` (report + JSON export),
``offload.py`` (recall offloaded tool results),
``computer_use.py`` (desktop automation, gated by env flag), and
``calendar.py`` (calendar list/create/sync). Each builder used to
live in its own <50-LOC file purely because the original split
followed "one file per tool surface" — but every builder is the
same shape (instantiate the tool class, wrap its ``aexecute`` in
a closure, return ``{tool_name: handler}``), and they share zero
state. Folding them removes 6 sibling files without coupling any
new code paths.

The ``_build_<area>_handlers`` symbol names are preserved verbatim
so ``core/cli/tool_handlers/__init__.py`` and external callers
(e.g. the tool-handler audit script) keep working unchanged.
"""

from __future__ import annotations

from typing import Any

from core.tools.computer_observation import (
    ComputerActionEvent,
    build_action_event,
    evaluate_trajectory,
    trajectory_metrics,
)

# ---------------------------------------------------------------------------
# data — generate_data
# ---------------------------------------------------------------------------


def _build_data_handlers() -> dict[str, Any]:
    """Build synthetic data tool handlers."""
    from core.tools.data_tools import GenerateDataTool

    generate_data_tool = GenerateDataTool()

    async def handle_generate_data(**kwargs: Any) -> dict[str, Any]:
        return await generate_data_tool.aexecute(**kwargs)

    return {
        "generate_data": handle_generate_data,
    }


# ---------------------------------------------------------------------------
# notification — send_notification
# ---------------------------------------------------------------------------


def _build_notification_handlers() -> dict[str, Any]:
    """Build notification tool handlers."""
    from core.tools.output_tools import SendNotificationTool

    notification_tool = SendNotificationTool()

    async def handle_send_notification(**kwargs: Any) -> dict[str, Any]:
        return await notification_tool.aexecute(**kwargs)

    return {
        "send_notification": handle_send_notification,
    }


# ---------------------------------------------------------------------------
# output — generate_report, export_json
# ---------------------------------------------------------------------------


def _build_output_handlers() -> dict[str, Any]:
    """Build artifact/output tool handlers."""
    from core.tools.output_tools import ExportJsonTool, GenerateReportTool

    report_tool = GenerateReportTool()
    export_tool = ExportJsonTool()

    async def handle_generate_report(**kwargs: Any) -> dict[str, Any]:
        return await report_tool.aexecute(**kwargs)

    async def handle_export_json(**kwargs: Any) -> dict[str, Any]:
        return await export_tool.aexecute(**kwargs)

    return {
        "generate_report": handle_generate_report,
        "export_json": handle_export_json,
    }


# ---------------------------------------------------------------------------
# offload — recall_tool_result
# ---------------------------------------------------------------------------


def _build_offload_handlers() -> dict[str, Any]:
    """Build recall_tool_result handler for retrieving offloaded tool results."""

    def handle_recall_tool_result(**kwargs: Any) -> dict[str, Any]:
        from core.orchestration.tool_offload import get_offload_store

        ref_id = kwargs.get("ref_id", "")
        if not ref_id:
            return {"error": "ref_id is required"}
        store = get_offload_store()
        if store is None:
            return {"error": "Tool offloading is not enabled in this session"}
        result: dict[str, Any] = store.recall(ref_id)
        return result

    return {
        "recall_tool_result": handle_recall_tool_result,
    }


# ---------------------------------------------------------------------------
# computer_use — desktop automation (env-gated)
# ---------------------------------------------------------------------------


def _openai_action_to_harness(action: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Translate ONE OpenAI Responses GA computer action object → the harness
    ``(action_name, params)`` pair.

    The GA ``computer_call`` carries a batched ``actions[]`` array; each entry is
    a typed object with a ``type`` discriminator. The harness already aliases the
    GA action NAMES (click / double_click / type / keypress / scroll / move /
    drag / wait / screenshot), but three GA field shapes differ from the
    harness's flat kwargs and are remapped here:

    - ``keypress``: GA sends ``keys`` as a LIST of key strings; the harness
      ``key()`` expects a ``+``-joined combo string — join them.
    - ``scroll``: GA sends ``scroll_x`` / ``scroll_y`` distances; the harness
      ``scroll()`` expects ``direction`` + ``amount`` — derive from the dominant
      axis sign.
    - ``drag``: GA sends ``path`` (array of ``{x, y}`` points); the harness
      ``drag()`` takes a single ``start_x/start_y`` → ``end_x/end_y`` segment —
      the first and last path points are used; intermediate waypoints drop
      (a straight drag).

    KNOWN GAPS (honest functional limits — the host pyautogui harness has no
    equivalent, so these are dropped, never silently misencoded):
    - The optional held-modifier ``keys`` array GA attaches to ``click`` /
      ``double_click`` / ``move`` / ``scroll`` / ``drag`` (no modifier-hold param
      on the harness primitives).
    - Intermediate ``drag`` ``path`` waypoints (see above).
    - The non-dominant axis on a diagonal ``scroll`` (dominant axis wins).

    Schema ref: ctx7 /websites/developers_openai_api
    api-reference/responses/get "actions: ComputerActionList"
    (Click/DoubleClick/Scroll/Type/Keypress/Move/Drag/Wait/Screenshot).
    # backend acceptance: platform live-verified 2026-06-17 (codex rejects)
    """
    atype = str(action.get("type", ""))
    if atype == "keypress":
        keys = action.get("keys")
        combo = "+".join(str(k) for k in keys) if isinstance(keys, list) else str(keys or "")
        return "keypress", {"keys": combo}
    if atype == "type":
        return "type", {"text": action.get("text", "")}
    if atype in ("click", "double_click", "move"):
        params: dict[str, Any] = {"x": action.get("x", 0), "y": action.get("y", 0)}
        if atype == "click":
            params["button"] = action.get("button", "left")
        return atype, params
    if atype == "scroll":
        scroll_x = int(action.get("scroll_x", 0) or 0)
        scroll_y = int(action.get("scroll_y", 0) or 0)
        # Pick the dominant axis; positive scroll_y scrolls DOWN, positive
        # scroll_x scrolls RIGHT (OpenAI convention).
        if abs(scroll_x) > abs(scroll_y):
            direction = "right" if scroll_x > 0 else "left"
            amount = abs(scroll_x)
        else:
            direction = "down" if scroll_y > 0 else "up"
            amount = abs(scroll_y)
        return "scroll", {
            "x": action.get("x", 0),
            "y": action.get("y", 0),
            "direction": direction,
            "amount": amount or 3,
        }
    if atype == "drag":
        path = action.get("path")
        points = path if isinstance(path, list) and path else []
        start = points[0] if points else {}
        end = points[-1] if points else {}
        return "drag", {
            "start_x": start.get("x", 0) if isinstance(start, dict) else 0,
            "start_y": start.get("y", 0) if isinstance(start, dict) else 0,
            "end_x": end.get("x", 0) if isinstance(end, dict) else 0,
            "end_y": end.get("y", 0) if isinstance(end, dict) else 0,
        }
    if atype in ("wait", "screenshot"):
        return atype, {}
    # Unmapped action type — surface it; the harness returns an honest error
    # dict (never a silent skip) for an unknown action name.
    return atype or "<missing-type>", {}


def _build_computer_use_handler() -> dict[str, Any]:
    """Build computer-use handler (screenshot + mouse + keyboard).

    Handlers are always registered so the declarative tool metadata has an
    executor path. Each handler checks ``GEODE_COMPUTER_USE_ENABLED`` at call
    time and returns a structured permission error when disabled.
    """
    from core.tools.computer_use import ComputerUseHarness, execute_emulated_computer_use

    harness = ComputerUseHarness()

    async def handle_computer(**kwargs: Any) -> dict[str, Any]:
        from core.llm.providers.anthropic import is_computer_use_enabled

        if not is_computer_use_enabled():
            return {
                "error": "computer-use is disabled",
                "error_type": "permission",
                "hint": "Enable computer_use_enabled and configure host or sandbox execution.",
            }
        # OpenAI Responses GA path: ``computer_call`` delivers a BATCHED
        # ``actions[]`` array (the adapter maps it onto ``input.actions``). Run
        # each action in order, return the FINAL screenshot, and collect any
        # per-action errors honestly. Anthropic delivers a single ``action`` +
        # flat params — that path is preserved below.
        actions = kwargs.get("actions")
        if isinstance(actions, list):
            return await _run_batched_actions(harness, kwargs)
        # ``pop`` (not ``get``) — ``aexecute(action, **kwargs)`` passes
        # ``action`` positionally, so leaving it in ``kwargs`` raised
        # "got multiple values for argument 'action'" on every non-default
        # call (the tool was never live-exercised, so the crash stayed latent).
        action = kwargs.pop("action", "screenshot")
        return await harness.aexecute(action, **kwargs)

    async def handle_computer_use(**kwargs: Any) -> dict[str, Any]:
        from core.llm.providers.anthropic import is_computer_use_enabled

        if not is_computer_use_enabled():
            return {
                "error": "computer-use is disabled",
                "error_type": "permission",
                "hint": "Enable computer_use_enabled and configure host or sandbox execution.",
            }
        kwargs.pop("_tool_context", None)
        return await execute_emulated_computer_use(harness, **kwargs)

    return {"computer": handle_computer, "computer_use": handle_computer_use}


async def _run_batched_actions(harness: Any, kwargs: dict[str, Any]) -> dict[str, Any]:
    """Execute an OpenAI GA batched ``actions[]`` list through the harness.

    Returns a computer-result dict whose ``screenshot`` is the FINAL action's
    screenshot (the screen state the model sees on the next turn). Any
    per-action errors are collected into an ``errors`` list (honest reporting —
    a failed action never silently disappears). An empty batch falls back to a
    single ``screenshot`` so the next-turn ``computer_call_output`` still
    carries the current screen. ``pending_safety_checks`` echo back as
    ``acknowledged_safety_checks`` so the originating ``computer_call``'s checks
    are cleared on the next turn.
    """
    actions = kwargs.get("actions") or []
    pending_safety = kwargs.get("pending_safety_checks")
    last_result: dict[str, Any] = {}
    errors: list[dict[str, Any]] = []
    trajectory_events: list[ComputerActionEvent] = []
    for idx, raw_action in enumerate(actions):
        action = raw_action if isinstance(raw_action, dict) else {}
        name, params = _openai_action_to_harness(action)
        result = await harness.aexecute(name, **params)
        if isinstance(result, dict) and result.get("error"):
            errors.append({"action": name, "error": result["error"]})
        last_result = result if isinstance(result, dict) else {}
        trajectory_events.append(
            build_action_event(
                index=idx,
                action=name,
                params=params,
                result=last_result,
            )
        )
    if not actions:
        last_result = await harness.aexecute("screenshot")

        trajectory_events.append(
            build_action_event(
                index=0,
                action="screenshot",
                params={},
                result=last_result if isinstance(last_result, dict) else {},
            )
        )
    if not (isinstance(last_result, dict) and last_result.get("screenshot")):
        # The final action errored or was unmapped, so its result has no
        # screenshot. Capture the current screen so the pending ``computer_call``
        # ALWAYS gets a paired ``computer_call_output`` — an output the adapter
        # can't serialize (no image) would leave the call unanswered and stall
        # the loop. The error is still surfaced below via ``errors``.
        shot = await harness.aexecute("screenshot")
        merged = dict(last_result) if isinstance(last_result, dict) else {}
        if isinstance(shot, dict) and shot.get("screenshot"):
            merged["screenshot"] = shot["screenshot"]
            if isinstance(shot.get("observation"), dict):
                merged["observation"] = shot["observation"]
        last_result = merged
    if errors:
        last_result = {**last_result, "errors": errors}

    metrics = trajectory_metrics(
        trajectory_events,
        target_size=(
            getattr(harness, "_target_width", 1280),
            getattr(harness, "_target_height", 800),
        ),
        final_has_screenshot=bool(isinstance(last_result, dict) and last_result.get("screenshot")),
    )
    last_result = {
        **last_result,
        "trajectory": {
            "schema_version": 1,
            "events": trajectory_events,
            "metrics": metrics,
            "evaluation": evaluate_trajectory(
                trajectory_events,
                target_size=(
                    getattr(harness, "_target_width", 1280),
                    getattr(harness, "_target_height", 800),
                ),
                final_has_screenshot=bool(
                    isinstance(last_result, dict) and last_result.get("screenshot")
                ),
            ),
        },
    }
    if pending_safety:
        # Echo the safety checks the model attached to the originating call so
        # the adapter's ``computer_call_output`` can acknowledge them.
        last_result = {**last_result, "acknowledged_safety_checks": pending_safety}
    return last_result


# ---------------------------------------------------------------------------
# calendar — list / create / sync-scheduler
# ---------------------------------------------------------------------------


def _build_calendar_handlers() -> dict[str, Any]:
    """Build calendar tool handlers."""
    from core.tools.calendar_tools import (
        CalendarCreateEventTool,
        CalendarListEventsTool,
        CalendarSyncSchedulerTool,
    )

    list_tool = CalendarListEventsTool()
    create_tool = CalendarCreateEventTool()
    sync_tool = CalendarSyncSchedulerTool()

    async def handle_calendar_list_events(**kwargs: Any) -> dict[str, Any]:
        return await list_tool.aexecute(**kwargs)

    async def handle_calendar_create_event(**kwargs: Any) -> dict[str, Any]:
        return await create_tool.aexecute(**kwargs)

    async def handle_calendar_sync_scheduler(**kwargs: Any) -> dict[str, Any]:
        return await sync_tool.aexecute(**kwargs)

    return {
        "calendar_list_events": handle_calendar_list_events,
        "calendar_create_event": handle_calendar_create_event,
        "calendar_sync_scheduler": handle_calendar_sync_scheduler,
    }


# ---------------------------------------------------------------------------
# skills — use_skill (Progressive Disclosure Tier 2)
# ---------------------------------------------------------------------------


def _build_use_skill_handler(skill_registry: Any = None) -> dict[str, Any]:
    """Build the use_skill handler — load a skill's full instructions.

    The system prompt advertises skill metadata only (``<available_skills>``);
    this handler is the model-side path that loads a skill body on demand.
    When no registry is supplied (sub-agent workers build handlers outside the
    daemon wiring), fall back to a fresh ``SkillLoader`` scan with the same
    3-tier discovery the daemon uses.
    """

    def handle_use_skill(**kwargs: Any) -> dict[str, Any]:
        from core.skills.skills import SkillLoader, SkillRegistry
        from core.tools.base import tool_error

        name = str(kwargs.get("name", "")).strip()
        arguments = str(kwargs.get("arguments", "") or "")
        registry = skill_registry
        if registry is None:
            registry = SkillRegistry()
            SkillLoader().load_all(registry=registry)
        skill = registry.get(name) if name else None
        if skill is None:
            available = ", ".join(registry.list_all()) or "(none discovered)"
            return tool_error(
                f"Unknown skill: {name!r}.",
                error_type="not_found",
                recoverable=True,
                hint=f"Available skills: {available}",
            )
        instructions = skill.render(arguments=arguments)
        if not instructions:
            return tool_error(
                f"Skill {name!r} has an empty body.",
                error_type="dependency",
                recoverable=False,
                hint="The SKILL.md file has frontmatter but no instructions.",
            )
        return {"result": {"name": skill.name, "instructions": instructions}}

    return {"use_skill": handle_use_skill}
