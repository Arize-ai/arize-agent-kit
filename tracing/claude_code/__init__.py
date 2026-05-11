from __future__ import annotations

import importlib
import sys
import types

_LAZY_SUBMODULES = frozenset({"agent_sdk"})


class _LazyModule(types.ModuleType):
    """Module subclass that lazily imports certain submodules without caching."""

    def __getattr__(self, name: str):
        if name in _LAZY_SUBMODULES:
            return importlib.import_module(f".{name}", self.__name__)
        raise AttributeError(f"module {self.__name__!r} has no attribute {name!r}")

    def __setattr__(self, name: str, value: object) -> None:
        if name in _LAZY_SUBMODULES:
            return  # Don't cache; __getattr__ handles lookup via proper import
        super().__setattr__(name, value)


sys.modules[__name__].__class__ = _LazyModule
