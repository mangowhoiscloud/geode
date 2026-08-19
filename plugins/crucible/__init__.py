"""Compatibility facade for :mod:`geode_product.crucible`."""

from plugins._compat import export_package as _export_package

_export_package(globals(), "geode_product.crucible")
