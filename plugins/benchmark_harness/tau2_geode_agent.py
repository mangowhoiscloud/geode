"""Compatibility launcher for the Tau2 GEODE adapter."""

if __name__ == "__main__":
    from geode_product.benchmark_harness.tau2_geode_agent import main

    raise SystemExit(main())
else:
    from plugins._compat import canonical_module as _canonical_module

    _canonical_module(__name__, "geode_product.benchmark_harness.tau2_geode_agent")
