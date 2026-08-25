# Public benchmark integrations and external-platform adapters.
from .manifest import BENCHMARKS, BenchmarkSpec, get_benchmark

HarnessSpec = BenchmarkSpec  # v1.0.x compatibility
BENCHMARK_HARNESSES = BENCHMARKS
get_harness = get_benchmark
