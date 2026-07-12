#!/usr/bin/env -S uv run --frozen --no-dev python
"""Frozen command entrypoint for Crucible paired tau2 evaluation."""

from plugins.crucible.tau2_live import run_command_evaluator

if __name__ == "__main__":
    raise SystemExit(run_command_evaluator())
