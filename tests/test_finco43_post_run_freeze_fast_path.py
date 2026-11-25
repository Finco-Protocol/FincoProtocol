"""FINCO43: the post-Run snapshot ``_freeze`` leaf fast path returns exactly what the generic path returned.

The reference below is a verbatim copy of the pre-FINCO43 ``_freeze`` body. Both are applied to a structure that
exercises every branch (Mapping / list / tuple / dataclass recursion, str- and int-enum subclasses, dates, Decimal,
bytes, None, bool, signed zero, NaN); the outputs must be structurally identical with the same leaf OBJECTS and the
same container types, and the frozen containers must stay read-only.
"""
from __future__ import annotations

import enum
import math
from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass, replace
from datetime import date, datetime
from decimal import Decimal
from types import MappingProxyType

import pytest

from app.v2 import post_run_context as prc


def _reference_freeze(value):
    if isinstance(value, Mapping):
        return prc._FrozenDict({k: _reference_freeze(v) for k, v in value.items()})
    if isinstance(value, list):
        return prc._FrozenList(_reference_freeze(v) for v in value)
    if isinstance(value, tuple):
        return tuple(_reference_freeze(v) for v in value)
    if is_dataclass(value):
        copy = replace(value)
        for f in fields(value):
            object.__setattr__(copy, f.name, _reference_freeze(getattr(value, f.name)))
        return copy
    return value


class _Status(str, enum.Enum):
    CURRENT = "CURRENT"


class _Level(enum.IntEnum):
    ONE = 1


class _StrSub(str):
    pass


@dataclass(frozen=True)
class _Inner:
    amounts: list
    meta: dict


@dataclass
class _Outer:
    name: str
    inner: _Inner
    when: date
    rows: tuple


def _sample():
    leaves = ["s", _StrSub("sub"), 0, -1, 2 ** 70, 1.5, -0.0, float("nan"), float("inf"), True, False, None,
              b"\x00b", Decimal("1.10"), date(2031, 2, 28), datetime(2031, 2, 28, 12, 0), _Status.CURRENT, _Level.ONE]
    inner = _Inner(amounts=[1.0, [2.0, {"k": -0.0}]], meta={"status": _Status.CURRENT, "n": None})
    return {
        "leaves": list(leaves),
        "tuple": tuple(leaves),
        "proxy": MappingProxyType({"a": [1, 2], "b": (3.0,)}),
        "outer": _Outer(name="x", inner=inner, when=date(2030, 1, 1), rows=({"r": 1.0}, [2])),
        7: {"nested": [{"deep": (date(2029, 12, 31), Decimal("0"))}]},
    }


def _shape(value):
    """Structural fingerprint: container types, mapping key order, and leaf identity/type/bits."""
    if isinstance(value, Mapping):
        return (type(value).__name__, tuple((k, _shape(v)) for k, v in value.items()))
    if isinstance(value, (list, tuple)):
        return (type(value).__name__, tuple(_shape(v) for v in value))
    if is_dataclass(value):
        return (type(value).__name__, tuple((f.name, _shape(getattr(value, f.name))) for f in fields(value)))
    if isinstance(value, float):
        return ("float", value.hex() if not math.isnan(value) else "nan")
    return (type(value).__name__, repr(value))


def test_fast_path_output_identical_to_reference():
    src = _sample()
    got, ref = prc._freeze(src), _reference_freeze(src)
    assert _shape(got) == _shape(ref)
    # leaf objects are the very same objects (no copies, no coercion of subclasses)
    for a, b in zip(got["leaves"], ref["leaves"]):
        assert a is b
    assert type(got["leaves"][1]) is _StrSub and got["leaves"][16] is _Status.CURRENT


def test_containers_remain_read_only():
    got = prc._freeze(_sample())
    with pytest.raises(TypeError):
        got["new"] = 1
    with pytest.raises(TypeError):
        got["leaves"].append(1)
    with pytest.raises(TypeError):
        got["outer"].inner.meta["n"] = 1


@pytest.mark.parametrize("leaf", ["x", 1, 1.0, True, None, b"b", Decimal("2"), date(2030, 1, 1),
                                  datetime(2030, 1, 1)])
def test_exact_leaf_types_short_circuit(leaf):
    assert prc._freeze(leaf) is leaf


def test_leaf_type_set_contains_no_container():
    for t in prc._FROZEN_LEAF_TYPES:
        assert not issubclass(t, (Mapping, list, tuple)) and not is_dataclass(t)
