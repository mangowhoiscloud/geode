"""DEPRECATED: Use core.mcp.slack_adapter instead."""

import importlib as _il
import sys as _sys

_sys.modules[__name__] = _il.import_module("core.mcp.slack_adapter")
