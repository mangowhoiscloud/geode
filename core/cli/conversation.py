"""DEPRECATED: Use core.agent.conversation instead."""

import importlib as _il
import sys as _sys

_sys.modules[__name__] = _il.import_module("core.agent.conversation")
