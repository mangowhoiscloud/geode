"""Evaluation subprocess-worker composition."""

from pathlib import Path

from core.agent.worker import main as run_worker
from core.wiring.runtime import build_middleware_registry

from evals.composition import compose_tool_plan
from evals.run_timeline import RunTimeline, current_run_timeline, set_current_run_timeline


def _bind_activity(run_dir: Path) -> None:
    set_current_run_timeline(
        RunTimeline(
            session_id=run_dir.name,
            gen_tag="",
            component="seed-generation",
            path=run_dir / "events.jsonl",
        )
    )


def main() -> None:
    run_worker(
        compose_tool_plan,
        middleware_builder=build_middleware_registry,
        activity_sink_provider=current_run_timeline,
        worker_activity_binder=_bind_activity,
    )


if __name__ == "__main__":
    main()
