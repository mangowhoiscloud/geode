"""DEPRECATED: Use core.gateway.auth instead."""

import importlib as _il
import sys as _sys

_sys.modules[__name__] = _il.import_module("core.gateway.auth.cooldown")
