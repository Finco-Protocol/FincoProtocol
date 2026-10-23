"""Runtime eligibility for the native candidate (V10-09). Stdlib only; importable on every runtime.

The canonical Python engine keeps its existing ``requires-python`` policy on every runtime.
Native eligibility is an explicit allow-list of runtime/target combinations that have full-engine
evidence. Anything else declines to canonical with a reason. The list here records what this
research validated; widening it requires new target evidence, never a code default.
"""
from __future__ import annotations

import platform
import struct
import sys

# (system, machine, implementation, (major, minor)) with full-engine exact-identity evidence.
VALIDATED_TARGETS = frozenset({
    ("Linux", "x86_64", "cpython", (3, 13)),      # this research: full matrix, Linux x86-64, gcc 13.3
    ("Linux", "x86_64", "cpython", (3, 12)),      # consolidated V10 matrix on CPython 3.12.3 (off / S1+2)
})
# Sum-only evidence (kernel sum() parity, no full-engine run on that target): NOT eligible.
SUM_ONLY_EVIDENCE = frozenset({
    ("Windows", "AMD64", "cpython", (3, 12)),     # independent review: full engine on Windows 3.12.10
})


def runtime_key() -> tuple:
    return (platform.system(), platform.machine(), sys.implementation.name, sys.version_info[:2])


def check_runtime(extra_targets: frozenset = frozenset()) -> str | None:
    """Return None if the running interpreter/target is eligible, else a decline reason."""
    key = runtime_key()
    if key not in VALIDATED_TARGETS | extra_targets:
        return f"RUNTIME_NOT_VALIDATED:{key}"
    if sys.version_info < (3, 12):
        return "RUNTIME_SUM_SEMANTICS_PRE_3_12"           # builtin sum() is not compensated before 3.12
    is_gil = getattr(sys, "_is_gil_enabled", lambda: True)()
    if not is_gil:
        return "RUNTIME_FREE_THREADED_NOT_VALIDATED"
    if struct.calcsize("P") != 8 or sys.byteorder != "little":
        return "RUNTIME_ABI_WIDTH_OR_ENDIANNESS"
    if sys.float_info.mant_dig != 53 or sys.float_info.max_exp != 1024 or sys.float_repr_style != "short":
        return "RUNTIME_FLOAT_NOT_IEEE_BINARY64"
    return None


# Canary lists whose builtin sum() differs between naive and compensated summation (3.11 vs 3.12+).
SUM_CANARIES = (
    (1e16, 1.0, -1e16),
    (0.1,) * 10,
    (1e308, 1e308, -1e308),
    (-0.0,),
    (1.0, 1e100, 1.0, -1e100),
    (3.14159, -2.71828, 1e-17, 1e17, -1e17),
)
