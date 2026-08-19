"""Compatibility launcher for the benchmark harness CLI."""

if __name__ == "__main__":
    from geode_product.benchmark_harness.cli import main

    raise SystemExit(main())
else:
    from plugins._compat import canonical_module as _canonical_module

    _canonical_module(__name__, "geode_product.benchmark_harness.cli")
