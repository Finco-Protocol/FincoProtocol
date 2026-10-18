"""RC-7 B2/B3 evidence: the monthly construction bridge on the REAL canonical engine (nothing persisted here).

The bridge (``app.capex_profiles.binding``) expands the construction input the Run already derives onto a month grid and applies
user monthly profiles.  The unchanged canonical Stage B2 / allocator / IDC path then computes uses, draws, commitment fees,
capitalised IDC and total uses.  These tests prove, on real Solar and Wind projects, that:
  * cash dates and totals of un-profiled CAPEX are preserved (date-preserving contract);
  * monthly hard-CAPEX uses equal an independent exact oracle (contract.allocate) month by month;
  * Sources = Uses, Senior draws never exceed the commitment, hard CAPEX is timing-independent;
  * every total-uses movement is attributable to financing costs (IDC + commitment fee + fees) and IDC follows draw dates.
"""
from __future__ import annotations

import dataclasses
from datetime import date
from decimal import Decimal
from fractions import Fraction

import pytest
from dateutil.relativedelta import relativedelta

from app.capex_profiles.binding import BindingUnsupported, Leaf, bind, month_grid
from app.capex_profiles.contract import ProfileError, ProfileShape as S, ProfileSpec, allocate
from financial_engine.financing.generic_product_policy import (
    GenericFinancingPolicy, derive_construction_financing, run_with_generic_financing_policy,
)
from financial_engine.run_scope import engine_run_scope
from financial_engine.shareholder_waterfall import run_project_shareholder_waterfall_model

CODES = ("production_units", "epc_other", "grid_connection", "audit_legal")
FAST = GenericFinancingPolicy(apply_construction_financing=True, apply_cash_dsra=False)   # one engine pass; identities hold under any policy
FC = date(2030, 1, 1)


@pytest.fixture(scope="module")
def projects(tmp_path_factory):
    from app.persistence import db
    original = db.DB_PATH
    db.DB_PATH = str(tmp_path_factory.mktemp("rc7") / "rc7.db")
    db.init_db()
    from app.persistence.workspace_repository import get_workspace_state
    from app.services.reference_seed_service import create_reference_seeded_project
    snaps = {}
    for template in ("generic_solar_reference", "generic_wind_reference"):
        record = create_reference_seeded_project(user_id="rc7-user", requested_name=template, template_source=template,
                                                  capacity_mw=25 if "wind" in template else 16)
        snaps[template] = dict(get_workspace_state("rc7-user", record.project_id).draft_snapshot)
    yield snaps
    db.DB_PATH = original


def _inputs(snaps, template, months):
    from app.input_adapter import build_projectinputs_from_snapshot
    snap = dict(snaps[template])
    if template == "generic_wind_reference" and months == int(snap["construction_months"]):
        return build_projectinputs_from_snapshot(snap)                      # the Wind reference's own native duration, untouched
    snap["construction_months"] = str(months)
    snap["cod_date"] = (FC + relativedelta(months=months)).isoformat()
    if months <= 12:      # the existing generic SHL maturity (+2 periods after Senior payoff) needs one more horizon year to stay on the grid
        snap["horizon_years"] = str(int(float(snap["horizon_years"])) + 1)
    return build_projectinputs_from_snapshot(snap)


def _amounts(pi):
    return {c: getattr(pi.capex, c).amount_keur for c in CODES}


def _run(pi, construction, policy=FAST):
    pi = dataclasses.replace(pi, financing=dataclasses.replace(pi.financing, construction_financing=construction))
    with engine_run_scope():
        g2c, _eff, _ev = run_with_generic_financing_policy(
            pi, lambda a: run_project_shareholder_waterfall_model(a, source_id="rc7_binding"), policy)
    return g2c.financing_result


def _leaves(pi, shapes: dict, **extra):
    amounts = _amounts(pi)
    return [Leaf(c, c, amounts[c], ProfileSpec(c, shapes[c], **extra.get(c, {})) if c in shapes else None) for c in CODES]


def _bound(pi, shapes, months, **extra):
    cfi = derive_construction_financing(pi)
    return bind(cfi, construction_months=months, category_amounts_keur=_amounts(pi), leaves=_leaves(pi, shapes, **extra))


def _financing_costs(f):
    c = f.construction_financing
    return (sum(c.senior_idc_capitalized_uses_keur) + c.senior_commitment_fee_capitalized_keur + sum(c.structuring_fee_keur)
            + c.vat_idc_keur + c.vat_commitment_fee_keur)


# ──────────────────────────── pure bridge (no engine) ────────────────────────────

@pytest.mark.parametrize("months", [12, 13, 14, 18, 24])
def test_monthly_baseline_is_date_preserving_for_regular_and_irregular_durations(projects, months):
    pi = _inputs(projects, "generic_solar_reference", months)
    cfi = derive_construction_financing(pi)
    grid = month_grid(cfi, months)
    assert len(grid.starts) == months and grid.starts[0] == FC and grid.ends[-1] == cfi.periods[-1].end_date
    for k in range(1, months):
        assert grid.starts[k] == grid.ends[k - 1] + relativedelta(days=1)          # contiguous, no gap or overlap
    bound = bind(cfi, construction_months=months, category_amounts_keur=_amounts(pi))
    assert len(bound.construction.periods) == months
    for item, original in zip(bound.construction.capex_items, cfi.capex_items):
        assert sum(item.payment_weights) == pytest.approx(1.0, abs=1e-12)
        for p, w in enumerate(original.payment_weights):                            # the semester weight sits on the period's last month
            assert item.payment_weights[grid.period_last_month[p]] == pytest.approx(w, abs=1e-12)
        assert sum(1 for w in item.payment_weights if w) <= sum(1 for w in original.payment_weights if w)
    fee = bound.construction.structuring_fee.payment_weights
    assert sum(fee) == pytest.approx(1.0) and fee[grid.period_last_month[0]] == pytest.approx(1.0)
    # period flags and every other contract field are carried unchanged
    for k, month in enumerate(bound.construction.periods):
        assert month.active_construction == cfi.periods[grid.month_to_period[k]].active_construction
    assert bound.construction.senior_pricing == cfi.senior_pricing and bound.construction.commitment_fee == cfi.commitment_fee


def test_category_timing_is_the_exact_amount_weighted_blend_of_its_leaves(projects):
    pi = _inputs(projects, "generic_solar_reference", 14)
    cfi = derive_construction_financing(pi)
    amounts = _amounts(pi)
    a = amounts["production_units"]
    split = 0.3 * a
    leaves = [Leaf("A", "production_units", split, ProfileSpec("A", S.FRONT_LOADED)),
              Leaf("B", "production_units", a - split, ProfileSpec("B", S.MILESTONE, milestone_month=14))]
    bound = bind(cfi, construction_months=14, category_amounts_keur=amounts, leaves=leaves)
    weights = next(i for i in bound.construction.capex_items if i.code == "production_units").payment_weights
    front = [Fraction(2 * (14 - k), 14 * 15) for k in range(14)]
    expected = [(Fraction(split) * front[k] + Fraction(a - split) * (1 if k == 13 else 0)) / Fraction(a) for k in range(14)]
    assert sum(weights) == pytest.approx(1.0, abs=1e-12)
    assert all(w == pytest.approx(float(e), abs=1e-12) for w, e in zip(weights, expected))
    assert next(i for i in bound.construction.capex_items if i.code == "epc_other").payment_weights == \
        bind(cfi, construction_months=14, category_amounts_keur=amounts).construction.capex_items[1].payment_weights   # untouched category


def test_partly_profiled_category_keeps_default_timing_for_the_rest(projects):
    pi = _inputs(projects, "generic_solar_reference", 14)
    cfi = derive_construction_financing(pi)
    amounts = _amounts(pi)
    a = amounts["epc_other"]
    leaves = [Leaf("A", "epc_other", 0.25 * a, ProfileSpec("A", S.UNIFORM)), Leaf("B", "epc_other", 0.75 * a)]
    weights = next(i for i in bind(cfi, construction_months=14, category_amounts_keur=amounts, leaves=leaves).construction.capex_items
                   if i.code == "epc_other").payment_weights
    base = next(i for i in bind(cfi, construction_months=14, category_amounts_keur=amounts).construction.capex_items
                if i.code == "epc_other").payment_weights
    assert all(w == pytest.approx(0.25 / 14 + 0.75 * b, abs=1e-12) for w, b in zip(weights, base))


def test_unsupported_inputs_are_refused_not_approximated(projects):
    pi = _inputs(projects, "generic_solar_reference", 14)
    cfi = derive_construction_financing(pi)
    amounts = _amounts(pi)
    ok = [Leaf(c, c, amounts[c]) for c in CODES]

    def refused(code, construction=cfi, months=14, amts=amounts, leaves=ok):
        with pytest.raises(BindingUnsupported) as exc:
            bind(construction, construction_months=months, category_amounts_keur=amts, leaves=leaves)
        assert exc.value.code == code

    refused("CAPEX_BINDING_AXIS_MISALIGNED", months=15)                                   # duration differs from the financial-close axis
    shifted = dataclasses.replace(cfi, periods=(dataclasses.replace(cfi.periods[0], start_date=date(2030, 1, 15)),) + cfi.periods[1:])
    refused("CAPEX_BINDING_AXIS_MISALIGNED", construction=shifted)                          # month grid crosses a period boundary
    refused("CAPEX_BINDING_AMOUNT_MISMATCH", leaves=[Leaf("x", "epc_other", 1.0, ProfileSpec("x", S.UNIFORM))])
    refused("CAPEX_BINDING_CATEGORY_NOT_IN_CONSTRUCTION",
            leaves=ok + [Leaf("z", "contingencies", 10.0, ProfileSpec("z", S.UNIFORM))], amts={**amounts, "contingencies": 10.0})
    with pytest.raises(ProfileError) as dup:
        bind(cfi, construction_months=14, category_amounts_keur=amounts,
             leaves=[Leaf("epc_other", "epc_other", amounts["epc_other"], ProfileSpec("epc_other", S.UNIFORM)),
                     Leaf("epc_other", "epc_other", 0.0, ProfileSpec("epc_other", S.UNIFORM))])
    assert dup.value.code == "CAPEX_PROFILE_DUPLICATE_ITEM"
    for bad, code in ((("50", "40"), "CAPEX_PROFILE_PERIOD_COUNT_MISMATCH"), (tuple(["8"] * 14), "CAPEX_PROFILE_WEIGHT_SUM_INVALID"),
                      (tuple(["-1"] + ["8"] * 13), "CAPEX_PROFILE_WEIGHT_NEGATIVE")):
        with pytest.raises(ProfileError) as exc:
            bind(cfi, construction_months=14, category_amounts_keur=amounts,
                 leaves=[Leaf("epc_other", "epc_other", amounts["epc_other"], ProfileSpec("epc_other", S.EXPLICIT, explicit_percent=bad))])
        assert exc.value.code == code
    from finco_core.inputs.construction_financing import ConstructionVatFacilityInput
    vat = dataclasses.replace(cfi, vat_facility=ConstructionVatFacilityInput(
        enabled=True, periods=cfi.periods, reimbursement_lag_periods=0, financing_cost_payment_weights=(1.0, 0.0, 0.0)))
    refused("CAPEX_BINDING_VAT_FACILITY_UNSUPPORTED", construction=vat)
    from finco_core.inputs.construction_financing import ConstructionSeniorPricingInput
    from finco_core.inputs.senior_rate_schedule import SeniorRateMode
    floating = dataclasses.replace(cfi, senior_pricing=ConstructionSeniorPricingInput(
        mode=SeniorRateMode.FLOATING_PLUS_MARGIN, margin_rate=0.02, floating_base_rate_curve=(0.03,) * 3))
    refused("CAPEX_BINDING_PERIOD_PRICING_UNSUPPORTED", construction=floating)
    refused("CAPEX_BINDING_CONSTRUCTION_DISABLED", construction=dataclasses.replace(cfi, enabled=False))


# ─────────────────────── real canonical engine: 14-month Solar ───────────────────────

SHAPES = {
    "base": {},
    "front": {c: S.FRONT_LOADED for c in CODES},
    "back": {c: S.BACK_LOADED for c in CODES},
    "milestone": {c: S.MILESTONE for c in CODES},
    "mixed": {"production_units": S.FRONT_LOADED, "epc_other": S.BACK_LOADED},
}
MILESTONE = {c: {"milestone_month": 3} for c in CODES}


@pytest.fixture(scope="module")
def solar14(projects):
    pi = _inputs(projects, "generic_solar_reference", 14)
    out = {"pi": pi}
    for name, shapes in SHAPES.items():
        bound = _bound(pi, shapes, 14, **(MILESTONE if name == "milestone" else {}))
        out[name] = (bound, _run(pi, bound.construction))
    return out


def _oracle_hard_uses(pi, bound, shapes, months, **extra):
    """Independent month-by-month hard CAPEX: exact Decimal allocation for profiled categories, existing timing for the rest."""
    amounts = _amounts(pi)
    cfi = derive_construction_financing(pi)
    grid = month_grid(cfi, months)
    uses = [Decimal(0)] * months
    for item in cfi.capex_items:
        if item.code in shapes:
            for row in allocate(ProfileSpec(item.code, shapes[item.code], **extra.get(item.code, {})), amounts[item.code], months).months:
                uses[row.month - 1] += row.amount_keur
        else:
            for p, w in enumerate(item.payment_weights):
                uses[grid.period_last_month[p]] += Decimal(str(amounts[item.code])) * Decimal(str(w))
    return [float(u) for u in uses]


@pytest.mark.parametrize("name", list(SHAPES))
def test_monthly_uses_equal_the_independent_oracle_and_conserve_hard_capex(solar14, name):
    bound, f = solar14[name]
    expected = _oracle_hard_uses(solar14["pi"], bound, SHAPES[name], 14, **(MILESTONE if name == "milestone" else {}))
    assert len(f.construction_financing.hard_capex_uses_keur) == 14
    for k, (got, want) in enumerate(zip(f.construction_financing.hard_capex_uses_keur, expected)):
        assert got == pytest.approx(want, abs=1e-5), (name, k)
    assert sum(f.construction_financing.hard_capex_uses_keur) == pytest.approx(sum(_amounts(solar14["pi"]).values()), abs=1e-5)


@pytest.mark.parametrize("name", list(SHAPES))
def test_sources_equal_uses_and_senior_draws_respect_the_commitment(solar14, name):
    f = solar14[name][1]
    fund = f.construction_funding
    assert fund.total_audit_sources_keur == pytest.approx(f.project_uses.total_project_uses_keur, abs=1e-6)
    cumulative = 0.0
    for period in fund.periods:
        assert period.senior_draw_keur >= -1e-9
        assert period.total_sources_keur == pytest.approx(period.project_cash_uses_keur, abs=1e-6)       # every month funds itself
        cumulative += period.senior_draw_keur
        assert cumulative <= f.final_senior_commitment_keur + 1e-6
    assert cumulative == pytest.approx(f.final_senior_commitment_keur, abs=1e-5)                         # commitment fully drawn by COD


def test_total_uses_movement_is_exactly_the_financing_cost_movement(solar14):
    runs = {n: solar14[n][1] for n in SHAPES}
    for a in runs:
        for b in runs:
            d_uses = runs[a].project_uses.total_project_uses_keur - runs[b].project_uses.total_project_uses_keur
            d_fin = _financing_costs(runs[a]) - _financing_costs(runs[b])
            assert d_uses == pytest.approx(d_fin, abs=1e-5), (a, b)
            assert runs[a].project_uses.hard_project_capex_keur == pytest.approx(runs[b].project_uses.hard_project_capex_keur, abs=1e-6)


def test_idc_and_commitment_fees_follow_the_actual_draw_dates(solar14):
    idc = {n: sum(solar14[n][1].construction_financing.senior_idc_capitalized_uses_keur) for n in SHAPES}
    commit = {n: solar14[n][1].construction_financing.senior_commitment_fee_capitalized_keur for n in SHAPES}
    assert idc["front"] > idc["base"] > idc["back"]                       # earlier draws accrue interest for longer
    assert commit["front"] < commit["base"] < commit["back"]              # earlier draws leave less undrawn commitment
    assert idc["milestone"] > idc["front"]                                # one payment in month 3 is earlier than the linear front-loaded average
    assert solar14["front"][1].project_uses.total_project_uses_keur > solar14["back"][1].project_uses.total_project_uses_keur


def test_zero_cost_months_are_stable_and_carry_no_hard_capex_or_senior_draw(solar14):
    f = solar14["milestone"][1]
    uses = f.construction_financing.hard_capex_uses_keur
    assert uses[2] == pytest.approx(sum(_amounts(solar14["pi"]).values()), abs=1e-5)
    assert all(abs(u) < 1e-9 for k, u in enumerate(uses) if k != 2)
    draws = [p.senior_draw_keur for p in f.construction_funding.periods]
    assert all(d >= 0 for d in draws)


def test_mixed_category_profiles_leave_other_categories_on_their_existing_dates(solar14):
    bound, f = solar14["mixed"]
    base = solar14["base"][0].construction
    for item, ref in zip(bound.construction.capex_items, base.capex_items):
        if item.code not in SHAPES["mixed"]:
            assert item.payment_weights == ref.payment_weights
    assert sum(solar14["mixed"][1].construction_financing.hard_capex_uses_keur) == pytest.approx(sum(_amounts(solar14["pi"]).values()), abs=1e-5)


def test_no_bound_profile_means_the_default_semester_path_is_untouched(projects):
    """Default parity: the bridge is opt-in and imported by no engine module; derive_construction_financing is unchanged."""
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    for rel in ("financial_engine", "finco_core"):
        for path in (root / rel).rglob("*.py"):
            assert "capex_profiles" not in path.read_text(encoding="utf-8"), path
    pi = _inputs(projects, "generic_solar_reference", 14)
    assert len(derive_construction_financing(pi).periods) == 3                  # still the semester axis without a bound profile


# ───────────────── other durations and technologies (real engine) ─────────────────

@pytest.mark.parametrize("template,months,shape", [
    ("generic_solar_reference", 12, S.FRONT_LOADED),
    ("generic_solar_reference", 18, S.BACK_LOADED),
    ("generic_wind_reference", 20, S.FRONT_LOADED),
])
def test_identities_hold_for_other_durations_and_technologies(projects, template, months, shape):
    pi = _inputs(projects, template, months)
    codes = tuple(c for c in CODES if getattr(pi.capex, c).amount_keur > 0)
    shapes = {c: shape for c in codes}
    amounts = _amounts(pi)
    cfi = derive_construction_financing(pi)
    base = bind(cfi, construction_months=months, category_amounts_keur=amounts)
    bound = bind(cfi, construction_months=months, category_amounts_keur=amounts,
                 leaves=[Leaf(c, c, amounts[c], ProfileSpec(c, shape) if c in shapes else None) for c in CODES])
    fb, fp = _run(pi, base.construction), _run(pi, bound.construction)
    expected = _oracle_hard_uses(pi, bound, shapes, months)
    for got, want in zip(fp.construction_financing.hard_capex_uses_keur, expected):
        assert got == pytest.approx(want, abs=1e-5)
    for f in (fb, fp):
        assert len(f.construction_financing.hard_capex_uses_keur) == months
        assert f.construction_funding.total_audit_sources_keur == pytest.approx(f.project_uses.total_project_uses_keur, abs=1e-6)
    assert fp.project_uses.hard_project_capex_keur == pytest.approx(fb.project_uses.hard_project_capex_keur, abs=1e-6)
    assert fp.project_uses.total_project_uses_keur - fb.project_uses.total_project_uses_keur == pytest.approx(
        _financing_costs(fp) - _financing_costs(fb), abs=1e-5)
    idc_b, idc_p = (sum(f.construction_financing.senior_idc_capitalized_uses_keur) for f in (fb, fp))
    assert idc_p != pytest.approx(idc_b, abs=1e-6)                           # the profile moves IDC; it is not ignored
