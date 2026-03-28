"""Tool handler factory — builds tool name -> handler function mapping.

Extracted from ``core/cli/__init__.py`` for architectural clarity.
Each handler receives tool_input kwargs and returns a dict result.

Handlers are organized into logical groups:
- Analysis: analyze_ip, compare_ips, search_ips, list_ips, batch_analyze, generate_report
- Memory: memory_search, memory_save, manage_rule
- Plan: create_plan, approve_plan, reject_plan, modify_plan, list_plans
- HITL: rate_result, accept_result, reject_result, rerun_node
- System: check_status, show_help, switch_model, set_api_key, manage_auth
- Execution: generate_data, schedule_job, trigger_event
- Delegated: web_fetch, general_web_search, read_document, note_save, note_read,
             profile_show, profile_update, profile_preference, profile_learn,
             youtube_search, reddit_sentiment, steam_info, google_trends
- MCP: install_mcp_server
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from core.cli.ui.console import console
from core.config import settings

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared utilities (used by multiple handler groups)
# ---------------------------------------------------------------------------


def _clarify(
    tool: str,
    missing: list[str],
    hint: str,
    **extra: Any,
) -> dict[str, Any]:
    """Standard clarification response for missing required params."""
    return {
        "error": f"{tool} requires: {', '.join(missing)}",
        "clarification_needed": True,
        "missing": missing,
        "hint": hint,
        **extra,
    }


def _safe_delegate(tool_class: type, kwargs: dict[str, Any]) -> dict[str, Any]:
    """Wrap delegated tool execution -- catch KeyError as clarification."""
    try:
        result: dict[str, Any] = tool_class().execute(**kwargs)
        return result
    except (KeyError, TypeError) as exc:
        param = str(exc).strip("'\"")
        return _clarify(
            tool_class.__name__,
            [param],
            f"'{param}' 값을 알려주세요.",
        )


# ---------------------------------------------------------------------------
# Handler group: Analysis
# ---------------------------------------------------------------------------


def _build_analysis_handlers(
    verbose: bool,
    force_dry: bool,
    skill_registry: Any,
) -> dict[str, Any]:
    """Build analysis-related tool handlers."""
    from core.cli import (
        _generate_report,
        _get_search_engine,
        _render_search_results,
        _run_analysis,
    )

    def handle_list_ips(**_kwargs: Any) -> dict[str, Any]:
        from core.cli.commands import cmd_list
        from core.domains.game_ip.fixtures import FIXTURE_MAP as _FM

        cmd_list()
        names = [n.title() for n in _FM]
        return {"status": "ok", "action": "list", "count": len(names), "ips": names}

    def handle_analyze_ip(**kwargs: Any) -> dict[str, Any]:
        ip_name = kwargs.get("ip_name", "")
        if not ip_name:
            return _clarify("analyze_ip", ["ip_name"], "어떤 IP를 분석할까요?")
        dry_run = kwargs.get("dry_run", force_dry)
        result = _run_analysis(ip_name, dry_run=dry_run, verbose=verbose)
        # Pipeline cost/model notice for live runs (non-dry-run)
        pipeline_notice: str | None = None
        if not dry_run:
            pipeline_notice = (
                "이 분석은 claude-opus-4-6 (Primary) + gpt-5.4 (Cross-LLM)을 사용합니다. "
                "예상: ~8 LLM 호출, ~$0.15, ~15초."
            )
        if result is None:
            return {"error": f"Analysis failed for '{ip_name}'"}
        # Extract analyst summaries for LLM context
        analyses_summary = []
        for a in result.get("analyses", []):
            if hasattr(a, "model_dump"):
                a = a.model_dump()
            analyses_summary.append(
                {
                    "type": a.get("analyst_type", "?"),
                    "score": a.get("score", 0),
                    "finding": a.get("key_finding", ""),
                }
            )
        synthesis = result.get("synthesis")
        if synthesis is not None and hasattr(synthesis, "model_dump"):
            synthesis = synthesis.model_dump()
        out: dict[str, Any] = {
            "status": "ok",
            "action": "analyze",
            "ip_name": result.get("ip_name", ip_name),
            "tier": result.get("tier", "N/A"),
            "score": round(result.get("final_score", 0), 1),
            "cause": (
                (synthesis or {}).get("cause", "unknown")
                if isinstance(synthesis, dict)
                else "unknown"
            ),
            "analyses": analyses_summary,
        }
        if pipeline_notice:
            out["pipeline_notice"] = pipeline_notice
        return out

    def handle_search_ips(**kwargs: Any) -> dict[str, Any]:
        query = kwargs.get("query", "")
        if not query:
            return _clarify("search_ips", ["query"], "무엇을 검색할까요?")
        results = _get_search_engine().search(query)
        _render_search_results(query, results)
        return {
            "status": "ok",
            "action": "search",
            "query": query,
            "count": len(results),
            "results": [{"name": r.ip_name, "score": r.score} for r in results],
        }

    def handle_compare_ips(**kwargs: Any) -> dict[str, Any]:
        ip_a = kwargs.get("ip_a", "")
        ip_b = kwargs.get("ip_b", "")
        dry_run = kwargs.get("dry_run", force_dry)

        # Clarification: both IPs required
        if not ip_a or not ip_b:
            missing = [k for k, v in {"ip_a": ip_a, "ip_b": ip_b}.items() if not v]
            hint = "어떤 IP와 비교할까요?" if ip_a else "비교할 두 IP를 알려주세요."
            return _clarify("compare_ips", missing, hint, provided={"ip_a": ip_a, "ip_b": ip_b})

        console.print(f"\n  [header]Compare: {ip_a} vs {ip_b}[/header]\n")
        result_a = _run_analysis(ip_a, dry_run=dry_run, verbose=verbose)
        result_b = _run_analysis(ip_b, dry_run=dry_run, verbose=verbose)

        def _ip_summary(name: str, r: dict[str, Any] | None) -> dict[str, Any]:
            if not r:
                return {"name": name, "tier": "N/A", "score": 0}
            return {
                "name": name,
                "tier": r.get("tier", "N/A"),
                "score": round(r.get("final_score", 0), 1),
            }

        return {
            "status": "ok",
            "action": "compare",
            "ip_a": _ip_summary(ip_a, result_a),
            "ip_b": _ip_summary(ip_b, result_b),
        }

    def handle_generate_report(**kwargs: Any) -> dict[str, Any]:
        ip_name = kwargs.get("ip_name", "")
        if not ip_name:
            return _clarify("generate_report", ["ip_name"], "어떤 IP의 리포트를 생성할까요?")
        fmt = kwargs.get("format", "markdown")
        if fmt == "md":
            fmt = "markdown"
        template = kwargs.get("template", "summary")
        dry_run = kwargs.get("dry_run", force_dry)
        report_result = _generate_report(
            ip_name,
            dry_run=dry_run,
            verbose=verbose,
            fmt=fmt,
            template=template,
            skill_registry=skill_registry,
        )
        if report_result is None:
            return {"error": f"Report generation failed for '{ip_name}'"}
        file_path, content = report_result
        return {
            "status": "ok",
            "action": "report",
            "ip_name": ip_name,
            "format": fmt,
            "template": template,
            "file_path": file_path,
            "content_preview": content[:500] if len(content) > 500 else content,
            "content_length": len(content),
        }

    def handle_batch_analyze(**kwargs: Any) -> dict[str, Any]:
        from core.cli.batch import render_batch_table, run_batch

        top = kwargs.get("top", 20)
        genre = kwargs.get("genre")
        dry_run = kwargs.get("dry_run", force_dry)
        batch_results = run_batch(top=top, genre=genre, dry_run=dry_run)
        render_batch_table(batch_results)
        summary = []
        for br in batch_results:
            if br:
                summary.append(
                    {
                        "ip_name": br.get("ip_name", "?"),
                        "tier": br.get("tier", "?"),
                        "score": round(br.get("final_score", 0), 1),
                    }
                )
        return {
            "status": "ok",
            "action": "batch",
            "count": len(batch_results),
            "results": summary[:20],
        }

    return {
        "list_ips": handle_list_ips,
        "analyze_ip": handle_analyze_ip,
        "search_ips": handle_search_ips,
        "compare_ips": handle_compare_ips,
        "generate_report": handle_generate_report,
        "batch_analyze": handle_batch_analyze,
    }


# ---------------------------------------------------------------------------
# Handler group: Memory
# ---------------------------------------------------------------------------


def _build_memory_handlers() -> dict[str, Any]:
    """Build memory-related tool handlers."""
    from core.cli import _handle_memory_action
    from core.memory.project import ProjectMemory

    def handle_memory_search(**kwargs: Any) -> dict[str, Any]:
        query = kwargs.get("query", "")
        if not query:
            return _clarify("memory_search", ["query"], "무엇을 검색할까요?")
        try:
            mem = ProjectMemory()
            content = mem.search(query) if hasattr(mem, "search") else mem.load_memory()
            return {"status": "ok", "action": "memory_search", "content": content[:2000]}
        except Exception as exc:
            return {"error": str(exc)}

    def handle_memory_save(**kwargs: Any) -> dict[str, Any]:
        key = kwargs.get("key", "")
        content = kwargs.get("content", "")
        if not key or not content:
            missing = [k for k, v in {"key": key, "content": content}.items() if not v]
            return _clarify("memory_save", missing, "저장할 키와 내용을 알려주세요.")
        try:
            mem = ProjectMemory()
            mem.add_insight(f"{key}: {content}")
            console.print(f"  [success]Saved to memory: {key}[/success]")
            return {"status": "ok", "action": "memory_save", "key": key}
        except Exception as exc:
            return {"error": str(exc)}

    def handle_manage_rule(**kwargs: Any) -> dict[str, Any]:
        rule_action = kwargs.get("action", "list")
        name = kwargs.get("name", "")
        if rule_action in ("add", "delete") and not name:
            return _clarify("manage_rule", ["name"], "규칙 이름을 알려주세요.")
        memory_args = {
            "rule_action": rule_action,
            "name": name,
            "paths": kwargs.get("paths", []),
            "content": kwargs.get("content", ""),
        }
        _handle_memory_action(memory_args, "", False)
        # Return rule list for LLM context
        try:
            mem = ProjectMemory()
            rules = mem.list_rules() if hasattr(mem, "list_rules") else []
            return {
                "status": "ok",
                "action": "manage_rule",
                "sub_action": rule_action,
                "name": name,
                "rules": [str(r) for r in rules][:20],
            }
        except Exception:
            return {"status": "ok", "action": "manage_rule", "sub_action": rule_action}

    return {
        "memory_search": handle_memory_search,
        "memory_save": handle_memory_save,
        "manage_rule": handle_manage_rule,
    }


# ---------------------------------------------------------------------------
# Handler group: Plan mode
# ---------------------------------------------------------------------------


def _build_plan_handlers(force_dry: bool) -> dict[str, Any]:
    """Build plan mode tool handlers (multi-plan cache keyed by plan_id)."""

    _plan_cache: dict[str, tuple[Any, Any]] = {}

    def _resolve_plan(
        plan_id: str,
    ) -> tuple[Any, Any] | None:
        """Resolve plan from cache by ID, falling back to most recent."""
        cached = _plan_cache.get(plan_id)
        if not cached and _plan_cache:
            last_key = list(_plan_cache.keys())[-1]
            cached = _plan_cache.get(last_key)
            if cached:
                log.debug(
                    "Plan ID '%s' not found, using latest '%s'",
                    plan_id,
                    last_key,
                )
        return cached

    def handle_create_plan(**kwargs: Any) -> dict[str, Any]:
        from core.config import settings
        from core.orchestration.plan_mode import PlanExecutionMode, PlanMode

        goal = kwargs.get("goal", "")
        ip_name = kwargs.get("ip_name", "")
        custom_steps = kwargs.get("steps", [])
        plan_summary: dict[str, Any] = {}

        # IP 분석: 기존 파이프라인 템플릿 사용
        if ip_name:
            template = kwargs.get("template", "full_pipeline")
            planner = PlanMode()
            plan = planner.create_plan(ip_name, template=template)
            plan_summary = planner.present_plan(plan)
            plan_title = ip_name
        elif goal:
            # 범용 계획: LLM이 제공한 steps 또는 goal 기반 자동 생성
            import uuid

            from core.orchestration.plan_mode import AnalysisPlan, PlanStep

            plan_id = f"plan_{uuid.uuid4().hex[:8]}"
            if custom_steps:
                steps = [
                    PlanStep(
                        step_id=f"step_{i}",
                        description=desc,
                        node_name="agentic",
                        estimated_time_s=10.0,
                    )
                    for i, desc in enumerate(custom_steps, 1)
                ]
            else:
                steps = [
                    PlanStep(
                        step_id="step_1",
                        description=goal,
                        node_name="agentic",
                        estimated_time_s=30.0,
                    )
                ]
            plan = AnalysisPlan(plan_id=plan_id, ip_name=goal, steps=steps)
            planner = PlanMode()
            plan_summary = {"goal": goal, "steps": len(steps)}
            plan_title = goal
        else:
            return _clarify("create_plan", ["goal"], "어떤 작업의 계획을 세울까요?")

        # Display plan steps with HITL approval prompt
        console.print()
        console.print(f"  [header]● Plan: {plan_title}[/header]")
        console.print()
        for i, step in enumerate(plan.steps, 1):
            console.print(f"    [bold]{i}.[/bold] {step.description}")
        console.print()
        console.print(
            f"  [muted]예상: {plan.total_estimated_time_s:.0f}s · "
            f"{plan.step_count} 단계 · plan_id={plan.plan_id}[/muted]"
        )
        if not settings.plan_auto_execute:
            console.print(
                "  [dim]→ 승인(approve_plan) · 수정(modify_plan) · 거부(reject_plan)[/dim]"
            )
        console.print()
        log.info(
            "Plan '%s' created for '%s' (%d steps)",
            plan.plan_id,
            ip_name,
            plan.step_count,
        )

        # AUTO mode: approve and execute immediately without user intervention
        if settings.plan_auto_execute:
            console.print(f"  [bold cyan]▸ Auto-executing plan {plan.plan_id}[/bold cyan]")
            exec_result = planner.auto_execute_plan(plan)

            completed = exec_result.get("completed_steps", 0)
            total = exec_result.get("total_steps", 0)
            failed = exec_result.get("failed_steps", [])

            if failed:
                console.print(
                    f"  [warning]Partial success: {completed}/{total} steps "
                    f"(failed: {', '.join(failed)})[/warning]"
                )
            else:
                console.print(f"  [success]✓ All {total} steps completed[/success]")
            console.print()

            return {
                "status": "ok",
                "action": "plan",
                "plan_id": plan.plan_id,
                "ip_name": ip_name,
                "template": template,
                "step_count": plan.step_count,
                "steps": [s.description for s in plan.steps],
                "summary": plan_summary,
                "execution_mode": PlanExecutionMode.AUTO.value,
                "auto_executed": True,
                "execution_result": exec_result,
                "hint": (
                    f"Plan auto-executed. Call analyze_ip with "
                    f"ip_name='{ip_name}' to run the full analysis."
                ),
            }

        # MANUAL mode: cache plan and wait for user approval
        _plan_cache[plan.plan_id] = (planner, plan)
        return {
            "status": "ok",
            "action": "plan",
            "plan_id": plan.plan_id,
            "ip_name": ip_name,
            "template": template,
            "step_count": plan.step_count,
            "steps": [s.description for s in plan.steps],
            "summary": plan_summary,
            "execution_mode": PlanExecutionMode.MANUAL.value,
            "hint": ("Use approve_plan, reject_plan, or modify_plan to proceed."),
        }

    def handle_approve_plan(**kwargs: Any) -> dict[str, Any]:
        plan_id = kwargs.get("plan_id", "")
        cached = _resolve_plan(plan_id)
        if not cached:
            return {"error": "No plan to approve. Use create_plan first."}

        planner, plan = cached
        if plan_id and plan.plan_id != plan_id:
            return {"error": (f"Plan ID mismatch: expected {plan.plan_id}, got {plan_id}")}

        planner.approve_plan(plan)
        result = planner.execute_plan(plan)
        _plan_cache.pop(plan.plan_id, None)

        ip = plan.ip_name
        console.print(f"  [success]✓ Plan approved: {ip}[/success]")
        console.print()
        log.info("Plan '%s' approved for '%s'", plan.plan_id, ip)
        return {
            "status": "ok",
            "action": "approve_plan",
            "plan_id": plan.plan_id,
            "executed": True,
            "result": str(result)[:500],
            "hint": (f"Plan approved. Call analyze_ip with ip_name='{ip}' to run the analysis."),
        }

    def handle_reject_plan(**kwargs: Any) -> dict[str, Any]:
        plan_id = kwargs.get("plan_id", "")
        reason = kwargs.get("reason", "")
        cached = _resolve_plan(plan_id)
        if not cached:
            return {"error": "No plan to reject."}

        planner, plan = cached
        planner.reject_plan(plan, reason=reason)
        _plan_cache.pop(plan.plan_id, None)
        console.print(f"  [warning]✗ Plan rejected: {plan.ip_name}[/warning]")
        log.info(
            "Plan '%s' rejected (reason=%s)",
            plan.plan_id,
            reason or "(none)",
        )
        return {
            "status": "ok",
            "action": "reject_plan",
            "plan_id": plan.plan_id,
            "reason": reason,
        }

    def handle_modify_plan(**kwargs: Any) -> dict[str, Any]:
        plan_id = kwargs.get("plan_id", "")
        cached = _resolve_plan(plan_id)
        if not cached:
            return {"error": "No plan to modify."}

        planner, plan = cached
        template = kwargs.get("template")
        remove = kwargs.get("remove_steps")
        planner.modify_plan(
            plan,
            template=template,
            remove_steps=remove,
        )
        _plan_cache[plan.plan_id] = (planner, plan)
        console.print(f"  [header]● Plan modified: {plan.ip_name}[/header]")
        for i, step in enumerate(plan.steps, 1):
            console.print(f"    {i}. {step.description}")
        console.print()
        log.info(
            "Plan '%s' modified (%d steps)",
            plan.plan_id,
            plan.step_count,
        )
        return {
            "status": "ok",
            "action": "modify_plan",
            "plan_id": plan.plan_id,
            "step_count": plan.step_count,
            "steps": [s.description for s in plan.steps],
        }

    def handle_list_plans(**kwargs: Any) -> dict[str, Any]:
        plans = []
        for pid, (_, plan) in _plan_cache.items():
            plans.append(
                {
                    "plan_id": pid,
                    "ip_name": plan.ip_name,
                    "status": plan.status.value,
                    "steps": plan.step_count,
                }
            )
        return {
            "status": "ok",
            "action": "list_plans",
            "count": len(plans),
            "plans": plans,
        }

    return {
        "create_plan": handle_create_plan,
        "approve_plan": handle_approve_plan,
        "reject_plan": handle_reject_plan,
        "modify_plan": handle_modify_plan,
        "list_plans": handle_list_plans,
    }


# ---------------------------------------------------------------------------
# Handler group: HITL (Human-in-the-Loop)
# ---------------------------------------------------------------------------


def _build_hitl_handlers() -> dict[str, Any]:
    """Build HITL feedback tool handlers."""

    _human_ratings: dict[str, dict[str, Any]] = {}
    _result_feedback: dict[str, str] = {}

    def handle_rate_result(**kwargs: Any) -> dict[str, Any]:
        ip_name = kwargs.get("ip_name", "")
        rating = kwargs.get("rating", 0)
        if not ip_name:
            return _clarify("rate_result", ["ip_name"], "어떤 IP에 평점을 매길까요?")
        if not (1 <= rating <= 5):
            return _clarify("rate_result", ["rating"], "평점은 1-5 사이로 입력해주세요.")
        comment = kwargs.get("comment", "")
        _human_ratings[ip_name] = {
            "rating": rating,
            "comment": comment,
        }
        console.print(f"  [success]✓ Rating saved for {ip_name}: {rating}/5[/success]")
        log.info(
            "HITL rating: %s = %d/5",
            ip_name,
            rating,
        )
        return {
            "status": "ok",
            "action": "rate_result",
            "ip_name": ip_name,
            "rating": rating,
        }

    def handle_accept_result(**kwargs: Any) -> dict[str, Any]:
        ip_name = kwargs.get("ip_name", "")
        if not ip_name:
            return _clarify("accept_result", ["ip_name"], "어떤 IP 결과를 수락할까요?")
        _result_feedback[ip_name] = "accepted"
        console.print(f"  [success]✓ Result accepted: {ip_name}[/success]")
        log.info("HITL accept: %s", ip_name)
        return {
            "status": "ok",
            "action": "accept_result",
            "ip_name": ip_name,
        }

    def handle_reject_result(**kwargs: Any) -> dict[str, Any]:
        ip_name = kwargs.get("ip_name", "")
        if not ip_name:
            return _clarify("reject_result", ["ip_name"], "어떤 IP 결과를 거부할까요?")
        reason = kwargs.get("reason", "")
        _result_feedback[ip_name] = "rejected"
        console.print(f"  [warning]✗ Result rejected: {ip_name}[/warning]")
        log.info(
            "HITL reject: %s (reason=%s)",
            ip_name,
            reason or "(none)",
        )
        return {
            "status": "ok",
            "action": "reject_result",
            "ip_name": ip_name,
            "reason": reason,
            "hint": ("Use rerun_node to re-execute specific pipeline steps."),
        }

    def handle_rerun_node(**kwargs: Any) -> dict[str, Any]:
        node_name = kwargs.get("node_name", "")
        ip_name = kwargs.get("ip_name", "")
        if not node_name or not ip_name:
            missing = [k for k, v in {"node_name": node_name, "ip_name": ip_name}.items() if not v]
            return _clarify("rerun_node", missing, "재실행할 노드와 IP를 알려주세요.")
        allowed = {"scoring", "verification", "synthesizer"}
        if node_name not in allowed:
            return {
                "error": (f"Cannot rerun '{node_name}'. Allowed: {sorted(allowed)}"),
            }
        console.print(f"  [header]▸ Rerunning {node_name} for {ip_name}[/header]")
        log.info(
            "HITL rerun: %s for %s",
            node_name,
            ip_name,
        )
        return {
            "status": "ok",
            "action": "rerun_node",
            "node_name": node_name,
            "ip_name": ip_name,
            "hint": ("Node re-execution queued. Results will update in-place."),
        }

    return {
        "rate_result": handle_rate_result,
        "accept_result": handle_accept_result,
        "reject_result": handle_reject_result,
        "rerun_node": handle_rerun_node,
    }


# ---------------------------------------------------------------------------
# Handler group: System
# ---------------------------------------------------------------------------


def _build_system_handlers(
    readiness: Any,
    force_dry: bool,
    mcp_manager: Any,
) -> dict[str, Any]:
    """Build system management tool handlers."""
    from core.cli import _set_readiness
    from core.cli.commands import cmd_auth, cmd_key, cmd_model, show_help
    from core.cli.startup import check_readiness, render_readiness

    def handle_show_help(**_kwargs: Any) -> dict[str, Any]:
        show_help()
        commands = [
            "/analyze <IP> -- Analyze an IP (dry-run)",
            "/run <IP> -- Analyze with real LLM",
            "/search <query> -- Search IPs by keyword",
            "/list -- Show available IPs",
            "/compare <A> <B> -- Compare two IPs",
            "/report <IP> -- Generate analysis report",
            "/batch -- Batch analyze multiple IPs",
            "/status -- Show system status",
            "/model -- Switch LLM model",
            "/help -- Show help",
        ]
        return {"status": "ok", "action": "help", "commands": commands}

    def handle_check_status(**_kwargs: Any) -> dict[str, Any]:
        from core.domains.game_ip.fixtures import FIXTURE_MAP as _FM

        ant_ok = bool(settings.anthropic_api_key)
        oai_ok = bool(settings.openai_api_key)
        mode = "full_llm" if (readiness and not readiness.force_dry_run) else "dry_run"

        console.print()
        console.print("  [header]GEODE System Status[/header]")
        console.print(f"  Model: [bold]{settings.model}[/bold]")
        console.print(f"  Ensemble: [bold]{settings.ensemble_mode}[/bold]")
        ant_status = "[green]configured[/green]" if ant_ok else "[red]not set[/red]"
        oai_status = "[green]configured[/green]" if oai_ok else "[red]not set[/red]"
        console.print(f"  Anthropic API: {ant_status}")
        console.print(f"  OpenAI API: {oai_status}")
        console.print(f"  Mode: [bold]{mode}[/bold]")
        console.print(f"  Fixtures: [bold]{len(_FM)} IPs[/bold]")

        # MCP status
        mcp_status = (
            mcp_manager.get_status()
            if mcp_manager is not None
            else {"active": [], "active_count": 0, "available_inactive": [], "catalog_total": 0}
        )

        console.print()
        console.print("  [header]MCP Servers[/header]")
        active = mcp_status["active"]
        if active:
            for srv in active:
                desc = f" -- {srv['description']}" if srv["description"] else ""
                console.print(f"    [green]OK[/green] {srv['name']} [dim]{desc}[/dim]")
        else:
            console.print("    [muted]No active servers[/muted]")

        inactive = mcp_status["available_inactive"]
        if inactive:
            console.print()
            console.print("  [header]MCP Available (env missing)[/header]")
            for srv in inactive:
                env_list = ", ".join(srv["missing_env"])
                console.print(f"    [yellow]--[/yellow] {srv['name']} [dim]needs: {env_list}[/dim]")
        console.print()

        return {
            "status": "ok",
            "action": "status",
            "model": settings.model,
            "ensemble": settings.ensemble_mode,
            "anthropic_configured": ant_ok,
            "openai_configured": oai_ok,
            "mode": mode,
            "fixture_count": len(_FM),
            "mcp_status": mcp_status,
        }

    def handle_switch_model(**kwargs: Any) -> dict[str, Any]:
        model_hint = kwargs.get("model_hint", "")
        cmd_model(model_hint)
        return {
            "status": "ok",
            "action": "model",
            "current_model": settings.model,
            "ensemble": settings.ensemble_mode,
        }

    def handle_set_api_key(**kwargs: Any) -> dict[str, Any]:
        key_value = kwargs.get("key_value", "")
        changed = cmd_key(key_value)
        if changed:
            new_readiness = check_readiness()
            _set_readiness(new_readiness)
            render_readiness(new_readiness)
        return {
            "status": "ok",
            "action": "key",
            "changed": changed,
            "anthropic_configured": bool(settings.anthropic_api_key),
            "openai_configured": bool(settings.openai_api_key),
        }

    def handle_manage_auth(**kwargs: Any) -> dict[str, Any]:
        sub_action = kwargs.get("sub_action", "")
        cmd_auth(sub_action)
        try:
            from core.cli.commands import _get_profile_store

            store = _get_profile_store()
            profiles = [
                {"name": p.name, "provider": p.provider, "type": p.credential_type.value}
                for p in store.list_all()
            ]
        except Exception:
            profiles = []
        return {
            "status": "ok",
            "action": "auth",
            "sub_action": sub_action,
            "profiles": profiles,
        }

    return {
        "show_help": handle_show_help,
        "check_status": handle_check_status,
        "switch_model": handle_switch_model,
        "set_api_key": handle_set_api_key,
        "manage_auth": handle_manage_auth,
    }


# ---------------------------------------------------------------------------
# Handler group: Execution (schedule, trigger, generate)
# ---------------------------------------------------------------------------


def _build_execution_handlers() -> dict[str, Any]:
    """Build execution-related tool handlers."""
    from core.cli import _scheduler_service_ctx
    from core.cli.commands import cmd_generate, cmd_schedule, cmd_trigger

    def handle_generate_data(**kwargs: Any) -> dict[str, Any]:
        count = kwargs.get("count", 5)
        genre = kwargs.get("genre", "")
        gen_args = str(count)
        if genre:
            gen_args += f" {genre}"
        cmd_generate(gen_args)
        return {
            "status": "ok",
            "action": "generate",
            "count": count,
            "genre": genre or "random",
        }

    def handle_schedule_job(**kwargs: Any) -> dict[str, Any]:
        sub_action = kwargs.get("sub_action", "") or "list"
        target_id = kwargs.get("target_id", "")
        expression = kwargs.get("expression", "")
        svc = _scheduler_service_ctx.get(None)

        if sub_action == "create" and expression:
            cmd_schedule(f"create {expression}", scheduler_service=svc)
            try:
                from core.automation.nl_scheduler import NLScheduleParser

                result = NLScheduleParser().parse(expression)
                if result.success and result.job:
                    return {
                        "status": "ok",
                        "action": "schedule",
                        "sub_action": "create",
                        "job_id": result.job.job_id,
                        "schedule_kind": (
                            result.inferred_kind.value if result.inferred_kind else ""
                        ),
                        "expression": expression,
                    }
                return {
                    "status": "error",
                    "action": "schedule",
                    "sub_action": "create",
                    "error": result.error or "parse failed",
                }
            except Exception as exc:
                return {
                    "status": "error",
                    "action": "schedule",
                    "sub_action": "create",
                    "error": str(exc),
                }

        sched_args = f"{sub_action} {target_id}".strip() if sub_action else ""
        cmd_schedule(sched_args, scheduler_service=svc)
        try:
            from core.automation.predefined import PREDEFINED_AUTOMATIONS

            templates = [
                {"id": t.id, "name": t.name, "enabled": t.enabled} for t in PREDEFINED_AUTOMATIONS
            ]
        except Exception:
            templates = []
        result_dict: dict[str, Any] = {
            "status": "ok",
            "action": "schedule",
            "sub_action": sub_action,
            "templates": templates[:10],
        }
        if svc is not None:
            try:
                dynamic = [
                    {"id": j.job_id, "name": j.name, "enabled": j.enabled}
                    for j in svc.list_jobs(include_disabled=True)
                    if not j.job_id.startswith("predefined:")
                ]
                result_dict["dynamic_jobs"] = dynamic
            except Exception:
                log.debug("Failed to list dynamic jobs", exc_info=True)
        return result_dict

    def handle_trigger_event(**kwargs: Any) -> dict[str, Any]:
        sub_action = kwargs.get("sub_action", "") or "list"
        event_name = kwargs.get("event_name", "")
        trigger_args = f"{sub_action} {event_name}".strip() if sub_action else ""
        cmd_trigger(trigger_args)
        return {
            "status": "ok",
            "action": "trigger",
            "sub_action": sub_action,
            "event_name": event_name,
        }

    return {
        "generate_data": handle_generate_data,
        "schedule_job": handle_schedule_job,
        "trigger_event": handle_trigger_event,
    }


# ---------------------------------------------------------------------------
# Handler group: Delegated tools (registry-based)
# ---------------------------------------------------------------------------

# Maps tool name → (module_path, class_name) for lazy-import delegation.
# Adding a new delegated tool requires only one line here.
_DELEGATED_TOOLS: dict[str, tuple[str, str]] = {
    # web / document / note
    "web_fetch": ("core.tools.web_tools", "WebFetchTool"),
    "general_web_search": ("core.tools.web_tools", "GeneralWebSearchTool"),
    "read_document": ("core.tools.document_tools", "ReadDocumentTool"),
    "note_save": ("core.tools.memory_tools", "NoteSaveTool"),
    "note_read": ("core.tools.memory_tools", "NoteReadTool"),
    # profile
    "profile_show": ("core.tools.profile_tools", "ProfileShowTool"),
    "profile_update": ("core.tools.profile_tools", "ProfileUpdateTool"),
    "profile_preference": ("core.tools.profile_tools", "ProfilePreferenceTool"),
    "profile_learn": ("core.tools.profile_tools", "ProfileLearnTool"),
    # signals
    "youtube_search": ("core.tools.signal_tools", "YouTubeSearchTool"),
    "reddit_sentiment": ("core.tools.signal_tools", "RedditSentimentTool"),
    "steam_info": ("core.tools.signal_tools", "SteamInfoTool"),
    "google_trends": ("core.tools.signal_tools", "GoogleTrendsTool"),
}


def _make_delegate_handler(
    module_path: str,
    class_name: str,
) -> Callable[..., dict[str, Any]]:
    """Return a handler that lazily imports *class_name* from *module_path* and delegates."""

    def _handler(**kwargs: Any) -> dict[str, Any]:
        import importlib

        mod = importlib.import_module(module_path)
        tool_cls = getattr(mod, class_name)
        return _safe_delegate(tool_cls, kwargs)

    return _handler


def _build_delegated_handlers() -> dict[str, Any]:
    """Build all delegated tool handlers from ``_DELEGATED_TOOLS`` registry."""
    return {name: _make_delegate_handler(mod, cls) for name, (mod, cls) in _DELEGATED_TOOLS.items()}


# ---------------------------------------------------------------------------
# Handler group: MCP auto-install
# ---------------------------------------------------------------------------


def _build_mcp_handler(
    mcp_manager: Any,
    agentic_ref: list[Any] | None,
) -> dict[str, Any]:
    """Build MCP server installation handler."""

    def handle_install_mcp_server(**kwargs: Any) -> dict[str, Any]:
        import os as _os

        from core.mcp.catalog import search_catalog

        query = kwargs.get("query", "")
        matches = search_catalog(query)
        if not matches:
            return {
                "status": "not_found",
                "message": f"'{query}'에 맞는 MCP 서버를 찾지 못했습니다.",
            }

        best = matches[0]

        # Already installed?
        if mcp_manager is not None:
            existing = {s["name"] for s in mcp_manager.list_servers()}
            if best.name in existing:
                return {
                    "status": "already_installed",
                    "server": best.name,
                    "message": f"{best.name}은 이미 설치되어 있습니다.",
                }

        if mcp_manager is None:
            return {"status": "error", "message": "MCP manager not available"}

        # Derive command + args from install_hint
        if not best.install_hint:
            return {"status": "error", "message": f"No install configuration for {best.name}"}
        hint_parts = best.install_hint.split()
        cmd = hint_parts[0]
        args = hint_parts[1:]
        env_map = {k: f"${{{k}}}" for k in best.env_keys} or None
        ok = mcp_manager.add_server(best.name, cmd, args=args, env=env_map)
        if not ok:
            return {"status": "error", "message": f"Failed to save {best.name}"}

        # Hot-reload tools into running AgenticLoop
        added = 0
        if agentic_ref and agentic_ref[0] is not None:
            added = agentic_ref[0].refresh_tools()

        # Check for missing env vars
        missing = [k for k in best.env_keys if not _os.environ.get(k)]

        msg = f"{best.name} 설치 완료. {added}개 도구 추가됨."
        if missing:
            msg += f" 환경변수 필요: {', '.join(missing)}"

        return {
            "status": "installed",
            "server": best.name,
            "install_hint": best.install_hint,
            "tools_added": added,
            "env_required": list(best.env_keys),
            "env_missing": missing,
            "message": msg,
        }

    return {
        "install_mcp_server": handle_install_mcp_server,
    }


# ---------------------------------------------------------------------------
# Context management handlers
# ---------------------------------------------------------------------------


def _build_context_handlers() -> dict[str, Any]:
    """Build context management tool handlers (manage_context)."""

    def handle_manage_context(**kwargs: Any) -> dict[str, Any]:
        action = kwargs.get("action", "status")
        force = kwargs.get("force", False)

        from core.cli.commands import get_conversation_context
        from core.config import settings
        from core.orchestration.context_monitor import check_context

        ctx = get_conversation_context()
        if ctx is None:
            return {"error": "No active conversation context"}

        if action == "status":
            if not ctx.messages:
                return {
                    "status": "ok",
                    "action": "status",
                    "messages": 0,
                    "estimated_tokens": 0,
                }
            metrics = check_context(ctx.messages, settings.model)
            return {
                "status": "ok",
                "action": "status",
                "messages": len(ctx.messages),
                "estimated_tokens": metrics.estimated_tokens,
                "context_window": metrics.context_window,
                "usage_pct": round(metrics.usage_pct, 1),
                "model": settings.model,
            }
        elif action == "compact":
            from core.cli.commands import cmd_compact

            cmd_compact("--hard" if force else "")
            if ctx.messages:
                metrics = check_context(ctx.messages, settings.model)
                return {
                    "status": "ok",
                    "action": "compacted",
                    "messages_after": len(ctx.messages),
                    "estimated_tokens": metrics.estimated_tokens,
                    "usage_pct": round(metrics.usage_pct, 1),
                }
            return {
                "status": "ok",
                "action": "compacted",
                "messages_after": 0,
                "estimated_tokens": 0,
                "usage_pct": 0.0,
            }
        elif action == "clear":
            if not force:
                return {
                    "status": "confirmation_needed",
                    "action": "clear",
                    "summary": (
                        f"대화 기록 {len(ctx.messages)}개 "
                        "메시지를 삭제합니다. "
                        "force=true로 확인하세요."
                    ),
                    "messages_count": len(ctx.messages),
                }
            ctx.clear()
            return {"status": "ok", "action": "cleared"}

        return {"error": f"Unknown action: {action}"}

    return {"manage_context": handle_manage_context}


# ---------------------------------------------------------------------------
# Public API: dispatcher
# ---------------------------------------------------------------------------


def _build_tool_handlers(
    verbose: bool = False,
    *,
    mcp_manager: Any = None,
    agentic_ref: list[Any] | None = None,
    skill_registry: Any = None,
) -> dict[str, Any]:
    """Build tool name -> handler function mapping for ToolExecutor.

    Each handler receives tool_input kwargs and returns a dict result.
    ``mcp_manager`` and ``agentic_ref`` are used by install_mcp_server.
    ``skill_registry`` is used by generate_report for skill-enhanced narrative.

    Delegates to group-specific builder functions and merges the results.
    """
    from core.cli import _get_readiness

    readiness = _get_readiness()
    force_dry = readiness.force_dry_run if readiness else True

    handlers: dict[str, Any] = {}
    handlers.update(_build_analysis_handlers(verbose, force_dry, skill_registry))
    handlers.update(_build_memory_handlers())
    handlers.update(_build_plan_handlers(force_dry))
    handlers.update(_build_hitl_handlers())
    handlers.update(_build_system_handlers(readiness, force_dry, mcp_manager))
    handlers.update(_build_execution_handlers())
    handlers.update(_build_delegated_handlers())
    handlers.update(_build_notification_handlers())
    handlers.update(_build_calendar_handlers())
    handlers.update(_build_mcp_handler(mcp_manager, agentic_ref))
    handlers.update(_build_context_handlers())
    handlers.update(_build_task_handlers())
    return handlers


# ---------------------------------------------------------------------------
# Task handlers
# ---------------------------------------------------------------------------


def _build_task_handlers() -> dict[str, Any]:
    """Build user-facing task management handlers (task_create/update/get/list/stop)."""
    import uuid

    from core.cli.session_state import _get_user_task_graph
    from core.orchestration.task_system import Task, TaskStatus

    def _status_to_internal(status: str) -> TaskStatus:
        return {
            "pending": TaskStatus.PENDING,
            "in_progress": TaskStatus.RUNNING,
            "completed": TaskStatus.COMPLETED,
            "failed": TaskStatus.FAILED,
        }.get(status, TaskStatus.PENDING)

    def _status_to_external(status: TaskStatus) -> str:
        return {
            TaskStatus.PENDING: "pending",
            TaskStatus.READY: "pending",
            TaskStatus.RUNNING: "in_progress",
            TaskStatus.COMPLETED: "completed",
            TaskStatus.FAILED: "failed",
            TaskStatus.SKIPPED: "failed",
        }.get(status, "pending")

    def _task_to_dict(task: Task, detail: bool = False) -> dict[str, Any]:
        out: dict[str, Any] = {
            "task_id": task.task_id,
            "subject": task.name,
            "task_status": _status_to_external(task.status),
            "owner": task.metadata.get("owner", ""),
        }
        if detail:
            out["description"] = task.metadata.get("description", "")
            out["elapsed_s"] = task.elapsed_s
            out["metadata"] = {
                k: v for k, v in task.metadata.items() if k not in ("owner", "description")
            }
            if task.error:
                out["error"] = task.error
        return out

    def handle_task_create(**kwargs: Any) -> dict[str, Any]:
        subject = kwargs.get("subject", "")
        if not subject:
            return _clarify("task_create", ["subject"], "작업 제목을 알려주세요.")
        graph = _get_user_task_graph()
        task_id = f"t_{uuid.uuid4().hex[:8]}"
        metadata: dict[str, Any] = dict(kwargs.get("metadata") or {})
        if desc := kwargs.get("description"):
            metadata["description"] = desc
        task = Task(task_id=task_id, name=subject, metadata=metadata)
        graph.add_task(task)
        return {"status": "ok", "action": "created", "task_id": task_id, "subject": subject}

    def handle_task_update(**kwargs: Any) -> dict[str, Any]:
        task_id = kwargs.get("task_id", "")
        if not task_id:
            return _clarify("task_update", ["task_id"], "변경할 task_id를 알려주세요.")
        graph = _get_user_task_graph()
        task = graph.get_task(task_id)
        if task is None:
            return {"error": f"Task '{task_id}' not found"}
        if new_subject := kwargs.get("subject"):
            task.name = new_subject
        if owner := kwargs.get("owner"):
            task.metadata["owner"] = owner
        if desc := kwargs.get("description"):
            task.metadata["description"] = desc
        if extra_meta := kwargs.get("metadata"):
            for k, v in extra_meta.items():
                if v is None:
                    task.metadata.pop(k, None)
                else:
                    task.metadata[k] = v
        if new_status := kwargs.get("status"):
            try:
                if new_status == "in_progress":
                    graph.mark_running(task_id)
                elif new_status == "completed":
                    graph.mark_completed(task_id)
                elif new_status == "failed":
                    graph.mark_failed(task_id, error="manually failed")
            except ValueError as exc:
                return {"error": str(exc)}
        return {"status": "ok", "action": "updated", **_task_to_dict(task)}

    def handle_task_get(**kwargs: Any) -> dict[str, Any]:
        task_id = kwargs.get("task_id", "")
        if not task_id:
            return _clarify("task_get", ["task_id"], "조회할 task_id를 알려주세요.")
        graph = _get_user_task_graph()
        task = graph.get_task(task_id)
        if task is None:
            return {"error": f"Task '{task_id}' not found"}
        return {"status": "ok", **_task_to_dict(task, detail=True)}

    def handle_task_list(**kwargs: Any) -> dict[str, Any]:
        graph = _get_user_task_graph()
        status_filter = kwargs.get("status_filter", "all")
        tasks = list(graph._tasks.values())
        if status_filter != "all":
            target = _status_to_internal(status_filter)
            # pending filter includes READY
            if status_filter == "pending":
                tasks = [t for t in tasks if t.status in (TaskStatus.PENDING, TaskStatus.READY)]
            else:
                tasks = [t for t in tasks if t.status == target]
        # Sort: in_progress first, then pending, then completed/failed
        order = {"in_progress": 0, "pending": 1, "completed": 2, "failed": 3}
        tasks.sort(key=lambda t: order.get(_status_to_external(t.status), 9))
        return {
            "status": "ok",
            "count": len(tasks),
            "tasks": [_task_to_dict(t) for t in tasks],
        }

    def handle_task_stop(**kwargs: Any) -> dict[str, Any]:
        task_id = kwargs.get("task_id", "")
        if not task_id:
            return _clarify("task_stop", ["task_id"], "취소할 task_id를 알려주세요.")
        graph = _get_user_task_graph()
        task = graph.get_task(task_id)
        if task is None:
            return {"error": f"Task '{task_id}' not found"}
        reason = kwargs.get("reason", "stopped")
        try:
            graph.mark_failed(task_id, error=reason)
            graph.propagate_failure(task_id)
        except ValueError as exc:
            return {"error": str(exc)}
        return {"status": "ok", "action": "stopped", "task_id": task_id, "reason": reason}

    return {
        "task_create": handle_task_create,
        "task_update": handle_task_update,
        "task_get": handle_task_get,
        "task_list": handle_task_list,
        "task_stop": handle_task_stop,
    }


# ---------------------------------------------------------------------------
# Notification handlers
# ---------------------------------------------------------------------------


def _build_notification_handlers() -> dict[str, Any]:
    """Build notification tool handlers."""
    from core.tools.output_tools import SendNotificationTool

    notification_tool = SendNotificationTool()

    def handle_send_notification(**kwargs: Any) -> dict[str, Any]:
        return notification_tool.execute(**kwargs)

    return {
        "send_notification": handle_send_notification,
    }


# ---------------------------------------------------------------------------
# Calendar handlers
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

    def handle_calendar_list_events(**kwargs: Any) -> dict[str, Any]:
        return list_tool.execute(**kwargs)

    def handle_calendar_create_event(**kwargs: Any) -> dict[str, Any]:
        return create_tool.execute(**kwargs)

    def handle_calendar_sync_scheduler(**kwargs: Any) -> dict[str, Any]:
        return sync_tool.execute(**kwargs)

    return {
        "calendar_list_events": handle_calendar_list_events,
        "calendar_create_event": handle_calendar_create_event,
        "calendar_sync_scheduler": handle_calendar_sync_scheduler,
    }
