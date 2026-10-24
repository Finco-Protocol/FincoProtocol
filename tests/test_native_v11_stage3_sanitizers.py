"""ASan / UBSan on the V11 Stage 3 kernel, and allocation-failure injection.

The ASan/UBSan build of kernel_v11_stage3.c (``build_stage3 --variant asan``) is verified by the real
loader and serves, in a separate interpreter (LD_PRELOAD), complete Runs and perturbed senior-debt models:
every served result is pickle-identical to the canonical result. Malformed plans (ABI/size, null pointers,
empty axes, out-of-range indices, wrong output capacities) are rejected with INVALID_PLAN / ABI_MISMATCH,
and structure-aware mutations of real plans return a status, never a sanitizer diagnostic. (As in V10, the
element count of each input array is the count field of the plan the admission layer builds together
with the array; the kernel validates every index read from those arrays against those counts.)

The allocation-failure build (``--variant alloc``) fails the n-th allocation for every n: the evaluation
declines (FK3_NOMEM) or returns the identical result, never anything else.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests.native_v11_support import HERE

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.usefixtures("stage3_artifacts")

SCRIPT = r'''
import ctypes as C, json, pickle, random, sys
sys.path[:0] = [".", "tests"]
from pathlib import Path
from financial_engine.native_v11 import stage3
from financial_engine.native_v11.config import Stage3Config, stage3_run
lib_dir, manifest_name, n_fuzz = Path(sys.argv[1]), sys.argv[2], int(sys.argv[3])
native, why = stage3._verify(lib_dir, manifest_name)
assert native is not None, why
stage3._RESULT[(str(stage3.HERE), stage3.MANIFEST)] = (native, None)
alloc = hasattr(native.lib, "fk3_test_set_alloc_budget")
from app.api.project_runner import run_project
from app.services import production_financial_authority as pfa
import financial_engine.financing.project as proj
import tests.test_native_v11_stage3_fuzz as F
res = {"runs": 0, "runs_equal": 0, "cases": 0, "equal": 0, "malformed": {}, "mutations": 0, "nomem": 0, "alloc_equal": 0}
cap = []
real = proj._senior_debt_model
def spy(m, *, shl_maturity_context=None):
    if len(cap) < 60: cap.append(m)
    return real(m, shl_maturity_context=shl_maturity_context)
for project in ("Solar", "Generic Data Center Reference"):
    pfa._POLICY_RUN_CACHE.clear(); proj._senior_debt_model = spy
    ref = pickle.dumps(run_project(project, "Base"))
    proj._senior_debt_model = real
    if alloc:
        continue
    pfa._POLICY_RUN_CACHE.clear()
    with stage3_run(Stage3Config(mode="candidate")) as st:
        got = pickle.dumps(run_project(project, "Base"))
    res["runs"] += 1; res["runs_equal"] += int(got == ref and st.native_models > 0)
rng = random.Random(4242)
for k in range(n_fuzz):
    inputs = cap[k % len(cap)] if k < len(cap) else F._variant(rng, cap[rng.randrange(len(cap))])
    kind = "none" if inputs.shareholder_loan is None else rng.choice(["none", "provisional"])
    ref = F._canonical(inputs, kind)
    if alloc:
        budget = (k * 7) % 400 if k % 3 else 10 ** 7     # failing allocations and a sufficient budget
        native.lib.fk3_test_set_alloc_budget(budget)
        got = F._stage3(inputs, kind)
        native.lib.fk3_test_set_alloc_budget(-1)
        if got[0] == "decline" and any("STATUS_4" in r for r in got[3]["declines"]):
            res["nomem"] += 1; res["cases"] += 1; res["equal"] += 1; continue
    else:
        got = F._stage3(inputs, kind)
    res["cases"] += 1
    if got[0] == "ok":
        res["equal"] += int(ref[0] == "ok" and got[1] == ref[1] and got[2] == ref[2]); res["alloc_equal"] += int(alloc)
    elif got[0] == "decline":
        res["equal"] += int(got[2] == () and not any("STATUS_4" in r for r in got[3]["declines"]) or alloc)
    else:
        res["equal"] += int(ref[0] == "raise" and got[1] == ref[1])
# ---- malformed and mutated plans (plain path plan of a real model input)
import financial_engine.orchestrator as orch
inputs = next(m for m in cap if m.shareholder_loan is None)
bank = orch.run_operating_model(orch.derive_debt_sizing_operating_input(inputs.operating, inputs.debt_sizing_case))
pol = inputs.senior_debt_policy
debt_periods = tuple(p for p in bank.periods if p.is_operation and pol.repayment_start_period_index <= p.period_index <= pol.maturity_period_index)
def fresh():
    from financial_engine.tax import engine as te
    g = stage3._build_geometry(te._tax_plan_for(bank.periods), bank.periods)
    tp, tk = stage3._tax_policy(inputs.tax.policy, inputs.tax.opening_loss_vintages, g)
    ctx, ck = stage3._merge_source(inputs.tax, g, inputs.tax.policy)
    d = stage3._debt_geometry(pol, inputs.senior_debt_inputs, debt_periods, g)
    P = stage3._plan(False, g, None, tp, ctx, None, d)
    return P, (g, tk, ck, d)
def call(P, cap_n=None):
    n = P.debt.n_d if cap_n is None else cap_n
    bufs = [(C.c_double * max(1, n))() for _ in range(4)]
    return native.lib.fk3_plain(C.byref(P), C.byref(stage3.Stage3Out()), *bufs, n)
P, keep = fresh()
assert call(P) == 0
def mal(name, mutate, cap_n=None):
    P, keep = fresh(); mutate(P, keep); res["malformed"][name] = call(P, cap_n)
mal("abi", lambda P, k: setattr(P, "abi_version", 1))
mal("size", lambda P, k: setattr(P, "struct_size", 8))
mal("rows0", lambda P, k: setattr(P.bank, "n_rows", 0))
mal("years0", lambda P, k: setattr(P.bank, "n_years", 0))
mal("slots_big", lambda P, k: setattr(P.bank, "n_slots", P.bank.n_slots + 5))
mal("null_slot_pos", lambda P, k: setattr(P.bank, "slot_pos", stage3.I_P()))
mal("null_rates", lambda P, k: setattr(P.debt, "rates", stage3.D_P()))
mal("nd0", lambda P, k: setattr(P.debt, "n_d", 0))
mal("nd_big", lambda P, k: setattr(P.debt, "n_d", P.debt.n_d + 1))
mal("use_shl", lambda P, k: setattr(P, "use_shl", 2))
mal("mode", lambda P, k: setattr(P.debt, "mode", 9))
mal("cap", lambda P, k: None, cap_n=1)
mal("slot_pos_range", lambda P, k: k[0].keep["slot_pos"].__setitem__(0, 10**6))
mal("idx_to_sorted_range", lambda P, k: k[0].keep["idx_to_sorted"].__setitem__(0, 10**6))
mal("row_cand_mismatch", lambda P, k: k[3].keep["row_cand"].__setitem__(k[3].keep["d_row"][0], -1))
mal("in_rep", lambda P, k: k[3].keep["in_rep"].__setitem__(0, 7))
mal("kind", lambda P, k: k[0].keep["row_kind"].__setitem__(0, 9))
def _open_without_arrays(P, k):
    P.pol.n_open = 3; P.pol.open_last = stage3.I_P(); P.pol.open_amount = stage3.D_P()
mal("open_without_arrays", _open_without_arrays)
# structure-aware mutations of integer geometry entries: any status, no sanitizer report
mrng = random.Random(77)
for i in range(300):
    P, keep = fresh()
    g, d = keep[0], keep[3]
    arr_name, arr = mrng.choice([("slot_pos", g.keep["slot_pos"]), ("row_sorted", g.keep["row_sorted"]),
                                 ("idx_to_sorted", g.keep["idx_to_sorted"]), ("row_slot_count", g.keep["slot_count"]),
                                 ("payment_idx", g.keep["payment_idx"]), ("d_row", d.keep["d_row"]),
                                 ("row_cand", d.keep["row_cand"]), ("year_key", g.keep["year_key"])])
    j = mrng.randrange(len(arr))
    arr[j] = mrng.choice([-2, -1, 0, 1, 2**40, -(2**62), 2**62, arr[j] + 1, arr[j] - 1])
    call(P); res["mutations"] += 1
# full-tax entry: malformed capacities / pointers
from financial_engine.tax import engine as te
g = stage3._build_geometry(te._tax_plan_for(bank.periods), bank.periods)
tp, tk = stage3._tax_policy(inputs.tax.policy, inputs.tax.opening_loss_vintages, g)
z = stage3._darr([0.0] * g.n_rows)
Q = stage3.FullTaxPlan(abi_version=stage3.ABI, struct_size=C.sizeof(stage3.FullTaxPlan), geom=g.struct, pol=tp,
                       gross=z, nd=z, elig=z, reint=z, fin=z)
nd_, ni_ = 9 * (g.n_years + g.n_slots + g.n_rows) + 1, 2 * g.n_years + g.n_rows
od, oi = (C.c_double * nd_)(), (C.c_int64 * ni_)()
res["malformed"]["full_ok"] = native.lib.fk3_full_tax(C.byref(Q), od, nd_, oi, ni_)
res["malformed"]["full_cap_d"] = native.lib.fk3_full_tax(C.byref(Q), od, nd_ - 1, oi, ni_)
res["malformed"]["full_cap_i"] = native.lib.fk3_full_tax(C.byref(Q), od, nd_, oi, ni_ + 1)
Q.gross = stage3.D_P()
res["malformed"]["full_null"] = native.lib.fk3_full_tax(C.byref(Q), od, nd_, oi, ni_)
Q.gross = z; Q.struct_size = 3
res["malformed"]["full_size"] = native.lib.fk3_full_tax(C.byref(Q), od, nd_, oi, ni_)
print(json.dumps(res))
'''


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


def _variant_dir(tmp_path, variant):
    from financial_engine.native_v11 import build_stage3
    shutil.copy(HERE / "approved_canonical_blobs_stage3.json", tmp_path / "approved_canonical_blobs_stage3.json")
    build_stage3.build(tmp_path, variant=variant)
    return tmp_path, f"fk_v11_stage3_manifest_{variant}.json"


def _run(env_extra, lib_dir, manifest, n):
    env = dict(os.environ, PYTHONPATH=str(ROOT), **env_extra)
    proc = subprocess.run([sys.executable, "-c", SCRIPT, str(lib_dir), manifest, str(n)], capture_output=True,
                          text=True, cwd=str(ROOT), env=env, timeout=1800)
    assert "ERROR: AddressSanitizer" not in proc.stderr and "runtime error" not in proc.stderr, proc.stderr[-3000:]
    assert proc.returncode == 0, proc.stderr[-3000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_stage3_kernel_under_asan_ubsan(tmp_path):
    asan_lib, ubsan_lib = _sanitizer_libs()
    lib_dir, manifest = _variant_dir(tmp_path, "asan")
    res = _run({"LD_PRELOAD": f"{asan_lib}:{ubsan_lib}", "ASAN_OPTIONS": "detect_leaks=0:halt_on_error=1",
                "UBSAN_OPTIONS": "halt_on_error=1"}, lib_dir, manifest, 160)
    assert res["runs"] == 2 and res["runs_equal"] == 2, res
    assert res["cases"] == 160 and res["equal"] == res["cases"], res
    assert res["mutations"] == 300
    m = res["malformed"]
    assert m.pop("full_ok") == 0
    assert all(v in (5, 6) for v in m.values()), json.dumps(m)


def test_stage3_allocation_failure_injection(tmp_path):
    lib_dir, manifest = _variant_dir(tmp_path, "alloc")
    res = _run({}, lib_dir, manifest, 120)
    assert res["cases"] == 120 and res["equal"] == res["cases"], res
    assert res["nomem"] > 0 and res["alloc_equal"] > 0, res
