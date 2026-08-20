"""Compatibility launcher for :mod:`geode_product.self_improving.train`."""

import sys

from geode_product.self_improving.train import main as _main

if __name__ == "__main__":
    raise SystemExit(_main())

sys.modules[__name__] = sys.modules[_main.__module__]
