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
    state = "[success]ON[/success]" if job.enabled else "[muted]OFF[/muted]"
    console.print(f"  {state} {job.name} ({_format_schedule_desc(job)})")
    if job.action:
        action_preview = job.action[:60] + ("..." if len(job.action) > 60 else "")
        console.print(f"  Action: {action_preview}")
    elif not job.action:
        console.print("  [warning]Action: (empty — job fires but does nothing)[/warning]")
    if job.last_status:
        console.print(f"  Last: {job.last_status} ({job.last_duration_ms:.0f}ms)")
    if job.active_hours:
        console.print(f"  Hours: {job.active_hours.start}-{job.active_hours.end}")


def _parse_create_args(text: str) -> tuple[str, str]:
    """Parse create arguments into (schedule_expr, action_text).

    Supports:
        "every 5m" "check status"   → ("every 5m", "check status")
        'every 5m' 'check status'   → ("every 5m", "check status")
        every 5m                    → ("every 5m", "")  — no action
    """
    import shlex

    try:
        parts = shlex.split(text)
    except ValueError:
        # Unmatched quotes — treat entire text as schedule
        return text, ""

    if len(parts) >= 2:
        # Last part is the action, everything before is the schedule
        # But if quoted: shlex gives us clean splits
        # Heuristic: if original text has quotes, respect the split
        if '"' in text or "'" in text:
            # shlex split: first part = schedule, second = action
            return parts[0], " ".join(parts[1:])
        # Unquoted: try to detect action separator
        # No good way to tell "every 5 minutes check status" apart
        # → require quotes for clarity
        return text, ""
    if len(parts) == 1:
        return parts[0], ""
    return text, ""


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
        # Dynamic jobs (active scheduler)
        if scheduler_service is not None:
            jobs = scheduler_service.list_jobs(include_disabled=True)
            if jobs:
                console.print()
                console.print("  [header]Scheduled Jobs[/header]")
                for job in jobs:
                    state = "[success]ON[/success]" if job.enabled else "[muted]OFF[/muted]"
                    desc = _format_schedule_desc(job)
                    action_hint = f" → {job.action[:40]}" if job.action else ""
                    console.print(
                        f"  {state}  [label]{job.job_id:<30}[/label] "
                        f"[muted]{desc:<16}[/muted] {job.name}{action_hint}"
                    )
            else:
                console.print()
                console.print("  [muted]No scheduled jobs.[/muted]")

        # Predefined templates (domain-specific, reference only)
        console.print()
        console.print("  [header]Templates[/header] [muted](domain reference, not active)[/muted]")
        for tmpl in PREDEFINED_AUTOMATIONS:
            console.print(f"  [muted]  {tmpl.id:<30} {tmpl.schedule:<16} {tmpl.name}[/muted]")

        console.print()
        console.print('  [muted]Usage: /schedule create "<schedule>" "<action>"[/muted]')
        console.print()
        return

    parts = arg.split(None, 1)
    sub = parts[0].lower()
    rest = parts[1] if len(parts) > 1 else ""
    target_id = rest.strip()

    # --- create ---------------------------------------------------------
    if sub == "create":
        if not rest.strip():
            console.print('  [warning]Usage: /schedule create "<schedule>" "<action>"[/warning]')
            console.print('  [muted]Example: /schedule create "every 5m" "check status"[/muted]')
            console.print()
            return
        if scheduler_service is None:
            console.print("  [warning]Scheduler not available[/warning]")
            console.print()
            return

        # Parse quoted args: /schedule create "every 5m" "do something"
        schedule_expr, action_text = _parse_create_args(rest.strip())
        if not action_text:
            console.print(
                "  [warning]Action is required. What should the job do when it fires?[/warning]"
            )
            console.print('  [muted]Usage: /schedule create "<schedule>" "<action>"[/muted]')
            console.print()
            return

        from core.automation.nl_scheduler import NLScheduleParser

        parser = NLScheduleParser()
        result = parser.parse(schedule_expr)
        if not result.success or result.job is None:
            console.print(f"  [warning]Failed to parse schedule: {schedule_expr}[/warning]")
            console.print()
            return
        result.job.action = action_text
        try:
            scheduler_service.add_job(result.job)
        except ValueError as exc:
            console.print(f"  [warning]{exc}[/warning]")
            console.print()
            return
        scheduler_service.save()
        console.print(f"  [success]Created: {result.job.job_id}[/success]")
        console.print(f"  Schedule: {_format_schedule_desc(result.job)}")
        console.print(f"  Action: {action_text[:80]}")
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

        # Reject predefined templates — they're reference only
        found_tmpl = next(
            (t for t in PREDEFINED_AUTOMATIONS if t.id == target_id),
            None,
        )
        if found_tmpl is not None:
            console.print(f"  [warning]'{target_id}' is a template (not an active job).[/warning]")
            console.print(
                '  [muted]Create a job instead: /schedule create "<schedule>" "<action>"[/muted]'
            )
            console.print()
            return

        # Dynamic jobs
        if scheduler_service is not None:
            updated = scheduler_service.update_job(target_id, enabled=new_state)
            if updated:
                scheduler_service.save()
                label = "enabled" if new_state else "disabled"
                console.print(f"  [success]{target_id}: {label}[/success]")
                console.print()
                return

        console.print(f"  [warning]Job not found: {target_id}[/warning]")
        console.print()
        return

    # --- run ------------------------------------------------------------
    if sub == "run":
        # Reject predefined templates
        found_tmpl = next(
            (t for t in PREDEFINED_AUTOMATIONS if t.id == target_id),
            None,
        )
        if found_tmpl is not None:
            console.print(f"  [warning]'{target_id}' is a template (not an active job).[/warning]")
            console.print()
            return

        # Dynamic jobs
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
