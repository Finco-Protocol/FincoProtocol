"""Run-scoped memo of pure engine sub-calculations.

One Run recomputes some pure, deterministic sub-calculations from identical inputs (the
operating model and the tax/CFADS model are re-derived for the same inputs across the
financing fixed points). ``scoped_memo`` lets such a function return the result it already
computed *within the current run* and nowhere else:

* the cache lives only while ``engine_run_scope()`` is open and is discarded with it, so
  nothing is reused across runs, projects or users;
* outside a scope (direct engine calls, tests that patch engine internals) the wrapper is a
  plain call, so behaviour there is unchanged;
* the key is the pickled arguments — exact on types and float bit patterns (0.0 vs -0.0,
  1 vs 1.0 differ), so equal-by-``==`` is never mistaken for identical;
* arguments that cannot be pickled, and calls that raise, are never cached.

Only functions whose results are immutable (frozen dataclasses of tuples) may be wrapped.
"""
from __future__ import annotations

import functools
import pickle
from collections import OrderedDict
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Callable, Iterator, TypeVar

_SCOPE: ContextVar["dict[str, OrderedDict] | None"] = ContextVar(
    "finco_engine_run_scope", default=None,
)

F = TypeVar("F", bound=Callable)


@contextmanager
def engine_run_scope() -> Iterator[None]:
    """Open a run scope. Nested use joins the enclosing scope instead of replacing it."""
    if _SCOPE.get() is not None:
        yield
        return
    token = _SCOPE.set({})
    try:
        yield
    finally:
        _SCOPE.reset(token)


def scoped_memo(maxsize: int) -> Callable[[F], F]:
    """Memoise a pure function for the lifetime of the current ``engine_run_scope``."""

    def decorate(fn: F) -> F:
        name = f"{fn.__module__}.{fn.__qualname__}"

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            scope = _SCOPE.get()
            if scope is None:
                return fn(*args, **kwargs)
            try:
                key = pickle.dumps(
                    (args, tuple(sorted(kwargs.items()))), protocol=pickle.HIGHEST_PROTOCOL,
                )
            except Exception:  # unpicklable argument: compute, never cache
                return fn(*args, **kwargs)
            cache = scope.get(name)
            if cache is None:
                cache = scope[name] = OrderedDict()
            hit = cache.get(key)
            if hit is not None:
                cache.move_to_end(key)
                return hit[0]
            value = fn(*args, **kwargs)
            cache[key] = (value,)
            if len(cache) > maxsize:
                cache.popitem(last=False)
            return value

        wrapper.__wrapped__ = fn  # type: ignore[attr-defined]
        return wrapper  # type: ignore[return-value]

    return decorate
