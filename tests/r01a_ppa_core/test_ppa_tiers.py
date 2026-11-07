from decimal import Decimal as D
from fractions import Fraction as F
import dataclasses
import pathlib
import re
import subprocess

import pytest

from revenue_reference_core import compute_ppa_tiers, PpaTierInput, Quantity, ContractError, STATUS, PROVENANCE
from tests.r01a_ppa_core import oracle

ROOT = pathlib.Path(__file__).resolve().parents[2]


def mk(sem="CUMULATIVE_LIFETIME_CEILING", gen=(100, 100, 100), cap1="0.15", cap2="0.25", **kw):
    if "cap_semantics" in kw:
        sem = kw.pop("cap_semantics")
    q1 = cap1 if isinstance(cap1, Quantity) else Quantity(D(cap1), "GWh")
    q2 = cap2 if isinstance(cap2, Quantity) else Quantity(D(cap2), "GWh")
    years = tuple(range(2030, 2030 + len(gen)))
    base = dict(cap_semantics=sem, generation=tuple((y, D(g)) for y, g in zip(years, gen)), generation_unit="MWh",
                cap1=q1, cap2=q2, base_price_eur_mwh=D(60),
                reduced_price_eur_mwh=D(40), merchant_price_eur_mwh=tuple((y, D(30)) for y in years),
                ppa_start_year=years[0], ppa_end_year=years[-1])
    base.update(kw)
    return PpaTierInput(**base)


def vols(res):
    return [(r.base.mwh, r.reduced.mwh, r.merchant.mwh) for r in res]


def test_prompt_example_cumulative_hand_values():
    res = compute_ppa_tiers(mk())
    assert vols(res) == [(D(100), 0, 0), (D(50), D(50), 0), (0, D(50), D(50))]
    assert [r.revenue_eur for r in res] == [D(6000), D(5000), D(3500)]       # 100*60 ; 50*60+50*40 ; 50*40+50*30
    assert [r.revenue_keur for r in res] == [D(6), D(5), D("3.5")]
    assert all(r.revenue_eur == r.base.revenue_eur + r.reduced.revenue_eur + r.merchant.revenue_eur for r in res)


def test_annual_vs_lifetime_distinction_hand_values():
    ann = compute_ppa_tiers(mk("ANNUAL_CEILING", cap1="0.06", cap2="0.09"))
    assert vols(ann) == [(D(60), D(30), D(10))] * 3
    life = compute_ppa_tiers(mk("CUMULATIVE_LIFETIME_CEILING", cap1="0.06", cap2="0.09"))
    assert vols(life) == [(D(60), D(30), D(10)), (0, 0, D(100)), (0, 0, D(100))]


def test_ceiling_vs_incremental_tranche_distinction():
    ceil = compute_ppa_tiers(mk("CUMULATIVE_LIFETIME_CEILING", cap1="0.15", cap2="0.25"))
    inc = compute_ppa_tiers(mk("CUMULATIVE_LIFETIME_INCREMENTAL", cap1="0.15", cap2="0.25"))      # tier2 = further 250 MWh
    assert vols(inc) == [(D(100), 0, 0), (D(50), D(50), 0), (0, D(100), 0)] and vols(ceil) != vols(inc)
    ann = compute_ppa_tiers(mk("ANNUAL_INCREMENTAL", cap1="0.04", cap2="0.03"))
    assert vols(ann) == [(D(40), D(30), D(30))] * 3


def test_exact_boundary_zero_generation_and_ppa_expiry():
    res = compute_ppa_tiers(mk(gen=(150, 0, 100, 100), cap1="0.15", cap2="0.25", ppa_end_year=2032))
    assert vols(res) == [(D(150), 0, 0), (0, 0, 0), (0, D(100), 0), (0, 0, D(100))]
    assert res[3].revenue_eur == D(3000) and res[1].revenue_eur == 0
    pre = compute_ppa_tiers(mk(ppa_start_year=2031))                    # year 1 is merchant and does NOT consume cap
    assert vols(pre) == [(0, 0, D(100)), (D(100), 0, 0), (D(50), D(50), 0)]


def test_indexation_no_double_counting_and_merchant_unindexed():
    res = compute_ppa_tiers(mk(index_base_year=2030, index_rate=D("0.10"), indexed_fraction=D("0.5")))
    # factor_y = 0.5 + 0.5*1.1^(y-2030)
    assert res[0].base.price_eur_mwh == D(60)
    assert res[1].base.price_eur_mwh == D(60) * D("1.05") and res[1].reduced.price_eur_mwh == D(40) * D("1.05")
    assert res[2].reduced.price_eur_mwh == D(40) * D("1.105")
    assert all(r.merchant.price_eur_mwh == D(30) for r in res)
    fixed = compute_ppa_tiers(mk(index_base_year=2030, index_rate=D("0.10"), indexed_fraction=D(0)))
    assert fixed[2].base.price_eur_mwh == D(60)


@pytest.mark.parametrize("sem", ["CUMULATIVE_LIFETIME_CEILING", "ANNUAL_CEILING", "CUMULATIVE_LIFETIME_INCREMENTAL", "ANNUAL_INCREMENTAL"])
@pytest.mark.parametrize("gen", [(100, 100, 100), (0, 7, 250, 3), (49, 51, 100, 1, 99)])
@pytest.mark.parametrize("start,end", [(2030, 2040), (2031, 2032), (2029, 2029)])
def test_matches_independent_brute_force_oracle(sem, gen, start, end):
    inp = mk(sem, gen, cap1="0.06", cap2="0.14", ppa_start_year=start, ppa_end_year=end, index_base_year=2029,
             index_rate=D("0.03"), indexed_fraction=D("0.4"))
    res = compute_ppa_tiers(inp)
    years = [r.year for r in res]
    # caps in MWh: cap1=60, cap2=140 (ceiling: absolute ceiling; incremental: tranche size)
    exp = oracle.brute(sem, years, list(gen), 60, 140, F(60), F(40), {y: F(30) for y in years}, start, end, 2029, F(3, 100), F(2, 5))
    for r in res:
        b, rd, m, eur = exp[r.year]
        assert (r.base.mwh, r.reduced.mwh, r.merchant.mwh) == (D(b), D(rd), D(m))
        assert abs(F(r.revenue_eur) - eur) <= F(3, 2_000_000)           # three components, each rounded half-even to 1e-6
        assert r.base.mwh + r.reduced.mwh + r.merchant.mwh == r.generation_mwh


def test_oracle_arg_order_is_the_documented_one():
    # (sem, years, gen, cap1, cap2, base, red, merch, start, end, idx_base, rate, frac)
    assert oracle.brute("CUMULATIVE_LIFETIME_CEILING", [1, 2], [10, 10], 15, 25, F(60), F(40), {1: F(30), 2: F(30)}, 1, 2)[2][3] == 5 * 60 + 5 * 40


def test_provenance_determinism_and_no_state_leak():
    a, b = compute_ppa_tiers(mk()), compute_ppa_tiers(mk())
    assert a == b
    compute_ppa_tiers(mk("ANNUAL_CEILING", cap1="0.06", cap2="0.09"))
    assert compute_ppa_tiers(mk()) == a
    assert (STATUS, PROVENANCE) == ("SEMANTICS_UNVERIFIED", "SYNTHETIC_ORACLE_ONLY")
    with pytest.raises(dataclasses.FrozenInstanceError):
        a[0].year = 1


def test_gwh_generation_unit_maps_to_mwh_and_keur():
    inp = mk(gen=(D("0.1"),) * 3, generation_unit="GWh")
    assert compute_ppa_tiers(inp)[0].base.mwh == D(100) and compute_ppa_tiers(inp)[0].revenue_keur == D(6)


@pytest.mark.parametrize("bad", [
    dict(cap_semantics=None), dict(cap_semantics=""), dict(cap_semantics="ROLLING_12M"), dict(cap_semantics="annual_ceiling"),
    dict(cap1=Quantity(D("0.25"), "GWh"), cap2=Quantity(D("0.15"), "GWh")),           # not ascending
    dict(cap1=Quantity(D("0.15"), "GWh"), cap2=Quantity(D("0.15"), "GWh")),
    dict(cap1=Quantity(D("-1"), "GWh")), dict(cap1=Quantity(D("0"), "GWh")),
    dict(cap1=Quantity(D("150"), "MWh"), cap2=Quantity(D("0.25"), "GWh")),            # mixed units
    dict(cap1=Quantity(D("0.15"), "kWh")), dict(cap1=Quantity(0.15, "GWh")),
    dict(cap1=Quantity(D("NaN"), "GWh")), dict(cap1=Quantity(D("Infinity"), "GWh")),
    dict(base_price_eur_mwh=D(-1)), dict(reduced_price_eur_mwh=D("NaN")), dict(base_price_eur_mwh=60.0),
    dict(merchant_price_eur_mwh=((2030, D(30)), (2031, D(30)))),                      # price unavailable for 2032
    dict(merchant_price_eur_mwh=((2030, D(30)), (2031, D(-1)), (2032, D(30)))),
    dict(generation=((2030, D(1)), (2030, D(1)))), dict(generation=((2031, D(1)), (2030, D(1)))),
    dict(generation=((2030, D(1)), (2032, D(1)))), dict(generation=((2030, D(-1)),)), dict(generation=()),
    dict(generation=((2030, 1.0),)), dict(generation_unit="kWh"),
    dict(ppa_start_year=2035, ppa_end_year=2031),
    dict(indexed_fraction=D("1.5"), index_base_year=2030), dict(indexed_fraction=D("0.5")),                 # no base year
    dict(indexed_fraction=D("0.5"), index_base_year=2031), dict(indexed_fraction=D("0.5"), index_base_year=2030, index_rate=D(-1)),
])
def test_fail_closed(bad):
    with pytest.raises(ContractError):
        compute_ppa_tiers(mk(**bad))


def test_default_semantics_does_not_exist():
    with pytest.raises(TypeError):
        PpaTierInput(generation=(), generation_unit="MWh")           # cap_semantics has no default
    assert "default" not in PpaTierInput.__dataclass_fields__["cap_semantics"].metadata


def test_package_is_isolated_and_existing_engine_is_untouched():
    pkg = ROOT / "revenue_reference_core"
    for f in pkg.glob("*.py"):
        assert not re.search(r"^\s*(from|import)\s+(financial_engine|app|finco_core|domain|main_|tools)", f.read_text(), re.M)
    hits = subprocess.run(["grep", "-rl", "--include=*.py", "--include=*.ts", "--include=*.tsx", "revenue_reference_core",
                           "app", "financial_engine", "finco_core", "domain", "frontend/src", "main_web.py", "main_api.py"],
                          cwd=ROOT, capture_output=True, text=True).stdout
    assert hits.strip() == ""                                         # nothing existing imports the candidate
