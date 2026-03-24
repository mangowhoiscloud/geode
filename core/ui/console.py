"""DEPRECATED: Use core.cli.ui.console instead."""
import importlib as _il
import sys as _sys
_sys.modules[__name__] = _il.import_module("core.cli.ui.console")
