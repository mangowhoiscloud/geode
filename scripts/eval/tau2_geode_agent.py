#!/usr/bin/env python3
"""Compatibility wrapper for the public benchmark harness plugin."""

from __future__ import annotations

from plugins.benchmark_harness.tau2_geode_agent import main

if __name__ == "__main__":
    raise SystemExit(main())
