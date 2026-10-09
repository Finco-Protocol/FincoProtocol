"""Financing F3 — reference compatibility and isolation (NON-AUTHORITATIVE prototype).

Proves the foundation changes nothing: the candidate mapping only READS legacy financing,
ProjectInputs / fingerprints are untouched, no production module imports the candidate, no route
exposes it, and nothing is persisted.
"""
from __future__ import annotations

import ast
import copy
from pathlib import Path

import pytest

from app import project_factories as pf
from app.model_v2.financing_f3_candidate.contracts import (
    CommitmentAuthority,
    InstrumentType,
    candidate_identity,
)
from app.model_v2.financing_f3_candidate.legacy_mapping import map_legacy_financing
from finco_core.inputs import hash_inputs_for_cache, project_inputs_to_dict

REPO = Path(__file__).resolve().parents[1]
REFERENCES = {
    "solar": pf.create_generic_solar_reference,
    "wind": pf.create_generic_wind_reference,
    "data_center": pf.create_generic_data_center_reference,
    "ev": pf.create_generic_ev_charging_reference,
}


@pytest.mark.parametrize("name", sorted(REFERENCES))
class TestLegacyMapping:
    def test_mapping_is_read_only_and_leaves_fingerprints_unchanged(self, name):
        pi = REFERENCES[name]()
        before_dict = copy.deepcopy(project_inputs_to_dict(pi))
        before_hash = hash_inputs_for_cache(pi)
        map_legacy_financing(pi)
        assert project_inputs_to_dict(pi) == before_dict
        assert hash_inputs_for_cache(pi) == before_hash
        assert not hasattr(pi, "financing_instruments")           # ProjectInputs gained nothing

    def test_exactly_one_senior_and_its_amount_is_never_read_as_zero(self, name):
        coll = map_legacy_financing(REFERENCES[name]())
        seniors = [i for i in coll.instruments if i.instrument_type is InstrumentType.SENIOR_TERM_LOAN]
        assert len(seniors) == 1
        assert seniors[0].commitment_keur is None
        assert seniors[0].commitment_authority is CommitmentAuthority.CANONICAL_SIZING_DERIVED

    def test_mapping_is_deterministic(self, name):
        assert candidate_identity(map_legacy_financing(REFERENCES[name]())) == \
            candidate_identity(map_legacy_financing(REFERENCES[name]()))

    def test_explicit_equity_equals_the_legacy_fields(self, name):
        pi = REFERENCES[name]()
        coll = {i.instrument_id: i for i in map_legacy_financing(pi).instruments}
        cap = coll.get("legacy-share-capital")
        assert (cap.commitment_keur if cap else 0.0) == float(pi.financing.share_capital_keur)
        prem = coll.get("legacy-share-premium")
        assert (prem.commitment_keur if prem else 0.0) == float(pi.financing.share_premium_keur)


class TestIsolation:
    NAME = "financing_f3_candidate"

    def _python_files(self):
        for root in ("app", "financial_engine", "finco_core", "domain", "main_web.py"):
            p = REPO / root
            if p.is_file():
                yield p
            elif p.is_dir():
                yield from p.rglob("*.py")

    def test_no_production_module_imports_the_candidate(self):
        offenders = []
        for path in self._python_files():
            if self.NAME in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
            for node in ast.walk(tree):
                mods = []
                if isinstance(node, ast.Import):
                    mods = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    mods = [node.module or ""]
                if any(self.NAME in m for m in mods):
                    offenders.append(str(path.relative_to(REPO)))
        assert offenders == []

    def test_candidate_package_imports_nothing_from_the_engine_or_persistence(self):
        forbidden = ("financial_engine", "app.persistence", "app.v2", "app.workbook", "fastapi", "sqlite3")
        for path in (REPO / "app/model_v2" / self.NAME).glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
            for node in ast.walk(tree):
                mods = ([a.name for a in node.names] if isinstance(node, ast.Import)
                        else [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
                assert not any(m.startswith(forbidden) for m in mods), (path.name, mods)

    def test_no_runtime_route_exposes_the_candidate(self):
        import main_web
        paths = [getattr(r, "path", "") for r in main_web.app.routes]
        assert not [p for p in paths if "f3" in p.lower() or "financing-instrument" in p.lower()]

    def test_candidate_declares_itself_non_authoritative(self):
        import app.model_v2.financing_f3_candidate as pkg
        assert pkg.NON_AUTHORITATIVE is True

    def test_project_inputs_schema_is_unchanged(self):
        import dataclasses
        from finco_core.inputs import ProjectInputs
        names = {f.name for f in dataclasses.fields(ProjectInputs)}
        assert not {n for n in names if "instrument" in n or "tranche" in n or "facilit" in n}


# ----------------------------------------------------------------------------------------------
# Correction A — mapping accuracy (no invented dates, proven SHL semantics, strict funding mode)
# ----------------------------------------------------------------------------------------------
import dataclasses
import hashlib
import json
from datetime import date

from app.model_v2.financing_f3_candidate.contracts import FinancingError, MaturityAuthority, RepaymentMode
from app.model_v2.financing_f3_candidate.legacy_mapping import UNRESOLVED
from finco_core.inputs import (
    DebtSizingMode,
    GearingCapRepaymentMethod,
    SHLRepaymentMethod,
    SponsorFundingMode,
)


def _with(pi, *, info=None, **fin_changes):
    return dataclasses.replace(
        pi,
        info=dataclasses.replace(pi.info, **info) if info else pi.info,
        financing=dataclasses.replace(pi.financing, **fin_changes))


def _by_id(coll):
    return {i.instrument_id: i for i in coll.instruments}


def _fingerprint(pi):
    return hashlib.sha256(json.dumps(project_inputs_to_dict(pi), sort_keys=True, default=str).encode()).hexdigest()


class TestSeniorMaturityIsNotInventedFromFinancialClose:
    def test_leap_day_financial_close_does_not_crash_or_invent_a_date(self):
        pi = _with(pf.create_generic_solar_reference(), info={"financial_close": date(2028, 2, 29)})
        senior = _by_id(map_legacy_financing(pi))["legacy-senior"]
        assert senior.repayment.maturity_date is None

    @pytest.mark.parametrize("name", sorted(REFERENCES))
    def test_maturity_is_period_axis_derived_with_the_canonical_tenor(self, name):
        pi = REFERENCES[name]()
        rep = _by_id(map_legacy_financing(pi))["legacy-senior"].repayment
        assert rep.maturity_authority is MaturityAuthority.PERIOD_AXIS_DERIVED
        assert rep.maturity_date is None and rep.tenor_years == pi.financing.senior_tenor_years

    def test_financial_close_and_cod_do_not_influence_the_mapping(self):
        base = pf.create_generic_solar_reference()
        moved = _with(base, info={"financial_close": date(2028, 2, 29), "cod_date": date(2032, 2, 29)})
        assert base.info.cod_date != base.info.financial_close
        assert candidate_identity(map_legacy_financing(base)) == candidate_identity(map_legacy_financing(moved))


class TestShlRepaymentSemantics:
    @pytest.mark.parametrize("name", sorted(REFERENCES))
    def test_references_map_the_real_cash_sweep_not_bullet(self, name):
        pi = REFERENCES[name]()
        assert pi.financing.clean_shl_repayment_method is SHLRepaymentMethod.CASH_SWEEP
        shl = _by_id(map_legacy_financing(pi))["legacy-shl"]
        assert shl.repayment.mode is RepaymentMode.CASH_SWEEP
        assert shl.repayment.maturity_date is None
        assert shl.repayment.maturity_period_index == pi.financing.shl_maturity_period_index

    def test_bullet_maps_to_bullet(self):
        pi = _with(pf.create_generic_solar_reference(), clean_shl_repayment_method=SHLRepaymentMethod.BULLET)
        assert _by_id(map_legacy_financing(pi))["legacy-shl"].repayment.mode is RepaymentMode.BULLET

    @pytest.mark.parametrize("method", [SHLRepaymentMethod.PIK, SHLRepaymentMethod.ACCRUED,
                                        SHLRepaymentMethod.PIK_THEN_SWEEP, SHLRepaymentMethod.PARTIAL_PAY_SWEEP,
                                        SHLRepaymentMethod.FCF_WATERFALL, None, "cash_sweep"])
    def test_unproven_or_unset_modes_fail_closed(self, method):
        pi = _with(pf.create_generic_solar_reference(), clean_shl_repayment_method=method)
        with pytest.raises(FinancingError) as exc:
            map_legacy_financing(pi)
        assert exc.value.code == UNRESOLVED


class TestSponsorFundingMode:
    @pytest.mark.parametrize("mode", [None, "equity_only", "share_capital_then_shl", 1, object()])
    def test_unset_or_unknown_mode_is_never_read_as_a_residual_policy(self, mode):
        pi = _with(pf.create_generic_solar_reference(), sponsor_funding_mode=mode)
        with pytest.raises(FinancingError) as exc:
            map_legacy_financing(pi)
        assert exc.value.code == UNRESOLVED

    def test_equity_only_maps_additional_equity_and_no_shl(self):
        pi = _with(pf.create_generic_solar_reference(), sponsor_funding_mode=SponsorFundingMode.EQUITY_ONLY,
                   clean_shl_repayment_method=None)
        ids = _by_id(map_legacy_financing(pi))
        assert "legacy-additional-equity" in ids and "legacy-shl" not in ids

    def test_share_capital_then_shl_maps_shl_and_no_additional_equity(self):
        ids = _by_id(map_legacy_financing(pf.create_generic_solar_reference()))
        assert "legacy-shl" in ids and "legacy-additional-equity" not in ids


class TestSeniorRepaymentAuthority:
    def test_unset_sizing_mode_fails_closed(self):
        with pytest.raises(FinancingError):
            map_legacy_financing(_with(pf.create_generic_solar_reference(), debt_sizing_mode=None))

    @pytest.mark.parametrize("method,expected", [(GearingCapRepaymentMethod.LEVEL_PRINCIPAL, RepaymentMode.LEVEL_PRINCIPAL),
                                                 (GearingCapRepaymentMethod.DSCR_SCULPTED, RepaymentMode.DSCR_SCULPTED)])
    def test_gearing_cap_follows_its_typed_repayment_method(self, method, expected):
        pi = _with(pf.create_generic_solar_reference(), debt_sizing_mode=DebtSizingMode.GEARING_CAP,
                   gearing_cap_repayment_method=method)
        assert _by_id(map_legacy_financing(pi))["legacy-senior"].repayment.mode is expected

    def test_legacy_amortization_string_is_not_an_authority(self):
        a = pf.create_generic_solar_reference()
        b = _with(a, amortization_type="anything-else")
        assert candidate_identity(map_legacy_financing(a)) == candidate_identity(map_legacy_financing(b))


class TestRunFingerprintsUntouched:
    @pytest.mark.parametrize("name", sorted(REFERENCES))
    def test_inputs_and_fingerprints_are_bit_identical_around_the_mapping(self, name):
        pi = REFERENCES[name]()
        before = (_fingerprint(pi), hash_inputs_for_cache(pi), repr(pi))
        map_legacy_financing(pi)
        assert (_fingerprint(pi), hash_inputs_for_cache(pi), repr(pi)) == before
