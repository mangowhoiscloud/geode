"""Public GEODE benchmark harness plugin.

The plugin owns GEODE-specific adapters and runners. Third-party benchmark
repositories stay as ignored local checkouts under ``artifacts/eval/harnesses``.
"""

from .manifest import BENCHMARK_HARNESSES, HarnessSpec, get_harness

__all__ = ["BENCHMARK_HARNESSES", "HarnessSpec", "get_harness"]
