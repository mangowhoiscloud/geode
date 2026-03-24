"""DEPRECATED: Use core.skills instead."""

import importlib as _il
import sys as _sys

_sys.modules[__name__] = _il.import_module("core.skills.skills")
