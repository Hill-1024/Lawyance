"""
模块描述：对话级记忆服务包入口，保持旧的 memory_system.service 导入兼容。
"""

from __future__ import annotations

import sys
import types

from . import api as _api
from . import core as _core
from . import embeddings as _embeddings
from . import errors as _errors
from . import extraction as _extraction
from . import mutations as _mutations
from . import ranking as _ranking
from . import schema as _schema
from . import scoring as _scoring
from . import state as _state
from . import store as _store
from . import utils as _utils
from .api import (
    MemoryRevisionConflict,
    clear_conversation_memory,
    inspect_conversation_memory,
    prune_conversation_memory,
    remember_conversation_turn,
    retrieve_conversation_memory,
    sync_conversation_memory,
    update_conversation_memory,
)

__all__ = [
    "MemoryRevisionConflict",
    "clear_conversation_memory",
    "inspect_conversation_memory",
    "prune_conversation_memory",
    "remember_conversation_turn",
    "retrieve_conversation_memory",
    "sync_conversation_memory",
    "update_conversation_memory",
]

_COMPAT_MODULES = (
    _api,
    _embeddings,
    _errors,
    _extraction,
    _mutations,
    _ranking,
    _schema,
    _scoring,
    _state,
    _store,
    _utils,
    _core,
)


class _ServicePackage(types.ModuleType):
    def __getattr__(self, name: str):
        for module in _COMPAT_MODULES:
            if hasattr(module, name):
                return getattr(module, name)
        raise AttributeError(name)

    def __setattr__(self, name: str, value):
        if name.startswith("__") or name in {"_core", "_COMPAT_MODULES"}:
            super().__setattr__(name, value)
            return
        updated = False
        for module in _COMPAT_MODULES:
            if hasattr(module, name):
                setattr(module, name, value)
                updated = True
        if name == "_EMBEDDING_CONFIG":
            _state._EMBEDDING_CONFIG = value
            _embeddings._EMBEDDING_CONFIG = value
            updated = True
        elif name == "_EMBEDDING_FAILURE_UNTIL":
            _state._EMBEDDING_FAILURE_UNTIL = value
            _embeddings._EMBEDDING_FAILURE_UNTIL = value
            updated = True
        if updated:
            setattr(_core, name, value)
        super().__setattr__(name, value)


sys.modules[__name__].__class__ = _ServicePackage
