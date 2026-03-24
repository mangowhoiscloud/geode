"""DEPRECATED: Use core.mcp.signal_port instead."""

import importlib as _il
import sys as _sys

_sys.modules[__name__] = _il.import_module("core.mcp.signal_port")
