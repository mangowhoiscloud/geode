"""Compatibility facade for :mod:`geode_product.benchmark_harness`."""

from plugins._compat import export_package as _export_package

_export_package(globals(), "geode_product.benchmark_harness")
