"""Registry of native methods, properties, prelude functions and native modules.

Method implementations have the signature `impl(interp, recv, args, span)`;
prelude/module functions `impl(interp, args, span)`. Signatures (`sig`) use the
language's own type syntax and are consumed by the static checker; `Self` stands for
the receiver type and `T`, `K`, `V`, `U`, `E` for its parameters or method generics.
"""
from __future__ import annotations

from typing import Callable

from ..values import Builtin

METHODS: dict[str, dict[str, Builtin]] = {}
PROPS: dict[str, dict[str, tuple[Callable, str]]] = {}
STATICS: dict[str, dict[str, Builtin]] = {}  # e.g. List.of, Duration.seconds
PRELUDE: dict[str, Builtin] = {}
MODULES: dict[str, dict[str, object]] = {}


def method(kinds, name: str, min_args: int = 0, max_args: int | None = None, sig: str | None = None,
           is_async: bool = False, effect=frozenset(), abandon_safe: bool = False, contract_safe: bool = False):
    if isinstance(kinds, str):
        kinds = [kinds]

    def deco(fn):
        for k in kinds:
            b = Builtin(f"{k}.{name}", fn, is_async=is_async, effect=effect, min_args=min_args,
                        max_args=min_args if max_args is None else max_args, abandon_safe=abandon_safe,
                        sig=sig, kind=k, contract_safe=contract_safe)
            METHODS.setdefault(k, {})[name] = b
        return fn
    return deco


def prop(kinds, name: str, sig: str = "Dyn"):
    if isinstance(kinds, str):
        kinds = [kinds]

    def deco(fn):
        for k in kinds:
            PROPS.setdefault(k, {})[name] = (fn, sig)
        return fn
    return deco


def static(kind: str, name: str, min_args: int = 0, max_args: int | None = None, sig: str | None = None,
           is_async: bool = False, effect=frozenset(), contract_safe: bool = False):
    def deco(fn):
        STATICS.setdefault(kind, {})[name] = Builtin(f"{kind}.{name}", fn, is_async=is_async, effect=effect,
                                                     min_args=min_args,
                                                     max_args=min_args if max_args is None else max_args,
                                                     sig=sig, kind=kind, contract_safe=contract_safe)
        return fn
    return deco


def prelude(name: str, min_args: int = 0, max_args: int | None = None, sig: str | None = None,
            is_async: bool = False, effect=frozenset(), contract_safe: bool = False):
    def deco(fn):
        PRELUDE[name] = Builtin(name, fn, is_async=is_async, effect=effect, min_args=min_args,
                                max_args=min_args if max_args is None else max_args, sig=sig,
                                contract_safe=contract_safe)
        return fn
    return deco


def module_fn(module: str, name: str, min_args: int = 0, max_args: int | None = None, sig: str | None = None,
              is_async: bool = False, effect=frozenset(), is_provider: bool = False, abandon_safe: bool = False):
    def deco(fn):
        MODULES.setdefault(module, {})[name] = Builtin(f"{module}.{name}", fn, is_async=is_async, effect=effect,
                                                       min_args=min_args,
                                                       max_args=min_args if max_args is None else max_args,
                                                       sig=sig, is_provider=is_provider, abandon_safe=abandon_safe)
        return fn
    return deco


def load_all() -> None:
    """Import every builtin module so their registrations run."""
    from . import core, colls, strings, numbers, optres, timing, fs, jsonmod, mathmod  # noqa: F401
