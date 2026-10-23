"""V9-P2a / OD-R financial acceptance harness (synthetic factory inputs only; read-only on the engine).

Runs every case of the 112-case OD-R research inventory through the production entry point
(``run_clean_production``; the release-closed quarterly cases through the policy runner) twice:

* ``canonical`` - ``DEFAULT_GENERIC_FINANCING_POLICY`` (the deployed interpretation);
* ``odr``       - the same policy with ``shl_maturity_authority=OD_R_FINAL_STATE_SHL_MATURITY_V1``.

No engine function is patched or wrapped; the in-process policy-run memo is cleared before
every case. Per case it records the verdict, the exact error text, a full-output leaf digest
(float bit patterns) of the complete result and its Run Integrity verdict, and final-state
financial checks. The financial digest excludes only the OD-R provenance keys that the
candidate adds to ``authority_metadata`` / the policy evidence; ``full_digest`` keeps them.

Case inputs are the repository's synthetic ``app.project_factories`` projects with parameter
variations. No customer, model or confidential benchmark data is used.

Usage: python tools/v9p2a_odr_acceptance.py --mode canonical|odr --shard 0/6 --out results.json
       python tools/v9p2a_odr_acceptance.py --compare canonical.json odr.json [--report out.json]
"""
from __future__ import annotations

import argparse
import dataclasses as dc
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
import hashlib
import json
from pathlib import Path
import struct
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ODR_METADATA_PREFIX = "shl_maturity_"

# Research classification of the inventory (V9-P2 / OD-R verification gate, main 5996453b).
EXPECTED_CLASS_COUNTS = {
    "PREVIOUSLY_FEASIBLE": 62,
    "PROVISIONAL_ONLY_NOW_FEASIBLE": 17,
    "FINAL_STATE_ECONOMICALLY_INFEASIBLE": 27,
    "STRUCTURAL_INPUT_REJECTION": 4,
    "NUMERICAL_DEGENERATE_REJECTION": 2,
}


# --------------------------------------------------------------------------------------------
# Case inventory: 63 (#327 matrix) + 39 (V9-P2 boundary) + 10 (V9 gate near-threshold) = 112
# --------------------------------------------------------------------------------------------

def _scale(pi, factor):
    fields = {name: dc.replace(getattr(pi.capex, name),
                               amount_keur=getattr(pi.capex, name).amount_keur * factor)
              for name in pi.capex._CAPEX_ITEM_FIELDS
              if getattr(getattr(pi.capex, name), "amount_keur", 0)}
    return dc.replace(pi, capex=dc.replace(pi.capex, **fields))


def _fin(pi, **fields):
    return dc.replace(pi, financing=dc.replace(pi.financing, **fields))


def _loss(pi):
    return dc.replace(pi, opex=type(pi.opex)([
        dc.replace(item, y1_amount_keur=item.y1_amount_keur * 1.8) for item in pi.opex]))


def _leap(pi):
    from dateutil.relativedelta import relativedelta
    fc = date(2028, 2, 29)
    return dc.replace(pi, info=dc.replace(pi.info, financial_close=fc,
                      cod_date=fc + relativedelta(months=pi.info.construction_months)))


def quarterly_inputs(kind):
    from dateutil.relativedelta import relativedelta
    from app import project_factories as pf
    from finco_core.inputs import PeriodFrequency, SponsorFundingMode
    from finco_core.inputs._models import QuarterlyProjectInfo
    from finco_core.engine.calendar_policy import quarterly_candidate_policy_v2
    pi = getattr(pf, f"create_generic_{kind}_reference")()
    cod = date(2031, 3, 31)
    values = {field.name: getattr(pi.info, field.name) for field in dc.fields(pi.info)}
    values.update(financial_close=cod - relativedelta(months=pi.info.construction_months), cod_date=cod,
                  period_frequency=PeriodFrequency.QUARTERLY,
                  operating_calendar_policy=quarterly_candidate_policy_v2())
    return dc.replace(pi, info=QuarterlyProjectInfo(**values), financing=dc.replace(
        pi.financing, sponsor_funding_mode=SponsorFundingMode.EQUITY_ONLY, shl_amount_keur=0.,
        clean_shl_principal_keur=0., dsra_months=0))


def cases() -> dict:
    """name -> (factory, vertical, base policy or None)."""
    from app import project_factories as pf
    from finco_core.inputs import SponsorFundingMode
    from financial_engine.financing.generic_product_policy import GenericFinancingPolicy

    def s16(**fields):
        return _scale(pf.create_default_solar_project(capacity_mw=16., **fields), .26)

    def s16r():
        return _scale(pf.create_default_solar_project(capacity_mw=16.), .18)

    def wind(**fields):
        return pf.create_default_wind_project(capacity_mw=25., **fields)

    def windr():
        return _scale(wind(), .7)

    E = {"S16": (s16, "Solar", None), "W25": (wind, "Wind", None),
         "DC": (pf.create_default_data_center_project, "DataCenter", None),
         "S50": (pf.create_default_solar_project, "Solar", None)}
    for prefix, factory, vertical in (("S16", s16, "Solar"), ("W25", wind, "Wind")):
        for dscr in (1.45, 2., 3.):
            E[f"{prefix}-dscr{dscr}"] = (lambda f=factory, d=dscr: _fin(f(), target_dscr=d), vertical, None)
        for gearing in ((.5, .9) if prefix == "W25" else (.5,)):
            E[f"{prefix}-gear{gearing:.2f}"] = (lambda f=factory, g=gearing: _fin(f(), gearing_ratio=g), vertical, None)
        E[f"{prefix}-dsra12"] = (lambda f=factory: _fin(f(), dsra_months=12), vertical, None)
        E[f"{prefix}-noCF"] = (factory, vertical, GenericFinancingPolicy(apply_construction_financing=False))
        E[f"{prefix}-taxloss"] = (lambda f=factory: _loss(f()), vertical, None)
    E.update({
        "DC-dscr2.0": (lambda: _fin(pf.create_default_data_center_project(), target_dscr=2.), "DataCenter", None),
        "S16-dsra0": (lambda: _fin(s16(), dsra_months=0), "Solar", None),
        "W25-noDSRA": (wind, "Wind", GenericFinancingPolicy(apply_cash_dsra=False)),
        "S16-shl-small": (lambda: _fin(s16(), share_capital_keur=4000.), "Solar", None),
        "S16-tenor10": (lambda: _fin(s16(), senior_tenor_years=10), "Solar", None),
        "W25-tenor18": (lambda: _fin(wind(), senior_tenor_years=18), "Wind", None),
        "S16-gear0": (lambda: _fin(s16(), gearing_ratio=0.), "Solar", None),
        "S16-gear0.001": (lambda: _fin(s16(), gearing_ratio=.001), "Solar", None),
        "S16-raw-infeasible": (lambda: pf.create_default_solar_project(capacity_mw=16.), "Solar", None),
        "S16-capex0.32-infeasible": (lambda: _scale(pf.create_default_solar_project(capacity_mw=16.), .32), "Solar", None),
        "S16-gearbound": (lambda: _scale(pf.create_default_solar_project(capacity_mw=16.), .24), "Solar", None),
        "W25-dscr9-infeasible": (lambda: _fin(wind(), target_dscr=9.), "Wind", None),
        "S16-leap": (lambda: _leap(s16()), "Solar", None),
        "S16-codstub9": (lambda: s16(construction_months=9), "Solar", None),
        "W25-codstub15": (lambda: wind(construction_months=15), "Wind", None),
        "DC-leap": (lambda: _leap(pf.create_default_data_center_project()), "DataCenter", None),
        "S16r": (s16r, "Solar", None),
    })
    for prefix, factory, vertical, changes in (
        ("S16r", s16r, "Solar", {"dscr2.0": {"target_dscr": 2.}, "dscr3.0": {"target_dscr": 3.},
         "gear0.50": {"gearing_ratio": .5}, "tenor10": {"senior_tenor_years": 10},
         "tenor12": {"senior_tenor_years": 12}, "dsra12": {"dsra_months": 12}, "gear0.001": {"gearing_ratio": .001}}),
        ("W25r", windr, "Wind", {"dscr2.0": {"target_dscr": 2.}, "dscr3.0": {"target_dscr": 3.},
         "gear0.50": {"gearing_ratio": .5}, "tenor10": {"senior_tenor_years": 10}}),
    ):
        for suffix, fields in changes.items():
            E[f"{prefix}-{suffix}"] = (lambda f=factory, k=fields: _fin(f(), **k), vertical, None)
        E[f"{prefix}-taxloss"] = (lambda f=factory: _loss(f()), vertical, None)
    assert len(E) == 49
    for kind, vertical in (("solar", "Solar"), ("wind", "Wind"),
                           ("data_center", "DataCenter"), ("ev_charging", "EVCharging")):
        E[f"reference-{kind}"] = (getattr(pf, f"create_generic_{kind}_reference"), vertical, None)
    E["Solar-equity-only"] = (lambda: _fin(pf.create_generic_solar_reference(),
        sponsor_funding_mode=SponsorFundingMode.EQUITY_ONLY, shl_amount_keur=0.,
        clean_shl_principal_keur=0., dsra_months=0), "Solar", None)
    for name, gearing in (("EQ-DSRA", .7), ("EQ-zero", 0.), ("EQ-nearzero", 1e-12)):
        E[name] = (lambda g=gearing: _fin(pf.create_default_solar_project(),
            sponsor_funding_mode=SponsorFundingMode.EQUITY_ONLY, shl_amount_keur=0.,
            clean_shl_principal_keur=0., dsra_months=6, gearing_ratio=g), "Solar", None)
    for target in (1.4, 1.6, 1.8, 2.2):
        E[f"boundary-S16r-{target}"] = (lambda d=target: _fin(s16r(), target_dscr=d), "Solar", None)
    for kind in ("solar", "wind"):
        E[f"quarterly-{kind}"] = (lambda k=kind: quarterly_inputs(k), "QUARTERLY_TEST_ONLY", None)
    assert len(E) == 63

    # V9-P2 boundary inventory (39)
    for d in (1.6, 1.7, 1.8, 1.9, 2.1, 2.25, 2.5, 2.75):
        E[f"X-S16-dscr{d}"] = (lambda d=d: _fin(s16(), target_dscr=d), "Solar", None)
    for d in (1.6, 1.8, 2.25, 2.5, 2.75):
        E[f"X-W25-dscr{d}"] = (lambda d=d: _fin(wind(), target_dscr=d), "Wind", None)
    for t in (12, 14, 16):
        E[f"X-S16-tenor{t}"] = (lambda t=t: _fin(s16(), senior_tenor_years=t), "Solar", None)
    for t in (10, 12, 14, 16):
        E[f"X-W25-tenor{t}"] = (lambda t=t: _fin(wind(), senior_tenor_years=t), "Wind", None)
    for m in (3, 9):
        E[f"X-S16-dsra{m}"] = (lambda m=m: _fin(s16(), dsra_months=m), "Solar", None)
        E[f"X-W25-dsra{m}"] = (lambda m=m: _fin(wind(), dsra_months=m), "Wind", None)
    for g in (0.6, 0.7):
        E[f"X-S16-gear{g}"] = (lambda g=g: _fin(s16(), gearing_ratio=g), "Solar", None)
    for g in (0.6, 0.7, 0.8):
        E[f"X-W25-gear{g}"] = (lambda g=g: _fin(wind(), gearing_ratio=g), "Wind", None)
    E["X-S16-dscr2.0-dsra12"] = (lambda: _fin(s16(), target_dscr=2.0, dsra_months=12), "Solar", None)
    E["X-W25-dscr2.0-tenor15"] = (lambda: _fin(wind(), target_dscr=2.0, senior_tenor_years=15), "Wind", None)
    E["X-S16-dscr2.25-taxloss"] = (lambda: _fin(_loss(s16()), target_dscr=2.25), "Solar", None)
    E["X-S16-dscr2.0-cm9"] = (lambda: _fin(s16(construction_months=9), target_dscr=2.0), "Solar", None)
    E["X-W25-dscr2.0-cm15"] = (lambda: _fin(wind(construction_months=15), target_dscr=2.0), "Wind", None)
    for mi in (35, 38):
        E[f"X-S16-dscr2.0-shlmat{mi}"] = (lambda mi=mi: _fin(s16(), target_dscr=2.0, shl_maturity_period_index=mi), "Solar", None)
        E[f"X-S16-shlmat{mi}"] = (lambda mi=mi: _fin(s16(), shl_maturity_period_index=mi), "Solar", None)
    E["X-W25-dscr2.0-shlmat46"] = (lambda: _fin(wind(), target_dscr=2.0, shl_maturity_period_index=46), "Wind", None)
    assert len(E) == 102
    # V9 gate near-threshold boundaries (10)
    for d in (1.5, 2.02, 2.04, 2.06, 2.08):
        E[f"G-S16-dscr{d}"] = (lambda d=d: _fin(s16(), target_dscr=d), "Solar", None)
    E["G-S16-tenor13"] = (lambda: _fin(s16(), senior_tenor_years=13), "Solar", None)
    E["G-W25-tenor13"] = (lambda: _fin(wind(), senior_tenor_years=13), "Wind", None)
    E["G-W25-dscr1.5"] = (lambda: _fin(wind(), target_dscr=1.5), "Wind", None)
    E["G-W25-gear0.55"] = (lambda: _fin(wind(), gearing_ratio=0.55), "Wind", None)
    E["G-S16-gear0.55"] = (lambda: _fin(s16(), gearing_ratio=0.55), "Solar", None)
    assert len(E) == 112
    return E


def supplementary_cases() -> dict:
    """P8 configurations the research inventory does not cover (interest limitation, bullet SHL)."""
    from app import project_factories as pf
    from finco_core.inputs import SHLRepaymentMethod
    from finco_core.inputs._models import (
        CapitalisationGatePolicyParams, InterestLimitationCarryforwardMode,
        InterestLimitationCombinationMode, InterestLimitationPolicyParams,
    )

    def s16(**fields):
        return _scale(pf.create_default_solar_project(capacity_mw=16., **fields), .26)

    def wind(**fields):
        return pf.create_default_wind_project(capacity_mw=25., **fields)

    def il(pi, limit=150.0):
        policy = InterestLimitationPolicyParams(
            enabled=True, absolute_interest_limit_keur=limit, ebitda_interest_limit_pct=0.3,
            capitalisation_gate_policy=CapitalisationGatePolicyParams(enabled=False, threshold=0.0),
            combination_mode=InterestLimitationCombinationMode.MAX_DISALLOWED,
            carryforward_mode=InterestLimitationCarryforwardMode.NONE)
        return dc.replace(pi, tax=dc.replace(pi.tax, interest_limitation_policy=policy))

    def bullet(pi):
        return _fin(pi, clean_shl_repayment_method=SHLRepaymentMethod.BULLET)

    E = {}
    for label, factory in (("S16", s16), ("W25", wind)):
        E[f"P8-{label}-IL"] = (lambda f=factory: il(f()), "Solar" if label == "S16" else "Wind", None)
        for d in (2.0, 3.0):
            E[f"P8-{label}-dscr{d}-IL"] = (lambda f=factory, d=d: il(_fin(f(), target_dscr=d)),
                                           "Solar" if label == "S16" else "Wind", None)
        E[f"P8-{label}-bullet"] = (lambda f=factory: bullet(f()), "Solar" if label == "S16" else "Wind", None)
        E[f"P8-{label}-dscr2.0-bullet"] = (lambda f=factory: bullet(_fin(f(), target_dscr=2.0)),
                                           "Solar" if label == "S16" else "Wind", None)
    E["P8-S16-taxloss-IL"] = (lambda: il(_loss(s16())), "Solar", None)
    return E


# --------------------------------------------------------------------------------------------
# Evidence
# --------------------------------------------------------------------------------------------

def flatten(value, path="", out=None):
    """Exact leaf map: floats as IEEE-754 bit patterns, enums by name, dataclasses by field."""
    if out is None:
        out = {}
    if isinstance(value, Enum):
        out[path] = [type(value).__qualname__, value.name]
    elif isinstance(value, float):
        out[path] = ["float64", struct.pack(">d", value).hex()]
    elif value is None or isinstance(value, (str, bool, int)):
        out[path] = [type(value).__name__, value]
    elif isinstance(value, (date, datetime, Decimal)):
        out[path] = [type(value).__name__, str(value)]
    elif dc.is_dataclass(value):
        out[path] = ["dataclass", type(value).__qualname__]
        for field in dc.fields(value):
            flatten(getattr(value, field.name), path + "." + field.name, out)
    elif isinstance(value, dict):
        out[path] = ["dict", len(value)]
        for key in sorted(value, key=repr):
            flatten(value[key], path + f"[{key!r}]", out)
    elif isinstance(value, (tuple, list, set, frozenset)):
        out[path] = [type(value).__name__, len(value)]
        sequence = sorted(value, key=repr) if isinstance(value, (set, frozenset)) else value
        for index, item in enumerate(sequence):
            flatten(item, path + f"[{index}]", out)
    elif hasattr(value, "__dict__"):
        out[path] = ["object", type(value).__qualname__]
        flatten(vars(value), path + ".__dict__", out)
    else:
        raise TypeError(f"Unsupported evidence leaf {path}: {type(value)}")
    return out


def digest(evidence: dict) -> str:
    return hashlib.sha256(json.dumps(evidence, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def policy_for(mode: str, base):
    from financial_engine.financing.generic_product_policy import DEFAULT_GENERIC_FINANCING_POLICY
    from financial_engine.shl.maturity_authority import SHL_MATURITY_POLICY_OD_R
    policy = base if base is not None else DEFAULT_GENERIC_FINANCING_POLICY
    if mode == "odr":
        policy = dc.replace(policy, shl_maturity_authority=SHL_MATURITY_POLICY_OD_R)
    elif mode != "canonical":
        raise ValueError(mode)
    return policy


@dc.dataclass
class QuarterlyResult:
    g2c_result: object
    project_inputs: object
    financial_statements_result: object
    policy_evidence: object


def run_case(name: str, mode: str, entries: dict | None = None):
    """Execute one case through the production entry point. Returns the result object."""
    from app.services import production_financial_authority as pfa
    entries = entries or cases()
    factory, vertical, base = entries[name]
    policy = policy_for(mode, base)
    pfa._POLICY_RUN_CACHE.clear()
    inputs = factory()
    if vertical == "QUARTERLY_TEST_ONLY":
        from financial_engine.financing.generic_product_policy import run_with_generic_financing_policy
        from financial_engine.shareholder_waterfall import run_project_shareholder_waterfall_model
        from financial_engine.financial_statements import assemble_decision_complete_financial_statements
        from financial_engine.run_scope import engine_run_scope
        with engine_run_scope():
            g2c, applied, evidence = run_with_generic_financing_policy(
                inputs, lambda value: run_project_shareholder_waterfall_model(
                    value, source_id="v9p2a_quarterly_isolated"), policy)
        return QuarterlyResult(g2c, applied, assemble_decision_complete_financial_statements(g2c, applied), evidence)
    return pfa.run_clean_production(inputs, project_type=vertical, financing_policy=policy)


def financial_leaves(result) -> dict:
    """Full output leaves minus only the OD-R provenance the candidate adds."""
    leaves = flatten(result)
    drop = [k for k in leaves if f"[{ODR_METADATA_PREFIX}" in k.replace("'", "")
            or ".policy_evidence.shl_maturity" in k]
    for key in drop:
        del leaves[key]
    for key in (".authority_metadata", ".policy_evidence"):
        if key in leaves and leaves[key][0] == "dict":
            leaves[key] = ["dict", "<count excluded>"]
        if key in leaves and leaves[key][0] == "dataclass":
            leaves[key] = ["dataclass", "<type excluded>"]
    return leaves


def final_checks(result) -> dict:
    g = result.g2c_result
    fr = g.financing_result
    pm = fr.project_model_result
    out = {"senior_keur": fr.final_senior_commitment_keur,
           "derived_shl_keur": fr.derived_shl_cash_principal_keur,
           "binding": getattr(fr, "binding_senior_constraint", None)}
    out["binding"] = getattr(out["binding"], "name", out["binding"])
    funding = fr.construction_funding
    out["sources_minus_uses_keur"] = funding.total_audit_sources_keur - funding.total_audit_uses_keur
    if fr.construction_financing is not None:
        out["construction_sources_uses_residual_keur"] = fr.construction_financing.sources_uses_residual_keur
    shl = pm.shareholder_loan
    rs = getattr(g, "return_summary", None)
    if rs is not None:
        term = rs.terminal
        out["senior_terminal"] = [term.senior.status.name, term.senior.balance_at_contractual_maturity_keur]
        if term.shareholder_loan is not None:
            out["shl_terminal"] = [term.shareholder_loan.status.name, term.shareholder_loan.unpaid_at_maturity_keur]
    sd = pm.senior_debt
    dscr = [x for x in (sd.base_dscr if sd else ()) if x is not None]
    out["min_base_dscr"] = min(dscr) if dscr else None
    if shl is not None:
        out["model_shl_closing_last_keur"] = shl.shl_closing_keur[-1]
    statements = getattr(result, "financial_statements_result", None)
    if statements is not None:
        out["statements_status"] = getattr(getattr(statements, "status", None), "name", None)
    return out


def evaluate(name: str, mode: str, entries: dict) -> dict:
    record: dict = {"mode": mode}
    t0 = time.perf_counter()
    try:
        result = run_case(name, mode, entries)
    except Exception as exc:  # noqa: BLE001 - the verdict IS the exception
        record.update(verdict="REJECTED", error_type=type(exc).__name__, error=str(exc))
        cause = exc.__cause__
        if cause is not None:
            record["cause_type"] = type(cause).__name__
            inner = cause.__cause__
            if inner is not None:
                record["inner_cause"] = f"{type(inner).__name__}: {str(inner)[:200]}"
    else:
        record["verdict"] = "FEASIBLE"
        leaves = financial_leaves(result)
        record["financial_digest"] = digest(leaves)
        record["full_digest"] = digest(flatten(result))
        record["leaf_count"] = len(leaves)
        if not isinstance(result, QuarterlyResult):
            from app.run_integrity import build_run_integrity_evidence, run_integrity_checks
            integrity = run_integrity_checks(build_run_integrity_evidence(result)).to_dict()
            record["integrity"] = integrity["overall"]
            record["integrity_digest"] = digest(flatten(integrity))
            record["integrity_not_pass"] = sorted(
                c["check_id"] for c in integrity["checks"] if c["status"] not in ("PASS", "NOT_APPLICABLE"))
            record["odr_metadata"] = {k: v for k, v in result.authority_metadata.items()
                                      if k.startswith(ODR_METADATA_PREFIX)}
        else:
            ev = getattr(result.policy_evidence, "shl_maturity", None)
            record["odr_metadata"] = ev.to_metadata() if ev is not None else {}
        record["final_checks"] = final_checks(result)
    record["seconds"] = round(time.perf_counter() - t0, 2)
    return record


# --------------------------------------------------------------------------------------------
# Comparison / classification
# --------------------------------------------------------------------------------------------

STRUCTURAL_MARKERS = ("G2A_FIXED_SOURCES_EXCEED_TOTAL_PROJECT_USES", "explicit_all_in_rates has")
NUMERICAL_MARKERS = ("SeniorDebtNonConvergenceError", "DID_NOT_CONVERGE", "NOT_CONVERGED", "IDEMPOTENCE")


def classify(canonical: dict, odr: dict) -> str:
    if canonical["verdict"] == "FEASIBLE":
        return "PREVIOUSLY_FEASIBLE"
    error = canonical.get("error", "")
    if "SHL_MATURITY_RESIDUAL_FAILS_CLOSED" in error:
        return ("PROVISIONAL_ONLY_NOW_FEASIBLE" if odr["verdict"] == "FEASIBLE"
                else "FINAL_STATE_ECONOMICALLY_INFEASIBLE")
    if any(m in error for m in STRUCTURAL_MARKERS):
        return "STRUCTURAL_INPUT_REJECTION"
    if any(m in error for m in NUMERICAL_MARKERS):
        return "NUMERICAL_DEGENERATE_REJECTION"
    return "OTHER_REJECTION"


def compare(canonical: dict, odr: dict) -> dict:
    rows, defects = {}, []
    for name in sorted(canonical):
        c, o = canonical[name], odr[name]
        cls = classify(c, o)
        row = {"class": cls, "canonical": c["verdict"], "odr": o["verdict"]}
        if cls == "PREVIOUSLY_FEASIBLE":
            row["bit_identical"] = (o["verdict"] == "FEASIBLE"
                                    and c["financial_digest"] == o["financial_digest"]
                                    and c.get("integrity_digest") == o.get("integrity_digest"))
            if not row["bit_identical"]:
                defects.append(f"{name}: previously feasible output changed under OD-R")
            if o.get("odr_metadata", {}).get("shl_maturity_provisional_violations"):
                defects.append(f"{name}: previously feasible case reports provisional violations")
        elif cls == "PROVISIONAL_ONLY_NOW_FEASIBLE":
            row["integrity"] = o.get("integrity", "N/A (quarterly)")
            row["odr_metadata"] = o.get("odr_metadata")
            row["final_checks"] = o.get("final_checks")
            if o.get("integrity") not in ("PASS", None):
                defects.append(f"{name}: admitted case Integrity {o.get('integrity')}")
            if not o.get("odr_metadata", {}).get("shl_maturity_provisional_violations"):
                defects.append(f"{name}: admitted case records no provisional violation")
        elif cls == "FINAL_STATE_ECONOMICALLY_INFEASIBLE":
            row["canonical_error"] = c["error"][:200]
            row["odr_error"] = o.get("error", "")[:400]
            if "SHL_MATURITY_RESIDUAL_FAILS_CLOSED" not in o.get("error", ""):
                defects.append(f"{name}: final-state rejection lost its SHL maturity code")
            if "od_r_final_check=" not in o.get("error", ""):
                defects.append(f"{name}: final-state rejection lacks final-check evidence")
        else:
            row["canonical_error"] = c.get("error", "")[:200]
            row["odr_error"] = o.get("error", "")[:200]
            same = (o["verdict"] == c["verdict"]
                    and o.get("error_type") == c.get("error_type")
                    and o.get("error") == c.get("error"))
            row["same_rejection"] = same
            if not same:
                defects.append(f"{name}: {cls} rejection changed under OD-R")
        rows[name] = row
    counts: dict = {}
    for row in rows.values():
        counts[row["class"]] = counts.get(row["class"], 0) + 1
    return {"cases": len(rows), "counts": counts, "expected_counts": EXPECTED_CLASS_COUNTS,
            "counts_match_research": counts == EXPECTED_CLASS_COUNTS, "defects": defects, "rows": rows}


def _load(paths):
    merged: dict = {}
    for p in paths:
        merged.update(json.loads(Path(p).read_text(encoding="utf-8")))
    return merged


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("canonical", "odr"))
    parser.add_argument("--shard", default="0/1")
    parser.add_argument("--names", nargs="*")
    parser.add_argument("--set", choices=("matrix", "p8"), default="matrix")
    parser.add_argument("--out")
    parser.add_argument("--compare", nargs=2, metavar=("CANONICAL_GLOB", "ODR_GLOB"))
    parser.add_argument("--report")
    args = parser.parse_args(argv)
    if args.compare:
        import glob
        canonical = _load(sorted(glob.glob(args.compare[0])))
        odr = _load(sorted(glob.glob(args.compare[1])))
        report = compare(canonical, odr)
        text = json.dumps(report, indent=1, sort_keys=True, default=str)
        if args.report:
            Path(args.report).write_text(text + "\n", encoding="utf-8", newline="\n")
        print(json.dumps({k: report[k] for k in ("cases", "counts", "counts_match_research", "defects")},
                         indent=1, sort_keys=True))
        return 0 if report["counts_match_research"] and not report["defects"] else 1
    entries = supplementary_cases() if args.set == "p8" else cases()
    names = args.names or sorted(entries)
    index, total = (int(x) for x in args.shard.split("/"))
    names = [n for i, n in enumerate(names) if i % total == index]
    out: dict = {}
    for name in names:
        out[name] = evaluate(name, args.mode, entries)
        print(args.mode, name, out[name]["verdict"], out[name].get("error", "")[:90], flush=True)
        if args.out:
            Path(args.out).write_text(json.dumps(out, indent=1, sort_keys=True, default=str) + "\n",
                                      encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
