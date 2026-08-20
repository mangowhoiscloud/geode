"""Compatibility launcher for the Crucible replay producer."""

if __name__ == "__main__":
    from geode_product.crucible.producers.replay import main

    raise SystemExit(main())
else:
    from plugins._compat import canonical_module as _canonical_module

    _canonical_module(__name__, "geode_product.crucible.producers.replay")
