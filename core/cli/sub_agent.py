"""DEPRECATED: Use core.agent.sub_agent instead."""

import importlib as _il
import sys as _sys

_sys.modules[__name__] = _il.import_module("core.agent.sub_agent")
