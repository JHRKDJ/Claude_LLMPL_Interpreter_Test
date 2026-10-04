"""Names visible without import (the prelude) and native std-module exports.

Derived from the runtime's builtin *metadata* (registry tables and core type
definitions). This is the one sanctioned dependency from `check` into `runtime`
(see ARCHITECTURE.md): metadata only, never evaluation.
"""
from __future__ import annotations

from functools import lru_cache

from ..runtime.builtins.registry import MODULES, PRELUDE, load_all
from ..runtime.core_types import CATEGORIES, CORE_ENUMS, CORE_RECORDS

load_all()

PRIM_TYPES = ["Int", "Float", "Bool", "Str", "Unit", "Dyn", "Never"]
BUILTIN_TYPE_NAMES = ["List", "Map", "Set", "MutableList", "MutableMap", "MutableSet", "Duration", "Instant",
                      "Channel", "Broadcast", "Task", "SendPort", "ReceivePort", "Range", "Option", "Result"]
CORE_CASES = {"Some", "None", "Ok", "Err"}
PRELUDE_VALUES = sorted(set(PRELUDE) | set(CORE_ENUMS) | set(CORE_RECORDS) | set(CATEGORIES) |
                        {"Some", "None", "Ok", "Err", "time", "cancel"})


@lru_cache(maxsize=1)
def native_module_exports() -> dict[str, list[str]]:
    return {m: sorted(v) for m, v in MODULES.items() if m.startswith("std.")}
