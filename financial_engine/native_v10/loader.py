"""Optional, lazy, verified native loader (V10-08, V10-09). Never compiles; never raises to callers.

``get_native()`` returns ``(NativeLibrary, None)`` or ``(None, reason)``. A missing, unreadable or
mismatched binary, an ABI/layout mismatch, an ineligible runtime, a failed builtin-sum canary or a
failed canonical-source authentication all decline cleanly: the Run continues canonically.
The verification result is cached per process (it is a pure check of immutable files/objects);
the per-call identity re-check of the authenticated region runs on every admission.
"""
from __future__ import annotations

import ctypes as C
import hashlib
import json
import threading
from pathlib import Path

from . import eligibility

HERE = Path(__file__).resolve().parent
ABI_VERSION = 10001
I64 = C.c_int64
D_P = C.POINTER(C.c_double)
I_P = C.POINTER(C.c_int64)


class Plan(C.Structure):
    _fields_ = [
        ("abi_version", I64), ("struct_size", I64),
        ("n_rows", I64), ("n_years", I64), ("n_slots", I64), ("n_sp", I64), ("n_sorted", I64),
        ("n_open", I64), ("idx_span", I64),
        ("row_kind", I_P), ("row_slot_start", I_P), ("row_slot_count", I_P),
        ("slot_pos", I_P), ("slot_frac", D_P), ("y_ebitda", D_P), ("y_dep", D_P),
        ("year_key", I_P), ("payment_idx", I_P),
        ("timing_payment", I64), ("lag", I64), ("max_idx", I64),
        ("sp_start", I_P), ("sp_count", I_P), ("sp_k", I_P), ("sp_nf", D_P),
        ("idx_min", I64), ("idx_to_sorted", I_P), ("row_sorted", I_P),
        ("atad_enabled", I64), ("atad_limit", C.c_double), ("atad_threshold", C.c_double),
        ("loss_gate", I64), ("corporate_rate", C.c_double), ("lcf_years", I64),
        ("open_last", I_P), ("open_amount", D_P),
        ("row_cand", I_P),
        ("row_other", D_P), ("row_elig", D_P), ("row_nd", D_P), ("row_static_gross", D_P),
        ("row_static_nd", D_P), ("row_reint", D_P), ("row_fin", D_P), ("row_ebitda", D_P),
        ("n_d", I64), ("rates", D_P), ("dfs", D_P), ("dscr", D_P), ("avail", D_P),
        ("in_rep", I_P), ("d_row", I_P),
        ("alpha", C.c_double), ("max_iter", I64), ("abs_tol", C.c_double), ("rel_tol", C.c_double),
        ("max_fin_iter", I64),
    ]


class SolveOut(C.Structure):
    _fields_ = [("abi_version", I64), ("iteration", I64), ("new_D", C.c_double),
                ("max_abs_diff", C.c_double), ("tax_evals", I64)]


class NativeLibrary:
    __slots__ = ("lib", "manifest", "build_id", "auth")

    def __init__(self, lib, manifest, auth):
        self.lib, self.manifest, self.build_id, self.auth = lib, manifest, manifest["build_id"], auth


_LOCK = threading.Lock()
_RESULT: dict = {}


def _verify(directory: Path, manifest_name: str):
    from . import provenance
    reason = eligibility.check_runtime()
    if reason:
        return None, reason
    try:
        manifest = json.loads((directory / manifest_name).read_text(encoding="utf-8"))
        artifact = directory / manifest["artifact"]
        blob = artifact.read_bytes()
    except (OSError, ValueError, KeyError) as exc:
        return None, f"LOADER_ARTIFACT_UNAVAILABLE:{type(exc).__name__}"
    if manifest.get("abi_version") != ABI_VERSION:
        return None, "LOADER_ABI_VERSION_MANIFEST"
    if hashlib.sha256(blob).hexdigest() != manifest.get("artifact_sha256"):
        return None, "LOADER_ARTIFACT_SHA256_MISMATCH"
    try:
        approved = (directory / "approved_canonical_blobs.json").read_bytes()
    except OSError as exc:
        return None, f"LOADER_APPROVED_MANIFEST_UNAVAILABLE:{type(exc).__name__}"
    if hashlib.sha256(approved).hexdigest() != manifest.get("approved_blobs_sha256"):
        return None, "LOADER_APPROVED_MANIFEST_NOT_SEALED"
    try:
        lib = C.CDLL(str(artifact))
        lib.fk_abi_version.restype = C.c_int
        lib.fk_plan_size.restype = I64
        lib.fk_build_id.restype = C.c_char_p
        lib.fk_py_sum.argtypes = [D_P, I64]
        lib.fk_py_sum.restype = C.c_double
        lib.fk_solve_dscr.argtypes = [C.POINTER(Plan), C.c_double, C.POINTER(SolveOut), D_P, I64, D_P, D_P, I64]
        lib.fk_solve_dscr.restype = C.c_int
        lib.fk_finalise.argtypes = [C.POINTER(Plan), C.c_double, D_P, I64, D_P, I64, D_P, D_P, I64, I_P]
        lib.fk_finalise.restype = C.c_int
        lib.fk_tax.argtypes = [C.POINTER(Plan), D_P, I64, D_P, D_P, I64]
        lib.fk_tax.restype = C.c_int
    except (OSError, AttributeError) as exc:
        return None, f"LOADER_DLOPEN:{type(exc).__name__}"
    if lib.fk_abi_version() != ABI_VERSION:
        return None, "LOADER_ABI_VERSION_BINARY"
    if lib.fk_plan_size() != C.sizeof(Plan):
        return None, "LOADER_PLAN_LAYOUT"
    if lib.fk_build_id().decode() != manifest.get("build_id"):
        return None, "LOADER_BUILD_ID"
    for canary in eligibility.SUM_CANARIES:
        arr = (C.c_double * len(canary))(*canary)
        if lib.fk_py_sum(arr, len(canary)).hex() != float(sum(canary)).hex():
            return None, "LOADER_SUM_SEMANTICS"
    auth, reason = provenance.authenticate(directory / "approved_canonical_blobs.json")
    if auth is None:
        return None, reason
    return NativeLibrary(lib, manifest, auth), None


def get_native(directory: Path | None = None, manifest_name: str = "fk_v10_manifest.json"):
    key = (str(directory or HERE), manifest_name)
    with _LOCK:
        if key not in _RESULT:
            try:
                _RESULT[key] = _verify(Path(key[0]), manifest_name)
            except Exception as exc:  # noqa: BLE001 - verification failure always means canonical
                _RESULT[key] = (None, f"LOADER_UNEXPECTED:{type(exc).__name__}")
        return _RESULT[key]


def _reset_for_tests() -> None:
    with _LOCK:
        _RESULT.clear()
