"""Actual legacy authority and cold, four-vertical financial non-mutation proof."""
import ast
import copy
from dataclasses import asdict, replace
from datetime import date
import json
from pathlib import Path
import re

import pytest

from app import project_factories as pf
from finco_core.inputs import (
    DebtSizingMode, GearingCapRepaymentMethod, PeriodAxisConvention, PeriodFrequency,
    SHLRepaymentMethod, SponsorFundingMode, hash_inputs_for_cache, project_inputs_to_dict,
)
from finco_core.inputs.financing_instruments import (
    CommitmentAuthority, FinancingCollection, FinancingError, InstrumentType, MaturityAuthority, RepaymentMode,
)
from finco_core.inputs.financing_instruments_legacy import (
    UNRESOLVED, map_legacy_financing, map_legacy_financing_with_authority,
)

ROOT = Path(__file__).resolve().parents[1]
KINDS = ("solar", "wind", "data_center", "ev_charging")


def project(kind="solar", **kwargs):
    pi = getattr(pf, f"create_generic_{kind}_reference")()
    return replace(pi, financing=replace(pi.financing, **kwargs)) if kwargs else pi


def by_id(collection):
    return {i.instrument_id: i for i in collection.instruments}


@pytest.mark.parametrize("kind", KINDS)
def test_four_verticals_bit_exact_economics_before_after_mapping(kind, tmp_path):
    from app.services import production_financial_authority as authority
    from app.run_integrity.evidence import build_run_integrity_evidence
    from app.run_integrity.checks import run_integrity_checks
    pi = project(kind)
    before_inputs = copy.deepcopy(project_inputs_to_dict(pi))
    before_hash = hash_inputs_for_cache(pi)
    authority._POLICY_RUN_CACHE.clear()
    before = authority.run_clean_production(pi)
    original = asdict(before)
    original_integrity = run_integrity_checks(build_run_integrity_evidence(before)).to_dict()
    mapped = map_legacy_financing_with_authority(pi)
    assert FinancingCollection.from_dict(mapped.collection.to_dict()) == mapped.collection
    assert project_inputs_to_dict(pi) == before_inputs
    assert hash_inputs_for_cache(pi) == before_hash
    authority._POLICY_RUN_CACHE.clear()  # force independent canonical recalculation
    after = authority.run_clean_production(pi)
    assert asdict(after) == original  # all financial fields, not only rounded summaries
    assert run_integrity_checks(build_run_integrity_evidence(after)).to_dict() == original_integrity
    senior = after.g2c_result.financing_result.project_model_result.senior_debt
    proposal = by_id(mapped.collection)["legacy-senior"]
    assert proposal.commitment_keur is None
    assert proposal.repayment.maturity_period_index == senior.period_indices[-1]
    terminal = after.g2c_result.return_summary.terminal.senior
    assert mapped.senior_contractual_maturity_date == terminal.contractual_maturity_date
    assert proposal.repayment.maturity_date is None
    assert mapped.senior_sizing_mode is pi.financing.debt_sizing_mode
    assert mapped.sponsor_funding_mode is pi.financing.sponsor_funding_mode
    assert original_integrity["overall"] == "PASS"
    # Structured, runner-local evidence; never a golden or an active Run input.
    evidence = dict(kind=kind, input_hash=repr(before_hash), input_payload=before_inputs,
                    proposal=mapped.collection.to_dict(), financial_before=original,
                    financial_after=asdict(after), integrity=original_integrity)
    (tmp_path / f"f3-{kind}.json").write_text(json.dumps(evidence, default=str, sort_keys=True), encoding="utf-8")


@pytest.mark.parametrize("kind", KINDS)
def test_legacy_source_representation_and_candidate_overlap(kind):
    from app.model_v2.financing_f3_candidate.legacy_mapping import map_legacy_financing as candidate_map
    from app.model_v2.financing_f3_candidate.contracts import to_canonical_dict
    pi = project(kind)
    new = map_legacy_financing(pi).to_dict()
    old = to_canonical_dict(candidate_map(pi))
    assert new["schema_version"] != old["schema_version"]
    new.pop("schema_version")
    old.pop("schema_version")
    # Canonical promotion resolves the existing symbolic Senior tenor to its
    # actual calendar-axis index; no inferred commitment or date is introduced.
    for value in new["instruments"]:
        if value["instrument_id"] == "legacy-senior":
            assert value["repayment"]["maturity_period_index"] is not None
            value["repayment"]["maturity_period_index"] = None
    assert new == old


@pytest.mark.parametrize("method,expected", [(GearingCapRepaymentMethod.LEVEL_PRINCIPAL, RepaymentMode.LEVEL_PRINCIPAL),
                                           (GearingCapRepaymentMethod.DSCR_SCULPTED, RepaymentMode.DSCR_SCULPTED)])
def test_gearing_repayment_comes_from_typed_authority(method, expected):
    value = map_legacy_financing(project(debt_sizing_mode=DebtSizingMode.GEARING_CAP,
                                        gearing_cap_repayment_method=method))
    assert by_id(value)["legacy-senior"].repayment.mode is expected


@pytest.mark.parametrize("mode,expected", [(DebtSizingMode.FLAT_DSCR_SCULPTED, RepaymentMode.DSCR_SCULPTED),
    (DebtSizingMode.MINIMUM_DSCR_SCULPTED, RepaymentMode.DSCR_SCULPTED),
    (DebtSizingMode.FROZEN_EXCEL_SCHEDULE, RepaymentMode.EXPLICIT_SCHEDULE)])
def test_sizing_mode_is_retained_without_claiming_runtime_enablement(mode, expected):
    mapped = map_legacy_financing_with_authority(project(debt_sizing_mode=mode))
    assert mapped.senior_sizing_mode is mode
    assert by_id(mapped.collection)["legacy-senior"].repayment.mode is expected


@pytest.mark.parametrize("method,expected", [(SHLRepaymentMethod.BULLET, RepaymentMode.BULLET),
                                            (SHLRepaymentMethod.CASH_SWEEP, RepaymentMode.CASH_SWEEP)])
def test_shl_proven_methods_only(method, expected):
    pi = project(clean_shl_repayment_method=method)
    shl = by_id(map_legacy_financing(pi))["legacy-shl"]
    assert shl.repayment.mode is expected
    assert shl.repayment.maturity_period_index == pi.financing.shl_maturity_period_index
    assert shl.commitment_keur is None and shl.commitment_authority is CommitmentAuthority.RESIDUAL_DERIVED


@pytest.mark.parametrize("method", [SHLRepaymentMethod.PIK, SHLRepaymentMethod.ACCRUED,
    SHLRepaymentMethod.PIK_THEN_SWEEP, SHLRepaymentMethod.PARTIAL_PAY_SWEEP, SHLRepaymentMethod.FCF_WATERFALL,
    None, "cash_sweep", True])
def test_unproven_shl_modes_fail_closed(method):
    with pytest.raises(FinancingError, match=UNRESOLVED):
        map_legacy_financing(project(clean_shl_repayment_method=method))


@pytest.mark.parametrize("mode", [None, "equity_only", "share_capital_then_shl", True])
def test_missing_or_coerced_funding_mode_is_not_an_authority(mode):
    with pytest.raises(FinancingError, match=UNRESOLVED):
        map_legacy_financing(project(sponsor_funding_mode=mode))


def test_explicit_equity_residual_equity_and_no_shl():
    pi = project(sponsor_funding_mode=SponsorFundingMode.EQUITY_ONLY, clean_shl_repayment_method=None,
                 share_capital_keur=400, share_premium_keur=50, other_equity_funding_before_shl_keur=30)
    values = by_id(map_legacy_financing(pi))
    assert "legacy-shl" not in values
    assert values["legacy-share-capital"].commitment_keur == 400
    assert values["legacy-share-premium"].commitment_keur == 50
    assert values["legacy-other-committed-equity"].commitment_keur == 30
    assert values["legacy-additional-equity"].commitment_keur is None


@pytest.mark.parametrize("kwargs", [dict(debt_sizing_mode=None), dict(debt_sizing_mode="gearing_cap"),
    dict(senior_tenor_years=0), dict(senior_tenor_years=True), dict(senior_tenor_years=100),
    dict(shl_maturity_period_index=None), dict(shl_maturity_period_index=999),
    dict(junior_or_other_project_funding_keur=1)])
def test_missing_or_unrepresentable_authority_fails_closed(kwargs):
    with pytest.raises(FinancingError, match=UNRESOLVED):
        map_legacy_financing(project(**kwargs))


@pytest.mark.parametrize("section", ["info", "financing", "revenue"])
def test_missing_legacy_sections_fail_with_typed_mapping_error(section):
    with pytest.raises(FinancingError, match=UNRESOLVED):
        map_legacy_financing(replace(project(), **{section: None}))


def test_mapping_never_turns_the_legacy_senior_anchor_into_an_amount():
    a = project()
    b = project(fixed_debt_keur=999999)
    assert map_legacy_financing(a).content_digest() == map_legacy_financing(b).content_digest()
    assert by_id(map_legacy_financing(b))["legacy-senior"].commitment_keur is None


def test_legacy_amortization_label_is_not_repayment_authority():
    assert map_legacy_financing(project()).content_digest() == map_legacy_financing(
        project(amortization_type="documentary-only")).content_digest()


def test_invalid_calendar_cannot_invent_maturity():
    pi = project()
    with pytest.raises(FinancingError, match=UNRESOLVED):
        map_legacy_financing(replace(pi, info=replace(pi.info, cod_date=date(2099, 1, 1))))


@pytest.mark.parametrize("field,bad", [("share_capital_keur", "400"), ("share_premium_keur", -1e-12),
                                      ("other_equity_funding_before_shl_keur", float("nan")), ("shl_rate", ".06")])
def test_legacy_numbers_are_not_coerced_or_silently_dropped(field, bad):
    with pytest.raises(FinancingError):
        map_legacy_financing(project(**{field: bad}))


def test_maturity_reuses_calendar_axis_with_leap_day_not_fc_plus_tenor():
    from dateutil.relativedelta import relativedelta
    pi = project(sponsor_funding_mode=SponsorFundingMode.EQUITY_ONLY)
    info = replace(pi.info, financial_close=date(2028, 2, 29),
                   cod_date=date(2028, 2, 29) + relativedelta(months=pi.info.construction_months),
                   period_axis_convention=PeriodAxisConvention.OPERATING_BOUNDARY_SINGLE_CONSTRUCTION_COLUMN)
    mapped = map_legacy_financing_with_authority(replace(pi, info=info))
    assert mapped.senior_contractual_maturity_date != info.financial_close + relativedelta(years=pi.financing.senior_tenor_years)
    assert by_id(mapped.collection)["legacy-senior"].repayment.maturity_date is None


@pytest.mark.parametrize("frequency", [PeriodFrequency.ANNUAL, PeriodFrequency.QUARTERLY, "Semestrial"])
def test_unsupported_period_frequency_not_silently_read_as_semiannual(frequency):
    pi = project()
    with pytest.raises(FinancingError, match=UNRESOLVED):
        map_legacy_financing(replace(pi, info=replace(pi.info, period_frequency=frequency)))


def test_legacy_mapping_does_not_call_financial_engine_or_persistence(monkeypatch):
    from app.services import production_financial_authority
    from app.persistence import db
    import financial_engine.shareholder_waterfall as waterfall
    def forbidden(*args, **kwargs):
        pytest.fail("proposal mapping attempted financial execution or persistence")
    monkeypatch.setattr(production_financial_authority, "run_clean_production", forbidden)
    monkeypatch.setattr(waterfall, "run_project_shareholder_waterfall_model", forbidden)
    monkeypatch.setattr(db, "get_connection", forbidden)
    assert map_legacy_financing(project()).instruments


def test_no_production_import_or_projectinputs_activation():
    allowed = {ROOT / "finco_core/inputs/financing_instruments.py",
               ROOT / "finco_core/inputs/financing_instruments_legacy.py"}
    offenders = []
    for name in ("app", "financial_engine", "finco_core", "domain", "main_web.py", "main_api.py"):
        root = ROOT / name
        paths = [root] if root.is_file() else root.rglob("*.py")
        for path in paths:
            if path in allowed:
                continue
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"))):
                names = [a.name for a in node.names] if isinstance(node, ast.Import) else (
                    [node.module or ""] + [a.name for a in node.names] if isinstance(node, ast.ImportFrom) else [])
                if any("financing_instruments" in value for value in names):
                    offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []
    assert not hasattr(project(), "financing_instruments")
    assert "financing_instruments" not in project_inputs_to_dict(project())


def test_all_documented_error_codes_have_executable_rejections():
    from tests.test_financing_f3_canonical_contract import INVALID_CASES
    spec = (ROOT / "docs/model_v2/financing_f3/F3_TYPED_CONTRACT_SPEC.md").read_text(encoding="utf-8")
    catalogue = spec.split("## 5. Validation catalogue", 1)[1].split("## 6.", 1)[0]
    expected = set(re.findall(r"\bF3_[A-Z_0-9]+\b", catalogue))
    assert expected == {code for code, _ in INVALID_CASES} | {UNRESOLVED}
