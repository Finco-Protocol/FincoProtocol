"""V10 Stage 2 (experimental native SHL operating schedule; ``stage2_experimental=False`` by default).

* default off inside a Stage 1 candidate Run; enabled only by its own flag;
* full-Run identity when enabled;
* a replaced canonical SHL region (fault-injected helper) declines every call, canonical decides;
* missing / corrupt Stage 2 artifact declines while Stage 1 keeps serving, result unchanged;
* deterministic differential fuzz (fixed seed) over real (periods, SHL input) pairs from canonical Runs:
  every native result is bit-identical (incl. the maturity-shortfall ledger) and every decline coincides
  with a canonical raise; native never succeeds where canonical raises.
"""
from __future__ import annotations

import dataclasses as dc
import json
import os
import random
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import financial_engine.shl.production as P
from financial_engine.native_v10.config import native_run
from financial_engine.run_scope import engine_run_scope
from tests.native_v10_support import HERE, OFF, STAGE1, STAGE2, outcome_key, run_case

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.usefixtures("native_artifacts")
FUZZ_CASES, FUZZ_SEED = 1500, 20261022


@pytest.fixture(scope="module")
def solar_off():
    return run_case("reference-solar", "canonical", OFF)


def test_stage2_is_off_in_a_stage1_candidate_run_and_identical_when_enabled(solar_off):
    stage1 = run_case("reference-solar", "canonical", STAGE1)
    assert outcome_key(stage1) == outcome_key(solar_off)
    assert stage1["native"]["stage2_native_calls"] == 0 and stage1["native"]["native_solves"] > 0
    enabled = run_case("reference-solar", "canonical", STAGE2)
    assert outcome_key(enabled) == outcome_key(solar_off)
    assert enabled["native"]["stage2_native_calls"] > 0
    assert not enabled["native"]["declines"]


@pytest.mark.parametrize("persistent", [False, True])
def test_replaced_canonical_shl_region_declines_and_canonical_decides(monkeypatch, persistent):
    real, calls = P.compute_shl_waterfall_period, {"n": 0}

    def faulty(*a, **k):
        calls["n"] += 1
        if calls["n"] == 7 or (persistent and calls["n"] >= 7):
            raise RuntimeError("INJECTED_SHL_HELPER_FAULT_7")
        return real(*a, **k)

    monkeypatch.setattr(P, "compute_shl_waterfall_period", faulty)
    calls["n"] = 0
    canonical = run_case("reference-solar", "canonical", OFF)
    canonical_calls, calls["n"] = calls["n"], 0
    candidate = run_case("reference-solar", "canonical", STAGE2)
    assert (candidate["verdict"], candidate["error"]) == (canonical["verdict"], canonical["error"])
    assert outcome_key(candidate) == outcome_key(canonical)
    assert calls["n"] == canonical_calls
    assert candidate["native"]["stage2_native_calls"] == 0
    assert any(k.startswith("STAGE2:CANONICAL_REGION_REPLACED") for k in candidate["native"]["declines"])


@pytest.mark.parametrize("damage", ["missing", "corrupt"])
def test_missing_or_corrupt_stage2_artifact_declines_with_identical_result(tmp_path, solar_off, damage):
    for f in HERE.iterdir():
        if f.is_file():
            shutil.copy(f, tmp_path / f.name)
    so = tmp_path / "_fk_v10_stage2.so"
    if damage == "missing":
        so.unlink()
    else:
        data = bytearray(so.read_bytes())
        data[2000] ^= 0xFF
        so.write_bytes(bytes(data))
    code = (
        "import json, pathlib\n"
        "from financial_engine.native_v10 import stage2\n"
        f"stage2.HERE = pathlib.Path({str(tmp_path)!r})\n"
        "from tests.native_v10_support import STAGE2, run_case\n"
        "print(json.dumps(run_case('reference-solar', 'canonical', STAGE2)))\n")
    env = dict(os.environ, PYTHONPATH=str(ROOT))
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=str(ROOT), env=env,
                          timeout=900)
    assert proc.returncode == 0, proc.stderr[-2000:]
    run = json.loads(proc.stdout.strip().splitlines()[-1])
    assert outcome_key(run) == outcome_key(solar_off)
    assert run["native"]["native_solves"] > 0 and run["native"]["stage2_native_calls"] == 0
    expected = "LOADER2_ARTIFACT_UNAVAILABLE" if damage == "missing" else "LOADER2_ARTIFACT_SHA256_MISMATCH"
    assert any(expected in k for k in run["native"]["declines"]), run["native"]["declines"]


# ------------------------------------------------------------------ deterministic differential fuzz
def _capture_shl_corpus():
    from tests.native_v10_support import acceptance, entries
    from app.services import production_financial_authority as pfa

    acc, pairs, real = acceptance(), {}, P.compute_shareholder_loan_schedules

    def probe(periods, shl_input, cash, **kw):
        key = (id(periods), id(shl_input))
        if key not in pairs and len(pairs) < 400:
            pairs[key] = (periods, shl_input, tuple(cash))
        return real(periods, shl_input, cash, **kw)

    catalogue = entries()
    P.compute_shareholder_loan_schedules = probe
    try:
        for name in ("reference-solar", "reference-wind", "P8-W25-bullet", "P8-S16-bullet"):
            f, v, b = catalogue[name]
            pfa._POLICY_RUN_CACHE.clear()
            try:
                pfa.run_clean_production(f(), project_type=v, financing_policy=acc.policy_for("canonical", b))
            except Exception:  # noqa: BLE001 - a rejected case still contributes its SHL calls
                pass
    finally:
        P.compute_shareholder_loan_schedules = real
        pfa._POLICY_RUN_CACHE.clear()
    seen, keep = set(), []
    for periods, shl_input, cash in pairs.values():
        k = (repr(shl_input), len(periods))
        if k not in seen:
            seen.add(k)
            keep.append((periods, shl_input, cash))
    return keep


def _canonical(periods, shl_input, cash, enforce, ctx):
    try:
        return "RETURN", P.compute_shareholder_loan_schedules(periods, shl_input, cash, diagnostics=None,
                                                              enforce_maturity_residual=enforce, maturity_context=ctx)
    except Exception as exc:  # noqa: BLE001
        return "RAISE", f"{type(exc).__name__}: {exc}"


def _bits(result):
    return [tuple(x.hex() if isinstance(x, float) else x for x in getattr(result, f.name))
            for f in dc.fields(result) if f.name != "diagnostics"]


def _ledger(ctx):
    return [tuple(x.hex() if isinstance(x, float) else x for x in dc.astuple(s)) for s in ctx.ledger.shortfalls]


def test_stage2_differential_fuzz_is_bit_identical_and_never_succeeds_where_canonical_raises():
    from financial_engine.native_v10 import stage2
    from financial_engine.shl.contracts import ShlRepaymentMode
    from financial_engine.shl.maturity_authority import ShlMaturityContext

    corpus = _capture_shl_corpus()
    assert len(corpus) >= 20
    rnd = random.Random(FUZZ_SEED)
    specials = [0.0, -0.0, 5e-324, 1e-300, 1.0, 1e6, 1e300, 1.7e308]
    bad = [-1.0, -5e-324, float("nan"), float("inf"), float("-inf")]
    counts = dict(cases=0, identical=0, decline_canonical_raise=0, decline_canonical_return=0, mismatch=0,
                  native_ok_canonical_raises=0, ledger_mismatch=0)
    for _ in range(FUZZ_CASES):
        periods, shl_input, cash0 = rnd.choice(corpus)
        idxs = [p.period_index for p in periods]
        changes = {}
        if rnd.random() < 0.5:
            changes["repayment_mode"] = rnd.choice([ShlRepaymentMode.BULLET, ShlRepaymentMode.CASH_SWEEP])
        if rnd.random() < 0.3:
            changes["annual_fixed_rate"] = rnd.choice([0.0, 0.05, 0.12, 1e-12, 3.0, 1e200])
        if rnd.random() < 0.3:
            rs = rnd.choice(idxs + [max(idxs) + 7])
            changes["repayment_start_period_index"] = rs
            changes["maturity_period_index"] = rnd.choice([i for i in idxs if i >= rs] or [rs])
        if rnd.random() < 0.2:
            changes["convergence_tolerance_keur"] = rnd.choice([0.0, 1e-6, 1e-3, 10.0])
        if rnd.random() < 0.2:
            changes["initial_principal_keur"] = rnd.choice([1e-9, 1.0, 5e4, 1e12])
        try:
            si = dc.replace(shl_input, **changes)
        except Exception:  # noqa: BLE001 - invalid combination: not a kernel question
            continue
        roll = rnd.random()
        if roll < 0.4:
            cash = list(cash0)
        elif roll < 0.7:
            cash = [rnd.choice([c, c * rnd.uniform(0, 2), rnd.choice(specials)]) for c in cash0]
        else:
            cash = [abs(rnd.uniform(-1, 1)) * rnd.choice([1.0, 1e3, 1e5]) for _ in cash0]
        if rnd.random() < 0.08:
            cash[rnd.randrange(len(cash))] = rnd.choice(bad)
        cash = tuple(float(c) for c in cash) if rnd.random() < 0.7 else [float(c) for c in cash]
        enforce, prov = rnd.random() < 0.5, rnd.random() < 0.5
        ctx_c = ShlMaturityContext.provisional_pass() if (enforce and prov) else None
        ctx_n = ShlMaturityContext.provisional_pass() if (enforce and prov) else None
        counts["cases"] += 1
        can = _canonical(periods, si, cash, enforce, ctx_c)
        with engine_run_scope(), native_run(STAGE2):
            nat = stage2.shl_schedules(periods, si, cash, diagnostics=None, enforce_maturity_residual=enforce,
                                       maturity_context=ctx_n)
        if nat is None:
            counts["decline_canonical_raise" if can[0] == "RAISE" else "decline_canonical_return"] += 1
            continue
        if can[0] == "RAISE":
            counts["native_ok_canonical_raises"] += 1
            continue
        counts["identical" if _bits(nat) == _bits(can[1]) else "mismatch"] += 1
        if ctx_c is not None and _ledger(ctx_c) != _ledger(ctx_n):
            counts["ledger_mismatch"] += 1
    assert counts["mismatch"] == counts["native_ok_canonical_raises"] == counts["ledger_mismatch"] == 0, counts
    assert counts["identical"] > counts["cases"] // 2, counts          # the fuzz really exercises the kernel
    assert counts["decline_canonical_raise"] > 0, counts              # and the decline-on-raise path
