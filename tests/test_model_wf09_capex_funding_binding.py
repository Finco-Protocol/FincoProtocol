"""WF-09 binding evidence: what the EXISTING production construction-funding path consumes, and what it does not.

Consumed (proved by running the production path on timing-modified inputs, nothing persisted):
  CapexItem.y0_share + spending_profile (per CATEGORY, per existing construction PERIOD) -> derive_construction_financing ->
  Stage B2 / canonical allocator -> hard CAPEX uses, Senior draws, capitalised IDC, total project uses, Sources = Uses.
NOT consumed (proved by a source guard): CapexSubLine.schedule_json and any monthly user profile.
"""
from __future__ import annotations

import dataclasses
import re
from decimal import Decimal
from pathlib import Path

import pytest

from app.capex_profiles.contract import ProfileShape as S, ProfileSpec, allocate
from financial_engine.financing.generic_product_policy import (
    DEFAULT_GENERIC_FINANCING_POLICY, derive_construction_financing, run_with_generic_financing_policy,
)
from financial_engine.run_scope import engine_run_scope
from financial_engine.shareholder_waterfall import run_project_shareholder_waterfall_model
from tests.test_model_decision_workspace_v2 import env  # noqa: F401

CODES = ("production_units", "epc_other", "grid_connection", "audit_legal")


def _run(pi):
    with engine_run_scope():
        g2c, _eff, evidence = run_with_generic_financing_policy(
            pi, lambda applied: run_project_shareholder_waterfall_model(applied, source_id="wf09_binding_test"), DEFAULT_GENERIC_FINANCING_POLICY)
    assert evidence.construction_financing_applied
    return g2c.financing_result.construction_financing


def _with_timing(pi, weights):
    # derive_construction_financing adds y0_share AND spending_profile[i] to construction period i, so a per-period weight vector
    # is expressed as y0_share=0 and spending_profile=weights.
    ups = {code: dataclasses.replace(getattr(pi.capex, code), y0_share=0.0, spending_profile=tuple(w)) for code, w in weights.items()}
    return dataclasses.replace(pi, capex=dataclasses.replace(pi.capex, **ups))


@pytest.fixture(scope="module")
def base_inputs(tmp_path_factory):
    from app.persistence import db
    original = db.DB_PATH
    db.DB_PATH = str(tmp_path_factory.mktemp("wf09") / "wf09.db")
    db.init_db()
    from app.input_adapter import build_projectinputs_from_snapshot
    from app.persistence.workspace_repository import get_workspace_state
    from app.services.reference_seed_service import create_reference_seeded_project
    project = create_reference_seeded_project(user_id="wf09-user", requested_name="WF09", template_source="generic_solar_reference", capacity_mw=16)
    snapshot = get_workspace_state("wf09-user", project.project_id).draft_snapshot
    pi = build_projectinputs_from_snapshot(snapshot)
    yield {"pi": pi, "snapshot": snapshot}
    db.DB_PATH = original


@pytest.fixture(scope="module")
def variants(base_inputs):
    pi = base_inputs["pi"]
    n = len(derive_construction_financing(pi).periods)
    assert n == 3
    # period-equivalent weights produced by the WF-09 planner from a MONTHLY profile (14 months -> 3 periods, 6/6/2 months)
    groups = (0,) * 6 + (1,) * 6 + (2,) * 2
    from app.capex_profiles.contract import aggregate_by_group

    def equivalent(shape):
        out = {}
        for code in CODES:
            amount = getattr(pi.capex, code).amount_keur
            agg = aggregate_by_group(allocate(ProfileSpec(code, shape), amount, 14), groups, 3)
            out[code] = tuple(float(a / Decimal(str(amount))) for a in agg)
        return out
    front, back = equivalent(S.FRONT_LOADED), equivalent(S.BACK_LOADED)
    out = {"base": _run(pi), "front": _run(_with_timing(pi, front)), "back": _run(_with_timing(pi, back))}
    out["weights"] = {"front": front, "back": back}
    return out


def test_hard_capex_total_is_independent_of_payment_timing(base_inputs, variants):
    pi = base_inputs["pi"]
    total = sum(getattr(pi.capex, c).amount_keur for c in pi.capex._CAPEX_ITEM_FIELDS)
    for name in ("base", "front", "back"):
        assert sum(variants[name].hard_capex_uses_keur) == pytest.approx(total, abs=1e-6), name


def test_period_uses_equal_amount_times_the_declared_weights(base_inputs, variants):
    """Independent oracle: period uses = sum(amount * weight), weights of untouched categories taken from the existing derivation."""
    pi = base_inputs["pi"]
    original = {item.code: item.payment_weights for item in derive_construction_financing(pi).capex_items}
    for name in ("front", "back"):
        declared = variants["weights"][name]
        for p, uses in enumerate(variants[name].hard_capex_uses_keur):
            expected = 0.0
            for code in original:
                w = declared[code] if code in declared else original[code]
                expected += getattr(pi.capex, code).amount_keur * w[p]
            assert uses == pytest.approx(expected, abs=1e-6), (name, p)


def _financing_costs(c):
    return sum(c.senior_idc_capitalized_uses_keur) + c.senior_commitment_fee_capitalized_keur + sum(c.structuring_fee_keur)


def test_timing_changes_senior_draws_idc_and_total_uses_in_the_expected_direction(variants):
    base, front, back = (variants[k] for k in ("base", "front", "back"))
    assert tuple(front.senior_draws_keur) != tuple(back.senior_draws_keur) != tuple(base.senior_draws_keur)
    assert sum(back.senior_idc_capitalized_uses_keur) < sum(front.senior_idc_capitalized_uses_keur)     # earlier spend -> more capitalised interest
    assert back.final_total_project_uses_keur < front.final_total_project_uses_keur
    # the financing-cost effect is reported SEPARATELY from the (unchanged) hard CAPEX
    assert sum(back.hard_capex_uses_keur) == pytest.approx(sum(front.hard_capex_uses_keur), abs=1e-6)
    assert 0 < _financing_costs(back) < _financing_costs(front)
    delta_total = front.final_total_project_uses_keur - back.final_total_project_uses_keur
    assert delta_total == pytest.approx(_financing_costs(front) - _financing_costs(back), abs=1e-6)  # timing moves ONLY financing costs
    # the existing template timing is a third, independent point: its own draws and costs, same hard CAPEX
    assert tuple(base.senior_draws_keur) not in (tuple(front.senior_draws_keur), tuple(back.senior_draws_keur))


def test_sources_equal_uses_each_period_and_in_total_for_every_profile(variants):
    for name in ("base", "front", "back"):
        c = variants[name]
        assert abs(c.sources_uses_residual_keur) < 1e-6 and all(abs(r) < 1e-6 for r in c.period_sources_uses_residual_keur), name
        sources = sum(sum(t) for t in (c.senior_draws_keur, c.share_capital_draws_keur, c.share_premium_draws_keur, c.shl_cash_contribution_keur,
                                       c.junior_draws_keur, c.other_committed_equity_draws_keur, c.additional_equity_draws_keur))
        assert sources == pytest.approx(sum(c.hard_capex_uses_keur) + _financing_costs(c), abs=1e-6), name   # construction sources = construction uses


def test_a_monthly_profile_is_only_visible_to_the_run_through_the_period_equivalent(base_inputs, variants):
    """Intra-period monthly timing is NOT represented: two monthly profiles with the same period totals give the same funding."""
    pi = base_inputs["pi"]
    groups = (0,) * 6 + (1,) * 6 + (2,) * 2
    from app.capex_profiles.contract import aggregate_by_group
    code = "epc_other"
    amount = getattr(pi.capex, code).amount_keur
    a = allocate(ProfileSpec(code, S.UNIFORM), amount, 14)
    # an explicit profile with identical period sums but different months inside each period
    per_period = aggregate_by_group(a, groups, 3)
    pct = [Decimal(0)] * 14
    pct[0], pct[6], pct[13] = (per_period[0] / Decimal(str(amount)) * 100, per_period[1] / Decimal(str(amount)) * 100, per_period[2] / Decimal(str(amount)) * 100)
    b = allocate(ProfileSpec(code, S.EXPLICIT, tuple(format(p, "f") for p in pct)), amount, 14)
    assert [m.amount_keur for m in a.months] != [m.amount_keur for m in b.months]
    assert aggregate_by_group(a, groups, 3) == aggregate_by_group(b, groups, 3)


def test_sub_line_schedule_json_and_monthly_profiles_do_not_reach_the_financial_path():
    """Source guard: nothing in the Run composition / engine reads CapexSubLine.schedule_json (it is persisted and passed through only)."""
    root = Path(__file__).resolve().parents[1]
    for rel in ("app/services/model_v2_composition/compose.py", "app/input_adapter.py", "app/services/run_service.py",
                "app/services/production_financial_authority.py", "app/api/project_runner.py"):
        assert "schedule_json" not in (root / rel).read_text(encoding="utf-8"), rel
    for tree in ("financial_engine", "finco_core", "domain"):
        for f in (root / tree).rglob("*.py"):
            assert "schedule_json" not in f.read_text(encoding="utf-8"), f
    # the only consumer of timing is CapexItem.y0_share/spending_profile through the existing derivation
    text = (root / "financial_engine/financing/generic_product_policy.py").read_text(encoding="utf-8")
    assert "item.spending_profile" in text and "item.y0_share" in text
    for f in (root / "app/capex_profiles").glob("*.py"):
        assert not re.search(r"\bspending_profile\s*=", f.read_text(encoding="utf-8")), f
