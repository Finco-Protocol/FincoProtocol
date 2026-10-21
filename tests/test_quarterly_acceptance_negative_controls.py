"""Quarterly institutional acceptance — robustness and negative controls.

Everything outside the candidate scope must fail closed with a typed ``QUARTERLY_*`` code BEFORE any calculation, the release-closed gate must stay
closed, the released default must be untouched, and the acceptance oracles must be able to FAIL (a harness that cannot detect a defect proves nothing).
No flag, pin, allow-list or exemption is changed to make any of these pass.
"""
from __future__ import annotations

import dataclasses
import json
from datetime import date

import pytest

import quarterly_acceptance_support as Q
import rc7b_quarterly_oracle as oracle
import rc7c_frequency_reconciliation as recon
from app.workbook import quarterly_frequency_config as cfg
from finco_core.engine.calendar_policy import (
    OperatingCalendarPolicy, quarterly_candidate_policy_v1, quarterly_candidate_policy_v2,
)
from financial_engine.financing.quarterly_scope import QuarterlyScopeUnsupported, require_supported_quarterly_project
from test_rc7b_quarterly_funding_statements import build, canonical_run


def _fin(pi, **kw):
    return dataclasses.replace(pi, financing=dataclasses.replace(pi.financing, **kw))


def _rev(pi, **kw):
    return dataclasses.replace(pi, revenue=dataclasses.replace(pi.revenue, **kw))


def _tax(pi, **kw):
    return dataclasses.replace(pi, tax=dataclasses.replace(pi.tax, **kw))


def _reserve():
    from finco_core.inputs import DebtServiceReserveSupportMode
    return DebtServiceReserveSupportMode


def _sfm():
    from finco_core.inputs import SponsorFundingMode
    return SponsorFundingMode


REFUSED = [
    ("shl-mode", lambda pi: _fin(pi, sponsor_funding_mode=_sfm().SHARE_CAPITAL_THEN_SHL), "QUARTERLY_SHL_UNSUPPORTED"),
    ("shl-amount", lambda pi: _fin(pi, shl_amount_keur=250.0), "QUARTERLY_SHL_UNSUPPORTED"),
    ("shl-clean-principal", lambda pi: _fin(pi, clean_shl_principal_keur=250.0), "QUARTERLY_SHL_UNSUPPORTED"),
    ("dsra-months", lambda pi: _fin(pi, dsra_months=6), "QUARTERLY_RESERVE_POLICY_PENDING_D09"),
    ("reserve-requirement", lambda pi: _fin(pi, debt_service_reserve_requirement_keur=10.0), "QUARTERLY_RESERVE_POLICY_PENDING_D09"),
    ("dsrf-mode", lambda pi: _fin(pi, dsra_support_mode=_reserve().DSRF, dsrf_commitment_keur=100.0, dsrf_commitment_fee_rate_pa=0.01),
     "QUARTERLY_RESERVE_POLICY_PENDING_D09"),
    ("cash-dsra-mode", lambda pi: _fin(pi, dsra_support_mode=_reserve().CASH_DSRA), "QUARTERLY_RESERVE_POLICY_PENDING_D09"),
    ("junior", lambda pi: _fin(pi, junior_or_other_project_funding_keur=10.0), "QUARTERLY_FACILITY_COMBINATION_UNSUPPORTED"),
    ("first-merchant-index", lambda pi: _rev(pi, first_merchant_operating_period_index=4), "QUARTERLY_LEGACY_PERIOD_VECTOR_UNSUPPORTED"),
    ("tariff-vector", lambda pi: _rev(pi, ppa_tariff_by_operating_period=(50.0,) * 10), "QUARTERLY_LEGACY_PERIOD_VECTOR_UNSUPPORTED"),
    ("calendar-prices", lambda pi: _rev(pi, market_price_calendar_start_year=2031, market_prices_by_calendar_year_eur_mwh=(50.0,)),
     "QUARTERLY_REVENUE_CONTRACT_HANDOFF_REQUIRED"),
    ("dated-indexation", lambda pi: _rev(pi, ppa_indexation_start_date=date(2032, 1, 1)), "QUARTERLY_PPA_INDEXATION_HANDOFF_REQUIRED"),
    ("fractional-ppa", lambda pi: _rev(pi, ppa_term_years=10.5), "QUARTERLY_PPA_TERM_UNSUPPORTED"),
    ("atad", lambda pi: _tax(pi, atad_enabled=True), "QUARTERLY_TAX_POLICY_UNSUPPORTED"),
    ("thin-cap", lambda pi: _tax(pi, thin_cap_enabled=True), "QUARTERLY_TAX_POLICY_UNSUPPORTED"),
    ("bess", lambda pi: dataclasses.replace(pi, technical=dataclasses.replace(pi.technical, bess_enabled=True)), "QUARTERLY_TECHNOLOGY_UNSUPPORTED"),
]
BASES = ["solar-q1end", "solar-dscr-bound", "wind-q3end", "wind-ppa-share", "solar-mid-q2", "solar-opex-step"]


@pytest.mark.parametrize("sid", BASES)
@pytest.mark.parametrize("name,change,code", REFUSED, ids=[r[0] for r in REFUSED])
def test_unsupported_combination_is_refused_with_its_typed_code_on_every_base_scenario(sid, name, change, code):
    pi = Q.project(Q.scenario(sid), "Q")
    with pytest.raises(QuarterlyScopeUnsupported) as caught:
        require_supported_quarterly_project(change(pi))
    assert str(caught.value).startswith(code) or code in str(caught.value)


@pytest.mark.parametrize("name,change,code", REFUSED[:7] + REFUSED[13:], ids=[r[0] for r in REFUSED[:7] + REFUSED[13:]])
def test_the_canonical_engine_entry_refuses_before_producing_any_result(name, change, code):
    pi = change(Q.project(Q.scenario("solar-q1end"), "Q"))
    with pytest.raises(QuarterlyScopeUnsupported, match=code):
        canonical_run(pi)                                   # nothing is returned, so no partial schedule can be consumed


def test_an_orphan_dsrf_commitment_without_dsrf_mode_is_inert_under_both_frequencies_finding_q_f_03():
    """P2 (usability): with support mode NONE the DSRF commitment/fee inputs are accepted and have NO effect, under 6/6 as under 3/3.

    Not a quarterly defect (the released engine behaves the same) and not fail-open (no reserve is claimed), but a silently inert input.
    The Working Copy selection contract is stricter and refuses it (RESERVE_POLICY_PENDING_D09).
    """
    for frequency in "SQ":
        scn = Q.scenario("solar-q1end")
        base = canonical_run(Q.project(scn, frequency))
        orphan = canonical_run(_fin(Q.project(scn, frequency), dsrf_commitment_keur=500.0, dsrf_commitment_fee_rate_pa=0.01))
        assert dataclasses.asdict(orphan.g2c_result) == dataclasses.asdict(base.g2c_result)
        assert orphan.g2c_result.total_dsrf_commitment_fee_keur == 0.0


@pytest.mark.parametrize("cod", [date(2031, 4, 1), date(2031, 4, 17), date(2031, 7, 1), date(2031, 8, 15), date(2032, 1, 1), date(2027, 11, 10)])
@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_a_ppa_expiring_inside_a_quarter_is_refused_not_split(kind, cod):
    scn = Q.Scenario(f"neg-{kind}-{cod}", recon.Case(kind, cod), "negative", "mid-quarter PPA expiry")
    with pytest.raises(QuarterlyScopeUnsupported, match="QUARTERLY_INTRAPERIOD_PPA_EXPIRY_UNSUPPORTED"):
        canonical_run(Q.project(scn, "Q"))
    merchant = Q.Scenario(f"neg-{kind}-{cod}-m", recon.Case(kind, cod, ppa=0.0), "negative", "same COD, no PPA")
    assert Q.operating_periods(Q.run(merchant, "Q")[1])[0].period_start == cod                  # the identical COD is supported once no PPA straddles a quarter


def test_mixed_operating_and_debt_frequencies_are_not_representable_d06_d07():
    base = quarterly_candidate_policy_v2().to_dict()
    for operating, debt in ((3, 6), (6, 3), (6, 6), (1, 1), (3, 1)):
        with pytest.raises(ValueError, match="QUARTERLY_MATCHED_3_3_REQUIRED"):
            OperatingCalendarPolicy.from_dict(base | {"operating_months": operating, "debt_service_months": debt})
    for bad in (3.0, "3", True):
        with pytest.raises(ValueError, match="QUARTERLY_POLICY_INTEGER_MONTHS_REQUIRED|QUARTERLY_MATCHED_3_3_REQUIRED"):
            OperatingCalendarPolicy.from_dict(base | {"operating_months": bad})


def test_policy_versions_rulesets_and_unknown_fields_are_strict():
    base = quarterly_candidate_policy_v2().to_dict()
    with pytest.raises(ValueError, match="QUARTERLY_POLICY_VERSION_UNSUPPORTED"):
        OperatingCalendarPolicy.from_dict(base | {"version": "rc7c-quarterly-candidate-v3"})
    with pytest.raises(ValueError, match="QUARTERLY_COMPLETE_VERSIONED_POLICY_REQUIRED"):
        OperatingCalendarPolicy.from_dict({k: v for k, v in base.items() if k != "maturity"})
    with pytest.raises(ValueError, match="QUARTERLY_COMPLETE_VERSIONED_POLICY_REQUIRED"):
        OperatingCalendarPolicy.from_dict(base | {"surprise": 1})
    with pytest.raises(ValueError, match="QUARTERLY_POLICY_VALUE_UNSUPPORTED"):
        OperatingCalendarPolicy.from_dict(base | {"fraction": "ACT_ACT_ISDA"})
    v1 = quarterly_candidate_policy_v1().to_dict()
    with pytest.raises(ValueError, match="QUARTERLY_POLICY_RULESET_MISMATCH"):
        OperatingCalendarPolicy.from_dict(base | {"maturity": v1["maturity"]})                       # a v2 label cannot carry v1 rules


def test_an_untyped_project_cannot_enter_the_quarterly_path_without_an_explicit_calendar_policy():
    six = Q.project(Q.scenario("solar-q1end"), "S")
    with pytest.raises(QuarterlyScopeUnsupported, match="QUARTERLY_EXPLICIT_CALENDAR_POLICY_REQUIRED"):
        require_supported_quarterly_project(six)


def test_a_six_month_authored_senior_vector_is_refused_not_silently_regridded():
    pi = Q.project(Q.scenario("solar-q1end"), "Q")
    cfgi = pi.financing.senior_debt_interest_config
    stepped = dataclasses.replace(cfgi, rate_schedule=dataclasses.replace(cfgi.rate_schedule, explicit_all_in_rates=(0.05,) * 15 + (0.06,) * 15))
    with pytest.raises(Exception, match="QUARTERLY_SENIOR_RATE_VECTOR_REGRID_UNSUPPORTED"):
        canonical_run(_fin(pi, senior_debt_interest_config=stepped))
    from finco_core.inputs.senior_rate_schedule import SeniorDayCountConvention
    for convention in (SeniorDayCountConvention.FIXED_SEMIANNUAL, SeniorDayCountConvention.EXPLICIT_FRACTIONS):
        # a fixed half-year or explicit six-month fraction vector would mis-accrue quarterly rows; both stay refused (untyped ValueError: P2, finding Q-F-04)
        with pytest.raises(ValueError):
            canonical_run(_fin(pi, senior_debt_interest_config=dataclasses.replace(cfgi, day_count=convention, explicit_period_fractions=(0.5,) * 80)))
    sculpt = dataclasses.replace(pi.financing.senior_sculpting_config, target_dscr_schedule=(1.3,) * 30)
    with pytest.raises(Exception, match="QUARTERLY_SENIOR_PERIOD_VECTOR_UNSUPPORTED"):
        canonical_run(_fin(pi, senior_sculpting_config=sculpt))


@pytest.mark.parametrize("mode", ["explicit_debt_service_schedule", "explicit_principal_schedule"])
def test_explicit_repayment_calendars_authored_on_the_wrong_grid_are_rejected(mode):
    """Invalid repayment calendar: a six-month principal/service schedule must never be re-gridded onto quarters."""
    pi = Q.project(Q.scenario("solar-q1end"), "Q")
    sculpt = dataclasses.replace(pi.financing.senior_sculpting_config, **{mode: (100.0,) * 30})
    with pytest.raises(Exception, match="QUARTERLY_"):
        canonical_run(_fin(pi, senior_sculpting_config=sculpt))


# ── release-closed gate, default Run and governance ──────────────────────────

def test_the_activation_gate_is_closed_and_refuses_every_project_type():
    assert cfg.ACTIVATION_ENABLED is False
    for project_type in ("solar", "wind", "bess", "", None):
        with pytest.raises(cfg.QuarterlyFrequencyError, match="QUARTERLY_ADMISSION_CLOSED"):
            cfg.require_admitted(project_type)


def test_the_selection_contract_rejects_mixed_frequencies_unknown_keys_duplicates_and_oversize():
    base = json.loads(cfg.candidate_config_json({"sponsor_funding_mode": "EQUITY_ONLY", "shl_amount_keur": 0.0,
                                                 "clean_shl_principal_keur": 0.0, "dsra_months": 0}))
    for mutation, code in (
        ({"operating_months": 3, "debt_service_months": 6}, "QUARTERLY_MATCHED_3_3_REQUIRED"),
        ({"operating_months": 6, "debt_service_months": 3}, "QUARTERLY_MATCHED_3_3_REQUIRED"),
        ({"version": 1}, "QUARTERLY_CONFIG_VERSION_UNSUPPORTED"),
        ({"authority": "SOMEONE_ELSE"}, "QUARTERLY_CONFIG_AUTHORITY_INVALID"),
        ({"sponsor_funding_mode": "SHARE_CAPITAL_THEN_SHL"}, "QUARTERLY_CONFIG_FINANCING_BINDING_INVALID"),
        ({"reserve_support_mode": "DSRA"}, "QUARTERLY_CONFIG_FINANCING_BINDING_INVALID"),
        ({"extra": 1}, "QUARTERLY_CONFIG_KEYS_INVALID"),
    ):
        with pytest.raises(cfg.QuarterlyFrequencyError, match=code):
            cfg.parse_config(json.dumps(base | mutation))
    with pytest.raises(cfg.QuarterlyFrequencyError, match="QUARTERLY_CONFIG_DUPLICATE_KEY"):
        cfg.parse_config('{"version": 2, "version": 2}')
    with pytest.raises(cfg.QuarterlyFrequencyError, match="QUARTERLY_CONFIG_BOUNDED_JSON_REQUIRED"):
        cfg.parse_config(json.dumps(base | {"padding": "x" * 5000}))
    with pytest.raises(cfg.QuarterlyFrequencyError, match="QUARTERLY_CONFIG_INVALID_JSON"):
        cfg.parse_config("{not json")
    assert cfg.parse_config(None) is None and cfg.parse_config("") is None                             # absent selection is the released 6/6 default


def test_a_selection_cannot_discard_shl_or_dsra_and_unsupported_technology_is_refused_at_apply_time():
    pi = Q.project(Q.scenario("solar-q1end"), "S")
    structure = cfg.structure_of(pi.financing)
    selection = cfg.candidate_config_json(structure)
    assert type(cfg.apply_config(pi, selection, "solar").info).__name__ == "QuarterlyProjectInfo"
    with pytest.raises(cfg.QuarterlyFrequencyError, match="QUARTERLY_TECHNOLOGY_UNSUPPORTED"):
        cfg.apply_config(pi, selection, "bess")
    with_shl = _fin(pi, sponsor_funding_mode=_sfm().SHARE_CAPITAL_THEN_SHL, shl_amount_keur=500.0, clean_shl_principal_keur=500.0)
    with pytest.raises(cfg.QuarterlyFrequencyError, match="QUARTERLY_SHL_UNSUPPORTED"):
        cfg.apply_config(with_shl, selection, "solar")
    with pytest.raises(cfg.QuarterlyFrequencyError, match="QUARTERLY_RESERVE_POLICY_PENDING_D09"):
        cfg.apply_config(_fin(pi, dsra_months=6), selection, "solar")


def test_the_released_default_run_is_unaffected_by_quarterly_runs():
    """Running the quarterly candidate first and the default project after it gives the same six-month result as running the default alone."""
    scn = Q.scenario("solar-q1end")
    alone = canonical_run(Q.project(scn, "S"), source_id="quarterly_acceptance_default_alone")
    Q.run(scn, "Q")
    canonical_run(Q.project(Q.scenario("wind-q3end"), "Q"), source_id="quarterly_acceptance_interleaved")
    after = canonical_run(Q.project(scn, "S"), source_id="quarterly_acceptance_default_alone")
    assert dataclasses.asdict(alone.g2c_result) == dataclasses.asdict(after.g2c_result)
    assert alone.financial_statements_result == after.financial_statements_result
    assert Q.project(scn, "S").info.period_frequency.name != "QUARTERLY"


def test_the_released_default_is_semiannual_and_has_no_calendar_policy():
    for sid in ("solar-q1end", "wind-yearend", "solar-mid-q2"):
        info = Q.project(Q.scenario(sid), "S").info
        assert info.period_frequency.name == "SEMESTRIAL" and not hasattr(info, "operating_calendar_policy")


def test_governance_pins_recognise_the_current_candidate_and_this_suite_adds_no_exemption():
    """The acceptance modules are new test files only: none of them names a pin, allow-list, exemption or workflow."""
    import pathlib
    root = pathlib.Path(__file__).parent
    forbidden = ("ALLOWLIST", "EXEMPT", "ACTIVATION_ENABLED = True", "monkeypatch.setattr(cfg", ".github/workflows")
    for path in root.glob("*quarterly_acceptance*.py"):
        if path.name == pathlib.Path(__file__).name:
            continue
        text = path.read_text()
        assert not any(token.lower() in text.lower() for token in forbidden), path.name


# ── the oracles can fail: defect shapes are detected ─────────────────────────

def _engine_rows(sid):
    return [(p.period_start, p.period_end, p.days_in_period) for p in Q.operating_periods(Q.run(Q.scenario(sid), "Q")[1])]


def test_the_date_oracle_detects_a_dropped_a_duplicated_and_a_shifted_row():
    expected = [(r.start, r.end, r.days) for r in Q.calendar_oracle(*(lambda i: (i.cod_date, i.horizon_years))(Q.project(Q.scenario("solar-q3end"), "Q").info))]
    assert expected == _engine_rows("solar-q3end")
    assert expected[:5] + expected[6:] != _engine_rows("solar-q3end")                                  # silently missing quarter
    assert expected[:5] + [expected[5]] + expected[5:] != _engine_rows("solar-q3end")                  # duplicated flow at a boundary
    shifted = [(s, e.replace(day=e.day - 1) if i == 3 else e, d) for i, (s, e, d) in enumerate(expected)]
    assert shifted != _engine_rows("solar-q3end")                                                       # one-day boundary slip


def test_the_historical_v1_row_count_defect_shape_is_still_detected_by_the_independent_oracles():
    """v1 added a quarter when COD fell in the second quarter of a half-year; the v2 engine must not, and the oracles must see the difference."""
    scn = Q.scenario("solar-q3end")
    pi, result = Q.run(scn, "Q")
    v1_info = dataclasses.replace(pi.info, operating_calendar_policy=quarterly_candidate_policy_v1())
    v1_rows = oracle.operating_rows(v1_info, int(pi.revenue.ppa_term_years))
    v2_rows = Q.calendar_oracle(pi.info.cod_date, pi.info.horizon_years)
    assert len(v1_rows) == len(v2_rows) + 1 and len(v2_rows) == len(Q.operating_periods(result))      # v1 shape has the extra quarter the engine must not have
    assert [(r.start, r.end) for r in v2_rows] == [(p.period_start, p.period_end) for p in Q.operating_periods(result)]


def test_the_senior_oracle_detects_a_wrong_day_count_a_wrong_target_and_a_wrong_rate():
    pi, result = Q.run(Q.scenario("solar-dscr-bound"), "Q")
    from financial_engine.adapters.project_inputs import from_project_inputs
    dep = from_project_inputs(result.project_inputs).depreciation
    uses = result.g2c_result.financing_result.project_uses.total_project_uses_keur
    engine = Q.d(result.g2c_result.financing_result.final_senior_commitment_keur)

    def solve(changed):
        return oracle.senior(changed, total_project_uses_keur=uses, dep_items=dep.tax_capex_items_for_depreciation,
                             financial_cost_life=dep.financial_cost_useful_life_years).debt

    assert abs(solve(pi) - engine) < Q.SOLVER_TOL                                                         # the correct inputs reproduce the engine
    assert abs(solve(_fin(pi, target_dscr=pi.financing.target_dscr + 0.05)) - engine) > Q.D("10")      # a different sculpting target is visible
    cfgi = pi.financing.senior_debt_interest_config
    higher = dataclasses.replace(cfgi.rate_schedule, explicit_all_in_rates=(0.065,) * 30)
    assert abs(solve(_fin(pi, senior_debt_interest_config=dataclasses.replace(cfgi, rate_schedule=higher))) - engine) > Q.D("10")
    assert abs(solve(_fin(pi, senior_tenor_years=pi.financing.senior_tenor_years - 2)) - engine) > Q.D("10")
