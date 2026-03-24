"""DEPRECATED: Use core.mcp.stdio_client instead."""

import importlib as _il
import sys as _sys

_sys.modules[__name__] = _il.import_module("core.mcp.stdio_client")
