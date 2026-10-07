"""Developer Economics V1 — typed end-to-end financial authority.

Developer Economics is a SEPARATE investor/developer ledger:
  A. development spend (developer ledger: negative, dated),
  B. development cost reimbursement (project USE at FC / developer receipt),
  C. developer fee (project USE at FC / developer receipt).

Proven here, against the real Solar/Wind reference economics:
  typed fail-closed input · serialization · input hashing · disabled bit-exact
  no-op · dating authority · fixed and non-circular percentage fee · developer
  vector · MOIC/IRR availability semantics · project-use treatment and financing
  propagation · no double counting / no sponsor-ledger injection · Assumption
  Register · Calculation Trace · Canonical Analytics.

Active Developer Economics legitimately changes project/sponsor results (it adds
project uses that the canonical financing policy funds); those results are NOT
asserted equal to the disabled case. Only misclassification, double counting and
canonical financing propagation are asserted.
"""
from __future__ import annotations

import dataclasses
import enum
import math
import re
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from app.model_v2.assumption_register import (
    AssumptionSourceKind,
    RegisterContext,
    RunIdentity,
    build_assumption_register,
    engine_version,
    workbook_version,
)
from app.model_v2.calculation_trace import build_calculation_trace
from app.model_v2.canonical_analytics import (
    CanonicalMetricStatus,
    MetricCategory,
    build_canonical_analytics,
)
from app.project_factories import (
    create_generic_solar_reference,
    create_generic_wind_reference,
)
from app.services.production_financial_authority import run_clean_production
from finco_core.inputs import (
    DeveloperFeeMode,
    DeveloperSettlementAuthority,
    DevelopmentEconomicsInput,
    DevelopmentOutcome,
    DevelopmentSpendEntry,
    hash_inputs_for_cache,
    project_inputs_from_dict,
    project_inputs_to_dict,
)
from finco_core.sponsor.xirr import xirr
from financial_engine.developer_economics import (
    DeveloperMetricStatus,
    compute_developer_economics,
    resolve_developer_project_uses,
)
from financial_engine.financing.generic_product_policy import build_sources_and_uses
from financial_engine.financing.project_uses import compute_project_uses
from financial_engine.sponsor_returns.contracts import ReturnMetricStatus

REPO = Path(__file__).resolve().parents[1]
TOL = 1e-9

# Distinctive amounts: unlikely to collide with any engine-derived number.
SPEND_1 = 1234.567
SPEND_2 = 765.433
REIMBURSED = 1500.0
FEE = 400.0


def _spend(*pairs):
    return tuple(DevelopmentSpendEntry(d, a) for d, a in pairs)


def _active(**overrides) -> DevelopmentEconomicsInput:
    base = dict(
        enabled=True,
        spend_schedule=_spend((date(2029, 3, 31), SPEND_1), (date(2029, 9, 30), SPEND_2)),
        reimbursed_development_cost_keur=REIMBURSED,
        developer_fee_value=FEE,
    )
    base.update(overrides)
    return DevelopmentEconomicsInput(**base)


def _flatten(obj, path="", out=None, depth=0, _seen=None):
    """Leaf map of a result tree (numerics/strings/enums), for bit-exact comparison."""
    out = {} if out is None else out
    _seen = set() if _seen is None else _seen
    if depth > 16:
        return out
    if obj is None or isinstance(obj, (bool, str)):
        out[path] = repr(obj)
        return out
    if isinstance(obj, (int, float)):
        out[path] = repr(obj)
        return out
    if isinstance(obj, enum.Enum):
        out[path] = repr(obj.value)
        return out
    if isinstance(obj, date):
        out[path] = obj.isoformat()
        return out
    if id(obj) in _seen:
        return out
    _seen = _seen | {id(obj)}
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        for f in dataclasses.fields(obj):
            _flatten(getattr(obj, f.name), f"{path}.{f.name}", out, depth + 1, _seen)
    elif isinstance(obj, dict):
        for k in sorted(obj, key=str):
            _flatten(obj[k], f"{path}[{k}]", out, depth + 1, _seen)
    elif isinstance(obj, (list, tuple, set)):
        for i, v in enumerate(obj):
            _flatten(v, f"{path}[{i}]", out, depth + 1, _seen)
    elif hasattr(obj, "__dict__"):
        for k, v in sorted(vars(obj).items()):
            if not k.startswith("_"):
                _flatten(v, f"{path}.{k}", out, depth + 1, _seen)
    else:
        try:
            import numpy as np

            if isinstance(obj, np.ndarray):
                for i, v in enumerate(obj.tolist()):
                    _flatten(v, f"{path}[{i}]", out, depth + 1, _seen)
        except ImportError:
            pass
    return out


def _results_leaves(run) -> dict[str, str]:
    leaves = _flatten(run.g2c_result, "g2c")
    leaves.update(_flatten(run.financial_statements_result, "statements"))
    return {k: v for k, v in leaves.items() if "development_economics" not in k}


# ---------------------------------------------------------------------------
# Shared real-engine runs (module scoped: each engine run is expensive)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def solar_inputs():
    return create_generic_solar_reference()


@pytest.fixture(scope="module")
def solar_off(solar_inputs):
    return run_clean_production(solar_inputs, "Base", project_type="solar")


@pytest.fixture(scope="module")
def solar_disabled(solar_inputs):
    return run_clean_production(
        replace(solar_inputs, development_economics=DevelopmentEconomicsInput()),
        "Base", project_type="solar")


@pytest.fixture(scope="module")
def solar_on(solar_inputs):
    return run_clean_production(
        replace(solar_inputs, development_economics=_active()),
        "Base", project_type="solar")


@pytest.fixture(scope="module")
def wind_inputs():
    return create_generic_wind_reference()


@pytest.fixture(scope="module")
def wind_off(wind_inputs):
    return run_clean_production(wind_inputs, "Base", project_type="wind")


@pytest.fixture(scope="module")
def wind_disabled(wind_inputs):
    return run_clean_production(
        replace(wind_inputs, development_economics=DevelopmentEconomicsInput()),
        "Base", project_type="wind")


# ===========================================================================
# 1. Typed input validation — fail closed
# ===========================================================================

class TestTypedInputFailsClosed:
    def test_default_is_a_disabled_neutral_noop(self):
        default = DevelopmentEconomicsInput()
        assert default.enabled is False and default.is_active is False
        assert default.spend_schedule == ()
        assert default.reimbursed_development_cost_keur == 0.0
        assert default.developer_fee_value == 0.0     # no default fee is fabricated
        assert default.total_development_spend_keur == 0.0

    @pytest.mark.parametrize("bad", [1, 0, "true", None])
    def test_enabled_must_be_strict_bool(self, bad):
        with pytest.raises(ValueError, match="DEV_ECON_INVALID_ENABLED"):
            DevelopmentEconomicsInput(enabled=bad)

    @pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf"), -1.0, True, "5"])
    def test_reimbursement_must_be_finite_non_negative_real(self, bad):
        with pytest.raises(ValueError, match="DEV_ECON_INVALID"):
            _active(reimbursed_development_cost_keur=bad)

    @pytest.mark.parametrize("bad", [float("nan"), float("inf"), -0.01, True, "5"])
    def test_fee_must_be_finite_non_negative_real(self, bad):
        with pytest.raises(ValueError, match="DEV_ECON_INVALID"):
            _active(developer_fee_value=bad)

    @pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1.0, True, "5"])
    def test_spend_amount_must_be_finite_non_negative_real(self, bad):
        with pytest.raises(ValueError, match="DEV_ECON_INVALID_SPEND_AMOUNT"):
            DevelopmentSpendEntry(date(2029, 1, 1), bad)

    def test_spend_date_must_be_a_real_date(self):
        from datetime import datetime

        for bad in ("2029-01-01", None, datetime(2029, 1, 1, 12, 0), 20290101):
            with pytest.raises(ValueError, match="DEV_ECON_INVALID_SPEND_DATE"):
                DevelopmentSpendEntry(bad, 10.0)

    def test_schedule_must_be_a_tuple_of_typed_entries(self):
        with pytest.raises(ValueError, match="DEV_ECON_INVALID_SCHEDULE"):
            _active(spend_schedule=[DevelopmentSpendEntry(date(2029, 1, 1), 10.0)])
        with pytest.raises(ValueError, match="DEV_ECON_INVALID_SCHEDULE"):
            _active(spend_schedule=((date(2029, 1, 1), 10.0),))

    def test_schedule_dates_must_be_strictly_increasing_and_unique(self):
        d = date(2029, 6, 30)
        for schedule in (_spend((d, 1.0), (d, 2.0)),
                         _spend((date(2029, 9, 30), 1.0), (d, 2.0))):
            with pytest.raises(ValueError, match="DEV_ECON_INVALID_SCHEDULE_ORDER"):
                _active(spend_schedule=schedule, reimbursed_development_cost_keur=0.0)

    def test_enum_fields_are_strictly_typed(self):
        for kw in ({"outcome": "REALIZED"}, {"developer_fee_mode": "FIXED_KEUR"},
                   {"settlement": "AT_FINANCIAL_CLOSE"}):
            with pytest.raises(ValueError, match="DEV_ECON_INVALID_ENUM"):
                _active(**kw)

    def test_reimbursement_cannot_exceed_eligible_spend(self):
        with pytest.raises(ValueError, match="REIMBURSEMENT_EXCEEDS_ELIGIBLE"):
            _active(reimbursed_development_cost_keur=SPEND_1 + SPEND_2 + 0.01)
        # exactly the eligible amount is allowed
        ok = _active(reimbursed_development_cost_keur=SPEND_1 + SPEND_2)
        assert ok.reimbursed_development_cost_keur == pytest.approx(SPEND_1 + SPEND_2)
        # no spend => nothing is eligible
        with pytest.raises(ValueError, match="REIMBURSEMENT_EXCEEDS_ELIGIBLE"):
            DevelopmentEconomicsInput(enabled=True, reimbursed_development_cost_keur=1.0)

    def test_percentage_fee_is_a_zero_to_one_fraction(self):
        with pytest.raises(ValueError, match="DEV_ECON_INVALID_FEE"):
            _active(developer_fee_mode=DeveloperFeeMode.PCT_OF_HARD_CAPEX,
                    developer_fee_value=5.0)
        assert _active(developer_fee_mode=DeveloperFeeMode.PCT_OF_HARD_CAPEX,
                       developer_fee_value=0.05).developer_fee_value == 0.05

    def test_abandoned_carries_no_receipts_and_needs_spend(self):
        for kw in ({"reimbursed_development_cost_keur": 1.0}, {"developer_fee_value": 1.0}):
            with pytest.raises(ValueError, match="ABANDONED_WITH_RECEIPTS"):
                _active(outcome=DevelopmentOutcome.ABANDONED,
                        **{"reimbursed_development_cost_keur": 0.0, "developer_fee_value": 0.0, **kw})
        with pytest.raises(ValueError, match="ABANDONED_WITHOUT_SPEND"):
            DevelopmentEconomicsInput(enabled=True, outcome=DevelopmentOutcome.ABANDONED)

    def test_enabled_but_economically_empty_is_rejected_not_interpreted(self):
        with pytest.raises(ValueError, match="ENABLED_WITHOUT_ECONOMICS"):
            DevelopmentEconomicsInput(enabled=True)

    def test_disabled_input_may_carry_latent_values_with_no_effect(self, solar_inputs):
        latent = DevelopmentEconomicsInput(
            enabled=False, spend_schedule=_spend((date(2029, 1, 1), 5.0)),
            developer_fee_value=9.0)
        pi = replace(solar_inputs, development_economics=latent)
        assert resolve_developer_project_uses(pi).total_keur == 0.0
        assert compute_developer_economics(pi) is None

    def test_spend_after_financial_close_fails_closed_in_the_engine(self, solar_inputs):
        fc = solar_inputs.info.financial_close
        late = _active(spend_schedule=_spend((date(fc.year, fc.month, fc.day), 10.0),
                                             (date(fc.year + 1, 1, 1), 10.0)),
                       reimbursed_development_cost_keur=0.0)
        pi = replace(solar_inputs, development_economics=late)
        for fn in (resolve_developer_project_uses, compute_developer_economics,
                   compute_project_uses):
            with pytest.raises(ValueError, match="DEV_ECON_SPEND_AFTER_FINANCIAL_CLOSE"):
                fn(pi)

    def test_spend_on_the_financial_close_date_itself_is_pre_fc_cash_boundary(self, solar_inputs):
        fc = solar_inputs.info.financial_close
        edge = _active(spend_schedule=_spend((fc, 10.0)), reimbursed_development_cost_keur=0.0)
        assert compute_developer_economics(replace(solar_inputs, development_economics=edge))


# ===========================================================================
# 2. Serialization + deterministic input hashing
# ===========================================================================

class TestSerializationAndHash:
    def test_round_trip_is_lossless(self, solar_inputs):
        for config in (_active(),
                       _active(developer_fee_mode=DeveloperFeeMode.PCT_OF_HARD_CAPEX,
                               developer_fee_value=0.04),
                       DevelopmentEconomicsInput(),
                       _active(outcome=DevelopmentOutcome.ABANDONED,
                               reimbursed_development_cost_keur=0.0, developer_fee_value=0.0)):
            pi = replace(solar_inputs, development_economics=config)
            restored = project_inputs_from_dict(project_inputs_to_dict(pi))
            assert restored.development_economics == config

    def test_absent_capability_is_not_serialized_so_existing_payloads_are_unchanged(self, solar_inputs):
        payload = project_inputs_to_dict(solar_inputs)
        assert "development_economics" not in payload
        assert project_inputs_from_dict(payload).development_economics is None

    def test_pre_existing_serialized_data_still_loads(self, solar_inputs):
        legacy = project_inputs_to_dict(solar_inputs)
        legacy.pop("development_economics", None)
        assert project_inputs_from_dict(legacy).development_economics is None

    def test_malformed_serialized_authority_fails_closed(self, solar_inputs):
        payload = project_inputs_to_dict(replace(solar_inputs, development_economics=_active()))
        broken = dict(payload["development_economics"], developer_fee_value=float("nan"))
        with pytest.raises(ValueError, match="DEV_ECON_INVALID"):
            project_inputs_from_dict({**payload, "development_economics": broken})
        broken = dict(payload["development_economics"], outcome="NOT_A_STATE")
        with pytest.raises(ValueError):
            project_inputs_from_dict({**payload, "development_economics": broken})

    def test_hash_is_deterministic(self, solar_inputs):
        pi = replace(solar_inputs, development_economics=_active())
        assert hash_inputs_for_cache(pi) == hash_inputs_for_cache(
            replace(solar_inputs, development_economics=_active()))

    def test_absent_and_disabled_share_one_neutral_identity(self, solar_inputs):
        absent = hash_inputs_for_cache(solar_inputs)
        assert hash_inputs_for_cache(
            replace(solar_inputs, development_economics=DevelopmentEconomicsInput())) == absent
        latent = DevelopmentEconomicsInput(
            enabled=False, spend_schedule=_spend((date(2029, 1, 1), 5.0)))
        assert hash_inputs_for_cache(replace(solar_inputs, development_economics=latent)) == absent

    @pytest.mark.parametrize("change", [
        dict(reimbursed_development_cost_keur=REIMBURSED - 1.0),
        dict(developer_fee_value=FEE + 1.0),
        dict(developer_fee_mode=DeveloperFeeMode.PCT_OF_HARD_CAPEX, developer_fee_value=0.01),
        dict(spend_schedule=_spend((date(2029, 3, 31), SPEND_1), (date(2029, 10, 31), SPEND_2))),
        dict(spend_schedule=_spend((date(2029, 3, 31), SPEND_1 + 1.0), (date(2029, 9, 30), SPEND_2))),
    ])
    def test_every_economic_field_changes_the_hash(self, solar_inputs, change):
        base = hash_inputs_for_cache(replace(solar_inputs, development_economics=_active()))
        changed = hash_inputs_for_cache(
            replace(solar_inputs, development_economics=_active(**change)))
        assert changed != base
        assert changed != hash_inputs_for_cache(solar_inputs)

    def test_active_differs_from_absent(self, solar_inputs):
        assert hash_inputs_for_cache(
            replace(solar_inputs, development_economics=_active())
        ) != hash_inputs_for_cache(solar_inputs)


# ===========================================================================
# 3. Developer ledger: dating, fee bases, vector, MOIC / IRR semantics
# ===========================================================================

class TestDeveloperLedger:
    def test_reimbursement_and_fee_settle_at_the_canonical_financial_close(self, solar_inputs):
        result = compute_developer_economics(
            replace(solar_inputs, development_economics=_active()))
        fc = solar_inputs.info.financial_close
        assert result.settlement_date == fc
        settle = [r for r in result.cashflows if r.cashflow_date == fc]
        assert len(settle) == 1
        assert settle[0].development_cost_reimbursement_keur == REIMBURSED
        assert settle[0].developer_fee_keur == FEE
        assert settle[0].development_spend_keur == 0.0   # spend is pre-FC

    def test_reimbursement_and_fee_are_two_distinct_never_collapsed_fields(self, solar_inputs):
        uses = resolve_developer_project_uses(
            replace(solar_inputs, development_economics=_active()))
        assert uses.development_cost_reimbursement_keur == REIMBURSED
        assert uses.developer_fee_keur == FEE
        assert uses.total_keur == REIMBURSED + FEE
        names = {f.name for f in dataclasses.fields(uses)}
        assert {"development_cost_reimbursement_keur", "developer_fee_keur"} <= names

    def test_spend_is_dated_exactly_as_typed_and_negative_in_the_developer_vector(self, solar_inputs):
        result = compute_developer_economics(
            replace(solar_inputs, development_economics=_active()))
        spend_rows = [r for r in result.cashflows if r.development_spend_keur > 0.0]
        assert [(r.cashflow_date, r.development_spend_keur) for r in spend_rows] == [
            (date(2029, 3, 31), SPEND_1), (date(2029, 9, 30), SPEND_2)]
        assert all(r.net_developer_cashflow_keur == -r.development_spend_keur for r in spend_rows)
        assert [r.cashflow_date for r in result.cashflows] == sorted(
            r.cashflow_date for r in result.cashflows)
        assert result.total_development_spend_keur == pytest.approx(SPEND_1 + SPEND_2)

    def test_fixed_fee(self, solar_inputs):
        result = compute_developer_economics(
            replace(solar_inputs, development_economics=_active(developer_fee_value=250.0)))
        assert result.developer_fee_keur == 250.0
        assert result.fee_basis.mode == "FIXED_KEUR" and result.fee_basis.basis_keur is None

    def test_percentage_fee_is_sized_on_the_pre_fee_hard_capex_basis(self, solar_inputs):
        config = _active(developer_fee_mode=DeveloperFeeMode.PCT_OF_HARD_CAPEX,
                         developer_fee_value=0.02)
        pi = replace(solar_inputs, development_economics=config)
        result = compute_developer_economics(pi)
        hard_capex = solar_inputs.capex.hard_capex_keur
        assert result.fee_basis.basis_keur == hard_capex
        assert result.developer_fee_keur == pytest.approx(0.02 * hard_capex)
        assert "non-circular" in result.fee_basis.basis_authority

    def test_percentage_fee_basis_is_non_circular(self, solar_inputs):
        """The fee never sizes itself: its basis is independent of the fee, of the
        financing stack and of total project uses (which include the fee)."""
        config = _active(developer_fee_mode=DeveloperFeeMode.PCT_OF_HARD_CAPEX,
                         developer_fee_value=0.02)
        base = replace(solar_inputs, development_economics=config)
        fee = compute_developer_economics(base).developer_fee_keur
        # 1. basis ignores the financing structure that funds the fee
        regeared = replace(base, financing=replace(base.financing, gearing_ratio=0.5))
        assert compute_developer_economics(regeared).developer_fee_keur == fee
        # 2. changing the fee value changes only the fee, not the basis
        bigger = replace(base, development_economics=replace(config, developer_fee_value=0.04))
        assert compute_developer_economics(bigger).fee_basis.basis_keur == \
            compute_developer_economics(base).fee_basis.basis_keur
        # 3. the basis is NOT total project uses (which includes the fee itself)
        total = compute_project_uses(base).total_project_uses_keur
        assert total > compute_developer_economics(base).fee_basis.basis_keur
        assert fee != pytest.approx(0.02 * total)
        # 4. the basis is a pure CAPEX input: exactly the hard-capex authority
        assert compute_developer_economics(base).fee_basis.basis_keur == \
            solar_inputs.capex.hard_capex_keur

    def test_moic_is_receipts_over_spend(self, solar_inputs):
        result = compute_developer_economics(
            replace(solar_inputs, development_economics=_active()))
        receipts = REIMBURSED + FEE
        assert result.total_developer_receipts_keur == receipts
        assert result.developer_moic == pytest.approx(receipts / (SPEND_1 + SPEND_2))
        assert result.developer_moic_status is DeveloperMetricStatus.OK

    def test_valid_developer_irr_is_xirr_over_the_dated_vector(self, solar_inputs):
        result = compute_developer_economics(
            replace(solar_inputs, development_economics=_active()))
        assert result.developer_xirr_status is DeveloperMetricStatus.OK
        values = [r.net_developer_cashflow_keur for r in result.cashflows]
        dates = [r.cashflow_date for r in result.cashflows]
        assert any(v < 0 for v in values) and any(v > 0 for v in values)
        reference = xirr(values, dates)      # independent call to the canonical solver
        assert reference is not None
        assert result.developer_xirr == pytest.approx(reference, abs=1e-9)
        assert -1.0 < result.developer_xirr < 0.0   # receipts 1,900 < spend 2,000

    def test_irr_is_unavailable_without_a_sign_change_never_fabricated(self, solar_inputs):
        # spend > 0, receipts = 0 (realized but nothing reimbursed, no fee)
        no_receipts = replace(solar_inputs, development_economics=_active(
            reimbursed_development_cost_keur=0.0, developer_fee_value=0.0))
        result = compute_developer_economics(no_receipts)
        assert result.developer_xirr is None
        assert result.developer_xirr_status is DeveloperMetricStatus.NO_POSITIVE_CASHFLOW
        # spend = 0, fee only
        fee_only = replace(solar_inputs, development_economics=DevelopmentEconomicsInput(
            enabled=True, developer_fee_value=300.0))
        result = compute_developer_economics(fee_only)
        assert result.developer_xirr is None            # no -100% / 0% invented
        assert result.developer_xirr_status is DeveloperMetricStatus.NO_NEGATIVE_CASHFLOW

    def test_moic_is_a_legitimate_zero_for_spent_but_unrealized(self, solar_inputs):
        abandoned = replace(solar_inputs, development_economics=_active(
            outcome=DevelopmentOutcome.ABANDONED,
            reimbursed_development_cost_keur=0.0, developer_fee_value=0.0))
        result = compute_developer_economics(abandoned)
        assert result.developer_moic == 0.0 and result.developer_moic is not None
        assert result.developer_moic_status is DeveloperMetricStatus.OK
        assert result.developer_xirr is None
        assert result.developer_xirr_status is DeveloperMetricStatus.NO_POSITIVE_CASHFLOW
        assert result.total_developer_receipts_keur == 0.0
        assert result.outcome == "ABANDONED"
        # an abandoned development creates NO project use
        assert resolve_developer_project_uses(abandoned).total_keur == 0.0

    def test_moic_is_unavailable_when_the_denominator_has_no_authority(self, solar_inputs):
        fee_only = replace(solar_inputs, development_economics=DevelopmentEconomicsInput(
            enabled=True, developer_fee_value=300.0))
        result = compute_developer_economics(fee_only)
        assert result.total_development_spend_keur == 0.0
        assert result.developer_moic is None
        assert result.developer_moic_status is DeveloperMetricStatus.ZERO_CONTRIBUTION
        assert result.total_developer_receipts_keur == 300.0

    def test_same_date_flows_net_into_one_dated_row(self, solar_inputs):
        fc = solar_inputs.info.financial_close
        config = _active(spend_schedule=_spend((date(2029, 6, 30), 1000.0), (fc, 100.0)),
                         reimbursed_development_cost_keur=1050.0, developer_fee_value=200.0)
        result = compute_developer_economics(replace(solar_inputs, development_economics=config))
        row = [r for r in result.cashflows if r.cashflow_date == fc][0]
        assert (row.development_spend_keur, row.development_cost_reimbursement_keur,
                row.developer_fee_keur) == (100.0, 1050.0, 200.0)
        assert row.net_developer_cashflow_keur == pytest.approx(1050.0 + 200.0 - 100.0)
        assert len({r.cashflow_date for r in result.cashflows}) == len(result.cashflows)

    def test_inactive_returns_no_ledger_and_no_uses(self, solar_inputs):
        assert compute_developer_economics(solar_inputs) is None
        assert resolve_developer_project_uses(solar_inputs).total_keur == 0.0

    def test_status_vocabulary_matches_the_repository_return_status(self):
        for status in DeveloperMetricStatus:
            assert ReturnMetricStatus(status.value).value == status.value


# ===========================================================================
# 4. Project uses + canonical financing propagation + no double counting
# ===========================================================================

class TestProjectUsesAndFinancing:
    def test_inactive_project_uses_are_unchanged_and_carry_no_developer_use(self, solar_inputs):
        uses = compute_project_uses(solar_inputs)
        assert uses.development_cost_reimbursement_keur == 0.0
        assert uses.developer_fee_keur == 0.0
        assert uses.total_project_uses_keur == pytest.approx(
            uses.hard_project_capex_keur + uses.explicit_financing_cost_uses_keur
            + uses.reserve_account_funding_keur + uses.other_explicit_project_uses_keur)

    def test_active_uses_add_exactly_reimbursement_plus_fee_once(self, solar_inputs):
        base = compute_project_uses(solar_inputs)
        active = compute_project_uses(
            replace(solar_inputs, development_economics=_active()))
        assert active.development_cost_reimbursement_keur == REIMBURSED
        assert active.developer_fee_keur == FEE
        assert active.total_project_uses_keur - base.total_project_uses_keur == \
            pytest.approx(REIMBURSED + FEE)
        # the developer uses are NOT hidden inside any pre-existing use bucket
        assert active.hard_project_capex_keur == base.hard_project_capex_keur
        assert active.explicit_financing_cost_uses_keur == base.explicit_financing_cost_uses_keur
        assert active.reserve_account_funding_keur == base.reserve_account_funding_keur
        assert active.other_explicit_project_uses_keur == 0.0
        assert active.total_project_uses_keur == pytest.approx(
            active.hard_project_capex_keur + active.explicit_financing_cost_uses_keur
            + active.reserve_account_funding_keur + active.other_explicit_project_uses_keur
            + active.development_cost_reimbursement_keur + active.developer_fee_keur)

    def test_percentage_fee_flows_into_project_uses_as_fraction_of_hard_capex(self, solar_inputs):
        config = _active(developer_fee_mode=DeveloperFeeMode.PCT_OF_HARD_CAPEX,
                         developer_fee_value=0.03)
        uses = compute_project_uses(replace(solar_inputs, development_economics=config))
        assert uses.developer_fee_keur == pytest.approx(0.03 * solar_inputs.capex.hard_capex_keur)

    def test_abandoned_does_not_change_the_project_uses(self, solar_inputs):
        abandoned = _active(outcome=DevelopmentOutcome.ABANDONED,
                            reimbursed_development_cost_keur=0.0, developer_fee_value=0.0)
        assert compute_project_uses(
            replace(solar_inputs, development_economics=abandoned)
        ) == compute_project_uses(solar_inputs)

    def test_financing_responds_through_the_canonical_policy(self, solar_inputs, solar_off, solar_on):
        fin_off = solar_off.g2c_result.financing_result
        fin_on = solar_on.g2c_result.financing_result
        # total uses rise by at least the developer uses (financing costs follow the
        # larger funded base through the existing fixed point)
        assert fin_on.project_uses.total_project_uses_keur - \
            fin_off.project_uses.total_project_uses_keur >= REIMBURSED + FEE - TOL
        # canonical gearing applies to the incremental uses: senior = gearing x uses
        gearing = solar_inputs.financing.gearing_ratio
        for fin in (fin_off, fin_on):
            assert fin.final_senior_commitment_keur == pytest.approx(
                gearing * fin.project_uses.total_project_uses_keur, rel=1e-9)
        assert fin_on.final_senior_commitment_keur > fin_off.final_senior_commitment_keur
        # the sponsor funds the remainder through the existing source waterfall
        assert fin_on.derived_shl_cash_principal_keur > fin_off.derived_shl_cash_principal_keur

    def test_sources_and_uses_balance_and_itemise_the_developer_uses(self, solar_on):
        fin = solar_on.g2c_result.financing_result
        su = build_sources_and_uses(fin)
        assert su.development_cost_reimbursement_keur == REIMBURSED
        assert su.developer_fee_keur == FEE
        assert su.difference_keur == pytest.approx(0.0, abs=1e-6)
        assert su.total_sources_keur == pytest.approx(su.total_uses_keur, abs=1e-6)
        itemised = (su.base_project_capex_keur + su.capitalized_idc_keur + su.commitment_fee_keur
                    + su.structuring_fee_keur + su.other_financing_costs_keur
                    + su.initial_dsra_funding_keur + su.other_uses_keur
                    + su.development_cost_reimbursement_keur + su.developer_fee_keur)
        assert itemised == pytest.approx(su.total_uses_keur, abs=1e-6)   # no double count

    def test_construction_audit_funds_the_developer_uses_at_close(self, solar_on):
        funding = solar_on.g2c_result.financing_result.construction_funding
        assert funding.non_construction_fc_use is not None
        assert funding.total_audit_uses_keur == pytest.approx(
            solar_on.g2c_result.financing_result.project_uses.total_project_uses_keur, abs=1e-6)
        assert abs(funding.total_audit_residual_keur) < 1e-6

    def test_project_return_methodology_is_unchanged_and_developer_uses_are_classified(
            self, solar_off, solar_on):
        off = solar_off.g2c_result.return_summary.project
        on = solar_on.g2c_result.return_summary.project
        assert on.project_xirr_status.value == "OK"
        assert on.project_xirr == off.project_xirr           # C1 hard-CAPEX methodology
        assert on.total_hard_capex_investment_keur == off.total_hard_capex_investment_keur
        assert on.other_explicit_project_uses_keur == 0.0     # never UNCLASSIFIED
        assert on.excluded_developer_economics_uses_keur == pytest.approx(REIMBURSED + FEE)
        assert off.excluded_developer_economics_uses_keur == 0.0

    def test_developer_uses_are_capitalised_so_statements_balance(self, solar_on):
        statements = solar_on.financial_statements_result
        assert statements.status.value == "OK"
        checks = [p.balance_check_keur for p in statements.balance_sheet_periods
                  if p.balance_check_keur is not None]
        assert checks and max(abs(c) for c in checks) < 1e-6
        basis = solar_on.g2c_result.financing_result.book_depreciable_asset_basis
        components = {c.code: c for c in basis.components}
        assert components["development_cost_reimbursement"].amount_keur == REIMBURSED
        assert components["developer_fee"].amount_keur == FEE
        assert components["developer_fee"].provenance == \
            "DEVELOPER_ECONOMICS_V1_CAPITALISED_PROJECT_USE"

    def test_run_carries_the_developer_ledger_exactly_as_computed_once(self, solar_inputs, solar_on):
        direct = compute_developer_economics(solar_on.project_inputs)
        assert solar_on.developer_economics_result == direct
        assert solar_on.developer_economics_result.developer_moic == pytest.approx(
            (REIMBURSED + FEE) / (SPEND_1 + SPEND_2))

    def test_scenario_application_preserves_the_typed_authority(self, solar_inputs):
        from app.scenario_manager import ScenarioManager

        pi = replace(solar_inputs, development_economics=_active())
        mutated = ScenarioManager("solar").apply_overrides(pi, "Base")
        assert mutated.development_economics == pi.development_economics


# ===========================================================================
# 5. Ledger isolation: developer flows never enter the sponsor ledger
# ===========================================================================

class TestSponsorLedgerIsolation:
    SPONSOR_PACKAGES = (
        "financial_engine/shareholder_waterfall",
        "financial_engine/sponsor_returns",
        "financial_engine/shl",
        "finco_core/sponsor",
    )

    def test_sponsor_and_waterfall_code_never_references_developer_economics(self):
        for package in self.SPONSOR_PACKAGES:
            for path in (REPO / package).rglob("*.py"):
                text = path.read_text(encoding="utf-8").lower()
                assert "developer_economics" not in text, path
                assert "developer_fee" not in text, path
                assert "development_cost_reimbursement" not in text, path

    def test_no_developer_amount_appears_in_any_sponsor_return_vector(self, solar_on):
        summary = solar_on.g2c_result.return_summary
        leaves = {}
        for name in ("legal_equity", "total_sponsor"):
            _flatten(getattr(summary, name), name, leaves)
        _flatten(solar_on.g2c_result.pure_equity_xirr, "pure_equity_xirr", leaves)
        numeric = []
        for value in leaves.values():
            try:
                numeric.append(float(value))
            except ValueError:
                continue
        assert numeric, "sponsor return leaves must exist"
        for developer_amount in (SPEND_1, SPEND_2, REIMBURSED, FEE, SPEND_1 + SPEND_2,
                                 REIMBURSED + FEE):
            assert all(abs(v - developer_amount) > 1e-6 for v in numeric), developer_amount

    def test_developer_cashflows_are_not_sponsor_contributions_or_distributions(self, solar_on):
        ledger = solar_on.developer_economics_result
        sponsor_dates = {
            period.cashflow_date
            for period in solar_on.g2c_result.financing_result.construction_funding.periods
            if period.cashflow_date is not None
        }
        developer_pre_fc = {r.cashflow_date for r in ledger.cashflows
                            if r.development_spend_keur > 0.0}
        assert developer_pre_fc and not (developer_pre_fc & sponsor_dates)


# ===========================================================================
# 6. Assumption Register / Calculation Trace / Canonical Analytics
# ===========================================================================

@pytest.fixture(scope="module")
def traced(solar_on):
    context = RegisterContext.for_working_copy(state_provenance=AssumptionSourceKind.USER_INPUT)
    register = build_assumption_register(solar_on.project_inputs, context)
    trace = build_calculation_trace(solar_on, context=context, assumption_register=register)
    return register, trace


class TestRegisterTraceAnalytics:
    def test_assumption_register_exposes_typed_inputs_with_their_source(self, traced):
        register, _ = traced
        section = {e.assumption_id: e for e in register.section("DEVELOPER")}
        assert section["developer.enabled"].value is True
        assert section["developer.outcome"].value == "REALIZED"
        assert section["developer.reimbursed_development_cost_keur"].value == REIMBURSED
        assert section["developer.fee_mode"].value == "FIXED_KEUR"
        assert section["developer.fee_value"].value == FEE
        assert section["developer.fee_value"].unit == "kEUR"
        assert section["developer.settlement"].value == "AT_FINANCIAL_CLOSE"
        assert section["developer.spend[0].date"].value == "2029-03-31"
        assert section["developer.spend[1].amount_keur"].value == SPEND_2
        assert {e.source_kind for e in section.values()} == {AssumptionSourceKind.USER_INPUT}

    def test_register_omits_the_section_when_inactive_so_it_is_unchanged(
            self, solar_inputs, solar_disabled):
        context = RegisterContext.for_working_copy(
            state_provenance=AssumptionSourceKind.FACTORY_DEFAULT)
        absent = build_assumption_register(solar_inputs, context)
        disabled = build_assumption_register(
            replace(solar_inputs, development_economics=DevelopmentEconomicsInput(enabled=False)), context)
        assert absent.section("DEVELOPER") == () and disabled.section("DEVELOPER") == ()
        assert absent.to_json() == disabled.to_json()

    def test_percentage_basis_is_documented_in_the_register(self, solar_inputs):
        config = _active(developer_fee_mode=DeveloperFeeMode.PCT_OF_HARD_CAPEX,
                         developer_fee_value=0.02)
        register = build_assumption_register(
            replace(solar_inputs, development_economics=config),
            RegisterContext.for_working_copy(state_provenance=AssumptionSourceKind.USER_INPUT))
        entry = {e.assumption_id: e for e in register.section("DEVELOPER")}["developer.fee_value"]
        assert entry.unit == "fraction" and "hard_capex_keur" in entry.notes

    def test_trace_explains_spend_reimbursement_fee_vector_moic_irr(self, traced):
        _, trace = traced
        entry = trace.entry
        ledger_keys = ("developer_total_development_spend_keur",
                       "developer_reimbursed_development_cost_keur",
                       "developer_fee_keur", "developer_total_receipts_keur",
                       "developer_moic", "developer_xirr")
        for key in ledger_keys:
            assert entry(key).authority.endswith("compute_developer_economics")
        assert entry("developer_total_development_spend_keur").output_value == pytest.approx(
            SPEND_1 + SPEND_2)
        assert entry("developer_reimbursed_development_cost_keur").output_value == REIMBURSED
        assert entry("developer_fee_keur").output_value == FEE
        assert entry("developer_total_receipts_keur").referenced_output_keys == (
            "developer_fee_keur", "developer_reimbursed_development_cost_keur")
        assert set(entry("developer_moic").referenced_output_keys) == {
            "developer_total_development_spend_keur", "developer_total_receipts_keur"}
        assert set(entry("developer_xirr").referenced_output_keys) == {
            "developer_total_development_spend_keur",
            "developer_reimbursed_development_cost_keur", "developer_fee_keur"}
        assert "dated developer cash-flow vector" in entry("developer_xirr").notes
        assert "2030-01-01" in entry("developer_xirr").notes     # canonical FC date
        assert entry("developer_xirr").referenced_assumption_ids       # register-linked

    def test_trace_values_are_verbatim_pass_through(self, solar_on, traced):
        _, trace = traced
        ledger = solar_on.developer_economics_result
        assert trace.entry("developer_moic").output_value == ledger.developer_moic
        assert trace.entry("developer_xirr").output_value == ledger.developer_xirr
        assert trace.entry("developer_xirr").status == "OK"

    def test_unavailable_developer_metrics_are_statused_missing_never_zero(self, solar_inputs):
        fee_only = replace(solar_inputs, development_economics=DevelopmentEconomicsInput(
            enabled=True, developer_fee_value=300.0))
        run = run_clean_production(fee_only, "Base", project_type="solar")
        context = RegisterContext.for_working_copy(state_provenance=AssumptionSourceKind.USER_INPUT)
        trace = build_calculation_trace(
            run, context=context,
            assumption_register=build_assumption_register(run.project_inputs, context))
        moic, irr = trace.entry("developer_moic"), trace.entry("developer_xirr")
        assert moic.output_value is None and moic.status == "ZERO_CONTRIBUTION"
        assert irr.output_value is None and irr.status == "NO_NEGATIVE_CASHFLOW"
        assert "never as zero" in irr.notes

    def test_trace_is_unchanged_when_inactive(self, solar_off):
        context = RegisterContext.for_working_copy(
            state_provenance=AssumptionSourceKind.FACTORY_DEFAULT)
        trace = build_calculation_trace(solar_off, context=context)
        assert len(trace.entries) == 12
        assert not [e for e in trace.entries if e.output_key.startswith("developer_")]

    def test_trace_round_trips_with_developer_entries(self, traced):
        from app.model_v2.calculation_trace import CalculationTrace

        _, trace = traced
        assert CalculationTrace.from_json(trace.to_json()).to_json() == trace.to_json()

    def test_canonical_analytics_has_a_typed_developer_category(self, solar_on):
        identity = RunIdentity(
            snapshot_id="DEV-A", composite_hash="hash-DEV-A",
            workbook_version=workbook_version(), engine_version=engine_version(),
            scenario_id="Base")
        snapshot = build_canonical_analytics(solar_on, run_identity=identity)
        developer = {m.metric_id: m for m in snapshot.category(MetricCategory.DEVELOPER.value)}
        assert set(developer) == {
            "developer_total_development_spend_keur",
            "developer_reimbursed_development_cost_keur", "developer_fee_keur",
            "developer_total_receipts_keur", "developer_moic", "developer_xirr"}
        ledger = solar_on.developer_economics_result
        assert developer["developer_moic"].value == ledger.developer_moic
        assert developer["developer_xirr"].value == ledger.developer_xirr
        assert developer["developer_fee_keur"].value == FEE
        assert all(m.status is CanonicalMetricStatus.AVAILABLE for m in developer.values())
        assert developer["developer_xirr"].source_status == "OK"
        # deterministic
        assert snapshot.to_json() == build_canonical_analytics(
            solar_on, run_identity=identity).to_json()

    def test_canonical_analytics_marks_unavailable_developer_metrics(self, solar_inputs):
        fee_only = replace(solar_inputs, development_economics=DevelopmentEconomicsInput(
            enabled=True, developer_fee_value=300.0))
        run = run_clean_production(fee_only, "Base", project_type="solar")
        identity = RunIdentity(
            snapshot_id="DEV-B", composite_hash="hash-DEV-B",
            workbook_version=workbook_version(), engine_version=engine_version(),
            scenario_id="Base")
        snapshot = build_canonical_analytics(run, run_identity=identity)
        moic, irr = snapshot.metric("developer_moic"), snapshot.metric("developer_xirr")
        assert moic.value is None and moic.status is CanonicalMetricStatus.UNAVAILABLE
        assert irr.value is None and irr.status is CanonicalMetricStatus.UNAVAILABLE
        assert snapshot.metric("developer_total_development_spend_keur").value == 0.0   # legit zero

    def test_analytics_has_no_developer_category_when_inactive(self, solar_off):
        identity = RunIdentity(
            snapshot_id="DEV-C", composite_hash="hash-DEV-C",
            workbook_version=workbook_version(), engine_version=engine_version(),
            scenario_id="Base")
        snapshot = build_canonical_analytics(solar_off, run_identity=identity)
        assert snapshot.category(MetricCategory.DEVELOPER.value) == ()


# ===========================================================================
# 7. Disabled / absent state: bit-exact Solar and Wind parity
# ===========================================================================

class TestDisabledStateIsABitExactNoop:
    def test_solar_disabled_is_bit_exact_with_absent(self, solar_off, solar_disabled):
        a, b = _results_leaves(solar_off), _results_leaves(solar_disabled)
        assert len(a) > 10000
        assert a == b
        assert solar_off.developer_economics_result is None
        assert solar_disabled.developer_economics_result is None

    def test_wind_disabled_is_bit_exact_with_absent(self, wind_off, wind_disabled):
        a, b = _results_leaves(wind_off), _results_leaves(wind_disabled)
        assert len(a) > 10000
        assert a == b

    def test_reference_headline_economics_are_the_pinned_values(self, solar_off, wind_off):
        """Pinned by the repository's own validation authority (unchanged)."""
        for run, irr, senior in ((solar_off, 0.11768, 26983.33), (wind_off, 0.13311, 36505.16)):
            assert round(run.g2c_result.return_summary.project.project_xirr, 5) == irr
            assert round(run.g2c_result.financing_result.final_senior_commitment_keur, 2) == senior

    def test_disabled_introduces_no_project_use_and_no_fabricated_fee(self, solar_disabled):
        uses = solar_disabled.g2c_result.financing_result.project_uses
        assert uses.development_cost_reimbursement_keur == 0.0
        assert uses.developer_fee_keur == 0.0
        basis_codes = {c.code for c in
                       solar_disabled.g2c_result.financing_result
                       .book_depreciable_asset_basis.components}
        assert not ({"developer_fee", "development_cost_reimbursement"} & basis_codes)

    def test_abandoned_leaves_financing_results_bit_exact(self, solar_inputs, solar_off):
        abandoned = replace(solar_inputs, development_economics=_active(
            outcome=DevelopmentOutcome.ABANDONED,
            reimbursed_development_cost_keur=0.0, developer_fee_value=0.0))
        run = run_clean_production(abandoned, "Base", project_type="solar")
        assert _results_leaves(run) == _results_leaves(solar_off)       # no project use
        assert run.developer_economics_result.developer_moic == 0.0


# ===========================================================================
# 8. Governance: exact, content-pinned, no marker, no wildcard
# ===========================================================================

class TestGovernanceTreatment:
    def test_epic_scope_marker_is_not_recreated(self):
        assert not (REPO / "docs" / "model_v2" / "ACTIVE_EPIC_SCOPE.json").exists()

    def test_developer_economics_authority_is_exact_path_and_content_pinned(self):
        import model_v2_governance as gov

        authorised = gov.DEVELOPER_ECONOMICS_V1_AUTHORITIES
        assert authorised, "authority table must exist"
        for path, blob in authorised.items():
            assert "*" not in path and not path.endswith("/")
            assert re.fullmatch(r"[0-9a-f]{40}", blob)
            assert path.startswith(("finco_core/", "financial_engine/"))
        # nothing outside the two reviewed namespaces, nothing in hard-deny namespaces
        assert not any(p.startswith(gov.PERMANENT_HARD_DENY_PREFIXES) for p in authorised)
        assert "finco_core/inputs/development.py" in authorised
        assert "financial_engine/developer_economics/model.py" in authorised

    def test_a_different_content_at_an_authorised_path_is_not_authorised(self, tmp_path):
        import subprocess
        import model_v2_governance as gov

        repo = tmp_path / "r"
        (repo / "finco_core/inputs").mkdir(parents=True)
        subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.email", "t"], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"], check=True)
        (repo / "finco_core/inputs/development.py").write_text("# tampered\n")
        subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "x"], check=True)
        assert not gov.approved_by_active_model_v2_scope(
            "finco_core/inputs/development.py", repo=repo)

    def test_other_core_and_engine_paths_stay_frozen(self):
        import model_v2_governance as gov

        for other in ("finco_core/inputs/valuation.py", "finco_core/sponsor/xirr.py",
                      "financial_engine/orchestrator.py",
                      "financial_engine/shareholder_waterfall/model.py",
                      "financial_engine/sponsor_returns/model.py"):
            assert not gov.approved_by_active_model_v2_scope(other), other
