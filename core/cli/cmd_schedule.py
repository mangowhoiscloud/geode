"""Schedule command — extracted from commands.py (Kent Beck Phase 3)."""

from __future__ import annotations

from typing import Any as _Any

from core.cli.ui.console import console


def _format_schedule_desc(job: _Any) -> str:
    """Format a ScheduledJob's schedule as human-readable string."""
    sched = job.schedule
    kind = sched.kind.value if hasattr(sched.kind, "value") else str(sched.kind)
    if kind == "every" and sched.every_ms:
        secs = sched.every_ms / 1000
        if secs >= 3600:
            return f"every {secs / 3600:.0f}h"
        if secs >= 60:
            return f"every {secs / 60:.0f}m"
        return f"every {secs:.0f}s"
    if kind == "cron" and sched.cron_expr:
        return f"cron: {sched.cron_expr}"
    if kind == "at":
        return "one-shot (at)"
    return kind


def _print_job_status(job: _Any) -> None:
    """Print detailed status for a dynamic ScheduledJob."""
    console.print(f"  Name: {job.name}")
    console.print(f"  Schedule: {_format_schedule_desc(job)}")
    state = "enabled" if job.enabled else "disabled"
    console.print(f"  State: {state}")
    if job.last_status:
        console.print(f"  Last status: {job.last_status}")
    if job.last_duration_ms is not None:
        console.print(f"  Last duration: {job.last_duration_ms:.1f}ms")
    if job.active_hours:
        console.print(f"  Active hours: {job.active_hours.start}-{job.active_hours.end}")


def cmd_schedule(args: str, *, scheduler_service: _Any = None) -> None:
    """Handle /schedule command — manage scheduled automations.

    /schedule                    → list predefined templates + dynamic jobs
    /schedule list               → same as above
    /schedule create <expr>      → create job from NL expression
    /schedule delete <id>        → delete a dynamic job
    /schedule status <id>        → show job/template status
    /schedule enable <id>        → enable a job/template
    /schedule disable <id>       → disable a job/template
    /schedule run <id>           → run a job/template immediately
    """
    from core.automation.predefined import PREDEFINED_AUTOMATIONS

    arg = args.strip()
    arg_lower = arg.lower()

    # --- list -----------------------------------------------------------
    if not arg_lower or arg_lower == "list":
        console.print()
        console.print("  [header]Predefined Automations[/header]")
        for tmpl in PREDEFINED_AUTOMATIONS:
            state = "[success]ON[/success]" if tmpl.enabled else "[muted]OFF[/muted]"
            console.print(
                f"  {state}  [label]{tmpl.id:<30}[/label] "
                f"[muted]{tmpl.schedule:<16}[/muted] {tmpl.name}"
            )

        # Dynamic jobs from scheduler_service
        if scheduler_service is not None:
            jobs = scheduler_service.list_jobs(include_disabled=True)
            if jobs:
                console.print()
                console.print("  [header]Dynamic Jobs[/header]")
                for job in jobs:
                    state = "[success]ON[/success]" if job.enabled else "[muted]OFF[/muted]"
                    desc = _format_schedule_desc(job)
                    console.print(
                        f"  {state}  [label]{job.job_id:<30}[/label] "
                        f"[muted]{desc:<16}[/muted] {job.name}"
                    )

        console.print()
        console.print(
            "  [muted]Usage: /schedule [create|delete|status|enable|disable|run] <id>[/muted]"
        )
        console.print()
        return

    parts = arg.split(None, 1)
    sub = parts[0].lower()
    rest = parts[1] if len(parts) > 1 else ""
    target_id = rest.strip()

    # --- create ---------------------------------------------------------
    if sub == "create":
        if not target_id:
            console.print("  [warning]Usage: /schedule create <expression>[/warning]")
            console.print()
            return
        if scheduler_service is None:
            console.print("  [warning]Scheduler not available[/warning]")
            console.print()
            return
        from core.automation.nl_scheduler import NLScheduleParser

        parser = NLScheduleParser()
        result = parser.parse(target_id)
        if not result.success or result.job is None:
            console.print(f"  [warning]Failed to parse: {target_id}[/warning]")
            console.print()
            return
        scheduler_service.add_job(result.job)
        scheduler_service.save()  # persist immediately — prevent crash data loss
        console.print(f"  [success]Created: {result.job.job_id}[/success]")
        console.print(f"  Schedule: {_format_schedule_desc(result.job)}")
        console.print()
        return

    # --- delete ---------------------------------------------------------
    if sub == "delete":
        if scheduler_service is None:
            console.print("  [warning]Scheduler not available[/warning]")
            console.print()
            return
        removed = scheduler_service.remove_job(target_id)
        if removed:
            scheduler_service.save()  # persist deletion immediately
            console.print(f"  [success]Deleted: {target_id}[/success]")
        else:
            console.print(f"  [warning]Job not found: {target_id}[/warning]")
        console.print()
        return

    # --- status ---------------------------------------------------------
    if sub == "status":
        # Check predefined templates first
        found_tmpl = next(
            (t for t in PREDEFINED_AUTOMATIONS if t.id == target_id),
            None,
        )
        if found_tmpl is not None:
            console.print()
            console.print(f"  Template: {found_tmpl.name}")
            console.print(f"  Schedule: {found_tmpl.schedule}")
            state = "enabled" if found_tmpl.enabled else "disabled"
            console.print(f"  State: {state}")
            console.print()
            return

        # Check dynamic jobs
        if scheduler_service is not None:
            job = scheduler_service.get_job(target_id)
            if job is not None:
                console.print()
                _print_job_status(job)
                console.print()
                return

        console.print(f"  [warning]Not found: {target_id}[/warning]")
        console.print()
        return

    # --- enable / disable -----------------------------------------------
    if sub in ("enable", "disable"):
        new_state = sub == "enable"

        # Check predefined templates
        found_tmpl = next(
            (t for t in PREDEFINED_AUTOMATIONS if t.id == target_id),
            None,
        )
        if found_tmpl is not None:
            found_tmpl.enabled = new_state
            label = "enabled" if new_state else "disabled"
            console.print(f"  [success]{found_tmpl.name}: {label}[/success]")
            console.print()
            return

        # Check dynamic jobs
        if scheduler_service is not None:
            updated = scheduler_service.update_job(target_id, enabled=new_state)
            if updated:
                label = "enabled" if new_state else "disabled"
                console.print(f"  [success]{target_id}: {label}[/success]")
                console.print()
                return

        console.print(f"  [warning]Unknown template: {target_id}[/warning]")
        console.print()
        return

    # --- run ------------------------------------------------------------
    if sub == "run":
        # Check predefined templates
        found_tmpl = next(
            (t for t in PREDEFINED_AUTOMATIONS if t.id == target_id),
            None,
        )
        if found_tmpl is not None:
            console.print(f"  [header]Running: {found_tmpl.name}[/header]")
            console.print(f"  Mode: {found_tmpl.pipeline_config.mode}")
            console.print(f"  Batch size: {found_tmpl.pipeline_config.batch_size}")
            console.print(f"  Dry-run: {found_tmpl.pipeline_config.dry_run}")
            console.print()
            console.print("  [muted]Template execution dispatched to runtime.[/muted]")
            console.print()
            return

        # Check dynamic jobs
        if scheduler_service is not None:
            result = scheduler_service.run_now(target_id)
            if result.get("status") == "error":
                console.print(f"  [warning]{result.get('error', 'Unknown error')}[/warning]")
            else:
                console.print(f"  [success]Executed: {target_id}[/success]")
            console.print()
            return

        console.print(f"  [warning]Unknown template: {target_id}[/warning]")
        console.print()
        return

    # --- fallback -------------------------------------------------------
    console.print(
        "  [warning]Usage: /schedule [list|create|delete|status|enable|disable|run] <id>[/warning]"
    )
    console.print()
