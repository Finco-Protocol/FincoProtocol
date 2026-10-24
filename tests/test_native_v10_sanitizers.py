"""ASan / UBSan / LSan on both native kernels (V10-04).

Stage 1: tests/fixtures/native_v10_fk_sanitize_harness.c is compiled together with kernel_v10.c under
AddressSanitizer + UndefinedBehaviorSanitizer (LeakSanitizer on) and driven over a corpus of REAL admitted
plans captured at test time from canonical-admission Runs: replay (status + every output bit-equal to the
release kernel), malformed plans (every structural violation rejected), allocation-failure injection
(NOMEM or the identical result, never another status, no leak) and structure-aware mutation (any status,
never a sanitizer diagnostic).

Stage 2: the ASan/UBSan build of kernel_v10_stage2.c runs in a separate interpreter (LD_PRELOAD) on plans
built by the real Stage 2 admission; every result is bit-identical to the release kernel and every
malformed plan is rejected.
"""
from __future__ import annotations

import ctypes as C
import json
import os
import shutil
import struct
import subprocess
import sys
from pathlib import Path

import pytest

from tests.native_v10_support import HERE, STAGE1

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "fixtures" / "native_v10_fk_sanitize_harness.c"
pytestmark = pytest.mark.usefixtures("native_artifacts")

LENGTHS = {
    "row_kind": "n_rows", "row_slot_start": "n_rows", "row_slot_count": "n_rows", "slot_pos": "n_slots",
    "slot_frac": "n_slots", "y_ebitda": "n_years", "y_dep": "n_years", "year_key": "n_years",
    "payment_idx": "n_years", "sp_start": "n_sorted", "sp_count": "n_sorted", "sp_k": "n_sp", "sp_nf": "n_sp",
    "idx_to_sorted": "idx_span", "row_sorted": "n_rows", "open_last": "n_open", "open_amount": "n_open",
    "row_cand": "n_rows", "row_other": "n_rows", "row_elig": "n_rows", "row_nd": "n_rows",
    "row_static_gross": "n_rows", "row_static_nd": "n_rows", "row_reint": "n_rows", "row_fin": "n_rows",
    "row_ebitda": "n_rows", "rates": "n_d", "dfs": "n_d", "dscr": "n_d", "avail": "n_d", "in_rep": "n_d", "d_row": "n_d",
}


def _sanitizer_libs():
    if shutil.which("gcc") is None:
        pytest.skip("gcc not available")
    libs = []
    for name in ("libasan.so", "libubsan.so"):
        path = subprocess.run(["gcc", f"-print-file-name={name}"], capture_output=True, text=True).stdout.strip()
        if not os.path.isabs(path) or not os.path.exists(path):
            pytest.skip(f"{name} not available")
        libs.append(path)
    return libs


def _capture_corpus(path: Path, limit: int = 120) -> int:
    """Real admitted Stage 1 plans + release-kernel outputs, in the harness's binary record format."""
    from financial_engine.native_v10 import dispatch, loader
    from financial_engine.native_v10.config import native_run
    from tests.native_v10_support import acceptance, entries
    from app.services import production_financial_authority as pfa

    native, why = loader.get_native()
    assert native is not None, why
    count, d0 = {"n": 0}, {"v": 25000.0}
    real_build, real_solve = dispatch._build_plan, dispatch.solve_dscr
    out = path.open("wb")

    def write(P, start):
        out.write(b"FKV1")
        for name, ctype in loader.Plan._fields_:
            v = getattr(P, name)
            if name in LENGTHS:
                n = getattr(P, LENGTHS[name])
                fmt = "d" if ctype is loader.D_P else "q"
                out.write(struct.pack("<q", n))
                out.write(struct.pack(f"<{n}{fmt}", *[v[i] for i in range(n)]) if n else b"")
            elif ctype is C.c_double:
                out.write(struct.pack("<d", v))
            else:
                out.write(struct.pack("<q", v))
        out.write(struct.pack("<d", start))
        n, nr = P.n_d, P.n_rows
        so, cf, ncf, ntx = loader.SolveOut(), (C.c_double * n)(), (C.c_double * nr)(), (C.c_double * nr)()
        st = native.lib.fk_solve_dscr(C.byref(P), start, C.byref(so), cf, n, ncf, ntx, nr)
        out.write(struct.pack("<qqdd", st, so.iteration, so.new_D, so.max_abs_diff))
        out.write(struct.pack(f"<{n}d", *cf) + struct.pack(f"<{nr}d", *ncf) + struct.pack(f"<{nr}d", *ntx))

    def spy_build(ctx, roll_plan, policy):
        P, keep, periods = real_build(ctx, roll_plan, policy)
        if count["n"] < limit:
            write(P, d0["v"])
            count["n"] += 1
        return P, keep, periods

    def spy_solve(**kw):
        d0["v"] = kw["inputs"].initial_debt_guess_keur
        return real_solve(**kw)

    acc, catalogue = acceptance(), entries()
    dispatch._build_plan, dispatch.solve_dscr = spy_build, spy_solve
    try:
        for name in ("reference-solar", "reference-wind"):
            f, v, base = catalogue[name]
            pfa._POLICY_RUN_CACHE.clear()
            with native_run(STAGE1):
                pfa.run_clean_production(f(), project_type=v, financing_policy=acc.policy_for("canonical", base))
    finally:
        dispatch._build_plan, dispatch.solve_dscr = real_build, real_solve
        pfa._POLICY_RUN_CACHE.clear()
        out.close()
    return count["n"]


def test_stage1_kernel_under_asan_ubsan_lsan(tmp_path):
    _sanitizer_libs()
    corpus = tmp_path / "corpus.bin"
    assert _capture_corpus(corpus) >= 20
    exe = tmp_path / "fk_asan"
    subprocess.run(["gcc", "-std=c11", "-O1", "-g", "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                    "-DFK_TEST_ALLOC", "-fno-fast-math", "-ffp-contract=off", f"-I{HERE}", str(HARNESS),
                    "-o", str(exe), "-lm"], check=True, capture_output=True, text=True, timeout=300)
    env = dict(os.environ, ASAN_OPTIONS="detect_leaks=1:halt_on_error=1", UBSAN_OPTIONS="halt_on_error=1")
    results = {}
    for mode in ("replay", "malformed", "alloc", "mutate"):
        proc = subprocess.run([str(exe), mode, str(corpus)], capture_output=True, text=True, env=env, timeout=600)
        assert "Sanitizer" not in proc.stderr and "runtime error" not in proc.stderr, proc.stderr[-3000:]
        assert proc.returncode == 0, (mode, proc.returncode, proc.stderr[-2000:])
        results[mode] = json.loads(proc.stdout)
    replay = results["replay"]
    assert replay["records"] >= 20 and replay["bit_equal"] == replay["records"] and replay["mismatch"] == 0
    assert len(results["malformed"]) >= 20 and all(r["rejected"] for r in results["malformed"])
    assert results["alloc"]["wrong_status"] == 0 and results["alloc"]["nomem"] > 0
    assert results["mutate"]["runs"] > 0


STAGE2_SCRIPT = r"""
import ctypes as C, json, random, sys
from financial_engine.native_v10 import stage2
from financial_engine.run_scope import engine_run_scope
from tests.test_native_v10_stage2 import _capture_shl_corpus

asan = C.CDLL(sys.argv[1])
rel, why = stage2.get_stage2()
assert rel is not None, why
rel = rel[0]
asan.fk2_shl_schedule.argtypes = [C.POINTER(stage2.ShlPlan), stage2.D_P, stage2.I64, C.POINTER(stage2.ShlOut),
                                  stage2.I64, stage2.I64]
asan.fk2_shl_schedule.restype = C.c_int
corpus = _capture_shl_corpus()
rnd = random.Random(7)
res = {"cases": 0, "equal": 0, "malformed": {}}

def copy_plan(tpl, **over):
    P = stage2.ShlPlan()
    C.memmove(C.byref(P), C.byref(tpl["plan"]), C.sizeof(stage2.ShlPlan))
    for k, v in over.items():
        setattr(P, k, v)
    return P

def outs(n):
    arrs = [(C.c_double * max(n, 1))() for _ in range(10)]
    return arrs, stage2.ShlOut(*arrs, 0, 0, 0.0)

with engine_run_scope():
    for _ in range(int(sys.argv[2])):
        periods, si, cash0 = rnd.choice(corpus)
        try:
            tpl = stage2._template(periods, si, None)
        except stage2._Decline:
            continue
        n = tpl["n"]
        pool = [0.0, -0.0, 5e-324, 1e308, 1.7976931348623157e308] + ([-1.0, float("nan"), float("inf")] if rnd.random() < 0.25 else [])
        cash = [rnd.choice([c, c * rnd.uniform(0, 3)] + pool) if rnd.random() < 0.15 else c for c in cash0]
        enforce = rnd.choice([0, 1, 2])
        P = copy_plan(tpl)
        ca = (C.c_double * n)(*cash)
        a_arr, a_out = outs(n)
        r_arr, r_out = outs(n)
        sa = asan.fk2_shl_schedule(C.byref(P), ca, n, C.byref(a_out), n, enforce)
        sr = rel.fk2_shl_schedule(C.byref(P), ca, n, C.byref(r_out), n, enforce)
        res["cases"] += 1
        same = sa == sr and (sa != 0 or (all(a_arr[k][j].hex() == r_arr[k][j].hex() for k in range(10) for j in range(n))
               and (a_out.shortfall_count, a_out.shortfall_period, a_out.shortfall_closing.hex())
               == (r_out.shortfall_count, r_out.shortfall_period, r_out.shortfall_closing.hex())))
        res["equal"] += same
    periods, si, cash0 = corpus[0]
    tpl = stage2._template(periods, si, None)
    n = tpl["n"]
    ca = (C.c_double * n)(*cash0)
    for label, kw in {"abi_version": dict(abi_version=1), "struct_size": dict(struct_size=8), "n_negative": dict(n=-1),
                      "n_mismatch_cash": dict(n=n + 1), "n_con_gt_n": dict(n_con=n + 1), "n_con_negative": dict(n_con=-3),
                      "mode_invalid": dict(mode=7), "mode_zero": dict(mode=0)}.items():
        arr, o = outs(n)
        res["malformed"][label] = asan.fk2_shl_schedule(C.byref(copy_plan(tpl, **kw)), ca, n, C.byref(o), n, 1)
    arr, o = outs(n)
    res["malformed"]["cap_lt_n"] = asan.fk2_shl_schedule(C.byref(copy_plan(tpl)), ca, n, C.byref(o), n - 1, 1)
    res["malformed"]["enforce_out_of_range"] = asan.fk2_shl_schedule(C.byref(copy_plan(tpl)), ca, n, C.byref(o), n, 3)
    res["malformed"]["null_plan"] = asan.fk2_shl_schedule(None, ca, n, C.byref(o), n, 1)
    res["malformed"]["null_out"] = asan.fk2_shl_schedule(C.byref(copy_plan(tpl)), ca, n, None, n, 1)
    res["malformed"]["null_cash"] = asan.fk2_shl_schedule(C.byref(copy_plan(tpl)), None, n, C.byref(o), n, 1)
    P = copy_plan(tpl); P.period_index = stage2.I_P()
    res["malformed"]["null_period_index"] = asan.fk2_shl_schedule(C.byref(P), ca, n, C.byref(o), n, 1)
    P = copy_plan(tpl); P.t_close = stage2.D_P()
    res["malformed"]["null_template_row"] = asan.fk2_shl_schedule(C.byref(P), ca, n, C.byref(o), n, 1)
    o.crem = stage2.D_P()
    res["malformed"]["null_output_vector"] = asan.fk2_shl_schedule(C.byref(copy_plan(tpl)), ca, n, C.byref(o), n, 1)
print(json.dumps(res))
"""


def test_stage2_kernel_under_asan_ubsan(tmp_path):
    asan_lib, ubsan_lib = _sanitizer_libs()
    from financial_engine.native_v10 import build_stage2
    build_stage2.build(tmp_path, variant="asan")
    so = tmp_path / "_fk_v10_stage2_asan.so"
    env = dict(os.environ, PYTHONPATH=str(ROOT), LD_PRELOAD=f"{asan_lib}:{ubsan_lib}",
               ASAN_OPTIONS="detect_leaks=0:halt_on_error=1", UBSAN_OPTIONS="halt_on_error=1")
    proc = subprocess.run([sys.executable, "-c", STAGE2_SCRIPT, str(so), "2000"], capture_output=True, text=True,
                          cwd=str(ROOT), env=env, timeout=900)
    assert "ERROR: AddressSanitizer" not in proc.stderr and "runtime error" not in proc.stderr, proc.stderr[-3000:]
    assert proc.returncode == 0, proc.stderr[-3000:]
    res = json.loads(proc.stdout.strip().splitlines()[-1])
    assert res["cases"] > 1000 and res["equal"] == res["cases"], res
    assert len(res["malformed"]) == 16 and all(v in (5, 6) for v in res["malformed"].values()), res["malformed"]
